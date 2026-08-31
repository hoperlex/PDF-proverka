"""Тесты раннера test lane (`scripts/ci_test_lane.py`), W0-OPS-03.

Раннер отвечает за §7–§8 контракта
`docs/architecture/QUALITY_RUNTIME_CONTRACT_V1.md`: hang обязан превращаться в
диагностируемый bounded failure, а отчёт — быть свежим или отсутствовать.
Проверяется здесь именно это, а не «раннер запускается»:

* зависший тест даёт ненулевой код, node ID в receipt и РОВНО ОДИН
  `<failure type="timeout">` именно с этим node ID;
* обычное падение и таймаут различимы машинно: у обычного падения нет
  `type="timeout"`, у таймаута — свой код возврата;
* зависшая нода не попадает в отчёт дважды. Она успевает отдать report фазы
  `setup`, и без явного вычёркивания оказалась бы в JUnit и как «passed», и как
  timeout. Наполовину зелёный зависший тест хуже отсутствующего отчёта;
* старый JUnit и старый журнал событий не переиспользуются: §8 требует
  удаления ДО прогона, иначе ранняя смерть pytest молча подсовывает прошлый
  результат;
* stale/missing/unparseable распознаются как infrastructure failure;
* receipt несёт ВСЕ поля из §8 — список берётся из самого документа;
* таблица бюджетов §7 сверяется с ДОКУМЕНТОМ, а не с числами, переписанными в
  тест. Смысл в том, чтобы расхождение кода и контракта ловилось автоматически:
  «увеличение timeout для сокрытия deadlock не принимается» (§7).

Изоляция и дисциплина прогона
─────────────────────────────
Тяжёлые сценарии гоняются через subprocess с маленькими бюджетами, чтобы весь
файл шёл секунды. Раннер работает не в этом репозитории, а в его КОПИИ внутри
tmp_path: свой `ROOT` он вычисляет от собственного `__file__`, и вместе с ним
переезжает ВЕСЬ каталог отчётов, включая `REPORT_DIR`, который создаётся
безусловно. Иначе тесты писали бы в `.ci/reports/` живого дерева и дрались бы
за одни и те же файлы с параллельным прогоном раннера — а прогон здесь бывает
и зависший по замыслу. Копия, а не symlink: `Path(__file__).resolve()`
разыменовал бы ссылку и вернул раннер обратно в репозиторий. Побочная выгода:
у pytest внутри копии свой rootdir без `pytest.ini` и `conftest.py` проекта,
поэтому сценарии детерминированы и не тащат тяжёлую тестовую инфраструктуру.

Каждый поднятый процесс добивается в `finally`, каждому прогону задан явный
`--lane-budget`, поэтому осиротевших процессов после файла не остаётся.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
CONTRACT_PATH = ROOT / "docs" / "architecture" / "QUALITY_RUNTIME_CONTRACT_V1.md"


def _load(name: str, path: Path):
    """Загрузить скрипт как модуль, не оставляя следов в sys.path.

    `ci_test_lane` сам делает `sys.path.insert(0, scripts)`, чтобы дотянуться до
    плагина. В нашем процессе это подсунуло бы каталог `scripts/` первым в
    путь импорта на весь прогон — 70 модулей, способных затенить чужие имена.
    Поэтому путь восстанавливается сразу после загрузки.
    """
    saved = list(sys.path)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = saved
    return module


_load("ci_timeout_plugin", SCRIPTS / "ci_timeout_plugin.py")
lane_mod = _load("ci_test_lane", SCRIPTS / "ci_test_lane.py")


# --------------------------------------------------------------------------
# Чтение контракта: тест сверяется с документом, а не с копией чисел
# --------------------------------------------------------------------------


def contract_section(number: int) -> str:
    """Текст раздела «## N. …» до следующего раздела того же уровня."""
    text = CONTRACT_PATH.read_text(encoding="utf-8")
    head = re.search(rf"^## {number}\.[^\n]*$", text, re.MULTILINE)
    assert head is not None, f"в контракте нет раздела {number}"
    tail = text[head.end() :]
    nxt = re.search(r"^## \d+\.", tail, re.MULTILINE)
    return tail if nxt is None else tail[: nxt.start()]


def contract_budgets() -> dict[str, dict[str, float]]:
    """Таблица §7 «Lane → per-test timeout / wall-clock budget» из документа."""
    units = {"s": 1.0, "min": 60.0, "h": 3600.0}
    budgets: dict[str, dict[str, float]] = {}
    for row in re.finditer(
        r"^\|\s*`(\w+)`\s*\|\s*([\d.]+)\s*(s|min|h)\s*\|\s*([\d.]+)\s*(s|min|h)\s*\|",
        contract_section(7),
        re.MULTILINE,
    ):
        lane, per_test, per_unit, wall, wall_unit = row.groups()
        budgets[lane] = {
            "per_test": float(per_test) * units[per_unit],
            "wall": float(wall) * units[wall_unit],
        }
    assert budgets, "не удалось разобрать таблицу бюджетов §7"
    return budgets


def contract_receipt_fields() -> list[str]:
    """Список обязательных полей receipt из блока ```text в §8."""
    block = re.search(r"```text\n(.*?)```", contract_section(8), re.DOTALL)
    assert block is not None, "в §8 нет блока с полями receipt"
    fields = re.findall(r"[a-z][a-z0-9_]+", block.group(1))
    assert "contract_id" in fields and "report_status" in fields
    return fields


# --------------------------------------------------------------------------
# Изолированная копия раннера
# --------------------------------------------------------------------------

#: Пороговый бюджет тестового прогона. Все сценарии обязаны укладываться в
#: секунды; всё, что дольше, — признак того, что раннер завис сам.
CLI_HARD_LIMIT = 90.0


class Harness:
    """Копия раннера со своим ROOT: артефакты не выходят за tmp_path."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.runner = root / "scripts" / "ci_test_lane.py"
        self.tests_dir = root / "t"
        self.junit = root / "report.xml"
        self.receipt_path = root / "receipt.json"

    def write_module(self, name: str, source: str) -> str:
        """Записать синтетический тест-модуль; вернуть его node-префикс."""
        path = self.tests_dir / name
        path.write_text(source, encoding="utf-8")
        # pytest считает node ID от rootdir, а rootdir здесь — корень копии.
        return path.relative_to(self.root).as_posix()

    def events_path(self) -> Path:
        """Фактический путь журнала событий.

        Раньше он брался из receipt. Так больше нельзя: receipt публикует путь
        только для канонической раскладки `.ci/reports/<lane>.*`, а для любого
        своего `--junit` отдаёт метку `<custom-events>` — путь целиком задан
        пользователем, и его форма безопасности не доказывает.

        Тест знает, какой `--junit` он передал, поэтому вычисляет журнал по
        тому же правилу, что и раннер: рядом с отчётом, с заменой расширения.
        """
        return self.junit.with_suffix("").with_suffix(".events.jsonl")

    def run(
        self,
        *extra: str,
        lane: str = "unit",
        paths: list[str] | None = None,
        per_test: float | None = 5.0,
        wall: float | None = 30.0,
        skip_probe: bool = True,
        timeout: float = CLI_HARD_LIMIT,
    ) -> subprocess.CompletedProcess:
        argv = ["--lane", lane]
        if skip_probe:
            argv.append("--skip-probe")
        if per_test is not None:
            argv += ["--per-test-timeout", str(per_test)]
        if wall is not None:
            argv += ["--lane-budget", str(wall)]
        argv += ["--junit", str(self.junit), "--receipt", str(self.receipt_path)]
        argv += list(extra)
        # `--paths` (nargs="*") идёт последним: иначе argparse отдаёт ему и
        # хвостовые аргументы тоже.
        argv += ["--paths", *(paths if paths is not None else [str(self.tests_dir)])]
        return run_cli(self, argv, timeout=timeout)

    def receipt(self) -> dict:
        return json.loads(self.receipt_path.read_text(encoding="utf-8"))

    def junit_root(self) -> ET.Element:
        return ET.parse(self.junit).getroot()

    def testcases(self) -> list[ET.Element]:
        return list(self.junit_root().iter("testcase"))


def run_cli(harness: Harness, argv: list[str], timeout: float) -> subprocess.CompletedProcess:
    """Запустить раннер как CLI, гарантированно ничего за собой не оставив.

    Раннер и его pytest живут в отдельных сессиях процессов, поэтому при
    выходе за внешний бюджет группа добивается вручную: тест не имеет права
    оставить осиротевший pytest, спящий 600 секунд.
    """
    proc = subprocess.Popen(
        [sys.executable, str(harness.runner), *argv],
        cwd=str(harness.root),
        env={**os.environ, "AUDIT_DISABLE_DOTENV": "1", "PYTHONDONTWRITEBYTECODE": "1"},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(os.getpgid(proc.pid), sig)
            except OSError:
                break
            try:
                proc.wait(timeout=5)
                break
            except subprocess.TimeoutExpired:
                continue
        out, err = proc.communicate(timeout=10)
        pytest.fail(
            f"раннер не уложился в {timeout:g}s — он сам стал источником "
            f"зависания, от которого защищает\nstdout:\n{out}\nstderr:\n{err[-2000:]}"
        )
    return subprocess.CompletedProcess(proc.args, proc.returncode, out, err)


@pytest.fixture
def harness(tmp_path: Path) -> Harness:
    """Свежая копия раннера и плагина на каждый тест.

    Копия, а не symlink: `Path(__file__).resolve()` разыменовал бы ссылку и
    вернул раннер в настоящий репозиторий вместе со всеми его артефактами.
    Копируется прямо перед тестом, поэтому проверяется текущий код скриптов.
    """
    root = tmp_path / "lane_root"
    (root / "scripts").mkdir(parents=True)
    (root / "t").mkdir()
    # `ci_redaction.py` копируется вместе с ними: плагин импортирует правило
    # redaction, и без него он вообще не грузится. Список — единственное место,
    # где связь раннера с его модулями зафиксирована, поэтому новая зависимость
    # обязана появляться здесь же.
    for script in ("ci_test_lane.py", "ci_timeout_plugin.py", "ci_redaction.py"):
        shutil.copy2(SCRIPTS / script, root / "scripts" / script)
    return Harness(root)


# --------------------------------------------------------------------------
# Синтетические тест-модули
# --------------------------------------------------------------------------

SOURCE_HANG = """import time


def test_fast_ok():
    assert True


def test_hangs_forever():
    time.sleep(600)


def test_never_reached():
    assert True
"""

SOURCE_MIXED = """import pytest


def test_ok():
    assert True


def test_plain_failure():
    assert 1 == 2


def test_skipped():
    pytest.skip("нарочно пропущен")


@pytest.fixture
def broken():
    raise RuntimeError("падение на setup")


def test_setup_error(broken):
    assert True
"""

SOURCE_GREEN = """def test_green_one():
    assert True


def test_green_two():
    assert True
"""


# --------------------------------------------------------------------------
# §7: бюджеты кода = бюджеты контракта
# --------------------------------------------------------------------------


def test_lane_budgets_match_contract_table():
    """LANE_BUDGETS сверяется с таблицей §7, разобранной из документа.

    Числа сознательно не переписаны в тест: тогда правка кода и правка теста
    делались бы одной рукой, и расхождение с контрактом прошло бы незамеченным.
    §7 прямо запрещает подбирать бюджеты «по месту», так что источник истины
    здесь — только документ.
    """
    assert lane_mod.LANE_BUDGETS == contract_budgets()


def test_lane_budgets_cover_exactly_contract_lanes():
    """Набор lanes тоже не должен разъезжаться с §5/§7."""
    assert set(lane_mod.LANE_BUDGETS) == set(contract_budgets())
    assert tuple(lane_mod.LANES) == ("unit", "contract", "integration", "network", "chaos")


def test_runner_exit_codes_are_pairwise_distinct():
    """CI обязан различать «тесты упали» и «прогон непригоден» по коду."""
    codes = {
        "ok": lane_mod.EXIT_OK,
        "tests_failed": lane_mod.EXIT_TESTS_FAILED,
        "setup_failure": lane_mod.EXIT_SETUP_FAILURE,
        "lane_timeout": lane_mod.EXIT_LANE_TIMEOUT,
        "report_invalid": lane_mod.EXIT_REPORT_INVALID,
    }
    assert len(set(codes.values())) == len(codes), codes
    assert codes["ok"] == 0
    assert all(code != 0 for name, code in codes.items() if name != "ok")


# --------------------------------------------------------------------------
# §7: зависший тест
# --------------------------------------------------------------------------


def test_hanging_test_becomes_bounded_timeout_failure(harness: Harness):
    """Зависание превращается в диагностируемый failure, а не в вечное ожидание.

    Проверяются все машиночитаемые следствия §7 сразу: ненулевой код, node ID
    в receipt и ровно один `<failure type="timeout">` именно с этим node ID.
    """
    module = harness.write_module("test_hang.py", SOURCE_HANG)
    node = f"{module}::test_hangs_forever"

    started = time.monotonic()
    done = harness.run(per_test=3, wall=40)
    elapsed = time.monotonic() - started

    assert done.returncode == lane_mod.EXIT_LANE_TIMEOUT, done.stdout + done.stderr
    assert done.returncode != 0
    assert elapsed < 30.0, f"бюджет 3 s, а прогон занял {elapsed:.1f}s"

    receipt = harness.receipt()
    assert receipt["timed_out_node"] == node
    assert receipt["exit_code"] == done.returncode
    assert receipt["report_status"] == "ok", "свежий JUnit обязан быть собран"
    # §7, требование 5: код таймаута доходит от плагина до раннера неизменным.
    assert receipt["pytest_exit_code"] == lane_mod.EXIT_TIMEOUT

    timeouts = [
        (case, failure)
        for case in harness.testcases()
        for failure in case.findall("failure")
        if failure.get("type") == "timeout"
    ]
    assert len(timeouts) == 1, "timeout обязан быть ровно один"
    case, failure = timeouts[0]
    assert case.get("name") == "test_hangs_forever"
    assert node in (failure.text or ""), "в теле failure нет полного node ID"
    assert "unit" in (failure.text or "")


def test_hanging_node_is_reported_exactly_once(harness: Harness):
    """Зависшая нода не попадает в отчёт дважды.

    Это реальный дефект, а не гипотеза: нода успевает отдать report фазы
    `setup` со статусом `passed` ДО того, как сработает watchdog. Если этот
    report не вычеркнуть, JUnit получит два testcase с одним именем — зелёный
    и timeout, — и любой агрегатор посчитает зависший тест наполовину
    успешным. Тест сначала доказывает, что ловушка на месте (setup-report в
    журнале есть), и только потом проверяет отчёт.
    """
    module = harness.write_module("test_hang.py", SOURCE_HANG)
    node = f"{module}::test_hangs_forever"

    harness.run(per_test=3, wall=40)

    events = [
        json.loads(line)
        for line in harness.events_path().read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    setup_reports = [
        event
        for event in events
        if event.get("event") == "report"
        and event.get("nodeid") == node
        and event.get("when") == "setup"
    ]
    assert setup_reports, "ловушка не воспроизвелась: setup-report зависшей ноды нет"
    assert setup_reports[0]["outcome"] == "passed"

    named = [case for case in harness.testcases() if case.get("name") == "test_hangs_forever"]
    assert len(named) == 1, "зависшая нода попала в отчёт дважды"
    assert named[0].find("failure") is not None
    assert named[0].find("failure").get("type") == "timeout"

    # Успевший пройти тест остался в отчёте, недостижимый — нет.
    names = {case.get("name") for case in harness.testcases()}
    assert "test_fast_ok" in names
    assert "test_never_reached" not in names


def test_lane_wall_budget_names_active_node(harness: Harness):
    """При исчерпании wall-бюджета §7 требует те же пять пунктов для активной ноды.

    Здесь watchdog внутри pytest сработать не успевает — процесс снимает
    раннер снаружи, — поэтому node ID приходится восстанавливать из журнала
    событий. Без этого зависание по wall-бюджету осталось бы безымянным.
    """
    module = harness.write_module("test_hang.py", SOURCE_HANG)
    node = f"{module}::test_hangs_forever"

    started = time.monotonic()
    done = harness.run(per_test=60, wall=3)
    elapsed = time.monotonic() - started

    assert done.returncode == lane_mod.EXIT_LANE_TIMEOUT, done.stdout + done.stderr
    assert elapsed < 30.0, f"wall-бюджет 3 s, а прогон занял {elapsed:.1f}s"

    receipt = harness.receipt()
    assert receipt["timed_out_node"] == node
    assert receipt["report_status"] == "ok"
    assert "wall" in (receipt["note"] or "").lower()

    timeouts = [
        failure
        for case in harness.testcases()
        for failure in case.findall("failure")
        if failure.get("type") == "timeout"
    ]
    assert len(timeouts) == 1
    assert node in (timeouts[0].text or "")


def test_timeout_and_plain_failure_are_machine_distinguishable(harness: Harness):
    """Обычное падение не имеет права выглядеть как таймаут, и наоборот.

    Если бы hang и assert-падение приходили в CI одинаково, §7 сводился бы к
    «тесты покраснели»: дежурный не отличил бы deadlock от логической ошибки
    ни по коду возврата, ни по JUnit.
    """
    harness.write_module("test_mixed.py", SOURCE_MIXED)
    done = harness.run(per_test=10, wall=40)

    assert done.returncode == lane_mod.EXIT_TESTS_FAILED
    receipt = harness.receipt()
    assert receipt["timed_out_node"] is None
    assert receipt["report_status"] == "ok"

    failures = [
        failure for case in harness.testcases() for failure in case.findall("failure")
    ]
    assert failures, "падения обязаны быть в отчёте"
    assert all(failure.get("type") != "timeout" for failure in failures)

    assert receipt["passed"] >= 1
    assert receipt["failed"] >= 1
    assert receipt["skipped"] == 1
    assert receipt["errors"] == 1, "падение на setup — это error, а не failure"
    assert receipt["selected"] == 4


# --------------------------------------------------------------------------
# §8: свежесть отчёта
# --------------------------------------------------------------------------


def test_stale_junit_is_not_reused(harness: Harness):
    """Отчёт прошлого прогона обязан быть удалён ДО запуска pytest.

    Иначе ранняя смерть pytest оставляет старый файл на месте, `inspect_report`
    видит «отчёт есть», и сравнение молча уезжает на прошлый результат — самый
    опасный вид зелёного CI.
    """
    harness.junit.write_text(
        '<?xml version="1.0"?><testsuite name="прошлый прогон" tests="1" '
        'failures="0"><testcase classname="из_прошлого" name="из_прошлого"/>'
        "</testsuite>",
        encoding="utf-8",
    )
    ancient = time.time() - 30 * 24 * 3600
    os.utime(harness.junit, (ancient, ancient))
    harness.write_module("test_green.py", SOURCE_GREEN)

    started = time.time()
    done = harness.run(per_test=10, wall=40)

    assert done.returncode == lane_mod.EXIT_OK, done.stdout + done.stderr
    assert harness.junit.stat().st_mtime >= started - 1.0, "mtime отчёта не обновился"

    text = harness.junit.read_text(encoding="utf-8")
    assert "из_прошлого" not in text, "переиспользован отчёт прошлого прогона"
    names = {case.get("name") for case in harness.testcases()}
    assert names == {"test_green_two", "test_green_one"} or names == {
        "test_green_one",
        "test_green_two",
    }
    assert harness.receipt()["report_status"] == "ok"
    assert harness.receipt()["selected"] == 2


def test_stale_event_journal_cannot_poison_a_clean_run(harness: Harness):
    """Журнал событий прошлого прогона тоже удаляется до старта.

    Журнал — источник, из которого собирается JUnit при таймауте. Уцелевшее
    timeout-событие прошлого раза объявило бы зелёный прогон зависшим и назвало
    бы node ID теста, который сегодня даже не запускался.
    """
    harness.write_module("test_green.py", SOURCE_GREEN)
    # Первый прогон нужен только чтобы узнать фактический путь журнала.
    assert harness.run(per_test=10, wall=40).returncode == lane_mod.EXIT_OK
    journal = harness.events_path()
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_text(
        json.dumps(
            {
                "event": "timeout",
                "lane": "unit",
                "nodeid": "t/призрак.py::test_из_прошлого",
                "budget_seconds": 1,
                "elapsed_seconds": 1,
                "children": [],
                "thread_dump": "",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    done = harness.run(per_test=10, wall=40)

    assert done.returncode == lane_mod.EXIT_OK, done.stdout + done.stderr
    receipt = harness.receipt()
    assert receipt["timed_out_node"] is None
    assert "призрак" not in harness.junit.read_text(encoding="utf-8")


def test_inspect_report_detects_missing_stale_and_unparseable(tmp_path: Path):
    """§8: три и только три вида непригодного отчёта распознаются по имени.

    Каждый из них — infrastructure failure, даже если pytest вернул ноль,
    поэтому их нельзя ни свести в один статус, ни спутать с «ok».
    """
    started = time.time()

    missing = tmp_path / "нет-такого.xml"
    assert lane_mod.inspect_report(missing, started) == ("missing", {})

    stale = tmp_path / "stale.xml"
    stale.write_text('<testsuite tests="1"><testcase name="a"/></testsuite>', encoding="utf-8")
    ancient = started - 3600
    os.utime(stale, (ancient, ancient))
    status, counts = lane_mod.inspect_report(stale, started)
    assert status == "stale", "старый по mtime отчёт принят за свежий"
    assert counts == {}

    broken = tmp_path / "broken.xml"
    broken.write_text("<testsuite><testcase name=", encoding="utf-8")
    assert lane_mod.inspect_report(broken, started) == ("unparseable", {})


def test_inspect_report_counts_every_outcome(tmp_path: Path):
    """Счётчики receipt берутся отсюда, поэтому разбор исходов проверяется явно."""
    report = tmp_path / "ok.xml"
    report.write_text(
        "<testsuite>"
        '<testcase classname="t" name="p"/>'
        '<testcase classname="t" name="f"><failure message="x"/></testcase>'
        '<testcase classname="t" name="e"><error message="x"/></testcase>'
        '<testcase classname="t" name="s"><skipped message="x"/></testcase>'
        "</testsuite>",
        encoding="utf-8",
    )
    status, counts = lane_mod.inspect_report(report, time.time() - 0.5)
    assert status == "ok"
    assert counts == {"selected": 4, "passed": 1, "failed": 1, "errors": 1, "skipped": 1}


def test_fresh_report_survives_coarse_mtime(tmp_path: Path):
    """Допуск в секунду обязателен: файловые метки времени грубее старта прогона."""
    report = tmp_path / "fresh.xml"
    report.write_text("<testsuite/>", encoding="utf-8")
    almost = report.stat().st_mtime + 0.9
    assert lane_mod.inspect_report(report, almost)[0] == "ok"
    assert lane_mod.inspect_report(report, report.stat().st_mtime + 5.0)[0] == "stale"


# --------------------------------------------------------------------------
# §8: receipt
# --------------------------------------------------------------------------


def test_receipt_carries_every_field_required_by_section_8(harness: Harness):
    """Список полей берётся из §8 документа, а не переписан в тест.

    Receipt — единственный машиночитаемый результат lane; отсутствующее поле
    ломает обязательные метрики §8 (completion ratio, timeout count,
    missing/stale report count) молча, без единой ошибки в CI.
    """
    harness.write_module("test_green.py", SOURCE_GREEN)
    done = harness.run(per_test=10, wall=40)
    assert done.returncode == lane_mod.EXIT_OK, done.stdout + done.stderr

    receipt = harness.receipt()
    missing = [field for field in contract_receipt_fields() if field not in receipt]
    assert not missing, f"в receipt нет полей §8: {missing}"

    assert receipt["contract_id"] == "quality-runtime/v1"
    assert receipt["lane"] == "unit"
    assert "pytest" in receipt["command"]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", receipt["started_at"])
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", receipt["completed_at"])
    assert receipt["duration_seconds"] > 0
    assert receipt["uid"] == os.getuid()
    assert receipt["report_status"] == "ok"
    assert receipt["timed_out_node"] is None


def test_receipt_json_on_stdout_matches_file(harness: Harness):
    """`--json` обязан отдавать ровно то же, что легло в файл receipt."""
    harness.write_module("test_green.py", SOURCE_GREEN)
    done = harness.run("--json", per_test=10, wall=40)
    assert done.returncode == lane_mod.EXIT_OK, done.stderr
    assert json.loads(done.stdout) == harness.receipt()


def test_timeout_receipt_and_junit_agree(harness: Harness):
    """Receipt и JUnit не должны расходиться в том, что и сколько случилось."""
    harness.write_module("test_hang.py", SOURCE_HANG)
    harness.run(per_test=3, wall=40)

    receipt = harness.receipt()
    suite = harness.junit_root()
    assert receipt["selected"] == len(harness.testcases()) == int(suite.get("tests"))
    assert receipt["failed"] == int(suite.get("failures"))
    assert receipt["errors"] == int(suite.get("errors"))
    assert receipt["skipped"] == int(suite.get("skipped"))
    # §8: JUnit несёт длительность и на уровне suite, и на уровне ноды.
    assert float(suite.get("time")) > 0
    assert all(case.get("time") is not None for case in harness.testcases())


# --------------------------------------------------------------------------
# §6, правило 1: probe не пропустил lane — pytest не запускался
# --------------------------------------------------------------------------


def write_probe_stub(harness: Harness, exit_code: int) -> None:
    """Подменить capability probe заглушкой с предсказуемым исходом.

    Настоящий probe тащит проверки окружения и под root отказывает — тогда
    тест доказывал бы не ветку раннера, а свойство машины. Заглушка даёт
    обе ветки детерминированно.
    """
    (harness.root / "scripts" / "ci_runtime_probe.py").write_text(
        "import json, sys\n"
        "print(json.dumps({\n"
        "    'source_commit': 'deadbeef',\n"
        "    'capabilities': {'base_python': 'PASS'},\n"
        "    'python_lock_sha256': 'aa',\n"
        "    'pip_freeze_sha256': 'bb',\n"
        "    'frontend_lock_sha256': 'cc',\n"
        "    'norm_artifact_sha256': 'dd',\n"
        "    'environment': {'os_image': 'test-os', 'architecture': 'x86_64',\n"
        "                    'uid': 1000, 'python_version': '3.12.3',\n"
        "                    'node_version': 'v20.0.0', 'npm_version': '10.0.0'},\n"
        "}))\n"
        f"sys.exit({exit_code})\n",
        encoding="utf-8",
    )


def test_failed_probe_is_setup_failure_and_pytest_never_starts(harness: Harness):
    """§6, правило 1: отсутствие capability — setup failure ДО тестов, не skip."""
    harness.write_module("test_green.py", SOURCE_GREEN)
    write_probe_stub(harness, exit_code=1)

    done = harness.run(per_test=10, wall=40, skip_probe=False)

    assert done.returncode == lane_mod.EXIT_SETUP_FAILURE
    receipt = harness.receipt()
    assert receipt["report_status"] == "missing", "отчёта нет — так и надо сказать"
    assert receipt["probe_ran"] is True
    assert receipt["probe_exit_code"] == 1
    assert "probe" in (receipt["note"] or "")
    assert not harness.events_path().exists(), "pytest не должен был запускаться"
    assert not harness.junit.exists()
    assert "skip" not in (receipt["note"] or "").lower()


def test_successful_probe_feeds_environment_fields_of_receipt(harness: Harness):
    """Половина полей §8 приходит из probe — проверяем, что она доезжает."""
    harness.write_module("test_green.py", SOURCE_GREEN)
    write_probe_stub(harness, exit_code=0)

    done = harness.run(per_test=10, wall=40, skip_probe=False)

    assert done.returncode == lane_mod.EXIT_OK, done.stdout + done.stderr
    receipt = harness.receipt()
    assert receipt["os_image"] == "test-os"
    assert receipt["architecture"] == "x86_64"
    assert receipt["python_version"] == "3.12.3"
    assert receipt["node_version"] == "v20.0.0"
    assert receipt["npm_version"] == "10.0.0"
    assert receipt["source_commit"] == "deadbeef"
    assert receipt["capabilities"] == {"base_python": "PASS"}
    assert receipt["norm_artifact_sha256"] == "dd"


# --------------------------------------------------------------------------
# Модульные проверки сборки отчёта из журнала событий
# --------------------------------------------------------------------------


def events_of(*items: dict) -> list[dict]:
    return list(items)


def test_active_node_tracks_open_node():
    """Активная нода — та, что начата и не закрыта. На ней и стоит wall-таймаут."""
    assert lane_mod.active_node([]) is None
    assert (
        lane_mod.active_node(
            events_of(
                {"event": "test_start", "nodeid": "t.py::a"},
                {"event": "test_finish", "nodeid": "t.py::a"},
                {"event": "test_start", "nodeid": "t.py::b"},
            )
        )
        == "t.py::b"
    )
    assert (
        lane_mod.active_node(
            events_of(
                {"event": "test_start", "nodeid": "t.py::a"},
                {"event": "test_finish", "nodeid": "t.py::a"},
            )
        )
        is None
    )


def test_synthetic_wall_timeout_builds_event_for_active_node():
    """Из активной ноды собирается полноценное timeout-событие для JUnit."""
    events = events_of(
        {"event": "test_start", "nodeid": "t.py::a"},
        {"event": "test_finish", "nodeid": "t.py::a"},
        {"event": "test_start", "nodeid": "t.py::b"},
    )
    synthetic = lane_mod.synthetic_wall_timeout(events, "network", 1200.0, 1201.5)
    assert synthetic is not None
    assert synthetic["event"] == "timeout"
    assert synthetic["nodeid"] == "t.py::b"
    assert synthetic["lane"] == "network"
    assert synthetic["budget_seconds"] == 1200.0
    assert synthetic["kind"] == "lane_wall_budget", "вид таймаута обязан быть назван"
    assert synthetic["thread_dump"], "причина отсутствия дампа обязана быть названа"

    tree = lane_mod.build_junit_from_events(events + [synthetic], "network", 1201.5)
    failures = [
        failure
        for case in tree.getroot().iter("testcase")
        for failure in case.findall("failure")
        if failure.get("type") == "timeout"
    ]
    assert len(failures) == 1
    assert "t.py::b" in failures[0].text


def test_synthetic_wall_timeout_marks_a_collection_hang_instead_of_inventing_a_node():
    """Без активной ноды событие обязано появиться, но НЕ выдавать себя за тест.

    Раньше здесь возвращался None, и обрыв на сборке давал пустой зелёный
    JUnit — молчаливый cancel, который §7 запрещает прямым текстом. Выдумывать
    node ID тоже нельзя: настоящего не существует. Компромисс — явный
    псевдо-node `<collection>` и `kind="collection"`: отчёт говорит, что
    зависание было и что искать его надо в сборке, а не в конкретном тесте.
    """
    synthetic = lane_mod.synthetic_wall_timeout([], "unit", 600.0, 601.0)
    assert synthetic is not None, "обрыв на сборке обязан оставить след в отчёте"
    assert synthetic["kind"] == "collection"
    assert synthetic["nodeid"] == lane_mod.COLLECTION_NODE
    assert "::" not in synthetic["nodeid"], "псевдо-node не должен выглядеть как настоящий"
    assert "сборк" in synthetic["thread_dump"], "куда смотреть — обязано быть сказано"


def test_outcomes_from_events_ranks_phases_like_pytest():
    """Падение на setup/teardown — error; худший исход фазы побеждает."""
    outcomes = lane_mod.outcomes_from_events(
        events_of(
            {"event": "report", "nodeid": "t.py::a", "when": "setup", "outcome": "passed"},
            {"event": "report", "nodeid": "t.py::a", "when": "call", "outcome": "passed"},
            {"event": "report", "nodeid": "t.py::b", "when": "setup", "outcome": "failed"},
            {"event": "report", "nodeid": "t.py::c", "when": "call", "outcome": "failed"},
            {"event": "report", "nodeid": "t.py::c", "when": "teardown", "outcome": "passed"},
            {"event": "report", "nodeid": "t.py::d", "when": "setup", "outcome": "skipped"},
            {"event": "test_start", "nodeid": "t.py::e"},
        )
    )
    assert outcomes == {
        "t.py::a": "passed",
        "t.py::b": "error",
        "t.py::c": "failed",
        "t.py::d": "skipped",
    }


def test_build_junit_drops_partial_report_of_timed_out_node():
    """Тот же анти-дубликат, но на уровне сборщика и без запуска pytest."""
    events = events_of(
        {"event": "report", "nodeid": "t.py::hang", "when": "setup", "outcome": "passed"},
        {
            "event": "timeout",
            "lane": "unit",
            "nodeid": "t.py::hang",
            "budget_seconds": 30,
            "elapsed_seconds": 30.0,
            "children": [],
            "thread_dump": "стек",
        },
    )
    suite = lane_mod.build_junit_from_events(events, "unit", 30.0).getroot()
    cases = list(suite.iter("testcase"))
    assert len(cases) == 1, "зависшая нода продублирована зелёным testcase"
    assert cases[0].find("failure").get("type") == "timeout"
    assert suite.get("tests") == "1"
    assert suite.get("failures") == "1"


def test_build_junit_counts_match_attributes():
    """Атрибуты testsuite обязаны совпадать с содержимым: §8 требует counts."""
    events = events_of(
        {"event": "report", "nodeid": "t.py::p", "when": "call", "outcome": "passed"},
        {"event": "report", "nodeid": "t.py::f", "when": "call", "outcome": "failed"},
        {"event": "report", "nodeid": "t.py::e", "when": "setup", "outcome": "failed"},
        {"event": "report", "nodeid": "t.py::s", "when": "setup", "outcome": "skipped"},
    )
    suite = lane_mod.build_junit_from_events(events, "unit", 1.0).getroot()
    assert suite.get("tests") == "4"
    assert suite.get("failures") == "1"
    assert suite.get("errors") == "1"
    assert suite.get("skipped") == "1"
    assert suite.get("name") == "ci-lane-unit"


def test_read_events_survives_truncated_last_line(tmp_path: Path):
    """Хвост журнала обрывается при `os._exit` — это не повод потерять журнал.

    Ровно ради этого случая журнал и пишется построчно с fsync: последняя
    строка может остаться недописанной, но всё, что до неё, обязано уцелеть.
    """
    path = tmp_path / "events.jsonl"
    path.write_text(
        '{"event": "session_start", "lane": "unit"}\n'
        '{"event": "test_start", "nodeid": "t.py::a"}\n'
        '{"event": "timeout", "nodei',
        encoding="utf-8",
    )
    events = lane_mod.read_events(path)
    assert [event["event"] for event in events] == ["session_start", "test_start"]
    assert lane_mod.read_events(tmp_path / "нет.jsonl") == []


def test_split_nodeid_matches_pytest_layout():
    """classname/name разбираются так же, как их публикует сам pytest."""
    assert lane_mod._split_nodeid("tests/test_x.py::test_y") == ("tests.test_x", "test_y")
    assert lane_mod._split_nodeid("test_x.py::test_y[a-b]") == ("test_x", "test_y[a-b]")


def test_split_nodeid_matches_pytest_layout_for_class_based_tests():
    """Для теста внутри класса classname обязан совпадать с pytest'овым.

    Сейчас `tests/test_x.py::TestC::test_y` даёт `tests.test_x.py.TestC`, тогда
    как сам pytest в своём JUnit пишет `tests.test_x.TestC` (проверено на
    `--junitxml`). Причина в порядке операций: `head.replace("/", ".")` даёт
    `tests/test_x.py::TestC` → `tests.test_x.py::TestC`, после чего
    `removesuffix(".py")` уже не срабатывает — строка кончается на `::TestC`, —
    и `.py` остаётся в СЕРЕДИНЕ имени.

    Последствие не косметическое. Обычный прогон и прогон с таймаутом
    публикуют один и тот же узел под РАЗНЫМИ classname, поэтому агрегаторы,
    которые ключуются на classname+name (история тестов, детектор flaky,
    слияние JUnit нескольких lanes), видят два разных теста и теряют историю
    ровно того теста, который завис. Докстрока самой функции обещает «как у
    pytest», так что это расхождение с её же контрактом.
    """
    assert lane_mod._split_nodeid("tests/test_x.py::TestC::test_y") == (
        "tests.test_x.TestC",
        "test_y",
    )


# --------------------------------------------------------------------------
# §7, требования 2–3: инвентарь и добивание дочерних процессов сквозным прогоном
# --------------------------------------------------------------------------


def source_hang_with_child(pidfile: Path) -> str:
    """Тест, который вешается, успев оставить за собой живой дочерний процесс."""
    return f'''import os
import subprocess
import sys
import time

PID_FILE = {str(pidfile)!r}
CHILD = (
    "import os, sys, time; "
    "open(sys.argv[1], 'w').write(str(os.getpid())); "
    "time.sleep(300)"
)


def test_hang_with_child():
    subprocess.Popen([sys.executable, "-c", CHILD, PID_FILE])
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            if int(open(PID_FILE, encoding="utf-8").read().strip()) > 0:
                break
        except (OSError, ValueError):
            pass
        time.sleep(0.05)
    time.sleep(600)
'''


def pid_alive(pid: int) -> bool:
    """Жив ли процесс. Зомби здесь не бывает: осиротевших забирает init."""
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def test_timeout_inventories_and_kills_child_processes(harness: Harness):
    """§7, требования 2–3 целиком: дети зависшего теста переписаны и добиты.

    Не добитый процесс переживает lane и держит порт, файл или лок; следующий
    job упадёт по причине, никак не связанной с его собственным кодом. Поэтому
    проверяется и то, что ребёнок ПОПАЛ в инвентарь отчёта (иначе дежурный о
    нём не узнает), и то, что после прогона его действительно нет.
    """
    pidfile = harness.root / "child.pid"
    harness.write_module("test_child.py", source_hang_with_child(pidfile))

    done = harness.run(per_test=5, wall=40)
    assert pidfile.is_file(), "ребёнок не успел подняться — сценарий не воспроизведён"
    child_pid = int(pidfile.read_text(encoding="utf-8").strip())
    try:
        assert done.returncode == lane_mod.EXIT_LANE_TIMEOUT, done.stdout + done.stderr

        failure = next(
            failure
            for case in harness.testcases()
            for failure in case.findall("failure")
            if failure.get("type") == "timeout"
        )
        text = failure.text or ""
        assert "дочерних процессов: 1" in text, text[:500]
        assert str(child_pid) in text, "pid ребёнка обязан быть в инвентаре отчёта"

        deadline = time.monotonic() + 15.0
        while pid_alive(child_pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not pid_alive(child_pid), (
            f"процесс {child_pid} пережил таймаут — bounded cleanup не сработал"
        )
    finally:
        # Тест не имеет права оставить осиротевший процесс даже при падении.
        try:
            os.kill(child_pid, signal.SIGKILL)
        except OSError:
            pass


# --------------------------------------------------------------------------
# Дефекты, найденные этими тестами и ИСПРАВЛЕННЫЕ в harness.
# Тесты оставлены как регрессия: оба отказа молчаливые, вернуться могут
# незаметно.
# --------------------------------------------------------------------------


def test_wall_timeout_failure_message_names_the_right_budget():
    """Wall-таймаут не должен выдаваться в JUnit за per-test.

    Подпись failure — первое и часто единственное, что читает дежурный. Пока
    сборщик JUnit не читал `kind` события, wall-таймаут подписывался как
    «per-test timeout <wall> s исчерпан»: в сообщении стоял номер ЧУЖОГО
    бюджета (при `--per-test-timeout 60 --lane-budget 3` — тройка), и вывод
    получался противоположный — будто тест не уложился в свой бюджет. Реакция
    на два случая разная: при per-test сужают тест, при wall разбирают весь
    lane, поэтому подпись обязана называть именно исчерпанный бюджет.
    """
    events = [{"event": "test_start", "nodeid": "t.py::slow"}]
    synthetic = lane_mod.synthetic_wall_timeout(events, "unit", 600.0, 601.0)
    assert synthetic is not None and synthetic["kind"] == "lane_wall_budget"

    suite = lane_mod.build_junit_from_events(events + [synthetic], "unit", 601.0).getroot()
    failure = next(f for f in suite.iter("failure") if f.get("type") == "timeout")
    message = failure.get("message") or ""
    assert "per-test" not in message, (
        f"wall-таймаут подписан как per-test: {message!r}"
    )
    assert "wall" in message.lower(), message
    assert "600" in message, "в подписи обязан стоять именно исчерпанный бюджет"


def test_collection_hang_is_recorded_in_junit(harness: Harness):
    """Зависание на сборке обязано быть видно в JUnit, а не только в коде возврата.

    Если виснет импорт `conftest.py`, ни один `test_start` в журнал не попадает
    и настоящего node ID не существует. Пока обрыв на сборке не обрабатывался
    отдельно, JUnit собирался ПУСТЫМ: `<testsuite tests="0" failures="0"/>` при
    `report_status=ok` и `timed_out_node=null`. Код возврата 3 был честный, но
    артефакт, который читают CI и человек, выглядел как «в lane просто нечего
    было запускать». §7 закрывается словами «Hang никогда не превращается в
    молчаливый cancel или skip», а пустой зелёный отчёт — ровно такой cancel.

    Хватает одного `<failure type="timeout">` с указанием фазы сборки: node ID
    здесь взять действительно неоткуда, и это нормально — ненормально молчать.
    """
    (harness.tests_dir / "conftest.py").write_text(
        "import time\n\n# зависание на импорте conftest — обрыв ещё до сбора тестов\ntime.sleep(600)\n",
        encoding="utf-8",
    )
    harness.write_module("test_green.py", SOURCE_GREEN)

    done = harness.run(per_test=60, wall=3)
    assert done.returncode == lane_mod.EXIT_LANE_TIMEOUT, done.stdout + done.stderr

    suite = harness.junit_root()
    assert int(suite.get("tests") or 0) > 0, (
        f"JUnit пуст: {ET.tostring(suite, encoding='unicode')}"
    )
    timeouts = [f for f in suite.iter("failure") if f.get("type") == "timeout"]
    assert timeouts, "в отчёте нет ни одной записи о таймауте"
    assert "сборк" in (timeouts[0].get("message") or "").lower(), (
        f"подпись не называет фазу сборки: {timeouts[0].get('message')!r}"
    )
    receipt = harness.receipt()
    assert receipt["timed_out_node"] == lane_mod.COLLECTION_NODE
    assert receipt["report_status"] == "ok"


# ---------------------------------------------------------------------------
# Блокирующие дефекты ревью: PGID-cleanup и redaction
# ---------------------------------------------------------------------------


def test_kill_group_works_after_the_leader_has_been_reaped():
    """Группа снимается по СОХРАНЁННОМУ pgid, а не по pid уже мёртвого лидера.

    Это был блокирующий дефект. После per-test таймаута watchdog внутри pytest
    выходит через `os._exit`, `proc.wait()` забирает лидера, и
    `os.getpgid(proc.pid)` отвечает `ProcessLookupError` — прежняя редакция
    молча выходила, не отправив группе ни одного сигнала. Группа при этом жива:
    она переживает своего лидера, её идентификатор — не идентификатор процесса.

    Сценарий воспроизводит ровно этот порядок: лидер порождает долгоживущего
    участника группы и выходит сам.
    """
    proc = subprocess.Popen(
        [
            sys.executable, "-c",
            "import subprocess, sys; "
            "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)']); "
            "sys.exit(0)",
        ],
        start_new_session=True,
    )
    pgid = os.getpgid(proc.pid)
    proc.wait()
    time.sleep(0.4)

    # Лидера уже нет — старый способ узнать pgid не работает.
    with pytest.raises(ProcessLookupError):
        os.getpgid(proc.pid)
    # А группа жива.
    os.killpg(pgid, 0)

    try:
        lane_mod._kill_group(proc, pgid)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                os.killpg(pgid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.05)
        else:
            pytest.fail("группа пережила cleanup: child_alive_after_kill_group")
    finally:
        try:
            os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, OSError):
            pass


def test_kill_group_without_pgid_is_a_no_op():
    """Неизвестный pgid — не повод разослать сигнал наугад.

    `os.getpgid` при запуске может отказать; тогда добивать группу нечем, но и
    бить по чужой группе нельзя. Молчаливый возврат здесь — правильное
    поведение, а не забытая ветка.
    """
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    lane_mod._kill_group(proc, None)   # не должно ни падать, ни кого-то трогать


def test_secret_from_child_cmdline_never_reaches_any_artifact(harness: Harness):
    """Сквозная проверка: секрет не попадает ни в JUnit, ни в receipt, ни в журнал.

    Дефект был именно сквозной: одна точка чтения `/proc/*/cmdline` питала три
    артефакта, и синтетический `--token=…` находился во всех трёх. Поэтому и
    проверка сквозная — модульной проверки источника мало, если публикация
    когда-нибудь пойдёт в обход него.
    """
    secret = "TEST_SECRET_SENTINEL_E2E"
    harness.write_module(
        "test_secret.py",
        "import subprocess, sys, time\n\n\n"
        "def test_hangs_with_secret_bearing_child():\n"
        "    subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(600)',\n"
        f"                      '--token={secret}'])\n"
        "    time.sleep(600)\n",
    )

    done = harness.run(per_test=4, wall=60)
    assert done.returncode == lane_mod.EXIT_LANE_TIMEOUT, done.stdout + done.stderr

    artifacts = {
        "JUnit": harness.junit.read_text(encoding="utf-8"),
        "receipt": harness.receipt_path.read_text(encoding="utf-8"),
        "журнал событий": harness.events_path().read_text(encoding="utf-8"),
    }
    for name, text in artifacts.items():
        assert secret not in text, f"секрет утёк в {name}"

    # Инвентарь при этом не опустел: дефект не «починен» удалением сведений.
    # Allowlist не помечает вырезанное — он просто не публикует значение, —
    # поэтому признаком служит не «[redacted]», а имя флага и отпечаток argv.
    junit_text = artifacts["JUnit"]
    assert "--token" in junit_text, "вместе с секретом исчезла вся диагностика"
    assert "argv:" in junit_text, "отпечаток обязан быть: без него процессы не сличить"


def test_receipt_command_does_not_publish_user_supplied_arguments(harness: Harness):
    """Поле `command` не публикует пользовательские пути, маркеры и хвост argv.

    Это был блокирующий дефект: receipt хранил `" ".join(cmd)`, а в cmd входят
    `--paths`, выражение маркеров и дополнительные аргументы pytest. Измерено —
    путь вида `/srv/customers/<id>/test.py` и `--token 0427` уходили в receipt
    дословно.

    §8 требует ПОЛЕ `command`, а не сырой argv, поэтому оно публикуется в той
    же безопасной форме, что и командные строки дочерних процессов.
    """
    harness.write_module("test_ok.py", SOURCE_GREEN)
    done = harness.run("-m", "not chaos")
    assert done.returncode == lane_mod.EXIT_OK, done.stdout + done.stderr

    receipt = harness.receipt()
    blob = json.dumps(receipt, ensure_ascii=False)
    assert str(harness.tests_dir) not in blob, "пользовательский путь в receipt"
    assert "not chaos" not in receipt["command"], "выражение маркеров опубликовано"
    # Опознать команду по-прежнему можно: программа, флаги и отпечаток.
    assert "pytest" in receipt["command"]
    assert "argv:" in receipt["command"]


def test_receipt_publishes_only_the_canonical_artifact_layout(harness: Harness):
    """Полный путь публикуется только для канонической раскладки §5.1.

    Обе прежние ветки были неверны по одной причине: путь целиком задаётся
    пользователем через `--junit`, а форма пути безопасности не доказывает.
    Внутри репозитория публиковался полный относительный путь, снаружи —
    имя файла; и то и другое сохраняло секрет.
    """
    harness.write_module("test_ok.py", SOURCE_GREEN)
    harness.run()
    receipt = harness.receipt()
    # Тест задаёт свой --junit во временный каталог — это НЕ каноническая
    # раскладка, поэтому путь не публикуется вовсе.
    assert receipt["junit"] == "<custom-junit>", receipt["junit"]
    assert receipt["events"] == "<custom-events>", receipt["events"]
    blob = json.dumps(receipt, ensure_ascii=False)
    assert str(harness.junit) not in blob, "полный путь --junit опубликован"
    assert str(harness.root) not in blob, "каталог прогона опубликован"


def test_publishable_path_accepts_only_the_exact_contract_layout():
    """Каноничен путь `.ci/reports/<lane>.*`, и только он.

    `<lane>` берётся из закрытого списка, поэтому такая форма задана
    контрактом, а не пользователем. Файл с произвольным именем ВНУТРИ того же
    каталога каноническим не становится — иначе достаточно было бы положить
    туда `q7z4m2n8p5r3t6v9.xml`.
    """
    canonical = lane_mod.REPORT_DIR / "unit.xml"
    assert lane_mod._publishable_path(canonical, "junit", "unit") == ".ci/reports/unit.xml"
    events = lane_mod.REPORT_DIR / "network.events.jsonl"
    assert lane_mod._publishable_path(events, "events", "network") == ".ci/reports/network.events.jsonl"

    secret = "q7z4m2n8p5r3t6v9"
    for path in (
        lane_mod.REPORT_DIR / f"{secret}.xml",          # чужое имя в нашем каталоге
        lane_mod.ROOT / "private" / secret / "r.xml",   # внутри репозитория
        Path("/tmp") / f"{secret}.xml",                 # снаружи
    ):
        published = lane_mod._publishable_path(path, "junit", "unit")
        assert published == "<custom-junit>", published
        assert secret not in published


def test_canonical_name_is_matched_exactly_not_by_prefix():
    """Имя сверяется целиком: «начинается с разрешённого» — не allowlist.

    Прежняя проверка брала `name.split(".")[0]` и потому пропускала любой
    пользовательский суффикс: `unit.q7z4m2n8p5r3t6v9.xml` начинается с имени
    lane и публиковался полным путём. Проверка по префиксу — имитация
    allowlist: допустимых имён конечное число, и они перечисляются полностью.
    """
    secret = "q7z4m2n8p5r3t6v9"
    hostile = [
        (f"unit.{secret}.xml", "junit"),
        (f"network.{secret}.events.jsonl", "events"),
        (f"chaos.{secret}", "junit"),
        (f"unit{secret}.xml", "junit"),
        # Тип артефакта тоже часть имени: отчёт не выдаёт себя за журнал.
        ("unit.events.jsonl", "junit"),
        ("unit.xml", "events"),
    ]
    for name, kind in hostile:
        published = lane_mod._publishable_path(lane_mod.REPORT_DIR / name, kind, "unit")
        assert published == f"<custom-{kind}>", f"{name} [{kind}] -> {published}"
        assert secret not in published

    # У каждого lane каноническое имя РОВНО ОДНО на вид артефакта.
    for lane in lane_mod.LANES:
        assert lane_mod._publishable_path(
            lane_mod.REPORT_DIR / f"{lane}.xml", "junit", lane
        ) == f".ci/reports/{lane}.xml"
        assert lane_mod._publishable_path(
            lane_mod.REPORT_DIR / f"{lane}.events.jsonl", "events", lane
        ) == f".ci/reports/{lane}.events.jsonl"


def test_canonicality_is_scoped_to_the_running_lane():
    """Имя ЧУЖОГО lane каноническим не является.

    §5.1 задаёт отображение lane → собственный файл, а не множество
    взаимозаменяемых имён. Прежний список из десяти имён не знал, какой lane
    выполняется, и `--lane unit --junit .ci/reports/contract.xml` признавался
    каноническим: receipt получался внутренне противоречивым — `lane: unit`
    при `junit: contract.xml`.
    """
    for lane in lane_mod.LANES:
        for other in lane_mod.LANES:
            if other == lane:
                continue
            assert lane_mod._publishable_path(
                lane_mod.REPORT_DIR / f"{other}.xml", "junit", lane
            ) == "<custom-junit>"
            assert lane_mod._publishable_path(
                lane_mod.REPORT_DIR / f"{other}.events.jsonl", "events", lane
            ) == "<custom-events>"


def test_relative_canonical_path_is_normalised():
    """Форма записи пути не меняет того, на какой файл он указывает.

    `.ci/reports/unit.xml` — дословно путь из канонической команды §5.1, и
    считать его пользовательским только потому, что он записан относительно,
    неверно.
    """
    assert lane_mod._publishable_path(
        Path(".ci/reports/unit.xml"), "junit", "unit"
    ) == ".ci/reports/unit.xml"
    assert lane_mod._publishable_path(
        Path(".ci/reports/network.events.jsonl"), "events", "network"
    ) == ".ci/reports/network.events.jsonl"
    # Нормализация не делает канонической чужую lane.
    assert lane_mod._publishable_path(
        Path(".ci/reports/contract.xml"), "junit", "unit"
    ) == "<custom-junit>"


def test_run_refuses_to_overwrite_another_lanes_canonical_artifact(harness: Harness):
    """Прогон одного lane не стирает канонический артефакт другого.

    Проверка обязана стоять ДО удаления: `run_lane()` чистит старые артефакты
    перед прогоном, и без неё чужой отчёт был бы снесён и заменён чужими
    результатами. Молча испортить артефакт хуже, чем отказать: следующий
    разбор пошёл бы по подменённому отчёту.
    """
    # Каталог отчётов КОПИИ раннера: у неё свой ROOT внутри tmp_path.
    foreign = harness.root / ".ci" / "reports" / "network.xml"
    foreign.parent.mkdir(parents=True, exist_ok=True)
    marker = "<testsuite name='контрольный отчёт network'/>"
    foreign.write_text(marker, encoding="utf-8")
    try:
        harness.write_module("test_ok.py", SOURCE_GREEN)
        # CLI зовётся напрямую: `Harness.run` подставляет свой --junit, а здесь
        # нужен именно чужой канонический путь.
        done = run_cli(
            harness,
            [
                "--lane", "unit", "--skip-probe",
                "--junit", str(foreign),
                "--paths", str(harness.tests_dir),
            ],
            timeout=CLI_HARD_LIMIT,
        )
        assert done.returncode != 0, done.stdout + done.stderr
        assert "network" in (done.stdout + done.stderr)
        # Главное: чужой артефакт цел.
        assert foreign.read_text(encoding="utf-8") == marker
    finally:
        foreign.unlink(missing_ok=True)
