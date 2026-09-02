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
import tarfile
from pathlib import Path

import pytest

# Primary lane §5: network — запускает настоящие дочерние процессы.
pytestmark = pytest.mark.network

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

    `QR_NORM_ARTIFACT_SHA256`, `SOURCE_DATE_EPOCH` и все переменные источника
    снимаются намеренно: каждая меняет исход, и унаследованное значение
    превратило бы тест в проверку чужой машины. На раннере с НАСТРОЕННЫМ
    источником без этой очистки половина тестов ходила бы в сеть.
    """
    env = dict(os.environ)
    env.pop(provision.NORM_CHECKSUM_ENV, None)
    env.pop(provision.SOURCE_DATE_EPOCH_ENV, None)
    for name in provision.NORM_SOURCE_ENV_VARS:
        env.pop(name, None)
    env["AUDIT_DISABLE_DOTENV"] = "1"
    env.update(overrides)
    return env


def make_artifact(tmp_path: Path, *, name: str = "norm-vault-1.0.0.tar.gz") -> tuple[Path, str]:
    """Синтетический артефакт корпуса и ожидаемый SHA-256 его дерева.

    Архив собирается С корневым каталогом `vault/`, как настоящий release
    asset: правило «спуститься в одиночный корень» — часть контракта приёмки,
    и проверять его надо на форме, в которой артефакт реально приезжает.
    """
    src = tmp_path / "artifact-src" / "vault"
    src.mkdir(parents=True)
    for member, text in VAULT_FILES.items():
        (src / member).write_text(text, encoding="utf-8")
    digest = provision.norm_artifact_digest(src)
    archive = tmp_path / name
    with tarfile.open(archive, "w:gz") as tf:
        tf.add(src, arcname="vault")
    return archive, digest


def source_env(archive: Path, digest: str | None, **overrides: str) -> dict[str, str]:
    """Окружение с полностью сконфигурированным источником `file://`.

    `file://` выбран сознательно: сетевого доступа у тестов нет и не должно
    быть, а проверяется здесь не транспорт, а контракт отказа. Транспортная
    часть (`https`, редиректы, credential) в тесте не участвует именно потому,
    что тест обязан быть детерминированным.
    """
    env = {
        provision.NORM_SOURCE_ID_ENV: "test/local-fixture",
        provision.NORM_SOURCE_URL_ENV: f"file://{archive}",
        provision.NORM_SOURCE_VERSION_ENV: "1.0.0",
    }
    if digest is not None:
        env[provision.NORM_CHECKSUM_ENV] = digest
    env.update(overrides)
    return cli_env(**env)


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


# --------------------------------------------------------------------------
# §3.3: получение артефакта из именованного внешнего источника
#
# Проверяется главное свойство wiring'а: он fail-closed ПО КОНФИГУРАЦИИ, а не
# по наличию каталога. Пока источник не назван — прежнее поведение; как только
# назван — любой сбой получения обязан быть setup failure с однозначным кодом,
# а несверенное дерево не должно становиться корпусом ни при каких условиях.
# --------------------------------------------------------------------------


def test_source_unconfigured_keeps_previous_semantics(tmp_path):
    """Источник не назван — поведение ровно прежнее, `--acquire` ничего не делает.

    Это условие совместимости: пока владелец источник не предоставил, включение
    wiring'а не имеет права изменить ни один исход CI.
    """
    root = make_root(tmp_path, vault=False)

    done, report = run_json("--acquire", "--build-index", "--root", str(root))
    assert done.returncode == 0
    assert report["source_configured"] is False
    assert report["acquire_requested"] is True
    assert report["acquired"] is False
    assert report["acquire_error"] is None
    assert report["state"]["reason_code"] == "OPTIONAL_NORM_CORPUS_ABSENT"
    assert report["result"] == "ok"
    assert report["baseline_allowed"] is False

    done_enforce, report_enforce = run_json(
        "--acquire", "--check", "--enforce", "--root", str(root)
    )
    assert done_enforce.returncode != 0
    assert report_enforce["failure_reason_code"] == "NORM_ARTIFACT_MISSING"


def test_enforce_if_configured_is_local_until_source_named(tmp_path):
    """`--enforce-if-configured` без источника — локальный профиль, не enforce.

    Именно это позволяет включить fail-closed wiring, ничего не переводя в
    enforce досрочно: строгость привязана к наличию источника, а не к дате.
    """
    root = make_root(tmp_path, vault=False)
    done, report = run_json(
        "--acquire", "--build-index", "--enforce-if-configured", "--root", str(root)
    )
    assert done.returncode == 0
    assert report["mode"] == "local"
    assert report["result"] == "ok"


def test_configured_source_provisions_and_builds_index(tmp_path):
    """Успешный путь: артефакт получен, SHA-256 сверен, индекс построен."""
    archive, digest = make_artifact(tmp_path)
    root = make_root(tmp_path, vault=False)
    env = source_env(archive, digest)

    done, report = run_json(
        "--acquire", "--build-index", "--enforce-if-configured",
        "--root", str(root), env=env,
    )

    assert done.returncode == 0, report["failure_reason_code"]
    # Источник назван — значит профиль строгий, и это видно в отчёте.
    assert report["source_configured"] is True
    assert report["mode"] == "enforce"
    assert report["acquired"] is True
    acquire = report["acquire"]
    assert acquire["source_id"] == "test/local-fixture"
    assert acquire["version"] == "1.0.0"
    assert acquire["outcome"] == "downloaded"
    assert acquire["files"] == len(VAULT_FILES)
    assert acquire["norm_artifact_sha256"] == digest
    # Корневой каталог архива снят: сумма считается от путей ОТНОСИТЕЛЬНО
    # корня корпуса, иначе эталон владельца никогда не сойдётся.
    vault = root / provision.NORM_VAULT_DIR
    assert sorted(p.name for p in vault.iterdir()) == sorted(VAULT_FILES)
    assert report["state"]["provisioned"] is True
    assert report["state"]["checksum_verified"] is True
    assert report["index_built"] is True
    assert (root / provision.NORM_STATUS_INDEX).is_file()
    assert report["baseline_allowed"] is True


def test_checksum_mismatch_never_becomes_the_corpus(tmp_path):
    """Несовпадение SHA-256 — setup failure, и дерево НЕ становится vault.

    Порядок §3.3 проверяется по последствиям, а не по тексту: если бы
    несверенное дерево всё же раскладывалось, следующий шаг работал бы с
    подделанным входом, о котором «уже сообщили».
    """
    archive, _digest = make_artifact(tmp_path)
    root = make_root(tmp_path, vault=False)
    env = source_env(archive, "0" * 64)

    done, report = run_json(
        "--acquire", "--build-index", "--enforce-if-configured",
        "--root", str(root), env=env,
    )

    assert done.returncode != 0
    assert report["result"] == "setup_failure"
    assert report["failure_reason_code"] == "NORM_ARTIFACT_CHECKSUM_MISMATCH"
    assert report["acquire_error"]["reason_code"] == "NORM_ARTIFACT_CHECKSUM_MISMATCH"
    assert not (root / provision.NORM_VAULT_DIR).exists()
    assert not (root / provision.NORM_STATUS_INDEX).exists()
    assert report["baseline_allowed"] is False
    # Staging не остаётся на диске: недоскачанное дерево не должно пережить прогон.
    assert not list((root / "norms").glob(".vault.staging*"))


def test_missing_manifest_refuses_before_touching_the_source(tmp_path):
    """Источник назван, эталона нет — отказ существующим кодом §3.3.

    Скачать артефакт, который не с чем сверить, значит доверять источнику на
    слово. Отказ обязан наступить ДО того, как в дереве что-то появится.
    """
    archive, _digest = make_artifact(tmp_path)
    root = make_root(tmp_path, vault=False)
    env = source_env(archive, None)

    done, report = run_json(
        "--acquire", "--build-index", "--enforce-if-configured",
        "--root", str(root), env=env,
    )

    assert done.returncode != 0
    assert report["failure_reason_code"] == "NORM_CHECKSUM_MANIFEST_MISSING"
    assert not (root / provision.NORM_VAULT_DIR).exists()


def test_unavailable_source_is_setup_failure_not_skip(tmp_path):
    """Недоступный источник — setup failure, а НЕ «набор не выбран».

    Это ключевое различие всего пакета: «источник не назван» ждёт владельца,
    «источник назван и не отвечает» ждёт починки доступа. Один код на два
    состояния сделал бы их неразличимыми в расписке.
    """
    archive, digest = make_artifact(tmp_path)
    root = make_root(tmp_path, vault=False)
    env = source_env(tmp_path / "нет-такого-файла.tar.gz", digest)

    done, report = run_json(
        "--acquire", "--build-index", "--enforce-if-configured",
        "--root", str(root), env=env,
    )

    assert done.returncode != 0
    assert report["failure_reason_code"] == "NORM_ARTIFACT_SOURCE_UNAVAILABLE"
    assert report["failure_reason_code"] != "OPTIONAL_NORM_CORPUS_ABSENT"
    assert not (root / provision.NORM_VAULT_DIR).exists()
    assert archive.exists()  # существующий артефакт тут ни при чём


def test_partial_source_config_is_refused(tmp_path):
    """Половина конфигурации — отказ, а не возврат к «набор не выбран».

    Половина конфигурации опаснее её отсутствия: она выглядит как подключённый
    источник и тихо давала бы зелёный прогон без корпуса.
    """
    archive, digest = make_artifact(tmp_path)
    root = make_root(tmp_path, vault=False)
    env = cli_env(**{
        provision.NORM_SOURCE_URL_ENV: f"file://{archive}",
        provision.NORM_CHECKSUM_ENV: digest,
    })

    done, report = run_json("--acquire", "--check", "--root", str(root), env=env)

    assert done.returncode != 0
    assert report["source_configured"] is True
    assert report["failure_reason_code"] == "NORM_ARTIFACT_SOURCE_MISCONFIGURED"
    # Названы ИМЕННО недостающие переменные — иначе владелец ищет наугад.
    detail = report["acquire_error"]["detail"]
    assert provision.NORM_SOURCE_ID_ENV in detail
    assert provision.NORM_SOURCE_VERSION_ENV in detail


def test_plaintext_transport_is_refused(tmp_path):
    """`http://` отвергается конфигурационно, до любого обращения наружу."""
    root = make_root(tmp_path, vault=False)
    env = source_env(tmp_path / "unused.tar.gz", "0" * 64, **{
        provision.NORM_SOURCE_URL_ENV: "http://example.invalid/vault-{version}.tar.gz",
    })

    done, report = run_json("--acquire", "--check", "--root", str(root), env=env)

    assert done.returncode != 0
    assert report["failure_reason_code"] == "NORM_ARTIFACT_SOURCE_MISCONFIGURED"


def test_unsafe_archive_member_is_refused(tmp_path):
    """Путь с `..` внутри архива — отказ, а не запись за пределы staging."""
    root = make_root(tmp_path, vault=False)
    archive = tmp_path / "evil-1.0.0.tar.gz"
    payload = tmp_path / "payload.md"
    payload.write_text("# вредонос\n", encoding="utf-8")
    with tarfile.open(archive, "w:gz") as tf:
        tf.add(payload, arcname="vault/../../escaped.md")
    env = source_env(archive, "0" * 64)

    done, report = run_json("--acquire", "--check", "--root", str(root), env=env)

    assert done.returncode != 0
    assert report["failure_reason_code"] == "NORM_ARTIFACT_UNPACK_FAILED"
    assert not (root.parent / "escaped.md").exists()
    assert not (root / "escaped.md").exists()


def test_existing_mismatching_vault_is_not_overwritten(tmp_path):
    """Уже лежащий и не совпавший корпус называется, а не затирается молча."""
    archive, digest = make_artifact(tmp_path)
    root = make_root(tmp_path, checksum=None)  # vault есть, но другой
    marker = next((root / provision.NORM_VAULT_DIR).glob("*.md"))
    marker.write_text("# чужое дерево\n", encoding="utf-8")
    env = source_env(archive, digest)

    done, report = run_json("--acquire", "--check", "--root", str(root), env=env)

    assert done.returncode != 0
    assert report["failure_reason_code"] == "NORM_ARTIFACT_CHECKSUM_MISMATCH"
    assert marker.read_text(encoding="utf-8") == "# чужое дерево\n"


def test_second_run_does_not_refetch(tmp_path):
    """Повторный прогон на сверенном корпусе идемпотентен и не ходит в источник."""
    archive, digest = make_artifact(tmp_path)
    root = make_root(tmp_path, vault=False)
    env = source_env(archive, digest)

    first, _ = run_json("--acquire", "--build-index", "--root", str(root), env=env)
    assert first.returncode == 0
    archive.unlink()  # источник недоступен — и это не должно ничего сломать

    done, report = run_json(
        "--acquire", "--build-index", "--enforce-if-configured",
        "--root", str(root), env=env,
    )

    assert done.returncode == 0
    assert report["acquire"]["outcome"] == "already_present"
    assert report["state"]["provisioned"] is True


def test_credentials_never_reach_stdout_or_stderr(tmp_path):
    """Токен не печатается ни при успехе, ни при отказе; query URL не публикуется.

    Проверяется на ОБОИХ исходах: путь отказа опаснее — именно в него попадают
    тексты чужих исключений, а urllib кладёт в них полный URL с query, где у
    presigned-ссылки и лежит секрет.
    """
    secret = "SHORT_PRIVATE_SENTINEL_VALUE_42"
    archive, digest = make_artifact(tmp_path)
    root = make_root(tmp_path, vault=False)

    ok_env = source_env(archive, digest, **{provision.NORM_SOURCE_TOKEN_ENV: secret})
    ok_done, ok_report = run_json(
        "--acquire", "--build-index", "--root", str(root), env=ok_env
    )
    assert ok_done.returncode == 0
    assert secret not in ok_done.stdout and secret not in ok_done.stderr
    # В отчёт попадает только ФАКТ наличия credential.
    assert ok_report["source"]["auth"] == "token"
    assert secret not in json.dumps(ok_report, ensure_ascii=False)

    fail_root = make_root(tmp_path / "second", vault=False)
    fail_env = source_env(
        tmp_path / "missing.tar.gz", digest,
        **{
            provision.NORM_SOURCE_TOKEN_ENV: secret,
            provision.NORM_SOURCE_URL_ENV: (
                f"file://{tmp_path}/missing.tar.gz?token={secret}"
            ),
        },
    )
    fail_done, fail_report = run_json(
        "--acquire", "--check", "--root", str(fail_root), env=fail_env
    )
    assert fail_done.returncode != 0
    assert secret not in fail_done.stdout and secret not in fail_done.stderr
    assert secret not in json.dumps(fail_report, ensure_ascii=False)


def test_digest_command_is_the_same_rule(tmp_path):
    """`--digest` печатает ТУ ЖЕ сумму, которой CI сверяет корпус.

    Без этой команды владелец источника считал бы эталон своим способом — то
    самое второе правило checksum, ради отсутствия которого digest и
    импортируется у probe.
    """
    _archive, digest = make_artifact(tmp_path)
    tree = tmp_path / "artifact-src" / "vault"

    done = run_cli("--digest", str(tree))

    assert done.returncode == 0
    assert done.stdout.strip() == digest
    assert digest == probe._norm_artifact_digest(tree)
