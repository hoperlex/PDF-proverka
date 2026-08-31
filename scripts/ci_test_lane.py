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

from ci_timeout_plugin import EXIT_TIMEOUT  # noqa: E402

CONTRACT_ID = "quality-runtime/v1"
CONTRACT_VERSION = "1.0.0"
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


def run_probe(lane: str, enforce: bool) -> dict[str, Any]:
    """§6: probe выполняется ДО pytest. Его JSON даёт половину полей receipt."""
    cmd = [sys.executable, str(SCRIPTS / "ci_runtime_probe.py"), "--profile", lane, "--json"]
    if enforce:
        cmd.append("--enforce")
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


def _kill_group(proc: subprocess.Popen) -> None:
    """Снять группу процессов лестницей SIGTERM → SIGKILL."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(os.getpgid(proc.pid), sig)
        except (OSError, ProcessLookupError):
            return
        try:
            proc.wait(timeout=5)
            return
        except subprocess.TimeoutExpired:
            continue


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

    # §8: старый отчёт удаляется ДО прогона. Без этого ранняя смерть pytest
    # оставила бы отчёт прошлого раза, и сравнение молча уехало бы на него.
    for path in (junit, events, diag):
        path.unlink(missing_ok=True)

    started_wall = time.time()
    started_mono = time.monotonic()

    probe: dict[str, Any] = {}
    if not args.skip_probe:
        probe = run_probe(lane, args.enforce)
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
    timed_out_by_wall = False
    try:
        exit_code = proc.wait(timeout=wall)
    except subprocess.TimeoutExpired:
        timed_out_by_wall = True
        _kill_group(proc)
        exit_code = proc.returncode if proc.returncode is not None else EXIT_TIMEOUT
    else:
        if exit_code == EXIT_TIMEOUT:
            # Watchdog внутри pytest снял дерево процессов, какое видел, и вышел
            # через os._exit. Группа — вторая линия: между обходом /proc и
            # выходом зависший тест мог породить ещё процесс, а сирота с
            # занятым портом валит СЛЕДУЮЩИЙ job причиной не из его кода.
            # Раньше добивание группы стояло только на ветке wall-бюджета.
            _kill_group(proc)

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
        exit_code=final, command=" ".join(cmd), per_test=per_test, wall=wall,
        report_status=report_status, counts=counts,
        timed_out=(str(timeout_info.get("nodeid")) if timeout_info else None),
        note=note, pytest_exit_code=exit_code,
        deselected=deselected_count(event_list),
    )


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
        "junit": str(junit.relative_to(ROOT)) if junit.is_relative_to(ROOT) else str(junit),
        "events": str(events.relative_to(ROOT)) if events.is_relative_to(ROOT) else str(events),
        "probe_ran": bool(probe),
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
    parser.add_argument("--enforce", action="store_true", help="probe в enforce-профиле")
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
