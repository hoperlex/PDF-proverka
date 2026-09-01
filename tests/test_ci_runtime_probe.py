"""Тесты runtime capability probe (`scripts/ci_runtime_probe.py`), W0-OPS-03.

Что здесь проверяется в первую очередь — не «probe зелёный», а то, что он
НЕ ВРЁТ и НЕ ВИСНЕТ:

* таблица «lane → обязательные capabilities» совпадает с §5 контракта
  `docs/architecture/QUALITY_RUNTIME_CONTRACT_V1.md` (иначе probe разрешит lane,
  для которого окружение не готово);
* отсутствие обязательной capability даёт setup failure и ненулевой код, а не
  skip (§6, правило 1) — статуса «skip» в отчёте нет вообще;
* не выбранные lanes видны как `NOT_RUN`, а не `passed`/`skipped` (§6, правило 2);
* зависшая проверка снимается по timeout и превращается в код причины, а не в
  вечное ожидание;
* значения секретов не попадают в вывод ни в человекочитаемом, ни в JSON-виде.

Тесты обязаны быть быстрыми и не ходить наружу: probe трогает только loopback.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

# Primary lane §5: network — запускает настоящие дочерние процессы.
pytestmark = pytest.mark.network

ROOT = Path(__file__).resolve().parent.parent
PROBE_PATH = ROOT / "scripts" / "ci_runtime_probe.py"
CONTRACT_PATH = ROOT / "docs" / "architecture" / "QUALITY_RUNTIME_CONTRACT_V1.md"

_spec = importlib.util.spec_from_file_location("ci_runtime_probe", PROBE_PATH)
probe = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
# Регистрация ДО exec_module обязательна: @dataclass с строковыми аннотациями
# резолвит их через sys.modules[cls.__module__].
sys.modules["ci_runtime_probe"] = probe
_spec.loader.exec_module(probe)

def clean_env(**overrides: str) -> dict[str, str]:
    """Окружение для дочернего probe без чужих provider secrets.

    Наследовать `os.environ` как есть нельзя: сам pytest-процесс сейчас грузит
    репозиторный `.env` (`tests/conftest.py` не выставляет
    `AUDIT_DISABLE_DOTENV=1`, а `backend/app/core/config.py` подхватывает файл),
    поэтому в окружении теста реально лежат провайдерские ключи. Это ровно то
    расхождение с §3.2, которое probe и обязан ловить; чтобы тест проверял
    заявленную ветку, а не это расхождение, ключи здесь снимаются.
    """
    env = {
        name: value
        for name, value in os.environ.items()
        if not (
            name in probe.PROVIDER_SECRET_ENV or probe.PROVIDER_SECRET_PATTERN.match(name)
        )
    }
    env["AUDIT_DISABLE_DOTENV"] = "1"
    env.update(overrides)
    return env


def run_cli(*args: str, env: dict[str, str] | None = None, timeout: float = 60.0):
    """Запустить probe как CLI. timeout здесь — страховка теста от зависания."""
    return subprocess.run(
        [sys.executable, str(PROBE_PATH), *args],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        env=env if env is not None else clean_env(),
        timeout=timeout,
    )


# --------------------------------------------------------------------------
# §5: таблица lane → обязательные capabilities
# --------------------------------------------------------------------------


def test_lane_capability_table_matches_contract_section5():
    """Таблица взята из §5 дословно; любое расхождение — правка контракта."""
    assert probe.LANE_CAPABILITIES == {
        "unit": ("base_python",),
        "contract": ("base_python", "process_spawn"),
        "integration": ("base_python", "thread_wakeup", "loopback"),
        "network": ("base_python", "thread_wakeup", "loopback", "process_spawn"),
        "chaos": (
            "base_python",
            "thread_wakeup",
            "loopback",
            "process_spawn",
            "process_signals",
            "temp_space_2gib",
        ),
    }
    assert tuple(probe.LANES) == ("unit", "contract", "integration", "network", "chaos")


def test_chaos_requires_all_capabilities():
    """§5: у chaos — «все capabilities, ≥2 GiB temp»."""
    chaos = set(probe.LANE_CAPABILITIES["chaos"])
    assert chaos == set(probe.LANE_CAPABILITY_IDS)
    for lane, caps in probe.LANE_CAPABILITIES.items():
        assert set(caps) <= chaos, lane
    assert "temp_space_2gib" in chaos
    assert "process_signals" in chaos


def test_only_chaos_requires_signals_and_only_it_probes_them():
    """SIGTERM/SIGKILL контракт требует именно для chaos (§5/§6)."""
    for lane in probe.LANES:
        required = "process_signals" in probe.LANE_CAPABILITIES[lane]
        assert required is (lane == "chaos"), lane


def test_contract_constants_match_frozen_document():
    """Пины и receipt-хеши в коде совпадают с текстом замороженного контракта."""
    text = CONTRACT_PATH.read_text(encoding="utf-8")
    assert probe.CONTRACT_ID in text
    assert probe.CONTRACT_VERSION in text
    assert probe.CONTRACT_BASE_COMMIT in text
    assert probe.REFERENCE_PIP_FREEZE_SHA256 in text
    for rel, digest in {**probe.DEPENDENCY_RECEIPT, **probe.FRONTEND_RECEIPT}.items():
        assert digest in text, rel
    assert probe.REQUIRED_NODE in text and probe.REQUIRED_NPM in text
    assert "3.12.3" in text


# --------------------------------------------------------------------------
# §6, правило 1: setup failure вместо skip
# --------------------------------------------------------------------------


def test_missing_required_capability_is_setup_failure_not_skip(monkeypatch):
    """Сломанная обязательная capability валит lane с ненулевым кодом."""
    spec = next(s for s in probe.CHECKS if s.check_id == "loopback")
    monkeypatch.setattr(
        spec,
        "runner",
        lambda ctx: probe.Outcome(False, "SOCKET_CREATE_DENIED", "socket запрещён (тест)"),
    )
    report = probe.run_probe("network", timeout=5.0)
    row = next(r for r in report["checks"] if r["check"] == "loopback")
    assert row["status"] == probe.STATUS_FAIL
    assert row["severity"] == probe.SEVERITY_REQUIRED
    assert row["reason_code"] == "SOCKET_CREATE_DENIED"
    assert report["result"] == "setup_failure"
    assert report["exit_code"] != 0
    assert any(f["check"] == "loopback" for f in report["required_failed"])


def test_capability_not_required_for_lane_is_not_run(monkeypatch):
    """Та же поломка для unit — NOT_RUN: §5 не требует loopback для unit."""
    spec = next(s for s in probe.CHECKS if s.check_id == "loopback")
    calls: list[str] = []

    def _boom(ctx):  # pragma: no cover — не должен вызываться
        calls.append(ctx.lane)
        return probe.Outcome(False, "SOCKET_CREATE_DENIED", "socket запрещён (тест)")

    monkeypatch.setattr(spec, "runner", _boom)
    report = probe.run_probe("unit", timeout=5.0)
    row = next(r for r in report["checks"] if r["check"] == "loopback")
    assert row["status"] == probe.STATUS_NOT_RUN
    assert row["reason_code"] == "NOT_REQUIRED_FOR_LANE"
    assert calls == [], "проверка, не обязательная для lane, не должна выполняться"


@pytest.mark.parametrize("lane", ["unit", "contract", "integration", "network", "chaos"])
def test_report_never_uses_skip_vocabulary(lane):
    """§6.1: skip запрещён — в словаре статусов его нет."""
    report = probe.run_probe(lane, timeout=8.0)
    statuses = {row["status"] for row in report["checks"]}
    assert statuses <= {
        probe.STATUS_PASS,
        probe.STATUS_FAIL,
        probe.STATUS_WARN,
        probe.STATUS_NOT_RUN,
    }
    assert not any("skip" in s.lower() for s in statuses)
    assert report["result"] in {"ok", "setup_failure"}


def test_user_non_root_severity_follows_section_6_rule_2():
    """Послабление §6.2 дано только локальным unit/contract; enforce — всем."""
    spec = next(s for s in probe.CHECKS if s.check_id == "user_non_root")
    for lane in ("unit", "contract"):
        assert probe.severity_for(spec, lane, enforce=False) == probe.SEVERITY_ADVISORY
        assert probe.severity_for(spec, lane, enforce=True) == probe.SEVERITY_REQUIRED
    for lane in ("integration", "network", "chaos"):
        assert probe.severity_for(spec, lane, enforce=False) == probe.SEVERITY_REQUIRED
        assert probe.severity_for(spec, lane, enforce=True) == probe.SEVERITY_REQUIRED


def test_lane_capabilities_are_required_in_both_modes():
    """Lane capability из §5 обязательна и локально, и в enforce."""
    for lane, caps in probe.LANE_CAPABILITIES.items():
        for spec in probe.CHECKS:
            if spec.profile_check:
                continue
            expected = (
                probe.SEVERITY_REQUIRED
                if spec.check_id in caps
                else probe.SEVERITY_NOT_APPLICABLE
            )
            assert probe.severity_for(spec, lane, enforce=False) == expected
            assert probe.severity_for(spec, lane, enforce=True) == expected


@pytest.mark.skipif(os.getuid() != 0, reason="проверка поведения именно под root")
def test_root_blocks_network_and_chaos_but_not_local_unit():
    """На root-машине network/chaos обязаны отказать, а unit — нет из-за uid."""
    for lane in ("network", "chaos"):
        report = probe.run_probe(lane, timeout=8.0)
        codes = {f["reason_code"] for f in report["required_failed"]}
        assert "USER_IS_ROOT" in codes, lane
        assert report["exit_code"] != 0
    unit = probe.run_probe("unit", timeout=8.0)
    unit_row = next(r for r in unit["checks"] if r["check"] == "user_non_root")
    assert unit_row["status"] == probe.STATUS_WARN
    assert unit_row["reason_code"] == "USER_IS_ROOT"


# --------------------------------------------------------------------------
# §6, правило 2: NOT_RUN, а не passed/skipped
# --------------------------------------------------------------------------


@pytest.mark.parametrize("lane", ["unit", "contract", "integration", "network", "chaos"])
def test_unselected_lanes_are_reported_as_not_run(lane):
    report = probe.run_probe(lane, timeout=8.0)
    assert report["lanes"][lane] == "PROBED"
    for other in probe.LANES:
        if other == lane:
            continue
        assert report["lanes"][other] == probe.STATUS_NOT_RUN
        assert report["lanes"][other] not in {"passed", "skipped", probe.STATUS_PASS}


def test_not_run_lanes_visible_in_human_output():
    report = probe.run_probe("unit", timeout=8.0)
    text = probe.render_text(report)
    assert "unit=PROBED" in text
    assert "network=NOT_RUN" in text and "chaos=NOT_RUN" in text
    assert "NOT_RUN — это НЕ passed и НЕ skipped" in text


# --------------------------------------------------------------------------
# Анти-hang
# --------------------------------------------------------------------------


def test_run_child_kills_hanging_probe_within_budget():
    """Зависший ребёнок снимается по внешнему timeout, а не ждёт вечно."""
    started = time.monotonic()
    result = probe.run_child("import time; time.sleep(120)", budget=1.0)
    elapsed = time.monotonic() - started
    assert result["timed_out"] is True
    assert result["ok"] is False
    assert elapsed < 15.0, f"cleanup занял {elapsed:.1f}s"


def test_thread_wakeup_hang_becomes_reason_code(monkeypatch):
    """AnyIO wake-up hang (§6, sandbox 2026-08-28) — код причины, а не зависание."""
    monkeypatch.setattr(
        probe,
        "run_child",
        lambda code, budget, args=(): {"ok": False, "code": None, "timed_out": True, "detail": ""},
    )
    ctx = probe.ProbeContext(lane="network", enforce=False, timeout=2.0, environment={})
    outcome = probe.check_thread_wakeup(ctx)
    assert outcome.ok is False
    assert outcome.reason_code == "ANYIO_ROUNDTRIP_HANG"


def test_loopback_hang_becomes_reason_code(monkeypatch):
    monkeypatch.setattr(
        probe,
        "run_child",
        lambda code, budget, args=(): {"ok": False, "code": None, "timed_out": True, "detail": ""},
    )
    ctx = probe.ProbeContext(lane="network", enforce=False, timeout=2.0, environment={})
    outcome = probe.check_loopback(ctx)
    assert outcome.ok is False
    assert outcome.reason_code == "LOOPBACK_PROBE_HANG"


def test_socket_denied_is_reported_with_its_own_code(monkeypatch):
    """Запрет socket в песочнице должен называться своим кодом."""
    monkeypatch.setattr(
        probe,
        "run_child",
        lambda code, budget, args=(): {
            "ok": False,
            "code": "SOCKET_CREATE_DENIED",
            "timed_out": False,
            "detail": "PermissionError: socket",
        },
    )
    ctx = probe.ProbeContext(lane="network", enforce=False, timeout=2.0, environment={})
    outcome = probe.check_loopback(ctx)
    assert outcome.reason_code == "SOCKET_CREATE_DENIED"
    assert "PermissionError" in outcome.message


@pytest.mark.parametrize("timeout", [0.01, 0.5, 1.0, 2.0, 10.0])
def test_inner_timeout_is_strictly_smaller_than_outer(timeout: float):
    """Внутренний бюджет меньше внешнего — иначе hang неотличим от отказа."""
    ctx = probe.ProbeContext(lane="network", enforce=False, timeout=timeout, environment={})
    assert 0 < ctx.inner_timeout < ctx.timeout


@pytest.mark.parametrize("lane", ["unit", "contract", "integration", "network", "chaos"])
def test_cli_finishes_fast_for_every_lane(lane):
    """Probe не имеет права стать источником зависания, от которого защищает."""
    started = time.monotonic()
    done = run_cli("--profile", lane, timeout=60.0)
    elapsed = time.monotonic() - started
    assert done.returncode in (0, 1), done.stderr[-500:]
    assert elapsed < 30.0, f"lane {lane} занял {elapsed:.1f}s"


# --------------------------------------------------------------------------
# Вывод: человек и парсер
# --------------------------------------------------------------------------


def test_json_report_carries_receipt_fields():
    """JSON пригоден как вход для run receipt §8."""
    done = run_cli("--profile", "contract", "--json")
    report = json.loads(done.stdout)
    for field in (
        "contract_id",
        "contract_version",
        "source_commit",
        "lane",
        "command",
        "started_at",
        "completed_at",
        "duration_seconds",
        "exit_code",
        "capabilities",
        "lanes",
        "checks",
        "environment",
        "norm_artifact_sha256",
        "python_lock_sha256",
        "pip_freeze_sha256",
        "frontend_lock_sha256",
    ):
        assert field in report, field
    assert report["contract_id"] == "quality-runtime/v1"
    assert report["lane"] == "contract"
    assert report["exit_code"] == done.returncode
    env = report["environment"]
    for field in ("os_image", "architecture", "uid", "python_version"):
        assert field in env, field


def test_every_check_has_machine_code_and_human_text():
    report = probe.run_probe("chaos", timeout=8.0)
    for row in report["checks"]:
        assert row["check"] and row["title"] and row["contract_ref"]
        if row["status"] == probe.STATUS_PASS:
            assert row["reason_code"] is None
        else:
            assert row["reason_code"] in probe.REASON_CODES, row
            assert row["reason_text"], row
            assert row["message"], row


def test_all_emitted_reason_codes_are_registered():
    """Ни один код причины не должен существовать вне реестра REASON_CODES."""
    source = PROBE_PATH.read_text(encoding="utf-8")
    emitted = set()
    for pattern in (
        r"emit\(False, \"([A-Z0-9_]+)\"",
        r"Outcome\(\s*False,\s*\n?\s*\"([A-Z0-9_]+)\"",
        r"or \"([A-Z0-9_]+)\",",
        r"\"code\": \"([A-Z0-9_]+)\"",
        r"reason_code=\"([A-Z0-9_]+)\"",
    ):
        emitted |= set(re.findall(pattern, source))
    assert emitted, "не нашли ни одного кода — сломан сам тест"
    unknown = sorted(emitted - set(probe.REASON_CODES))
    assert not unknown, f"коды вне реестра: {unknown}"


def test_usage_errors_exit_with_code_2():
    assert run_cli("--profile", "smoke").returncode == probe.EXIT_USAGE
    assert run_cli().returncode == probe.EXIT_USAGE
    for value in ("0", "-1", "nan", "inf", "-inf"):
        assert run_cli("--profile", "unit", "--timeout", value).returncode == probe.EXIT_USAGE


# --------------------------------------------------------------------------
# Секреты: имена — да, значения — никогда
# --------------------------------------------------------------------------


def test_secret_values_are_never_printed():
    sentinel = "sk-qr-v1-do-not-print-3f8a91"
    env = clean_env(OPENROUTER_API_KEY=sentinel)
    human = run_cli("--profile", "unit", env=env)
    machine = run_cli("--profile", "unit", "--json", env=env)
    for done in (human, machine):
        assert done.returncode == probe.EXIT_SETUP_FAILURE
        blob = done.stdout + done.stderr
        assert sentinel not in blob, "значение секрета попало в вывод"
        assert "OPENROUTER_API_KEY" in blob, "имя переменной должно быть названо"
    report = json.loads(machine.stdout)
    row = next(r for r in report["checks"] if r["check"] == "secrets_absent")
    assert row["status"] == probe.STATUS_FAIL
    assert row["reason_code"] == "SECRET_PRESENT_IN_ENV"


def test_paid_api_enabled_is_a_hard_failure():
    env = clean_env(PAID_API_ENABLED="true")
    done = run_cli("--profile", "unit", "--json", env=env)
    report = json.loads(done.stdout)
    row = next(r for r in report["checks"] if r["check"] == "secrets_absent")
    assert row["reason_code"] == "PAID_API_ENABLED_TRUE"
    assert done.returncode == probe.EXIT_SETUP_FAILURE


def test_dotenv_scan_returns_names_without_values(tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "# комментарий\n"
        "OPENROUTER_API_KEY=sk-secret-value\n"
        "export ANTHROPIC_API_KEY=another-secret\n"
        "OPENAI_API_KEY=\n"
        "GOOGLE_API_KEY=''\n"
        "MISTRAL_API_KEY=  # intentionally unset\n"
        "AUDIT_UI_THEME=dark\n"
        "BROKEN LINE\n",
        encoding="utf-8",
    )
    names = probe._dotenv_secret_names(dotenv)
    assert names == ["ANTHROPIC_API_KEY", "OPENROUTER_API_KEY"]
    assert all("secret-value" not in n and "another" not in n for n in names)


def test_temp_fsync_failure_has_specific_reason_code(monkeypatch):
    """Отказ fsync не должен маскироваться общим TEMP_WRITE_FAILED."""

    def deny_fsync(_fd):
        raise OSError("fsync denied (test)")

    monkeypatch.setattr(probe.os, "fsync", deny_fsync)
    ctx = probe.ProbeContext(lane="unit", enforce=False, timeout=2.0, environment={})
    outcome = probe.check_temp_rw(ctx)
    assert outcome.ok is False
    assert outcome.reason_code == "TEMP_FSYNC_FAILED"


def test_secret_scan_ignores_harness_variables(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_MESSAGING_TOKEN", "harness-token")
    monkeypatch.setenv("OPENAI_API_KEY", "provider-key")
    found = probe._scan_provider_secrets()
    assert "OPENAI_API_KEY" in found
    assert "CLAUDE_CODE_MESSAGING_TOKEN" not in found


# --------------------------------------------------------------------------
# Профильные проверки §2/§3
# --------------------------------------------------------------------------


def test_dependency_and_frontend_receipts_match_frozen_inputs():
    """Рабочее дерево обязано совпадать с §2, иначе receipt протух."""
    ctx = probe.ProbeContext(lane="unit", enforce=True, timeout=10.0, environment={})
    assert probe.check_dependency_receipt(ctx).ok, "dependency receipt разошёлся с §2"
    assert probe.check_frontend_receipt(ctx).ok, "frontend receipt разошёлся с §2"
    assert ctx.environment["frontend_lock_sha256"] == (
        probe.FRONTEND_RECEIPT["frontend/package-lock.json"]
    )


def test_norm_corpus_absence_uses_contract_reason_code():
    """§3.3: локально отсутствие корпуса — именно OPTIONAL_NORM_CORPUS_ABSENT."""
    if (ROOT / probe.NORM_VAULT_DIR).is_dir():
        pytest.skip("norm corpus присутствует — ветка отсутствия не воспроизводима")
    local = probe.check_norm_artifact(
        probe.ProbeContext(lane="unit", enforce=False, timeout=10.0, environment={})
    )
    assert local.reason_code == "OPTIONAL_NORM_CORPUS_ABSENT"
    enforced = probe.check_norm_artifact(
        probe.ProbeContext(lane="unit", enforce=True, timeout=10.0, environment={})
    )
    assert enforced.reason_code == "NORM_ARTIFACT_MISSING"


def test_enforce_mode_makes_profile_checks_required():
    """В enforce ни одна профильная проверка не остаётся advisory."""
    report = probe.run_probe("unit", enforce=True, timeout=8.0)
    for row in report["checks"]:
        assert row["severity"] != probe.SEVERITY_ADVISORY, row["check"]
    assert report["mode"] == "enforce"


def test_frozen_receipt_matches_document() -> None:
    """§2 существует в двух местах — в контракте и в константах probe.

    Пока это дубликат, он обязан быть проверяемым: расхождение таблицы и кода
    означает, что один из них молча устарел, и тогда «receipt сошёлся» перестаёт
    что-либо значить. Дополнительно каждая строка таблицы сверяется с файлом на
    диске: receipt, отставший от worktree, — это не receipt.
    """
    import hashlib

    doc = (ROOT / "docs/architecture/QUALITY_RUNTIME_CONTRACT_V1.md").read_text(
        encoding="utf-8"
    )
    section = doc.split("## 2. Frozen input receipt", 1)[1].split("## 3.", 1)[0]
    table = dict(re.findall(r"^\| `([^`]+)` \| `([0-9a-f]{64})` \|$", section, re.M))
    assert table, "таблица §2 не разобралась — изменился формат"

    for rel, digest in table.items():
        path = ROOT / rel
        assert path.is_file(), f"§2 перечисляет несуществующий вход {rel}"
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        assert actual == digest, f"{rel}: worktree {actual[:12]}… != §2 {digest[:12]}…"

    enforced = {**probe.DEPENDENCY_RECEIPT, **probe.FRONTEND_RECEIPT}
    unknown = set(enforced) - set(table)
    assert not unknown, f"probe сверяет входы, которых нет в §2: {sorted(unknown)}"
    for rel, digest in enforced.items():
        assert table[rel] == digest, f"{rel}: §2 и probe разошлись"
