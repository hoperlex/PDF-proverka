#!/usr/bin/env python3
"""Раннер одного test lane по контракту `quality-runtime/v1` §7–§8.

Что он гарантирует
──────────────────
§7 Hang становится bounded failure. Каждый тест идёт под per-test бюджетом
   (`scripts/ci_timeout_plugin.py`), весь lane — под wall-clock бюджетом.
   Превышение любого из них даёт failure с node ID, thread dump, инвентарём
   дочерних процессов и ненулевым кодом возврата. Молчаливый cancel или skip
   невозможен: у таймаута отдельный код возврата и отдельная запись в JUnit.

§8 Отчёт свежий или его нет. Старый JUnit удаляется ДО прогона; после прогона
   проверяются существование, mtime не старше времени старта и разбираемость.
   Stale/missing/unparseable — infrastructure failure, даже если pytest вернул
   ноль. Рядом кладётся JSON receipt с полями из §8.

Почему JUnit иногда собирается здесь, а не pytest'ом
────────────────────────────────────────────────────
При таймауте процесс pytest снимается принудительно и `--junitxml` не
дописывается. Поэтому плагин пишет результаты в журнал событий ПО ХОДУ
прогона, а раннер собирает из него валидный JUnit: все успевшие testcase
плюс один `<failure type="timeout">` с node ID зависшего теста. Так требование
«записать testcase failure типа timeout в свежий JUnit» выполняется именно
тогда, когда оно и нужно, — на зависании.

Использование:
    python scripts/ci_test_lane.py --lane unit
    python scripts/ci_test_lane.py --lane network --skip-probe
    python scripts/ci_test_lane.py --lane unit --paths tests/test_cpu_pool.py

Каталог отчётов: `.ci/reports/` (§5.1). Каталог целиком временный и в git не
попадает.

Границы задачи: раннер НЕ меняет `pytest.ini`, `.github/workflows/**` и
root-зависимости — они принадлежат `W0-INT-01`. Пока workflow его не вызывает,
он остаётся observe-only инструментом (§«Rollback/integration» W0-OPS-03).
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from ci_redaction import safe_cmdline  # noqa: E402
from ci_timeout_plugin import EXIT_TIMEOUT  # noqa: E402

CONTRACT_ID = "quality-runtime/v1"
CONTRACT_VERSION = "1.1.0"
HARNESS_VERSION = "1.0.0"

REPORT_DIR = ROOT / ".ci" / "reports"
DEFAULT_TEST_PATHS = ("tests", "backend/tests")

#: §7, таблица бюджетов. Значения взяты из контракта дословно и не подбираются
#: здесь: увеличение бюджета ради сокрытия deadlock контрактом запрещено.
LANE_BUDGETS: dict[str, dict[str, float]] = {
    "unit": {"per_test": 30, "wall": 10 * 60},
    "contract": {"per_test": 60, "wall": 10 * 60},
    "integration": {"per_test": 120, "wall": 30 * 60},
    "network": {"per_test": 180, "wall": 20 * 60},
    "chaos": {"per_test": 300, "wall": 20 * 60},
}
LANES = tuple(LANE_BUDGETS)

#: Коды возврата раннера. Отделены от pytest'овых, чтобы CI мог различить
#: «тесты упали» и «прогон непригоден».
EXIT_OK = 0
EXIT_TESTS_FAILED = 1
EXIT_SETUP_FAILURE = 2      # probe не пропустил lane
EXIT_LANE_TIMEOUT = 3       # исчерпан per-test или wall бюджет
EXIT_REPORT_INVALID = 4     # stale/missing/unparseable JUnit
EXIT_NO_TESTS = 5           # выборка пуста — прогон ничего не доказал

#: Коды возврата pytest, при которых прогон непригоден для выводов.
#: 2 — прерван (в т.ч. обрыв сбора), 3 — внутренняя ошибка, 4 — ошибка
#: аргументов. 5 («не собрано ни одного теста») разбирается отдельно: отчёт
#: там как раз исправен, пуста именно выборка.
PYTEST_UNUSABLE_EXITS = frozenset({2, 3, 4})
PYTEST_NO_TESTS_EXIT = 5


# ---------------------------------------------------------------------------
# Журнал событий → счётчики и JUnit
# ---------------------------------------------------------------------------


def read_events(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            # Обрыв последней строки при принудительном снятии процесса —
            # ожидаемая ситуация, а не повод потерять весь журнал.
            continue
    return events


def outcomes_from_events(events: list[dict[str, Any]]) -> dict[str, str]:
    """Свести отчёты фаз в один исход на node ID.

    Одна нода даёт до трёх report'ов (setup/call/teardown). Правило то же, что
    у pytest: ошибка на любой фазе важнее пропуска, пропуск важнее успеха.
    """
    rank = {"passed": 0, "skipped": 1, "failed": 2, "error": 3}
    result: dict[str, str] = {}
    for event in events:
        if event.get("event") != "report":
            continue
        nodeid = str(event.get("nodeid") or "")
        if not nodeid:
            continue
        outcome = str(event.get("outcome") or "passed")
        if event.get("when") in {"setup", "teardown"} and outcome == "failed":
            outcome = "error"
        current = result.get(nodeid)
        if current is None or rank.get(outcome, 0) > rank.get(current, 0):
            result[nodeid] = outcome
    return result


def deselected_count(events: list[dict[str, Any]]) -> int | None:
    """Сумма deselected из журнала. None — если хук ни разу не сработал.

    Ноль и «неизвестно» — разные вещи: при обрыве сборки ноль означал бы
    «ничего не отфильтровано», хотя мы просто не успели узнать.
    """
    seen = False
    total = 0
    for event in events:
        if event.get("event") == "deselected":
            seen = True
            total += int(event.get("count") or 0)
    if not seen:
        # Сессия дошла до сборки, но deselected не было — это честный ноль.
        return 0 if any(e.get("event") == "collected" for e in events) else None
    return total


def timeout_event(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    for event in reversed(events):
        if event.get("event") == "timeout":
            return event
    return None


def active_node(events: list[dict[str, Any]]) -> str | None:
    """Нода, которая была в работе на момент обрыва.

    Нужна при исчерпании WALL-бюджета: там процесс снимает раннер снаружи, и
    watchdog внутри pytest сработать не успевает. §7 распространяет те же пять
    требований на этот случай, поэтому node ID обязан найтись и здесь.
    """
    started: str | None = None
    for event in events:
        kind = event.get("event")
        if kind == "test_start":
            started = str(event.get("nodeid") or "") or None
        elif kind == "test_finish" and started == str(event.get("nodeid") or ""):
            started = None
    return started


#: Псевдо-node для случая, когда прогон оборвался ДО первого теста. Это не
#: pytest node ID и не притворяется им: настоящего ID здесь не существует.
COLLECTION_NODE = "<collection>"


def synthetic_wall_timeout(
    events: list[dict[str, Any]], lane: str, budget: float, elapsed: float
) -> dict[str, Any]:
    """Собрать timeout-событие при wall-таймауте.

    Возвращает событие ВСЕГДА. Когда активной ноды нет — прогон оборвался на
    сборке, например на импорте зависшего `conftest.py`, — событие всё равно
    создаётся, но помечается `kind="collection"`.

    Молчать в этом случае нельзя. §7 закрывается словами «Hang никогда не
    превращается в молчаливый cancel или skip», а раньше здесь получался
    именно он: журнал пуст, `active_node()` возвращал None, JUnit собирался
    как `<testsuite tests="0" failures="0"/>` со статусом `ok`. Код возврата
    был честный, но артефакт, который читают CI и человек, выглядел как «в
    lane просто нечего было запускать».
    """
    node = active_node(events)
    if node is not None:
        return {
            "event": "timeout",
            "kind": "lane_wall_budget",
            "lane": lane,
            "nodeid": node,
            "budget_seconds": budget,
            "elapsed_seconds": round(elapsed, 3),
            "children": [],
            "thread_dump": (
                "wall-clock бюджет lane исчерпан; процесс снят раннером снаружи, "
                "поэтому thread dump изнутри pytest недоступен. Для дампа "
                "конкретного зависшего теста уменьшите --per-test-timeout."
            ),
        }
    return {
        "event": "timeout",
        "kind": "collection",
        "lane": lane,
        "nodeid": COLLECTION_NODE,
        "budget_seconds": budget,
        "elapsed_seconds": round(elapsed, 3),
        "children": [],
        "thread_dump": (
            "Прогон оборван до старта первого теста: ни одного события "
            "test_start в журнале нет. Node ID здесь не существует — искать "
            "надо в сборке: импорт conftest.py, фикстуры уровня сессии, "
            "коллекторы. Повторить с меньшим --lane-budget и смотреть stderr."
        ),
    }


def _split_nodeid(nodeid: str) -> tuple[str, str]:
    """`tests/test_x.py::TestC::test_y` → (classname, name), как у pytest.

    `.py` снимается с ФАЙЛОВОЙ части, а не с конца всей строки. Прежний
    порядок (`replace("/", ".")`, затем `removesuffix(".py")`) на тестах в
    классе не срабатывал вовсе: строка кончалась на `::TestC`, и получалось
    `tests.test_x.py.TestC` вместо `tests.test_x.TestC`.

    Это не косметика. Обычный прогон (JUnit пишет pytest) и прогон с таймаутом
    (JUnit собираем мы) публиковали бы ОДИН узел под разными classname, и
    агрегаторы, ключующиеся на classname+name — история тестов, детектор
    flaky, слияние отчётов нескольких lanes, — теряли бы историю ровно того
    теста, который завис.
    """
    if "::" not in nodeid:
        return nodeid, nodeid
    head, _, tail = nodeid.rpartition("::")
    parts = head.split("::")
    file_part = parts[0].removesuffix(".py").replace("/", ".")
    classname = ".".join([file_part, *parts[1:]])
    return classname, tail


def build_junit_from_events(
    events: list[dict[str, Any]], lane: str, duration: float
) -> ET.ElementTree:
    """Собрать валидный JUnit, когда pytest не успел его дописать."""
    outcomes = outcomes_from_events(events)
    timeout = timeout_event(events)
    if timeout is not None:
        # Зависшая нода успевает отдать report фазы setup, и без этой строки
        # она попала бы в отчёт ДВАЖДЫ: один раз как «passed» по setup и один
        # раз как timeout. Отчёт, в котором зависший тест наполовину зелёный,
        # хуже отсутствующего.
        outcomes.pop(str(timeout.get("nodeid") or ""), None)
    durations: dict[str, float] = {}
    for event in events:
        if event.get("event") == "report" and event.get("when") == "call":
            durations[str(event.get("nodeid"))] = float(event.get("duration") or 0.0)

    counts = {"failures": 0, "errors": 0, "skipped": 0}
    suite = ET.Element("testsuite", {"name": f"ci-lane-{lane}"})
    for nodeid, outcome in sorted(outcomes.items()):
        classname, name = _split_nodeid(nodeid)
        case = ET.SubElement(
            suite,
            "testcase",
            {"classname": classname, "name": name, "time": f"{durations.get(nodeid, 0.0):.3f}"},
        )
        if outcome == "failed":
            ET.SubElement(case, "failure", {"message": "test failed"})
            counts["failures"] += 1
        elif outcome == "error":
            ET.SubElement(case, "error", {"message": "test error"})
            counts["errors"] += 1
        elif outcome == "skipped":
            ET.SubElement(case, "skipped", {"message": "skipped"})
            counts["skipped"] += 1

    if timeout is not None:
        # Зависший тест не имеет report'а — его testcase создаётся здесь, и
        # это единственная запись с type="timeout".
        nodeid = str(timeout.get("nodeid") or "<unknown>")
        classname, name = _split_nodeid(nodeid)
        case = ET.SubElement(
            suite,
            "testcase",
            {
                "classname": classname,
                "name": name,
                "time": f"{float(timeout.get('elapsed_seconds') or 0.0):.3f}",
            },
        )
        # Подпись обязана называть ТОТ бюджет, который исчерпан. Реакция на
        # два случая разная: при per-test сужают тест, при wall разбирают весь
        # lane, а при обрыве на сборке — импорт conftest. Одинаковая подпись
        # уводила дежурного к противоположному выводу.
        kind = str(timeout.get("kind") or "per_test")
        budget_label = {
            "per_test": "per-test timeout",
            "lane_wall_budget": "wall-clock бюджет lane",
            "collection": "бюджет прогона исчерпан на сборке",
        }.get(kind, "timeout")
        failure = ET.SubElement(
            case,
            "failure",
            {
                "type": "timeout",
                "message": (
                    f"{budget_label} {timeout.get('budget_seconds')} s исчерпан "
                    f"за {timeout.get('elapsed_seconds')} s (lane {lane})"
                ),
            },
        )
        children = timeout.get("children") or []
        failure.text = (
            f"node: {nodeid}\nlane: {lane}\n"
            f"дочерних процессов: {len(children)}\n"
            f"{json.dumps(children, ensure_ascii=False, indent=2)}\n\n"
            f"{timeout.get('thread_dump') or ''}"
        )
        counts["failures"] += 1

    suite.set("tests", str(len(outcomes) + (1 if timeout is not None else 0)))
    suite.set("failures", str(counts["failures"]))
    suite.set("errors", str(counts["errors"]))
    suite.set("skipped", str(counts["skipped"]))
    suite.set("time", f"{duration:.3f}")
    return ET.ElementTree(suite)


# ---------------------------------------------------------------------------
# Проверка отчёта (§8)
# ---------------------------------------------------------------------------


def inspect_report(path: Path, started_wall: float) -> tuple[str, dict[str, Any]]:
    """Вернуть (report_status, counts).

    `report_status` ∈ {ok, missing, stale, unparseable} — ровно те три отказа,
    которые §8 объявляет infrastructure failure.
    """
    if not path.is_file():
        return "missing", {}
    # mtime не старше времени старта: иначе разбирается отчёт прошлого прогона.
    # Допуск в секунду — на грубость файловых меток времени.
    if path.stat().st_mtime < started_wall - 1.0:
        return "stale", {}
    try:
        tree = ET.parse(path)
    except ET.ParseError:
        return "unparseable", {}
    counts = {"selected": 0, "passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    for case in tree.iter("testcase"):
        counts["selected"] += 1
        tags = {child.tag for child in case}
        if "error" in tags:
            counts["errors"] += 1
        elif "failure" in tags:
            counts["failed"] += 1
        elif "skipped" in tags:
            counts["skipped"] += 1
        else:
            counts["passed"] += 1
    return "ok", counts


# ---------------------------------------------------------------------------
# Preflight и запуск
# ---------------------------------------------------------------------------


def run_probe(lane: str, enforce: bool, ci: bool = False) -> dict[str, Any]:
    """§6: probe выполняется ДО pytest. Его JSON даёт половину полей receipt."""
    cmd = [sys.executable, str(SCRIPTS / "ci_runtime_probe.py"), "--profile", lane, "--json"]
    if enforce:
        cmd.append("--enforce")
    elif ci:
        cmd.append("--ci")
    try:
        done = subprocess.run(  # noqa: S603
            cmd, capture_output=True, text=True, timeout=300, cwd=str(ROOT)
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"__probe_error__": f"{type(exc).__name__}: {exc}", "exit_code": 1}
    try:
        report = json.loads(done.stdout)
    except json.JSONDecodeError:
        return {
            "__probe_error__": "probe вернул неразбираемый JSON",
            "exit_code": done.returncode,
            "stderr": done.stderr[-2000:],
        }
    report["exit_code"] = done.returncode
    return report


def _kill_group(proc: subprocess.Popen, pgid: int | None) -> None:
    """Снять группу процессов лестницей SIGTERM → SIGKILL.

    PGID передаётся снаружи, а НЕ вычисляется здесь через `os.getpgid(pid)`.
    Причина в порядке событий: после per-test таймаута лидер группы уже вышел
    (watchdog внутри pytest вызывает `os._exit`) и `proc.wait()` его забрал,
    поэтому `os.getpgid()` отвечает `ProcessLookupError` — и прежняя редакция
    молча выходила из функции, не отправив группе ни одного сигнала. Группа
    при этом жива: измерено, `child_alive_after_kill_group: true`. Сама
    группа переживает своего лидера, её идентификатор — не идентификатор
    процесса, и снимать её надо по номеру, сохранённому при запуске.

    Возврат при `ProcessLookupError` от `killpg` остаётся правильным: там он
    означает «в группе никого нет», то есть цель уже достигнута.
    """
    if pgid is None:
        return
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            return          # группа пуста — добивать некого
        except OSError:
            return
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                os.killpg(pgid, 0)
            except ProcessLookupError:
                return      # группа опустела
            except OSError:
                return
            time.sleep(0.05)


def run_lane(args: argparse.Namespace) -> dict[str, Any]:
    lane = args.lane
    budgets = LANE_BUDGETS[lane]
    per_test = float(args.per_test_timeout or budgets["per_test"])
    wall = float(args.lane_budget or budgets["wall"])

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    junit = Path(args.junit) if args.junit else REPORT_DIR / f"{lane}.xml"
    # Журнал и диагностика привязаны к ФАЙЛУ отчёта, а не только к имени lane:
    # иначе прогон с собственным --junit затирал бы журнал штатного прогона
    # того же lane, и два одновременных запуска молча портили бы друг другу
    # отчёты.
    stem = junit.with_suffix("")
    events = Path(f"{stem}.events.jsonl")
    diag = Path(f"{stem}.timeout.json")
    receipt_path = Path(args.receipt) if args.receipt else Path(f"{stem}.receipt.json")

    # Отказ ДО удаления: прогон одного lane не имеет права стереть канонический
    # артефакт другого. Иначе `--lane unit --junit .ci/reports/contract.xml`
    # снёс бы отчёт lane `contract` и записал бы на его место результаты
    # `unit`, а receipt заявил бы `lane: unit` при `junit: contract.xml`.
    # Молча испортить чужой артефакт хуже, чем отказать: следующий разбор
    # пошёл бы по подменённому отчёту.
    # Проверяются ВСЕ четыре артефакта, а не только отчёт и журнал: receipt и
    # диагностика таймаута тоже канонические, и подменить можно любой из них.
    for path, kind in (
        (junit, "junit"), (events, "events"),
        (receipt_path, "receipt"), (diag, "timeout"),
    ):
        foreign = is_foreign_canonical(path, lane, kind)
        if foreign is not None:
            raise SystemExit(
                f"[lane {lane}] FATAL: {kind} указывает на канонический артефакт "
                f"«{foreign}» ({path}). §5.1 задаёт отображение (lane, вид) → свой "
                f"файл; прогон отменён до удаления чужого артефакта.\n"
                f"        Ожидается: {canonical_artifact_path(lane, kind)}"
            )

    # §8: старый отчёт удаляется ДО прогона. Без этого ранняя смерть pytest
    # оставила бы отчёт прошлого раза, и сравнение молча уехало бы на него.
    for path in (junit, events, diag):
        path.unlink(missing_ok=True)

    started_wall = time.time()
    started_mono = time.monotonic()

    probe: dict[str, Any] = {}
    if not args.skip_probe:
        probe = run_probe(lane, args.enforce, args.ci)
        if probe.get("__probe_error__") or probe.get("exit_code"):
            return _finish(
                lane=lane, junit=junit, events=events, receipt_path=receipt_path,
                started_wall=started_wall, started_mono=started_mono, probe=probe,
                exit_code=EXIT_SETUP_FAILURE, command="(probe)", per_test=per_test,
                wall=wall, report_status="missing", counts={}, timed_out=None,
                note="probe не пропустил lane — pytest не запускался (§6, правило 1)",
            )

    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(SCRIPTS)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])
    )
    env["CI_LANE_NAME"] = lane
    env["CI_LANE_PER_TEST_TIMEOUT"] = str(per_test)
    env["CI_LANE_EVENTS"] = str(events)
    env["CI_LANE_DIAG"] = str(diag)

    paths = list(args.paths) if args.paths else list(DEFAULT_TEST_PATHS)
    cmd = [
        sys.executable, "-m", "pytest", *paths,
        "-p", "ci_timeout_plugin",
        "--junitxml", str(junit),
        "-q", "-p", "no:cacheprovider", "--no-header",
    ]
    marker = args.marker
    if marker is None and args.use_lane_marker:
        marker = lane
    if marker is None and lane == "chaos":
        # `pytest.ini` держит `addopts = -m "not chaos"`, поэтому lane chaos без
        # явного выбора маркера гарантированно пуст. Молча отдать «0 тестов»
        # здесь хуже, чем выбрать очевидное: у chaos маркер уже материализован,
        # и §5.1 контракта именно так его и запускает.
        marker = "chaos"
    if marker:
        cmd += ["-m", marker]
    if args.extra:
        cmd += list(args.extra)

    # Своя группа процессов: иначе добить дочерние процессы зависшего теста
    # можно только поимённо, а часть их к тому моменту уже осиротела.
    #
    # При `--json` вывод pytest уводится в stderr. Иначе прогресс-точки pytest
    # перемешиваются с receipt на общем stdout, и машиночитаемый отчёт
    # перестаёт разбираться — ровно то, ради чего он и нужен. Обнаружено на
    # полном наборе: receipt оказался внутри строки точек.
    proc = subprocess.Popen(  # noqa: S603
        cmd, cwd=str(ROOT), env=env, start_new_session=True,
        stdout=(sys.stderr if args.json else None),
    )
    # PGID снимается СРАЗУ и хранится до конца: после выхода лидера группы его
    # уже не узнать, а группа к тому моменту как раз и нуждается в добивании.
    # `start_new_session=True` делает потомка лидером, поэтому pgid == pid, но
    # полагаться на это совпадение нельзя — спрашиваем ядро.
    try:
        child_pgid: int | None = os.getpgid(proc.pid)
    except OSError:
        child_pgid = None
    timed_out_by_wall = False
    try:
        exit_code = proc.wait(timeout=wall)
    except subprocess.TimeoutExpired:
        timed_out_by_wall = True
        _kill_group(proc, child_pgid)
        exit_code = proc.returncode if proc.returncode is not None else EXIT_TIMEOUT
    else:
        if exit_code == EXIT_TIMEOUT:
            # Watchdog внутри pytest снял дерево процессов, какое видел, и вышел
            # через os._exit. Группа — вторая линия: между обходом /proc и
            # выходом зависший тест мог породить ещё процесс, а сирота с
            # занятым портом валит СЛЕДУЮЩИЙ job причиной не из его кода.
            # Раньше добивание группы стояло только на ветке wall-бюджета.
            _kill_group(proc, child_pgid)

    duration = time.monotonic() - started_mono
    event_list = read_events(events)
    timeout_info = timeout_event(event_list)
    if timeout_info is None and timed_out_by_wall:
        timeout_info = synthetic_wall_timeout(event_list, lane, wall, duration)
        event_list.append(timeout_info)

    hit_timeout = exit_code == EXIT_TIMEOUT or timed_out_by_wall or timeout_info is not None
    if hit_timeout:
        # pytest снят принудительно — свежий JUnit собираем из журнала.
        tree = build_junit_from_events(event_list, lane, duration)
        tree.write(junit, encoding="utf-8", xml_declaration=True)

    report_status, counts = inspect_report(junit, started_wall)

    if report_status != "ok":
        final = EXIT_REPORT_INVALID
    elif hit_timeout:
        final = EXIT_LANE_TIMEOUT
    elif exit_code == 0:
        final = EXIT_OK
    elif exit_code == 1:
        final = EXIT_TESTS_FAILED
    elif exit_code == PYTEST_NO_TESTS_EXIT:
        # Пустая выборка — отдельный отказ, а не «битый отчёт». Отчёт здесь
        # как раз исправен; ложное `unparseable` отправило бы дежурного
        # искать повреждённый XML, которого нет. Зелёным такой прогон тоже
        # быть не может: он ничего не доказал.
        final = EXIT_NO_TESTS
    else:
        final = EXIT_REPORT_INVALID

    note = None
    if timed_out_by_wall:
        note = f"исчерпан wall-clock бюджет lane {wall:g} s"
    elif final == EXIT_NO_TESTS:
        note = (
            "выборка пуста: pytest не собрал ни одного теста (код 5). "
            "Отчёт исправен, доказывать нечего — проверьте --paths и -m. "
            "Маркеры lanes материализованы не полностью (§5, находка OPS03-F2), "
            "поэтому --use-lane-marker сегодня почти всегда даёт пустую выборку"
        )
    elif final == EXIT_REPORT_INVALID and report_status == "ok":
        note = (
            f"pytest завершился кодом {exit_code}: прогон оборван и непригоден "
            "для сравнения с baseline (пригодны только 0 и 1)"
        )

    return _finish(
        lane=lane, junit=junit, events=events, receipt_path=receipt_path,
        started_wall=started_wall, started_mono=started_mono, probe=probe,
        # Команда публикуется в той же безопасной форме, что и командные строки
        # дочерних процессов. Сырой argv тут не безопаснее: в него входят
        # пользовательские --paths, выражение маркеров и хвостовые аргументы
        # pytest. Измерено — путь /srv/customers/<id>/test.py и `--token 0427`
        # уходили в receipt дословно. §8 требует ПОЛЕ command, а не сырой argv.
        exit_code=final, command=safe_cmdline(cmd), per_test=per_test, wall=wall,
        report_status=report_status, counts=counts,
        timed_out=(str(timeout_info.get("nodeid")) if timeout_info else None),
        note=note, pytest_exit_code=exit_code,
        deselected=deselected_count(event_list),
    )


#: Канонический каталог отчётов из §5.1. Путь внутри него безопасен не потому,
#: что «лежит в репозитории», а потому, что его форма задана контрактом и не
#: содержит ничего пользовательского: `<lane>` берётся из закрытого списка.
#: ФИЗИЧЕСКИЙ каталог — только для СРАВНЕНИЯ. Нормализуется, потому что
#: сравнение имеет смысл лишь при приведении обеих сторон: если сам каталог
#: окажется symlink'ом, ненормализованная константа не совпала бы ни с одним
#: разрешённым путём, и guard пропускал бы вообще всё.
_CANONICAL_REPORT_DIR = REPORT_DIR.resolve()

#: ЛОГИЧЕСКАЯ метка — только для ПУБЛИКАЦИИ. Отделена от физического пути
#: намеренно: собирать публикуемую строку из разрешённого target значит
#: печатать то, куда ведёт ссылка. Если `.ci/reports` — symlink на
#: `<repo>/private/<customer>/reports`, физический путь несёт идентификатор
#: клиента и уезжает в receipt (P-13), а target ВНЕ репозитория вдобавок роняет
#: `relative_to` с ValueError.
#:
#: Метка задана контрактом §5.1 и одинакова на любой машине, поэтому публикуется
#: она, а не то, что нашлось на диске.
_CANONICAL_REPORT_LABEL = Path(".ci/reports")

#: Суффикс канонического имени по виду артефакта. §5.1 задаёт ОТОБРАЖЕНИЕ
#: lane → собственный файл, а не множество взаимозаменяемых имён: у прогона
#: lane `unit` каноническое имя ровно одно.
#:
#: Прежние две редакции ошибались по нарастающей. Сначала сверялся префикс, и
#: `unit.q7z4m2n8p5r3t6v9.xml` проходил. Потом появился список из десяти имён —
#: но он не знал, КАКОЙ lane выполняется, и `--lane unit --junit
#: .ci/reports/contract.xml` признавался каноническим. Receipt получался
#: внутренне противоречивым: `lane: unit`, `junit: contract.xml`.
#: ВСЕ четыре вида канонических артефактов, а не два. Прежняя таблица знала
#: только отчёт и журнал, поэтому `--lane unit --receipt
#: .ci/reports/network.receipt.json` молча перезаписывал receipt чужого lane, а
#: `--lane unit --junit .ci/reports/network.receipt.json` клал на его место
#: XML. Неполная таблица допустимого — такая же дыра, как её отсутствие.
_CANONICAL_SUFFIX: dict[str, str] = {
    "junit": ".xml",
    "events": ".events.jsonl",
    "receipt": ".receipt.json",
    "timeout": ".timeout.json",
}

#: Обратное отображение «имя файла → вид артефакта». Сравнение идёт по ПОЛНОМУ
#: суффиксу, а не по расширению после первой точки: разбор по первой точке
#: спутал бы `.events.jsonl` с `.xml`. Суффиксы между собой не пересекаются,
#: поэтому порядок перебора значения не имеет — важна именно полнота
#: сравнения.
_SUFFIX_TO_KIND: dict[str, str] = {v: k for k, v in _CANONICAL_SUFFIX.items()}


def canonical_artifact_name(lane: str, kind: str) -> str | None:
    """Единственное каноническое имя файла для пары (lane, вид артефакта)."""
    suffix = _CANONICAL_SUFFIX.get(kind)
    return f"{lane}{suffix}" if suffix and lane in LANES else None


def canonical_artifact_path(lane: str, kind: str) -> Path | None:
    """Единственный канонический путь для пары (lane, вид артефакта)."""
    name = canonical_artifact_name(lane, kind)
    return _CANONICAL_REPORT_DIR / name if name else None


def classify_canonical(path: Path) -> tuple[str, str] | None:
    """Разобрать канонический путь в пару (lane, вид) или вернуть None."""
    resolved = _resolve(path)
    if resolved.parent != _CANONICAL_REPORT_DIR:
        return None
    for suffix, kind in _SUFFIX_TO_KIND.items():
        if resolved.name.endswith(suffix):
            lane = resolved.name[: -len(suffix)]
            if lane in LANES:
                return lane, kind
    return None


def is_foreign_canonical(path: Path, lane: str, kind: str) -> str | None:
    """Чужой канонический артефакт — вернуть описание, иначе None.

    Чужой значит любой из двух случаев: артефакт ДРУГОГО lane либо артефакт
    другого ВИДА у своего же lane. Второй случай не безобиднее первого:
    `--lane unit --junit .ci/reports/unit.receipt.json` положил бы XML на
    место JSON-квитанции того же прогона.

    Проверка нужна ДО удаления и до открытия на запись: `run_lane()` чистит
    старые артефакты перед прогоном. Молча испортить чужой артефакт хуже, чем
    отказать: следующий разбор пошёл бы по подменённому файлу.
    """
    found = classify_canonical(path)
    if found is None:
        return None
    other_lane, other_kind = found
    if other_lane == lane and other_kind == kind:
        return None
    return f"{other_lane}.{other_kind}"


def _resolve(path: Path) -> Path:
    """Привести путь к каноническому абсолютному виду.

    `resolve()` вызывается ВСЕГДА, а не только для относительных путей.
    Прежняя редакция возвращала абсолютный путь как есть, и этого хватало для
    обхода: `.../.ci/reports/../reports/network.xml` указывает ровно на
    канонический артефакт чужого lane, но по строке с ним не совпадает —
    `classify_canonical()` возвращал None, и guard пропускал запись. Так же
    работал бы и symlink-alias.

    Сравнивать пути по написанию — та же ошибка, что сравнивать имена по
    префиксу: одна сущность имеет бесконечно много написаний, и перечислить их
    нельзя. Нормализуются обе стороны сравнения.

    `strict=False`: файла может ещё не быть — артефакт как раз создаётся.
    """
    candidate = path if path.is_absolute() else ROOT / path
    return candidate.resolve(strict=False)


def _publishable_path(path: Path, kind: str, lane: str) -> str:
    """Путь артефакта в форме, пригодной для публикации.

    Обе прежние ветки были неверны, и по одной причине: путь ЦЕЛИКОМ задаётся
    пользователем через `--junit`, а форма пути безопасности не доказывает.

      * внутри репозитория публиковался полный относительный путь —
        `private/q7z4m2n8p5r3t6v9/report.xml` уезжал в receipt как есть;
      * снаружи оставалось имя файла — `/tmp/q7z4m2n8p5r3t6v9.xml`
        превращалось в `q7z4m2n8p5r3t6v9.xml`, то есть секрет сохранялся
        целиком.

    Поэтому полный путь публикуется ТОЛЬКО для единственного канонического
    имени ТЕКУЩЕГО lane: `.ci/reports/<lane>.xml` и
    `.ci/reports/<lane>.events.jsonl`. §5.1 задаёт отображение lane → свой
    файл, а не набор взаимозаменяемых имён, поэтому имя чужого lane
    каноническим здесь не является.

    Сравнение идёт с полным именем, а не с префиксом:
    `unit.q7z4m2n8p5r3t6v9.xml` тоже начинается с имени lane и при проверке по
    префиксу публиковался целиком.

    Любой другой путь заменяется меткой вида `<custom-junit>`: где лежит
    артефакт, знает тот, кто задал `--junit`, а receipt для этого не нужен.
    """
    resolved = _resolve(path)
    expected = canonical_artifact_name(lane, kind)
    if expected and resolved.parent == _CANONICAL_REPORT_DIR and resolved.name == expected:
        # Сравнение — по физическому каталогу, публикация — по логической
        # метке. Разные роли и потому разные значения: физический путь может
        # вести куда угодно, включая приватный каталог с идентификатором
        # клиента или вовсе наружу репозитория.
        return (_CANONICAL_REPORT_LABEL / expected).as_posix()
    return f"<custom-{kind}>"


def _finish(
    *, lane: str, junit: Path, events: Path, receipt_path: Path,
    started_wall: float, started_mono: float, probe: dict[str, Any],
    exit_code: int, command: str, per_test: float, wall: float,
    report_status: str, counts: dict[str, Any], timed_out: str | None,
    note: str | None = None, pytest_exit_code: int | None = None,
    deselected: int | None = None,
) -> dict[str, Any]:
    """Собрать §8 receipt. Поля перечислены контрактом дословно."""
    env = probe.get("environment") or {}
    receipt = {
        "contract_id": CONTRACT_ID,
        "contract_version": CONTRACT_VERSION,
        "harness_version": HARNESS_VERSION,
        "source_commit": probe.get("source_commit"),
        # §8 требует provenance; источник записывается рядом со значением,
        # потому что env-переменная — более слабое доказательство, чем git.
        "source_commit_origin": probe.get("source_commit_origin"),
        "lane": lane,
        "command": command,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started_wall)),
        "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "duration_seconds": round(time.monotonic() - started_mono, 3),
        "exit_code": exit_code,
        "pytest_exit_code": pytest_exit_code,
        "selected": counts.get("selected", 0),
        "passed": counts.get("passed", 0),
        "failed": counts.get("failed", 0),
        "errors": counts.get("errors", 0),
        "skipped": counts.get("skipped", 0),
        # В JUnit числа deselected нет; оно приходит из хука pytest_deselected
        # через журнал событий. null означает «не удалось узнать» (сборка
        # оборвалась), а не ноль — путать эти два случая нельзя.
        "deselected": deselected,
        "timed_out_node": timed_out,
        "per_test_timeout_seconds": per_test,
        "lane_wall_budget_seconds": wall,
        "os_image": env.get("os_image"),
        "architecture": env.get("architecture"),
        "uid": env.get("uid", os.getuid()),
        "python_version": env.get("python_version"),
        "node_version": env.get("node_version"),
        "npm_version": env.get("npm_version"),
        "python_lock_sha256": probe.get("python_lock_sha256"),
        "pip_freeze_sha256": probe.get("pip_freeze_sha256"),
        "frontend_lock_sha256": probe.get("frontend_lock_sha256"),
        "capabilities": probe.get("capabilities") or {},
        "norm_artifact_sha256": probe.get("norm_artifact_sha256"),
        "report_status": report_status,
        # Путь внутри репозитория безопасен и полезен — это наша же раскладка.
        # Путь СНАРУЖИ задан пользователем и может нести каталог клиента,
        # поэтому от него остаётся только имя файла.
        "junit": _publishable_path(junit, "junit", lane),
        "receipt": _publishable_path(receipt_path, "receipt", lane),
        "events": _publishable_path(events, "events", lane),
        "probe_ran": bool(probe),
        # Строгость preflight — часть свидетельства: в режиме local
        # профильные проверки §3 лишь информативны, в ci/enforce обязательны.
        "probe_mode": probe.get("mode"),
        "probe_exit_code": probe.get("exit_code"),
        "note": note,
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return receipt


def render(receipt: dict[str, Any]) -> str:
    lines = [
        f"[lane {receipt['lane']}] exit={receipt['exit_code']} "
        f"report={receipt['report_status']} "
        f"за {receipt['duration_seconds']:.1f} s",
        f"  тестов {receipt['selected']}: passed {receipt['passed']}, "
        f"failed {receipt['failed']}, errors {receipt['errors']}, "
        f"skipped {receipt['skipped']}",
        f"  бюджеты: per-test {receipt['per_test_timeout_seconds']:g} s, "
        f"lane {receipt['lane_wall_budget_seconds']:g} s",
    ]
    if receipt.get("timed_out_node"):
        lines.append(f"  ТАЙМАУТ: {receipt['timed_out_node']}")
    if receipt.get("note"):
        lines.append(f"  {receipt['note']}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--lane", required=True, choices=LANES)
    parser.add_argument("--paths", nargs="*", help="пути с тестами (по умолчанию tests backend/tests)")
    parser.add_argument("-m", "--marker", help="выражение маркеров для -m")
    parser.add_argument(
        "--use-lane-marker",
        action="store_true",
        help="выбирать тесты по маркеру, одноимённому lane (§5.1). Пока маркеры "
        "не материализованы полностью, выборка будет почти пустой — включать "
        "после W0-OPS-03 §5 и разметки, владелец переключения W0-INT-01",
    )
    parser.add_argument("--per-test-timeout", type=float, help="переопределить бюджет теста (§7)")
    parser.add_argument("--lane-budget", type=float, help="переопределить wall-clock бюджет lane")
    parser.add_argument("--junit", help="путь JUnit (по умолчанию .ci/reports/<lane>.xml)")
    parser.add_argument("--receipt", help="путь JSON receipt")
    parser.add_argument("--skip-probe", action="store_true", help="не запускать capability probe")
    parser.add_argument("--enforce", action="store_true", help="probe в enforce-профиле (§3 + corpus §3.3)")
    parser.add_argument("--ci", action="store_true", help="probe в режиме CI-полосы (§6 правило 1): без послаблений §6.2, corpus пока optional")
    parser.add_argument("--json", action="store_true", help="печатать receipt на stdout")
    parser.add_argument("extra", nargs="*", help="дополнительные аргументы pytest после --")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    receipt = run_lane(args)
    if args.json:
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
    else:
        print(render(receipt))
    return int(receipt["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
