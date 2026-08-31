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


def test_hanging_run_leaves_no_orphan_processes(tmp_path: Path):
    """После снятия по бюджету не остаётся осиротевшего pytest.

    Осиротевший процесс держит порт, файл или лок и валит СЛЕДУЮЩИЙ прогон
    причиной, не связанной с его кодом.
    """
    root = tmp_path / "gate_root2"
    (root / "scripts").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "backend" / "tests").mkdir(parents=True)
    (root / "scripts" / "ci_regression_gate.py").write_bytes(
        (_ROOT / "scripts" / "ci_regression_gate.py").read_bytes()
    )
    (root / "scripts" / "ci_known_failures.txt").write_text("# Кол-во: 0\n", encoding="utf-8")
    marker = "orphan_probe_marker_12345"
    (root / "tests" / "test_hang.py").write_text(
        f"import time\n\n\ndef test_hangs():\n    {marker} = 1\n    time.sleep(600)\n",
        encoding="utf-8",
    )

    env = dict(os.environ, AUDIT_DISABLE_DOTENV="1")
    env[gate.WALL_BUDGET_ENV] = "5"
    proc = subprocess.Popen(
        [sys.executable, str(root / "scripts" / "ci_regression_gate.py")],
        cwd=str(root), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, start_new_session=True,
    )
    proc.communicate(timeout=90)

    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        alive = subprocess.run(
            ["pgrep", "-f", str(root / "tests")], capture_output=True, text=True
        ).stdout.strip()
        if not alive:
            break
        time.sleep(0.2)
    else:
        pytest.fail("после снятия по бюджету остался осиротевший pytest")
