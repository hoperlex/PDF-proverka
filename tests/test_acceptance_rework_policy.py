"""Исполняемый контракт ограниченной приёмки ``acceptance-rework/v1``."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest


pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parent.parent
POLICY_JSON = (
    ROOT / "docs" / "architecture" / "policies" / "acceptance-rework-v1.json"
)
POLICY_MD = ROOT / "docs" / "architecture" / "ACCEPTANCE_REWORK_POLICY_V1.md"
ROADMAP = ROOT / "docs" / "architecture" / "HYBRID_REWRITE_ROADMAP.md"
WAVE_PLAN = ROOT / "docs" / "architecture" / "WAVE_0_0_04_PLAN.md"
AGENT_RULES = ROOT / "AGENTS.md"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
REGRESSION_GATE = ROOT / "scripts" / "ci_regression_gate.py"


def _policy() -> dict:
    return json.loads(POLICY_JSON.read_text(encoding="utf-8"))


def test_policy_has_hard_non_retrying_budget() -> None:
    policy = _policy()
    budget = policy["budgets"]

    assert policy["policy_id"] == "acceptance-rework/v1"
    assert policy["status"] == "enforced"
    assert budget == {
        "max_full_gate_attempts_per_window": 2,
        "max_remediation_rounds_per_window": 1,
        "max_full_gate_wall_seconds": 1800,
        "max_failure_triage_minutes": 15,
        "automatic_retries": 0,
    }
    assert policy["every_started_full_gate_counts"] is True
    assert policy["terminal_after_second_unsuccessful_attempt"] is True
    assert policy["new_window_after_limit_requires_human_owner"] is True
    assert "third_full_gate_attempt" in policy["forbidden_same_window_actions"]


def test_policy_classes_only_candidate_regression_as_same_window_fix() -> None:
    policy = _policy()

    assert policy["same_window_remediation_classes"] == ["candidate_regression"]
    assert set(policy["finding_classes"]) == {
        "candidate_regression",
        "pre_existing_or_flaky",
        "environment_or_evidence",
        "out_of_scope_improvement",
        "security_or_data_blocker",
    }
    assert set(policy["terminal_statuses"]) == {
        "accepted",
        "split",
        "rejected",
        "blocked_external",
    }


def test_prose_and_workflow_entrypoints_adopt_the_policy() -> None:
    policy_text = POLICY_MD.read_text(encoding="utf-8")
    assert "максимум **2** запущенных полных гейта" in policy_text
    assert "максимум **1** remediation round" in policy_text
    assert "третья попытка в том же окне запрещена" in policy_text.lower()

    for path in (ROADMAP, WAVE_PLAN):
        text = path.read_text(encoding="utf-8")
        assert "acceptance-rework/v1" in text, path.relative_to(ROOT)
        assert "трет" in text.lower(), path.relative_to(ROOT)

    agent_text = AGENT_RULES.read_text(encoding="utf-8")
    assert "acceptance-rework/v1" in agent_text
    assert "third attempt" in agent_text.lower()

    workflow = CI_WORKFLOW.read_text(encoding="utf-8")
    assert re.search(r"(?m)^concurrency:\s*$", workflow)
    assert re.search(r"(?m)^\s+cancel-in-progress:\s+true\s*$", workflow)


def test_full_gate_wall_budget_matches_policy() -> None:
    source = REGRESSION_GATE.read_text(encoding="utf-8")
    match = re.search(
        r"(?m)^DEFAULT_WALL_BUDGET_SEC\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*$",
        source,
    )
    assert match, "ci_regression_gate.py не объявляет DEFAULT_WALL_BUDGET_SEC"
    assert float(match.group(1)) == _policy()["budgets"]["max_full_gate_wall_seconds"]
