"""Бюджет прогона регресс-гейта (находка OPS03-F10).

Что доказывают эти тесты
────────────────────────
Гейт запускал pytest без ограничения по времени. На машине, где тест зависает,
он не отказывал, а висел неопределённо долго: ревью наблюдало отсутствие
прогресса дольше семи минут и сняло прогон вручную. Это ровно тот класс
отказа, ради которого §7 контракта вводит бюджеты, — но сам гейт под них
заведён не был, их получил только новый lane-раннер.

Здесь проверяется, что зависание превращается в отказ с диагнозом и что
бюджет нельзя обессмыслить значением.

Run: python -m pytest tests/test_ci_regression_gate_budget.py -q -p no:cacheprovider
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_ROOT / "scripts"))

import ci_regression_gate as gate  # noqa: E402


def test_budget_rejects_values_that_defeat_its_purpose(monkeypatch):
    """Бюджет, который нельзя выдержать, не принимается молча.

    Ноль, отрицательное и бесконечность обессмысливают само ограничение:
    сторож с бесконечным бюджетом — это отсутствие сторожа.
    """
    monkeypatch.delenv(gate.WALL_BUDGET_ENV, raising=False)
    assert gate.wall_budget_sec() == gate.DEFAULT_WALL_BUDGET_SEC

    for bad in ("0", "-1", "nan", "inf", "не-число", ""):
        monkeypatch.setenv(gate.WALL_BUDGET_ENV, bad)
        assert gate.wall_budget_sec() == gate.DEFAULT_WALL_BUDGET_SEC, bad

    monkeypatch.setenv(gate.WALL_BUDGET_ENV, "42.5")
    assert gate.wall_budget_sec() == 42.5


def test_default_budget_leaves_room_for_a_slow_runner():
    """Потолок не должен мешать медленной машине.

    Наблюдённые времена полного прогона — 335–500 с в зависимости от загрузки.
    Бюджет обязан быть заметно больше, иначе он начнёт снимать здоровые
    прогоны, и его выключат.
    """
    assert gate.DEFAULT_WALL_BUDGET_SEC >= 1200


def test_hanging_run_becomes_a_bounded_failure(tmp_path: Path):
    """Зависание превращается в отказ с диагнозом, а не в бесконечное ожидание.

    Гоняется настоящий гейт в отдельном дереве: подменять `subprocess` внутри
    процесса значило бы проверять заглушку, а не проводку.
    """
    root = tmp_path / "gate_root"
    (root / "scripts").mkdir(parents=True)
    (root / "tests").mkdir()
    for name in ("ci_regression_gate.py",):
        (root / "scripts" / name).write_bytes((_ROOT / "scripts" / name).read_bytes())
    (root / "scripts" / "ci_known_failures.txt").write_text(
        "# Кол-во: 0\n", encoding="utf-8"
    )
    (root / "tests" / "test_hang.py").write_text(
        "import time\n\n\ndef test_hangs():\n    time.sleep(600)\n", encoding="utf-8"
    )
    (root / "backend").mkdir()
    (root / "backend" / "tests").mkdir()

    env = dict(os.environ, AUDIT_DISABLE_DOTENV="1")
    env[gate.WALL_BUDGET_ENV] = "5"
    started = time.monotonic()
    proc = subprocess.Popen(
        [sys.executable, str(root / "scripts" / "ci_regression_gate.py")],
        cwd=str(root), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, start_new_session=True,
    )
    try:
        out, _ = proc.communicate(timeout=90)
    except subprocess.TimeoutExpired:
        os.killpg(os.getpgid(proc.pid), 9)
        out, _ = proc.communicate(timeout=10)
        pytest.fail("гейт не уложился во внешний бюджет — сторож сам завис")
    elapsed = time.monotonic() - started

    assert proc.returncode != 0, out
    assert "бюджет" in out.lower(), out
    assert "ci_test_lane" in out, "отказ обязан подсказать, чем найти зависший тест"
    assert elapsed < 60, f"отказ занял {elapsed:.1f} с при бюджете 5 с"


def _pid_alive(pid: int) -> bool:
    """Жив ли процесс. Зомби считается мёртвым."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return True
    close = stat.rfind(")")
    fields = stat[close + 2 :].split() if close >= 0 else []
    return bool(fields) and fields[0] != "Z"


def _build_gate_tree(root: Path, test_body: str) -> None:
    """Отдельное дерево с копией гейта и одним подопытным тестом."""
    (root / "scripts").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "backend" / "tests").mkdir(parents=True)
    (root / "scripts" / "ci_regression_gate.py").write_bytes(
        (_ROOT / "scripts" / "ci_regression_gate.py").read_bytes()
    )
    (root / "scripts" / "ci_known_failures.txt").write_text(
        "# Кол-во: 0\n", encoding="utf-8"
    )
    (root / "tests" / "test_hang.py").write_text(test_body, encoding="utf-8")


#: Подопытный тест записывает СВОЙ pid и pid своего ребёнка в файлы. Только по
#: ним и можно доказать, что после снятия не осталось ни одного процесса:
#: прежняя проверка звала `pgrep -f <абсолютный tmp>/tests`, а дочерний pytest
#: запускается с ОТНОСИТЕЛЬНЫМИ argv `tests backend/tests` — рабочий каталог в
#: командную строку не входит, и pgrep не находил живого сироту никогда.
_HANG_WITH_CHILD = """
import os, subprocess, sys, time
from pathlib import Path

OUT = Path(os.environ["ORPHAN_PID_DIR"])


def test_hangs():
    OUT.joinpath("pytest.pid").write_text(str(os.getpid()))
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
    OUT.joinpath("child.pid").write_text(str(child.pid))
    time.sleep(600)
"""


def test_hanging_run_leaves_no_orphan_processes(tmp_path: Path):
    """После снятия по бюджету не остаётся ни pytest, ни его потомка.

    Доказывается по РЕАЛЬНЫМ pid, которые подопытный тест записывает сам.
    Прежняя редакция искала процесс через `pgrep -f <абсолютный путь>/tests`,
    но дочерний pytest запускается с относительными `tests backend/tests`:
    рабочего каталога в его командной строке нет, и проверка проходила бы даже
    при живом сироте.

    Осиротевший процесс держит порт, файл или лок и валит СЛЕДУЮЩИЙ прогон
    причиной, не связанной с его кодом.
    """
    root = tmp_path / "gate_root"
    pid_dir = tmp_path / "pids"
    pid_dir.mkdir()
    _build_gate_tree(root, _HANG_WITH_CHILD)

    env = dict(os.environ, AUDIT_DISABLE_DOTENV="1", ORPHAN_PID_DIR=str(pid_dir))
    env[gate.WALL_BUDGET_ENV] = "8"
    proc = subprocess.Popen(
        [sys.executable, str(root / "scripts" / "ci_regression_gate.py")],
        cwd=str(root), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, start_new_session=True,
    )
    out, _ = proc.communicate(timeout=120)

    pids = {}
    for name in ("pytest.pid", "child.pid"):
        path = pid_dir / name
        assert path.is_file(), f"{name} не записан — подопытный тест не стартовал:\n{out}"
        pids[name] = int(path.read_text().strip())

    deadline = time.monotonic() + 20
    alive = {n: p for n, p in pids.items() if _pid_alive(p)}
    while alive and time.monotonic() < deadline:
        time.sleep(0.2)
        alive = {n: p for n, p in alive.items() if _pid_alive(p)}
    try:
        assert not alive, f"после снятия по бюджету остались сироты: {alive}"
    finally:
        for pid in pids.values():
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass


def test_interrupt_also_kills_the_detached_pytest(tmp_path: Path):
    """Прерывание гейта не оставляет отвязанный pytest работать.

    `start_new_session=True` отвязывает pytest от управляющего процесса, и
    сигнал, посланный гейту, до pytest не доходит. Пока cleanup стоял только в
    ветке бюджета, Ctrl+C убивал гейт и оставлял pytest сиротой до конца его
    собственного прогона.
    """
    root = tmp_path / "gate_root_int"
    pid_dir = tmp_path / "pids_int"
    pid_dir.mkdir()
    _build_gate_tree(root, _HANG_WITH_CHILD)

    env = dict(os.environ, AUDIT_DISABLE_DOTENV="1", ORPHAN_PID_DIR=str(pid_dir))
    env[gate.WALL_BUDGET_ENV] = "600"          # бюджет заведомо не сработает
    proc = subprocess.Popen(
        [sys.executable, str(root / "scripts" / "ci_regression_gate.py")],
        cwd=str(root), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if (pid_dir / "child.pid").is_file():
                break
            time.sleep(0.2)
        else:
            proc.kill()
            pytest.fail("подопытный тест не успел стартовать")
        time.sleep(0.5)

        proc.send_signal(signal.SIGINT)          # ровно то, что делает Ctrl+C
        proc.communicate(timeout=60)

        pids = {
            name: int((pid_dir / name).read_text().strip())
            for name in ("pytest.pid", "child.pid")
            if (pid_dir / name).is_file()
        }
        assert pids, "pid не записаны"
        deadline = time.monotonic() + 20
        alive = {n: p for n, p in pids.items() if _pid_alive(p)}
        while alive and time.monotonic() < deadline:
            time.sleep(0.2)
            alive = {n: p for n, p in alive.items() if _pid_alive(p)}
        assert not alive, f"прерывание оставило сирот: {alive}"
    finally:
        for name in ("pytest.pid", "child.pid"):
            path = pid_dir / name
            if path.is_file():
                try:
                    os.kill(int(path.read_text().strip()), signal.SIGKILL)
                except OSError:
                    pass
        if proc.poll() is None:
            proc.kill()
