"""Тесты provisioning contract норм-корпуса (`scripts/ci_provision_norms.py`), W0-OPS-03 ч.2.

Проверяется не «скрипт отработал», а то, что он НЕ ВРЁТ о состоянии корпуса и
НЕ ПОРТИТ живое дерево:

* отсутствие корпуса локально — не ошибка, но и не «всё в порядке»: код причины
  ровно `OPTIONAL_NORM_CORPUS_ABSENT`, `provisioned=false`, baseline запрещён
  (§3.3 контракта `docs/architecture/QUALITY_RUNTIME_CONTRACT_V1.md`);
* то же состояние в enforce — setup failure с ненулевым кодом возврата, а не
  skip (§3.3 и §6, правило 4);
* подделанный vault называется подделанным (`NORM_ARTIFACT_CHECKSUM_MISMATCH`),
  а не «индекса нет»: диагноз, который лечится не тем действием, хуже
  отсутствия диагноза;
* индекс собирается только над сверенным артефактом и побайтово воспроизводим —
  иначе «детерминированно строит индекс» из §3.3 остаётся словами;
* правило контрольной суммы — ОДНО, взятое у `ci_runtime_probe`.

Всё, что пишет на диск, работает на `tmp_path`: живой репозиторий тесты только
читают.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
PROVISION_PATH = SCRIPTS / "ci_provision_norms.py"

_spec = importlib.util.spec_from_file_location("ci_provision_norms", PROVISION_PATH)
provision = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
sys.modules["ci_provision_norms"] = provision
_spec.loader.exec_module(provision)

probe = sys.modules["ci_runtime_probe"]

#: Коды причин §3.3, которые обязаны существовать: на них ссылается и контракт,
#: и `ci_regression_gate.py`.
CONTRACT_REASON_CODES = (
    "OPTIONAL_NORM_CORPUS_ABSENT",
    "NORM_ARTIFACT_MISSING",
    "NORM_STATUS_INDEX_MISSING",
    "NORM_CHECKSUM_MANIFEST_MISSING",
    "NORM_ARTIFACT_CHECKSUM_MISMATCH",
)

VAULT_FILES = {
    "СП 256_1325800_2016_ Свод правил_ Электроустановки жилых зданий_document.md": (
        "# СП 256.1325800.2016\n\nТекст нормы (synthetic fixture).\n"
    ),
    "ГОСТ 10434-82_ Соединения контактные электрические_document.md": (
        "# ГОСТ 10434-82\n\nТекст нормы (synthetic fixture).\n"
    ),
}
OVERRIDES_YAML = (
    "overrides:\n"
    "  ГОСТ 10434-76:\n"
    "    replaced_by: ГОСТ 10434-82\n"
    "  СНиП 3.05.06-85:\n"
    "    doc_status: cancelled\n"
)


def make_root(tmp_path: Path, *, vault: bool = True, checksum: str | None = None) -> Path:
    """Синтетическое дерево норм на tmp_path.

    Сборщик индекса берётся из живого репозитория и КОПИРУЕТСЯ: он вычисляет
    пути от собственного `__file__`, поэтому копия автоматически работает с
    временным vault и пишет временный индекс. Так тест проверяет настоящий
    сборщик, ни разу не тронув `norms/` рабочего дерева.
    """
    root = tmp_path / "tree"
    tools = root / "norms" / "tools"
    tools.mkdir(parents=True)
    for name in ("build_status_index.py", "parse_filename.py"):
        shutil.copy(ROOT / "norms" / "tools" / name, tools / name)
    (tools / "status_overrides.yaml").write_text(OVERRIDES_YAML, encoding="utf-8")
    if vault:
        vault_dir = root / "norms" / "vault"
        vault_dir.mkdir(parents=True)
        for name, text in VAULT_FILES.items():
            (vault_dir / name).write_text(text, encoding="utf-8")
    if checksum == "valid":
        digest = provision.norm_artifact_digest(root / "norms" / "vault")
        (root / "norms" / "vault.sha256").write_text(digest + "\n", encoding="utf-8")
    elif checksum == "stale":
        (root / "norms" / "vault.sha256").write_text("0" * 64 + "\n", encoding="utf-8")
    return root


def cli_env(**overrides: str) -> dict[str, str]:
    """Окружение дочернего процесса без внешних влияний на провижининг.

    `QR_NORM_ARTIFACT_SHA256` и `SOURCE_DATE_EPOCH` снимаются намеренно: обе
    переменные меняют исход, и унаследованное значение превратило бы тест в
    проверку чужой машины.
    """
    env = dict(os.environ)
    env.pop(provision.NORM_CHECKSUM_ENV, None)
    env.pop(provision.SOURCE_DATE_EPOCH_ENV, None)
    env["AUDIT_DISABLE_DOTENV"] = "1"
    env.update(overrides)
    return env


def run_cli(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROVISION_PATH), *args],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        env=env if env is not None else cli_env(),
        timeout=120,
    )


def run_json(*args: str, env: dict[str, str] | None = None):
    done = run_cli(*args, "--json", env=env)
    assert done.stdout, f"пустой stdout, rc={done.returncode}, stderr={done.stderr[-400:]}"
    return done, json.loads(done.stdout)


# --------------------------------------------------------------------------
# Публичный контракт norm_corpus_state()
# --------------------------------------------------------------------------


def test_norm_corpus_state_returns_contract_shape():
    """Форма результата зафиксирована: её импортирует ci_regression_gate.py."""
    state = provision.norm_corpus_state()
    assert set(state) == {
        "provisioned",
        "reason_code",
        "vault_present",
        "status_index_present",
        "checksum_verified",
        "norm_artifact_sha256",
        "detail",
    }
    assert isinstance(state["provisioned"], bool)
    assert isinstance(state["vault_present"], bool)
    assert isinstance(state["status_index_present"], bool)
    assert isinstance(state["checksum_verified"], bool)
    assert isinstance(state["detail"], str) and state["detail"]
    assert state["norm_artifact_sha256"] is None or len(state["norm_artifact_sha256"]) == 64
    if state["provisioned"]:
        assert state["reason_code"] is None
    else:
        assert state["reason_code"] in provision.REASON_CODES


def test_norm_corpus_state_has_no_side_effects():
    """«Без побочных эффектов» проверяется буквально: живое дерево не меняется.

    Именно этой функцией гейт решает судьбу `--record`; если бы она попутно
    строила индекс, то сама создавала бы состояние, о котором отчитывается.
    """
    tools = ROOT / "norms" / "tools"
    before = sorted(p.name for p in tools.iterdir())
    index_before = (ROOT / provision.NORM_STATUS_INDEX).exists()
    vault_before = (ROOT / provision.NORM_VAULT_DIR).exists()

    provision.norm_corpus_state()

    assert sorted(p.name for p in tools.iterdir()) == before
    assert (ROOT / provision.NORM_STATUS_INDEX).exists() is index_before
    assert (ROOT / provision.NORM_VAULT_DIR).exists() is vault_before


def test_checksum_rule_is_the_probe_rule(tmp_path, monkeypatch):
    """Правило digest не продублировано, а импортировано из probe.

    Две независимые реализации контрольной суммы расходятся молча, и после
    расхождения «checksum сошёлся» перестаёт что-либо доказывать.
    """
    assert provision.norm_artifact_digest is probe._norm_artifact_digest

    root = make_root(tmp_path, checksum="valid")
    monkeypatch.delenv(provision.NORM_CHECKSUM_ENV, raising=False)
    state = provision.corpus_state(root)
    assert state["norm_artifact_sha256"] == probe._norm_artifact_digest(
        root / "norms" / "vault"
    )


def test_reason_codes_are_shared_with_probe():
    """Коды §3.3 общие с probe; собственные коды provision с ними не конфликтуют."""
    for code in CONTRACT_REASON_CODES:
        assert code in probe.REASON_CODES
        assert code in provision.REASON_CODES
    assert set(provision.EXTRA_REASON_CODES) & set(probe.REASON_CODES) == set()


# --------------------------------------------------------------------------
# §3.3: корпус не выбран
# --------------------------------------------------------------------------


def test_absent_corpus_is_optional_locally(tmp_path):
    """Локально отсутствие набора — не ошибка, но и не «provisioned»."""
    root = make_root(tmp_path, vault=False)
    done, report = run_json("--check", "--root", str(root))

    assert done.returncode == 0
    state = report["state"]
    assert state["provisioned"] is False
    assert state["reason_code"] == "OPTIONAL_NORM_CORPUS_ABSENT"
    assert state["vault_present"] is False
    assert state["checksum_verified"] is False
    assert state["norm_artifact_sha256"] is None
    assert report["result"] == "ok"
    # §3.3: такой прогон не создаёт baseline и не считается G0 receipt.
    assert report["baseline_allowed"] is False


def test_absent_corpus_in_enforce_is_setup_failure(tmp_path):
    """§6, правило 4: в enforce CI norms/vault не optional — падение, не skip."""
    root = make_root(tmp_path, vault=False)
    done, report = run_json("--check", "--enforce", "--root", str(root))

    assert done.returncode != 0
    assert report["result"] == "setup_failure"
    assert report["exit_code"] == done.returncode
    # Optional-код в enforce смысла не имеет: skip запрещён, отсутствие
    # артефакта контракт называет setup failure.
    assert report["failure_reason_code"] == "NORM_ARTIFACT_MISSING"
    assert report["state"]["reason_code"] == "OPTIONAL_NORM_CORPUS_ABSENT"
    assert report["baseline_allowed"] is False


def test_build_index_without_corpus_builds_nothing(tmp_path):
    """`--build-index` без набора локально не ошибка, но и индекс не появляется."""
    root = make_root(tmp_path, vault=False)
    done, report = run_json("--build-index", "--root", str(root))

    assert done.returncode == 0
    assert report["index_built"] is False
    assert report["index_build_error"]["reason_code"] == "OPTIONAL_NORM_CORPUS_ABSENT"
    assert not (root / provision.NORM_STATUS_INDEX).exists()


# --------------------------------------------------------------------------
# §3.3: артефакт есть, но не подтверждён
# --------------------------------------------------------------------------


def test_tampered_vault_is_reported_as_checksum_mismatch(tmp_path):
    """Подделанное дерево обязано называться подделанным, а не «индекса нет»."""
    root = make_root(tmp_path, checksum="valid")
    victim = next((root / "norms" / "vault").glob("*.md"))
    victim.write_text("# подмена содержимого\n", encoding="utf-8")

    done, report = run_json("--check", "--root", str(root))

    assert report["state"]["reason_code"] == "NORM_ARTIFACT_CHECKSUM_MISMATCH"
    assert report["state"]["vault_present"] is True
    assert report["state"]["checksum_verified"] is False
    assert report["state"]["provisioned"] is False
    # Битый артефакт — это не «набор не выбран», поэтому локальное послабление
    # §3.3 на него не распространяется: молчаливый ноль выдал бы порчу за норму.
    assert done.returncode != 0

    done_enforce, report_enforce = run_json("--check", "--enforce", "--root", str(root))
    assert done_enforce.returncode != 0
    assert report_enforce["failure_reason_code"] == "NORM_ARTIFACT_CHECKSUM_MISMATCH"


def test_build_index_refuses_unverified_artifact(tmp_path):
    """§3.3 задаёт порядок: сверка SHA-256, и только ЗАТЕМ сборка индекса."""
    root = make_root(tmp_path, checksum="stale")
    done, report = run_json("--build-index", "--root", str(root))

    assert done.returncode != 0
    assert report["index_built"] is False
    assert report["index_build_error"]["reason_code"] == "NORM_ARTIFACT_CHECKSUM_MISMATCH"
    assert not (root / provision.NORM_STATUS_INDEX).exists()


def test_vault_without_manifest_is_not_provisioned(tmp_path):
    """Артефакт без эталона неотличим от подделанного, значит не provisioned."""
    root = make_root(tmp_path, checksum=None)
    done, report = run_json("--check", "--root", str(root))

    assert report["state"]["reason_code"] == "NORM_CHECKSUM_MANIFEST_MISSING"
    assert report["state"]["norm_artifact_sha256"] is not None
    assert done.returncode != 0


def test_env_checksum_wins_over_manifest_file(tmp_path):
    """Порядок источников тот же, что у probe: сначала env, потом файл в дереве.

    Иначе одно дерево оценивалось бы по разным эталонам в зависимости от того,
    кто спрашивает: provisioning-шаг CI отдаёт checksum именно переменной.
    """
    root = make_root(tmp_path, checksum="stale")
    digest = provision.norm_artifact_digest(root / "norms" / "vault")
    env = cli_env(**{provision.NORM_CHECKSUM_ENV: digest})

    done, report = run_json("--build-index", "--root", str(root), env=env)

    assert done.returncode == 0
    assert report["checksum_source"] == provision.NORM_CHECKSUM_ENV
    assert report["state"]["checksum_verified"] is True


# --------------------------------------------------------------------------
# §3.3: provisioned корпус и детерминированная сборка
# --------------------------------------------------------------------------


def test_valid_corpus_is_provisioned(tmp_path):
    """Vault + сошедшийся checksum + построенный индекс = provisioned."""
    root = make_root(tmp_path, checksum="valid")

    done_build, report_build = run_json("--build-index", "--root", str(root))
    assert done_build.returncode == 0
    assert report_build["index_built"] is True
    assert (root / provision.NORM_STATUS_INDEX).is_file()

    done, report = run_json("--check", "--enforce", "--root", str(root))
    state = report["state"]
    assert done.returncode == 0
    assert state["provisioned"] is True
    assert state["reason_code"] is None
    assert state["vault_present"] and state["status_index_present"]
    assert state["checksum_verified"] is True
    assert state["norm_artifact_sha256"] == provision.norm_artifact_digest(
        root / "norms" / "vault"
    )
    assert report["baseline_allowed"] is True
    assert report["checksum_source"] == "norms/vault.sha256"


def test_rebuild_gives_byte_identical_index(tmp_path):
    """«Детерминированно строит индекс» — проверяется побайтово, а не на словах."""
    root = make_root(tmp_path, checksum="valid")
    index_path = root / provision.NORM_STATUS_INDEX

    done_first, report_first = run_json("--build-index", "--root", str(root))
    first = index_path.read_bytes()
    done_second, report_second = run_json("--build-index", "--root", str(root))
    second = index_path.read_bytes()

    assert done_first.returncode == 0 and done_second.returncode == 0
    assert first == second
    assert (
        report_first["index_build"]["status_index_sha256"]
        == report_second["index_build"]["status_index_sha256"]
    )
    # Невоспроизводимые поля сборщика приведены к фиксированным значениям —
    # именно они и ломали побайтовое сравнение (время сборки, путь чекаута).
    meta = json.loads(first.decode("utf-8"))["meta"]
    assert meta["indexed_at"] == provision.PINNED_INDEXED_AT
    assert meta["vault_path"] == provision.NORM_VAULT_DIR


def test_source_date_epoch_pins_indexed_at(tmp_path):
    """Если сборочная система задаёт SOURCE_DATE_EPOCH, индекс подчиняется ей."""
    root = make_root(tmp_path, checksum="valid")
    env = cli_env(**{provision.SOURCE_DATE_EPOCH_ENV: "1700000000"})

    run_json("--build-index", "--root", str(root), env=env)
    first = (root / provision.NORM_STATUS_INDEX).read_bytes()
    run_json("--build-index", "--root", str(root), env=env)
    second = (root / provision.NORM_STATUS_INDEX).read_bytes()

    assert first == second
    assert json.loads(first.decode("utf-8"))["meta"]["indexed_at"] == (
        "2023-11-14T22:13:20+00:00"
    )


def test_index_content_equals_upstream_builder(tmp_path):
    """Логика классификации не форкнута: расхождение только в нормализованных полях.

    Если бы provision собирал индекс «сам», статусы норм в CI и локально
    разъехались бы незаметно — а индекс объявлен single source of truth по
    статусам (`norms/tools/README.md`).
    """
    root = make_root(tmp_path, checksum="valid")
    index_path = root / provision.NORM_STATUS_INDEX

    run_json("--build-index", "--root", str(root))
    ours = json.loads(index_path.read_text(encoding="utf-8"))

    done = subprocess.run(
        [sys.executable, str(root / provision.NORM_INDEX_BUILDER), "--quiet"],
        capture_output=True,
        text=True,
        cwd=str(root),
        env=cli_env(),
        timeout=120,
    )
    assert done.returncode == 0, done.stderr[-400:]
    upstream = json.loads(index_path.read_text(encoding="utf-8"))

    for payload in (ours, upstream):
        payload["meta"].pop("indexed_at")
        payload["meta"].pop("vault_path")
    assert ours == upstream


def test_missing_builder_is_named_explicitly(tmp_path):
    """Нет сборщика — отказ с собственным кодом, а не туманное «не собралось»."""
    root = make_root(tmp_path, checksum="valid")
    (root / provision.NORM_INDEX_BUILDER).unlink()

    done, report = run_json("--build-index", "--root", str(root))

    assert done.returncode != 0
    assert report["index_build_error"]["reason_code"] == "NORM_INDEX_BUILDER_MISSING"
    assert report["failure_reason_code"] == "NORM_INDEX_BUILDER_MISSING"


def test_index_missing_after_verified_artifact(tmp_path):
    """Сверенный артефакт без индекса — отдельное состояние с лечением в тексте."""
    root = make_root(tmp_path, checksum="valid")
    done, report = run_json("--check", "--root", str(root))

    assert report["state"]["checksum_verified"] is True
    assert report["state"]["status_index_present"] is False
    assert report["state"]["reason_code"] == "NORM_STATUS_INDEX_MISSING"
    assert "--build-index" in report["state"]["detail"]
    assert done.returncode != 0


def test_cli_reports_every_emitted_reason_code(tmp_path):
    """Любой код, попавший в отчёт, обязан быть описан в REASON_CODES."""
    roots = {
        "absent": make_root(tmp_path / "a", vault=False),
        "no_manifest": make_root(tmp_path / "b", checksum=None),
        "stale": make_root(tmp_path / "c", checksum="stale"),
        "verified": make_root(tmp_path / "d", checksum="valid"),
    }
    for name, root in roots.items():
        for extra in ([], ["--enforce"]):
            _done, report = run_json("--check", "--root", str(root), *extra)
            for code in (report["state"]["reason_code"], report["failure_reason_code"]):
                if code is not None:
                    assert code in provision.REASON_CODES, f"{name}: {code}"
