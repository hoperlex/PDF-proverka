"""Сторож disposition разметки полос (`W0-INT-01`, REV-29).

Числа в документе устаревают на каждом коммите — ревью поймало это дважды.
Поэтому фиксируется не счётчик, а СТРУКТУРНОЕ утверждение, ради которого
disposition и делался: полоса не должна получать тест, которому нужно больше,
чем она предоставляет.

Обратное направление (маркер тяжелее поведения) под сторожем не стоит намеренно:
оно безопасно по построению и признано долгом, см.
`docs/architecture/LANE_DISPOSITION_W0-INT-01.md` §4.2.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

# Primary lane §5: network — инвентарь запускается дочерним процессом.
pytestmark = pytest.mark.network

ROOT = Path(__file__).resolve().parent.parent

#: Единственное расхождение, признанное ложным при разборе глазами.
#: `uvicorn` в этом тесте — строка в списке ЗАПРЕЩЁННЫХ имён, которые он ищет в
#: чужом AST; сам он ничего не поднимает. См. §4.1 disposition.
KNOWN_FALSE_POSITIVES = {
    "tests/test_distributed_workers_network_e2e_11g.py"
    "::test_ad_worker_opens_no_inbound_port",
}


def _inventory() -> dict:
    done = subprocess.run(
        [sys.executable, str(ROOT / "scripts/ci_lane_inventory.py"), "--json"],
        capture_output=True,
        text=True,
        timeout=600,
        cwd=str(ROOT),
    )
    assert done.returncode in (0, 1), f"инвентарь вернул {done.returncode}: {done.stderr[-400:]}"
    return json.loads(done.stdout)


@pytest.fixture(scope="module")
def report() -> dict:
    return _inventory()


def test_lane_invariant_holds(report: dict) -> None:
    """§5: ровно один первичный маркер на ноду, сумма по полосам сходится."""
    totals = report["totals"]
    assert totals["functions_without_primary_marker"] == 0
    assert totals["double_marked_functions"] == 0
    marked = report["markers"]["primary_marker_functions"]
    assert sum(marked.values()) == totals["test_functions"]


def test_no_test_needs_more_than_its_lane_provides(report: dict) -> None:
    """Опасное направление обязано оставаться пустым сверх известных ложных.

    Именно оно ломает прогон: тест, которому нужен процесс или сокет, в полосе
    `unit` не получит гарантии §6 на эти capability.
    """
    dangerous = {
        f"{c['path']}::{c['function']}"
        for c in report["conflicts"]
        if c.get("direction") == "understated"
    }
    new = dangerous - KNOWN_FALSE_POSITIVES
    assert not new, (
        "появились тесты, которым нужно больше, чем даёт их полоса: "
        + ", ".join(sorted(new))
    )


def test_known_false_positives_still_exist(report: dict) -> None:
    """Список исключений не должен пережить свою причину.

    Если расхождение исчезло — инструмент стал точнее или тест переписан, — запись
    обязана уйти из списка, иначе она молча начнёт покрывать что-то другое.
    """
    dangerous = {
        f"{c['path']}::{c['function']}"
        for c in report["conflicts"]
        if c.get("direction") == "understated"
    }
    stale = KNOWN_FALSE_POSITIVES - dangerous
    assert not stale, f"исключение больше не нужно, удалите его: {sorted(stale)}"


def test_no_overstated_marker_is_chaos(report: dict) -> None:
    """Перетяжеление безопасно — кроме одного случая.

    `chaos` исключён из прогона по умолчанию (`addopts = -m "not chaos"`), поэтому
    тест, ошибочно уехавший туда, молча выпадает из покрытия.
    """
    stowaways = [
        f"{c['path']}::{c['function']}"
        for c in report["conflicts"]
        if c.get("direction") == "overstated" and c["marker"] == "chaos"
    ]
    assert not stowaways, f"уехали в chaos и выпали из прогона по умолчанию: {stowaways}"
