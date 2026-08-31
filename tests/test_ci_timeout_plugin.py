"""Тесты pytest-плагина per-test timeout (`scripts/ci_timeout_plugin.py`), W0-OPS-03.

Плагин — это последняя линия обороны против зависания (§7 контракта
`docs/architecture/QUALITY_RUNTIME_CONTRACT_V1.md`). Он срабатывает ровно
тогда, когда всё остальное уже сломано, и переписать его поведение «по факту
прогона» будет некому: процесс к тому моменту снимается через `os._exit`.
Поэтому здесь проверяется не «плагин работает», а то, что его диагностика НЕ
ВРЁТ:

* инвентарь дочерних процессов находит своих и не приписывает себе чужих, а
  разбор `/proc/<pid>/stat` выдерживает `comm` с пробелами и скобками — на этом
  наивный `split()` разваливается и в отчёт уезжает мусор вместо ppid;
* зомби считается МЁРТВЫМ: `os.kill(pid, 0)` для зомби возвращает успех, и без
  проверки состояния телеметрия cleanup рапортовала бы «пришлось слать SIGKILL»
  там, где процесс давно завершился;
* счётчики terminated/killed отражают то, что реально произошло, а игнорирующий
  SIGTERM процесс всё-таки добивается;
* thread dump содержит настоящий стек, а не строку «дамп недоступен» — без
  дампа таймаут сообщает, ЧТО зависло, но не ГДЕ;
* мусорный бюджет в окружении откатывается на значение по умолчанию, а не
  превращается в 0/inf, то есть в молчаливое отключение watchdog.

Все тесты обязаны быть быстрыми и не оставлять осиротевших процессов: каждый
поднятый процесс добивается в `finally`, каждый заведённый таймер снимается.
Ни один тест не имеет права взводить watchdog с малым бюджетом — сработавший
watchdog вызовет `os._exit(87)` в НАШЕМ pytest-процессе и снесёт весь прогон.
"""
from __future__ import annotations

import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PLUGIN_PATH = ROOT / "scripts" / "ci_timeout_plugin.py"

_spec = importlib.util.spec_from_file_location("ci_timeout_plugin", PLUGIN_PATH)
plug = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
# Регистрация в sys.modules до exec_module — та же причина, что и в
# tests/test_ci_runtime_probe.py: аннотации резолвятся через sys.modules.
sys.modules["ci_timeout_plugin"] = plug
_spec.loader.exec_module(plug)


# --------------------------------------------------------------------------
# Вспомогательное: подопытные процессы, которые гарантированно умирают
# --------------------------------------------------------------------------

#: Ребёнок печатает `ready` ПОСЛЕ того, как выставил себе имя и обработчики.
#: Ждать этой строки обязательно: сразу после fork у процесса ещё старое `comm`
#: и старые обработчики, и тест ловил бы состояние, которого в проверяемом
#: сценарии не бывает.
_SLEEPER = (
    "import sys, time; sys.stdout.write('ready\\n'); sys.stdout.flush(); time.sleep(60)"
)
_SIGTERM_IGNORER = (
    "import signal, sys, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
    "sys.stdout.write('ready\\n'); sys.stdout.flush(); time.sleep(60)"
)
#: `comm` длиной ≤15 символов с пробелами и закрывающими скобками внутри —
#: ровно та строка, на которой ломается разбор `stat` по первому `)`.
_WEIRD_COMM = "we (ir) d) x"
_WEIRD_NAME = (
    "import ctypes, sys, time; "
    "ctypes.CDLL('libc.so.6').prctl(15, b'we (ir) d) x\\0', 0, 0, 0); "
    "sys.stdout.write('ready\\n'); sys.stdout.flush(); time.sleep(60)"
)


def spawn(code: str) -> subprocess.Popen:
    """Поднять дочерний процесс и дождаться его готовности."""
    proc = subprocess.Popen(
        [sys.executable, "-c", code], stdout=subprocess.PIPE, text=True
    )
    line = proc.stdout.readline()
    assert line.strip() == "ready", f"ребёнок не поднялся: {line!r}"
    return proc


def reap(proc: subprocess.Popen | None) -> None:
    """Гарантированно снять и забрать процесс. Вызывается только из finally."""
    if proc is None:
        return
    try:
        proc.kill()
    except OSError:
        pass
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:  # pragma: no cover — ядро не отдало SIGKILL
        pass
    if proc.stdout is not None:
        proc.stdout.close()


def proc_state(pid: int) -> str | None:
    """Состояние процесса из /proc: 'R', 'S', 'Z', … или None, если его нет."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    close = stat.rfind(")")
    fields = stat[close + 2 :].split()
    return fields[0] if fields else None


def wait_for_state(pid: int, state: str, budget: float = 10.0) -> str | None:
    """Дождаться состояния процесса. Ограничено бюджетом — тест не виснет."""
    deadline = time.monotonic() + budget
    current = proc_state(pid)
    while current != state and time.monotonic() < deadline:
        time.sleep(0.02)
        current = proc_state(pid)
    return current


requires_proc = pytest.mark.skipif(
    not Path("/proc").is_dir(), reason="инвентарь процессов читается только из /proc"
)


# --------------------------------------------------------------------------
# §7, требование 2: инвентарь дочерних процессов
# --------------------------------------------------------------------------


@requires_proc
def test_child_processes_finds_own_child():
    """Свой ребёнок обязан оказаться в инвентаре — иначе cleanup его пропустит."""
    proc = None
    try:
        proc = spawn(_SLEEPER)
        found = [item for item in plug.child_processes() if item["pid"] == proc.pid]
        assert len(found) == 1, "ребёнок не найден в инвентаре"
        entry = found[0]
        assert entry["state"] in {"R", "S"}, entry
        # Содержимое `-c` НЕ публикуется: это аргумент произвольной формы, и
        # allowlist его не пропускает. Опознаётся процесс по исполняемому
        # файлу, имени флага и отпечатку argv.
        # sys.executable может заканчиваться как `python`, `python3`
        # или версионное имя; проверяем фактический executable.
        assert Path(sys.executable).name in entry["cmdline"], entry
        assert "-c" in entry["cmdline"], entry
        assert "time.sleep(60)" not in entry["cmdline"], (
            "содержимое -c опубликовано — allowlist пропустил произвольный аргумент"
        )
        assert len(str(entry["argv_fingerprint"])) == 64, entry
        assert isinstance(entry["comm"], str) and entry["comm"]
    finally:
        reap(proc)


@requires_proc
def test_child_processes_covers_descendants_but_not_strangers():
    """Инвентарь охватывает ВСЕХ потомков указанного pid — и только их.

    Прежняя редакция требовала обратного: чтобы внук в список НЕ попадал.
    Это и был дефект. `terminate_children()` бьёт ровно тех, кого перечислил
    инвентарь, поэтому «только прямые дети» означало, что связка
    «тест → uvicorn → воркер» оставляла воркера с ppid=1: осиротевший процесс
    держит порт и валит следующий job причиной не из его кода.

    Вторая половина требования осталась в силе и важнее первой: чужие
    процессы в списке — это расстрел посторонних процессов машины.
    """
    proc = None
    try:
        # Ребёнок сам поднимает внука и печатает его pid.
        code = (
            "import subprocess, sys, time; "
            "kid = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
            "sys.stdout.write(str(kid.pid) + '\\n'); "
            "sys.stdout.write('ready\\n'); sys.stdout.flush(); "
            "time.sleep(60)"
        )
        proc = subprocess.Popen(
            [sys.executable, "-c", code], stdout=subprocess.PIPE, text=True
        )
        grandchild = int(proc.stdout.readline().strip())
        assert proc.stdout.readline().strip() == "ready"

        mine = {item["pid"]: item for item in plug.child_processes()}
        assert proc.pid in mine
        assert grandchild in mine, "внук пережил бы cleanup: он не в инвентаре"
        assert mine[proc.pid]["depth"] == 1
        assert mine[grandchild]["depth"] == 2, "глубина обязана быть видна"
        # Границы обхода: сам процесс и его родитель — не потомки.
        assert os.getpid() not in mine and os.getppid() not in mine

        # Для самого ребёнка внук — потомок первого уровня.
        theirs = {item["pid"]: item for item in plug.child_processes(proc.pid)}
        assert set(theirs) == {grandchild}
        assert theirs[grandchild]["depth"] == 1
    finally:
        reap(proc)


@requires_proc
def test_child_processes_parses_comm_with_spaces_and_parens():
    """`comm` с пробелами и `)` не должен ломать разбор /proc/<pid>/stat.

    Формат `stat` — «pid (comm) state ppid …», причём `comm` не экранируется.
    Наивный `split()` или срез по ПЕРВОЙ `)` даёт для такого имени сдвиг полей:
    в `state` попадает кусок имени, в `ppid` — что угодно, и ребёнок либо
    теряется, либо его pid подменяется числом из середины stat.
    """
    proc = None
    try:
        proc = spawn(_WEIRD_NAME)
        raw = Path(f"/proc/{proc.pid}/stat").read_text(encoding="utf-8")
        assert f"({_WEIRD_COMM})" in raw, f"prctl не применился: {raw[:80]!r}"

        found = [item for item in plug.child_processes() if item["pid"] == proc.pid]
        assert len(found) == 1, "процесс с «злым» comm потерян инвентарём"
        # Разбор проверяется по СОСЕДНИМ полям, а не по самому comm: он теперь
        # проходит allowlist и наружу не выходит (процесс задаёт его себе сам
        # через prctl, то есть это недоверенный ввод). Целостность разбора это
        # доказывает не хуже: при сдвиге полей в state попал бы кусок имени, а
        # pid подменился бы числом из середины stat.
        assert found[0]["state"] in {"R", "S"}
        assert found[0]["comm"] == "<comm>", "недоверенный comm опубликован"
        assert _WEIRD_COMM not in str(found[0])
    finally:
        reap(proc)


@requires_proc
def test_child_processes_is_sorted_and_shaped():
    """Инвентарь стабильно упорядочен и несёт ровно объявленные поля.

    Порядок — сначала самые глубокие потомки: cleanup снимает листья раньше
    их родителей, чтобы родитель не успел породить замену уже после того,
    как его собственный pid обошли.
    """
    proc = None
    try:
        proc = spawn(_SLEEPER)
        children = plug.child_processes()
        assert children, "хотя бы один ребёнок сейчас точно есть"
        keys = [(-int(item["depth"]), int(item["pid"])) for item in children]
        assert keys == sorted(keys), "порядок обхода не от листьев к корню"
        for item in children:
            assert set(item) == {
                "pid", "comm", "state", "cmdline", "depth",
                "argc", "positional_count", "hidden_flag_count", "argv_fingerprint",
            }
            assert int(item["depth"]) >= 1
            assert len(item["cmdline"]) <= 400, "cmdline обязан быть обрезан"
    finally:
        reap(proc)


# --------------------------------------------------------------------------
# _alive(): зомби — мёртв
# --------------------------------------------------------------------------


@requires_proc
def test_alive_treats_zombie_as_dead():
    """Зомби считается мёртвым, хотя сигнал 0 до него доходит.

    Это специально исправленный дефект. `os.kill(pid, 0)` для зомби успешен:
    запись в таблице процессов жива, пока родитель не сделал wait(). Если
    считать такой процесс живым, `terminate_children()` отрапортует лишний
    SIGKILL, и телеметрия cleanup будет врать в сторону паники — дежурный
    начнёт искать процесс, сопротивляющийся завершению, которого не было.
    """
    proc = None
    try:
        proc = subprocess.Popen([sys.executable, "-c", "raise SystemExit(0)"])
        assert wait_for_state(proc.pid, "Z") == "Z", "процесс не стал зомби"

        # Вот та самая ловушка: сигнал 0 проходит.
        assert os.kill(proc.pid, 0) is None
        assert plug._alive(proc.pid) is False, "зомби посчитан живым"
    finally:
        reap(proc)


@requires_proc
def test_alive_reports_running_process():
    """Обратная сторона: живой процесс не должен объявляться мёртвым."""
    proc = None
    try:
        proc = spawn(_SLEEPER)
        assert plug._alive(proc.pid) is True
        assert plug._alive(os.getpid()) is True
    finally:
        reap(proc)


@requires_proc
def test_alive_is_false_for_reaped_process():
    """После wait() записи в таблице нет — процесс мёртв без вариантов."""
    proc = subprocess.Popen([sys.executable, "-c", "raise SystemExit(0)"])
    proc.wait(timeout=10)
    assert plug._alive(proc.pid) is False


# --------------------------------------------------------------------------
# §7, требование 3: bounded cleanup дочерних процессов
# --------------------------------------------------------------------------


@requires_proc
def test_terminate_children_counts_only_sigterm_for_wellbehaved_child():
    """Послушный ребёнок уходит по SIGTERM: killed обязан остаться нулём."""
    proc = None
    try:
        proc = spawn(_SLEEPER)
        started = time.monotonic()
        result = plug.terminate_children([{"pid": proc.pid}])
        elapsed = time.monotonic() - started

        assert result == {"terminated": 1, "killed": 0}, result
        assert elapsed < plug.CHILD_KILL_GRACE_SEC + 1.0, (
            f"cleanup ждал {elapsed:.2f}s, хотя ребёнок ушёл сразу"
        )
        assert plug._alive(proc.pid) is False
        assert proc.wait(timeout=10) == -signal.SIGTERM
    finally:
        reap(proc)


@requires_proc
def test_terminate_children_kills_sigterm_ignorer():
    """Игнорирующий SIGTERM добивается SIGKILL, и это видно в счётчиках.

    Без добивания зависший тест оставил бы за собой живой процесс, который
    держит порт/файл и валит следующий lane. Bounded — значит cleanup сам
    укладывается в свой бюджет, а не ждёт вечно.
    """
    proc = None
    try:
        proc = spawn(_SIGTERM_IGNORER)
        started = time.monotonic()
        result = plug.terminate_children([{"pid": proc.pid}])
        elapsed = time.monotonic() - started

        assert result == {"terminated": 1, "killed": 1}, result
        assert plug.CHILD_KILL_GRACE_SEC <= elapsed < plug.CHILD_KILL_GRACE_SEC + 5.0, (
            f"cleanup вышел за собственный бюджет: {elapsed:.2f}s"
        )
        assert proc.wait(timeout=10) == -signal.SIGKILL
    finally:
        reap(proc)


def test_terminate_children_on_empty_inventory_is_noop():
    """Пустой инвентарь не должен ни падать, ни выдумывать счётчики."""
    assert plug.terminate_children([]) == {"terminated": 0, "killed": 0}


def test_terminate_children_survives_vanished_pid():
    """Ребёнок, умерший между инвентаризацией и SIGTERM, — обычное дело.

    Гонка неизбежна: инвентарь снимается, потом шлются сигналы. Cleanup обязан
    её пережить и не завышать terminated по несуществующему pid.
    """
    proc = subprocess.Popen([sys.executable, "-c", "raise SystemExit(0)"])
    proc.wait(timeout=10)
    result = plug.terminate_children([{"pid": proc.pid}])
    assert result == {"terminated": 0, "killed": 0}, result


# --------------------------------------------------------------------------
# §7, требование 2: thread dump
# --------------------------------------------------------------------------


def test_thread_dump_contains_real_stack():
    """Дамп обязан содержать настоящий стек, а не заглушку.

    §7 требует снять thread dump; отчёт со строкой «thread dump недоступен»
    формально требование закрывает, а фактически оставляет дежурного без
    единственного ответа на вопрос «где именно повисло».
    """
    dump = plug.thread_dump()
    assert dump.strip(), "дамп пуст"
    assert "недоступен" not in dump, dump[:400]
    assert "test_thread_dump_contains_real_stack" in dump, (
        "в дампе нет кадра вызывающего теста — значит это не стек"
    )
    # faulthandler называет текущий поток «Current thread», остальные — «Thread».
    assert "thread" in dump.lower()


def test_thread_dump_falls_back_when_faulthandler_fails(monkeypatch):
    """Отказ faulthandler не имеет права оставить таймаут без дампа."""

    def boom(*_args, **_kwargs):
        raise OSError("faulthandler запрещён (тест)")

    monkeypatch.setattr(plug.faulthandler, "dump_traceback", boom)
    dump = plug.thread_dump()
    assert "недоступен" not in dump, dump[:400]
    assert "MainThread" in dump, "запасной дамп обязан называть потоки"
    assert "test_thread_dump_falls_back_when_faulthandler_fails" in dump


def test_frames_dump_reports_failure_honestly(monkeypatch):
    """Если не сработал и запасной путь — это должно быть СКАЗАНО, а не скрыто."""
    monkeypatch.setattr(
        plug.threading, "enumerate", lambda: (_ for _ in ()).throw(RuntimeError("нет"))
    )
    assert "недоступен" in plug._frames_dump()


# --------------------------------------------------------------------------
# Разбор бюджета из окружения
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    ["", "   ", "мусор", "30s", "0", "0.0", "-1", "-0.5", "nan", "inf", "-inf", "1e400"],
)
def test_budget_falls_back_to_default_on_unusable_value(monkeypatch, raw: str):
    """Непригодный бюджет откатывается на умолчание, а не отключает watchdog.

    0, отрицательное и inf одинаково обесценивают бюджет: при них таймер либо
    не взводится, либо не срабатывает никогда — то есть §7 молча перестаёт
    действовать. Молчаливое отключение защиты от зависания хуже, чем её
    отсутствие: CI продолжает утверждать, что бюджет соблюдается.
    """
    monkeypatch.setenv("CI_LANE_TEST_BUDGET", raw)
    assert plug._env_float("CI_LANE_TEST_BUDGET", 30.0) == 30.0


def test_budget_falls_back_when_variable_is_absent(monkeypatch):
    monkeypatch.delenv("CI_LANE_TEST_BUDGET", raising=False)
    assert plug._env_float("CI_LANE_TEST_BUDGET", 42.5) == 42.5


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("30", 30.0), ("60", 60.0), ("0.5", 0.5), (" 120 ", 120.0), ("1e2", 100.0)],
)
def test_budget_accepts_valid_number(monkeypatch, raw: str, expected: float):
    """Корректное число берётся как есть — подмена бюджета запрещена §7."""
    monkeypatch.setenv("CI_LANE_TEST_BUDGET", raw)
    assert plug._env_float("CI_LANE_TEST_BUDGET", 30.0) == expected


# --------------------------------------------------------------------------
# Плагин: журнал событий и взведение watchdog
# --------------------------------------------------------------------------


def make_plugin(tmp_path: Path, monkeypatch, budget: str = "0"):
    """Плагин с журналом в tmp_path.

    По умолчанию бюджет 0 — watchdog не взводится. Это не косметика: живой
    таймер в нашем же процессе при срабатывании сделает `os._exit(87)` и
    убьёт весь прогон тестов.
    """
    monkeypatch.setenv("CI_LANE_NAME", "unit")
    monkeypatch.setenv("CI_LANE_PER_TEST_TIMEOUT", budget)
    monkeypatch.setenv("CI_LANE_EVENTS", str(tmp_path / "events.jsonl"))
    monkeypatch.setenv("CI_LANE_DIAG", str(tmp_path / "diag.json"))
    return plug.LaneTimeoutPlugin()


def read_events(tmp_path: Path) -> list[dict]:
    import json

    path = tmp_path / "events.jsonl"
    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_journal_records_node_lifecycle(tmp_path, monkeypatch):
    """Старт/финиш ноды пишутся в журнал сразу.

    Журнал — единственный источник результатов, если процесс снимут
    принудительно: `--junitxml` в этот момент ещё не написан. Запись «по ходу»
    и есть то, из чего раннер потом собирает свежий JUnit (§8).
    """
    plugin = make_plugin(tmp_path, monkeypatch)
    try:
        plugin.pytest_sessionstart(session=None)
        plugin.pytest_runtest_logstart("t/test_a.py::test_x", location=None)
        plugin.pytest_runtest_logfinish("t/test_a.py::test_x", location=None)
        plugin.pytest_sessionfinish(session=None, exitstatus=0)
    finally:
        plugin._disarm()

    events = read_events(tmp_path)
    kinds = [event["event"] for event in events]
    assert kinds == ["session_start", "test_start", "test_finish", "session_finish"]
    assert events[0]["lane"] == "unit"
    assert events[1]["nodeid"] == "t/test_a.py::test_x"


def test_watchdog_is_not_armed_without_budget(tmp_path, monkeypatch):
    """Нулевой бюджет = watchdog выключен; таймер не должен заводиться."""
    plugin = make_plugin(tmp_path, monkeypatch, budget="0")
    try:
        assert plugin.budget == 0.0
        plugin.pytest_runtest_logstart("t/test_a.py::test_x", location=None)
        assert plugin._timer is None
    finally:
        plugin._disarm()


def test_watchdog_is_armed_and_disarmed_around_node(tmp_path, monkeypatch):
    """Таймер взводится на ноду и обязательно снимается на её финише.

    Не снятый таймер — это отложенный `os._exit(87)` посреди следующего теста:
    lane упал бы с чужим node ID в отчёте.
    """
    # Заведомо огромный бюджет: таймер в этом тесте сработать не должен.
    plugin = make_plugin(tmp_path, monkeypatch, budget="3600")
    try:
        assert plugin.budget == 3600.0
        plugin.pytest_runtest_logstart("t/test_a.py::test_x", location=None)
        armed = plugin._timer
        assert armed is not None and armed.is_alive()
        assert armed.daemon is True, "недемонический таймер задержит выход процесса"

        plugin.pytest_runtest_logfinish("t/test_a.py::test_x", location=None)
        assert plugin._timer is None
        assert plugin._current is None
    finally:
        plugin._disarm()
        if armed is not None:
            armed.cancel()


def test_arming_next_node_replaces_previous_timer(tmp_path, monkeypatch):
    """Каждая нода получает СВОЙ бюджет: старый таймер снимается при взводе нового."""
    plugin = make_plugin(tmp_path, monkeypatch, budget="3600")
    first = second = None
    try:
        plugin.pytest_runtest_logstart("t/test_a.py::test_x", location=None)
        first = plugin._timer
        plugin.pytest_runtest_logstart("t/test_a.py::test_y", location=None)
        second = plugin._timer
        assert first is not second
        assert first is not None and second is not None
        assert not first.is_alive() or first.finished.is_set()
    finally:
        plugin._disarm()
        for timer in (first, second):
            if timer is not None:
                timer.cancel()


def test_report_events_carry_phase_and_outcome(tmp_path, monkeypatch):
    """Отчёт фазы пишется с when/outcome — из них раннер сводит исход ноды."""

    class FakeReport:
        nodeid = "t/test_a.py::test_x"
        when = "call"
        outcome = "failed"
        duration = 1.23456
        failed = True
        longrepr = "полный текст падения"

    plugin = make_plugin(tmp_path, monkeypatch)
    try:
        plugin.pytest_runtest_logreport(FakeReport())
    finally:
        plugin._disarm()

    event = read_events(tmp_path)[0]
    assert event["event"] == "report"
    assert event["when"] == "call"
    assert event["outcome"] == "failed"
    assert event["duration"] == pytest.approx(1.2346, abs=1e-4)
    # `longrepr` не публикуется вовсе. Bible объявляет traceback непроверенным
    # вводом, а журнал его ни одним потребителем не читал: сборщик JUnit строит
    # отчёт из исходов. Измерено — туда уезжал `customer_password=…` из
    # assert-сообщения. Непубликуемое поле не может протечь.
    assert "longrepr" not in event
    assert "полный текст падения" not in json.dumps(event, ensure_ascii=False)


def test_journal_is_optional(monkeypatch):
    """Без CI_LANE_EVENTS плагин обязан молчать, а не падать.

    Плагин подключается явным `-p`, в том числе руками; отсутствие журнала —
    легальный режим, и он не должен ронять чужой прогон.
    """
    monkeypatch.delenv("CI_LANE_EVENTS", raising=False)
    monkeypatch.delenv("CI_LANE_DIAG", raising=False)
    monkeypatch.delenv("CI_LANE_PER_TEST_TIMEOUT", raising=False)
    plugin = plug.LaneTimeoutPlugin()
    try:
        assert plugin.events_path is None and plugin.diag_path is None
        plugin.pytest_runtest_logstart("t/test_a.py::test_x", location=None)
        plugin.pytest_runtest_logfinish("t/test_a.py::test_x", location=None)
    finally:
        plugin._disarm()


def test_deselected_hook_feeds_receipt_field(tmp_path, monkeypatch):
    """§8 требует поле `deselected`; в JUnit его нет — источник только хук."""
    if not hasattr(plug.LaneTimeoutPlugin, "pytest_deselected"):
        pytest.skip("хук pytest_deselected в плагине не объявлен")
    plugin = make_plugin(tmp_path, monkeypatch)
    try:
        plugin.pytest_deselected([object(), object(), object()])
    finally:
        plugin._disarm()
    event = read_events(tmp_path)[0]
    assert event["event"] == "deselected"
    assert event["count"] == 3


# --------------------------------------------------------------------------
# Код возврата
# --------------------------------------------------------------------------


def test_timeout_exit_code_cannot_be_confused_with_pytest():
    """§7, требование 5: у таймаута свой ненулевой код, не пересекающийся с pytest.

    pytest занимает 0–5. Если бы таймаут возвращал что-то из этого диапазона,
    раннер не отличил бы hang от обычного падения и §7 свёлся бы к «тесты
    покраснели».
    """
    assert plug.EXIT_TIMEOUT != 0
    assert plug.EXIT_TIMEOUT not in range(0, 6)
    assert 0 < plug.EXIT_TIMEOUT < 256, "код обязан быть представим в wait status"


# ---------------------------------------------------------------------------
# Redaction в источнике инвентаря (P-13)
# ---------------------------------------------------------------------------


@requires_proc
def test_child_cmdline_is_redacted_at_the_source():
    """Секрет из командной строки ребёнка не доживает до инвентаря.

    Это был блокирующий дефект. `child_processes()` читал сырой
    `/proc/<pid>/cmdline`, и раннер публиковал его в JUnit, журнал событий И
    диагностику таймаута — секрет попадал во все три артефакта сразу.
    P-13 объявляет redaction контрактом, а не соглашением.

    Очистка стоит именно В ИСТОЧНИКЕ, а не перед каждой публикацией: трёх
    точек очистки достаточно, чтобы однажды забыть одну. Тест проверяет
    источник, потому что все каналы питаются из него.
    """
    proc = None
    secret = "TEST_SECRET_SENTINEL_IN_CMDLINE"
    try:
        proc = subprocess.Popen(
            [
                sys.executable, "-c",
                "import sys,time; sys.stdout.write('ready\\n'); "
                "sys.stdout.flush(); time.sleep(60)",
                f"--token={secret}",
            ],
            stdout=subprocess.PIPE,
            text=True,
        )
        assert proc.stdout.readline().strip() == "ready"

        mine = [item for item in plug.child_processes() if item["pid"] == proc.pid]
        assert mine, "ребёнок не попал в инвентарь — проверять нечего"
        cmdline = str(mine[0]["cmdline"])
        assert secret not in cmdline, f"секрет пережил инвентарь: {cmdline!r}"
        # Диагностическая ценность сохранена: имя флага видно, значение — нет.
        assert "--token" in cmdline
        assert "argv:" in cmdline, "отпечаток обязан быть, иначе процессы не сличить"
    finally:
        reap(proc)


def test_redaction_helper_is_shared_not_forked():
    """Плагин пользуется общим модулем правила, а не своей копией.

    Второе правило публикации в репозитории хуже, чем ни одного: они
    разойдутся, и никто не заметит. Тест фиксирует, что импорт идёт из
    `ci_redaction`.
    """
    import ci_redaction

    assert plug.safe_cmdline is ci_redaction.safe_cmdline
    assert plug.summarize_argv is ci_redaction.summarize_argv


@requires_proc
def test_inventory_publishes_counters_and_digest():
    """Запись инвентаря несёт отпечаток и счётчики, а не только строку.

    Сокращённая строка сама по себе не даёт сличить два процесса: по ней не
    видно, сколько сведений скрыто. Поэтому рядом публикуются полное число
    аргументов, число скрытых позиционных и SHA-256 исходного argv.
    """
    proc = None
    try:
        proc = subprocess.Popen(
            [
                sys.executable, "-c",
                "import sys,time; sys.stdout.write('ready\\n'); "
                "sys.stdout.flush(); time.sleep(60)",
                "позиционный-секрет",
            ],
            stdout=subprocess.PIPE,
            text=True,
        )
        assert proc.stdout.readline().strip() == "ready"
        mine = [item for item in plug.child_processes() if item["pid"] == proc.pid]
        assert mine, "ребёнок не попал в инвентарь"
        record = mine[0]
        assert record["argc"] == 4
        assert record["positional_count"] >= 1
        assert len(str(record["argv_fingerprint"])) == 64
        assert "позиционный-секрет" not in str(record)
    finally:
        reap(proc)


@requires_proc
def test_forged_comm_from_a_real_child_never_reaches_the_inventory():
    """Ребёнок, подделавший себе `comm`, не публикует его через инвентарь.

    Это был блокирующий дефект. `comm` читался из `/proc/<pid>/stat` и клался
    в запись как есть, а процесс задаёт его себе сам через
    `prctl(PR_SET_NAME)`. Пятнадцать символов, полностью подконтрольных
    источнику, уходили в журнал событий, диагностику таймаута и JUnit.

    Тест поднимает НАСТОЯЩИЙ процесс с подделанным именем: проверка на
    синтетической строке доказала бы только правило, но не проводку.
    """
    secret = "q7z4m2n8p5r3t"
    proc = None
    try:
        proc = spawn(
            "import ctypes, sys, time; "
            'ctypes.CDLL("libc.so.6").prctl(15, b"' + secret + '", 0, 0, 0); '
            "sys.stdout.write('ready\\n'); sys.stdout.flush(); time.sleep(60)"
        )
        raw = Path(f"/proc/{proc.pid}/stat").read_text(encoding="utf-8")
        assert f"({secret})" in raw, f"prctl не применился: {raw[:80]!r}"

        found = [item for item in plug.child_processes() if item["pid"] == proc.pid]
        assert found, "процесс потерян инвентарём"
        assert secret not in json.dumps(found[0], ensure_ascii=False), (
            f"подделанный comm опубликован: {found[0]!r}"
        )
        assert found[0]["comm"] == "<comm>"
    finally:
        reap(proc)


def test_thread_dump_is_sanitised_before_publication():
    """Дамп проходит обработку до попадания в артефакт.

    Каталоги в путях несут идентификаторы проекта и клиента. Дамп нужен
    целиком — он единственный отвечает, ГДЕ зависло, — поэтому от пути
    остаётся имя файла, а не пустое место.
    """
    dump = plug.thread_dump()
    assert dump.strip(), "дамп пуст — проверять нечего"
    cleaned = plug.sanitize_traceback(dump)
    assert "line " in cleaned, "потеряны номера строк — дамп обесценен"
    assert "/root/" not in cleaned and "/usr/" not in cleaned, (
        f"каталоги пережили обработку: {cleaned[:200]!r}"
    )
