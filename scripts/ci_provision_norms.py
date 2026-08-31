#!/usr/bin/env python3
"""Provisioning contract норм-корпуса по `quality-runtime/v1` §3.3 (W0-OPS-03, ч.2).

Зачем:
    Контракт `docs/architecture/QUALITY_RUNTIME_CONTRACT_V1.md` §3.3 требует
    буквально следующее: в enforce CI `norms/vault/**` и производный
    `norms/tools/status_index.json` ОБЯЗАТЕЛЬНЫ; provision получает versioned
    artifact, проверяет SHA-256 и ЗАТЕМ детерминированно строит индекс; нет
    artifact/checksum — setup failure, не skip. §6, правило 4 повторяет то же
    короче: «`norms/vault` в enforce CI не optional».

    Локально набор может быть не выбран — тогда допускается ТОЛЬКО явный skip
    тестов, доказывающих наличие внешнего корпуса, с reason code
    `OPTIONAL_NORM_CORPUS_ABSENT`, и такой прогон не создаёт baseline и не
    считается G0 receipt. Именно поэтому состояние корпуса обязано быть
    машиночитаемым: без него `ci_regression_gate.py --record` не отличает
    «корпуса нет» от «корпус есть», и запись увековечивает состояние машины.

Почему это отдельный скрипт, а не ещё одна ветка в `ci_runtime_probe.py`:
    probe — preflight, он не имеет права ничего менять в дереве (иначе он
    перестаёт быть свидетелем и становится участником). Provisioning, наоборот,
    обязан уметь ПОСТРОИТЬ производный индекс. Разделение ролей: probe
    свидетельствует, provision материализует.

Почему digest не переписан здесь:
    правило контрольной суммы дерева живёт в `ci_runtime_probe._norm_artifact_digest`
    и импортируется как есть. Два независимых правила подсчёта checksum хуже, чем
    ни одного: они расходятся молча, и «checksum сошёлся» перестаёт что-либо
    значить. По той же причине коды причин берутся из `probe.REASON_CODES`.

Интерфейс:

    python scripts/ci_provision_norms.py [--check | --build-index]
                                         [--enforce] [--json] [--root PATH]

    --check        (по умолчанию) сообщить состояние, ничего не меняя
    --build-index  детерминированно собрать `norms/tools/status_index.json`
    --enforce      режим enforce CI: не provisioned → setup failure (не skip)
    --json         машиночитаемый отчёт на stdout
    --root         корень дерева (по умолчанию корень репозитория); существует,
                   чтобы тесты работали на временной копии и не пачкали живое
                   дерево

Правило кода возврата (одно, проверяемое):

    enforce:  exit 0 ⇔ корпус provisioned;
    локально: exit 0 ⇔ корпус provisioned ИЛИ корпус не выбран вовсе
              (`OPTIONAL_NORM_CORPUS_ABSENT`).

    То есть локальное послабление §3.3 распространяется РОВНО на «набор не
    выбран». Присутствующий, но не подтверждённый checksum-ом vault — это не
    «optional отсутствие», это битый артефакт: вернуть на него 0 значило бы
    выдать порчу корпуса за норму.

Детерминированность:
    §3.3 говорит «детерминированно строит индекс», а существующий сборщик
    `norms/tools/build_status_index.py` пишет в `meta.indexed_at` время сборки и
    в `meta.vault_path` абсолютный путь. Оба поля делают файл невоспроизводимым
    (по времени и по месту чекаута), поэтому provision их нормализует —
    см. `INDEX_NORMALIZED_FIELDS`. Логика классификации норм не дублируется:
    вызывается ровно `build_index()` того же сборщика. Реальное время работы
    провижининга не теряется — оно в отчёте (`generated_at`), где ему и место.

Сеть:
    наружу скрипт не ходит: только чтение дерева и запись одного файла.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    # Сосед по каталогу: правило digest и коды причин обязаны быть ОДНИ.
    sys.path.insert(0, str(_SCRIPTS_DIR))

import ci_runtime_probe as probe  # noqa: E402

# ---------------------------------------------------------------------------
# Контрактные константы — все до одной переиспользованы у probe
# ---------------------------------------------------------------------------

CONTRACT_ID = probe.CONTRACT_ID
CONTRACT_VERSION = probe.CONTRACT_VERSION
CONTRACT_DOC = probe.CONTRACT_DOC
CONTRACT_REF = "§3.3, §6 (правило 4)"
#: Версия самого provisioning-скрипта: меняется вместе с набором проверок/кодов.
PROVISION_VERSION = "1"

NORM_VAULT_DIR = probe.NORM_VAULT_DIR
NORM_STATUS_INDEX = probe.NORM_STATUS_INDEX
NORM_CHECKSUM_FILES = probe.NORM_CHECKSUM_FILES
NORM_CHECKSUM_ENV = probe.NORM_CHECKSUM_ENV
#: Существующий детерминированный сборщик индекса. Своего у provision нет.
NORM_INDEX_BUILDER = "norms/tools/build_status_index.py"

#: Единственное правило контрольной суммы дерева норм (относительный путь +
#: содержимое каждого файла). Импортируется, а не повторяется: две реализации
#: расходятся молча.
norm_artifact_digest = probe._norm_artifact_digest

EXIT_OK = probe.EXIT_OK
EXIT_SETUP_FAILURE = probe.EXIT_SETUP_FAILURE
EXIT_USAGE = probe.EXIT_USAGE

#: Коды причин, которых нет у probe. Всё остальное берётся из его словаря:
#: один код причины обязан значить одно и то же в probe, provision и gate.
EXTRA_REASON_CODES: dict[str, str] = {
    "NORM_INDEX_BUILDER_MISSING": (
        f"{NORM_INDEX_BUILDER} отсутствует — строить индекс нечем"
    ),
    "NORM_INDEX_BUILD_FAILED": "сборка status_index.json не удалась",
}
REASON_CODES: dict[str, str] = {**probe.REASON_CODES, **EXTRA_REASON_CODES}

#: Поля индекса, которые provision приводит к воспроизводимому виду (см. шапку).
INDEX_NORMALIZED_FIELDS = ("meta.indexed_at", "meta.vault_path")
#: Значение `meta.indexed_at` по умолчанию. Ноль эпохи выбран намеренно: он не
#: маскируется под правдоподобное время и сразу читается как «время исключено».
PINNED_INDEXED_AT = "1970-01-01T00:00:00+00:00"
#: Общепринятая (reproducible-builds) переменная для воспроизводимой отметки
#: времени. Если сборочная система её задаёт — индекс подчиняется ей.
SOURCE_DATE_EPOCH_ENV = "SOURCE_DATE_EPOCH"

ACTION_CHECK = "check"
ACTION_BUILD_INDEX = "build-index"


class ProvisionError(Exception):
    """Отказ провижининга с машиночитаемым кодом причины."""

    def __init__(self, reason_code: str, detail: str) -> None:
        super().__init__(detail)
        self.reason_code = reason_code
        self.detail = detail


# ---------------------------------------------------------------------------
# Состояние корпуса (без побочных эффектов)
# ---------------------------------------------------------------------------


def expected_checksum(root: Path = ROOT) -> tuple[str | None, str | None]:
    """Ожидаемый SHA-256 артефакта и источник, откуда он взят.

    Порядок такой же, как у probe: сначала переменная окружения (её выставляет
    provisioning-шаг CI, получивший versioned artifact), потом манифесты в
    дереве. Иначе одно и то же дерево оценивалось бы по разным эталонам в
    зависимости от того, кто спрашивает.
    """
    value = os.environ.get(NORM_CHECKSUM_ENV)
    if value and value.strip():
        return value.strip(), NORM_CHECKSUM_ENV
    for candidate in NORM_CHECKSUM_FILES:
        path = root / candidate
        if not path.is_file():
            continue
        raw = path.read_text(encoding="utf-8").split()
        if raw:
            return raw[0], candidate
    return None, None


def corpus_state(root: Path = ROOT) -> dict[str, Any]:
    """Состояние norm corpus в указанном дереве. Ничего не читает из сети и не пишет.

    Порядок проверок отличается от `probe.check_norm_artifact` намеренно:
    checksum сверяется ДО наличия индекса. Причина в §3.3: индекс — производное
    от артефакта, и строить его над неподтверждённым vault нельзя. Значит,
    подделанный vault обязан называться подделанным, а не «индекса нет»:
    диагноз, который лечится не тем действием, хуже отсутствия диагноза.

    Пустой каталог `norms/vault` считается присутствующим корпусом с пустым
    digest-ом (правило digest одно на всех, исключений в нём нет). Такое дерево
    не пройдёт сверку с манифестом — то есть неудачная распаковка артефакта
    поймается как несовпадение checksum, а не выдаст себя за «набор не выбран».
    """
    vault = root / NORM_VAULT_DIR
    index = root / NORM_STATUS_INDEX
    state: dict[str, Any] = {
        "provisioned": False,
        "reason_code": None,
        "vault_present": vault.is_dir(),
        "status_index_present": index.is_file(),
        "checksum_verified": False,
        "norm_artifact_sha256": None,
        "detail": "",
    }

    if not state["vault_present"]:
        # Единственное состояние, которое §3.3 разрешает считать необязательным —
        # и только локально. В enforce тот же факт превращается в setup failure
        # с кодом NORM_ARTIFACT_MISSING (см. failure_reason_code в отчёте).
        state["reason_code"] = "OPTIONAL_NORM_CORPUS_ABSENT"
        state["detail"] = (
            f"{NORM_VAULT_DIR} отсутствует: norm-набор не выбран. Локально это не "
            "ошибка (§3.3) — тесты, доказывающие наличие внешнего корпуса, обязаны "
            "сделать явный skip с кодом OPTIONAL_NORM_CORPUS_ABSENT, а прогон не "
            "создаёт baseline и не считается G0 receipt. В enforce CI то же "
            "состояние — setup failure, не skip (§6, правило 4)."
        )
        return state

    actual = norm_artifact_digest(vault)
    state["norm_artifact_sha256"] = actual
    expected, source = expected_checksum(root)

    if not expected:
        state["reason_code"] = "NORM_CHECKSUM_MANIFEST_MISSING"
        state["detail"] = (
            f"{NORM_VAULT_DIR} на месте (sha256 {actual[:16]}…), но сверять не с чем: "
            f"нет ни {NORM_CHECKSUM_ENV}, ни " + " / ".join(NORM_CHECKSUM_FILES)
            + ". Артефакт без эталона неотличим от подделанного, поэтому он не "
            "считается provisioned."
        )
        return state

    if expected.strip().lower() != actual:
        state["reason_code"] = "NORM_ARTIFACT_CHECKSUM_MISMATCH"
        state["detail"] = (
            f"SHA-256 не совпал: ожидался {expected.strip()[:16]}… (источник {source}), "
            f"получен {actual[:16]}…. Дерево {NORM_VAULT_DIR} не то, что описано "
            "манифестом — это порча артефакта, а не отсутствие набора."
        )
        return state

    state["checksum_verified"] = True

    if not state["status_index_present"]:
        state["reason_code"] = "NORM_STATUS_INDEX_MISSING"
        state["detail"] = (
            f"артефакт сверен по {source}, но производный {NORM_STATUS_INDEX} не "
            "построен. Лечится `python scripts/ci_provision_norms.py --build-index`; "
            "коммитить индекс нельзя — он производный (norms/tools/README.md)."
        )
        return state

    state["provisioned"] = True
    state["detail"] = (
        f"корпус provisioned: {NORM_VAULT_DIR} сверен по {source} "
        f"(sha256 {actual[:16]}…), {NORM_STATUS_INDEX} на месте."
    )
    return state


def norm_corpus_state() -> dict:
    """Вернуть состояние norm corpus без побочных эффектов.

    Публичный контракт W0-OPS-03 ч.2: этим пользуется `ci_regression_gate.py`,
    чтобы запретить `--record` без provisioned корпуса (§3.3). Форма результата
    фиксирована — ключи `provisioned`, `reason_code`, `vault_present`,
    `status_index_present`, `checksum_verified`, `norm_artifact_sha256`,
    `detail`; менять её можно только вместе с потребителями.
    """
    return corpus_state(ROOT)


# ---------------------------------------------------------------------------
# Детерминированная сборка индекса
# ---------------------------------------------------------------------------


def _deterministic_indexed_at() -> str:
    """Отметка времени индекса, одинаковая при любом повторном прогоне."""
    raw = (os.environ.get(SOURCE_DATE_EPOCH_ENV) or "").strip()
    if raw.isdigit():
        return datetime.fromtimestamp(int(raw), timezone.utc).isoformat(timespec="seconds")
    return PINNED_INDEXED_AT


def _load_index_builder(root: Path):
    """Загрузить `norms/tools/build_status_index.py` ИМЕННО из указанного дерева.

    Сборщик вычисляет пути к vault и выходному файлу от собственного `__file__`,
    поэтому загрузка по пути автоматически привязывает его к нужному дереву — не
    нужно ни копировать логику, ни подменять его константы.

    `sys.path` и запись `parse_filename` в `sys.modules` восстанавливаются: сам
    сборщик добавляет свой каталог в `sys.path` и импортирует оттуда
    `parse_filename`. Без восстановления второй вызов для ДРУГОГО дерева
    молча взял бы парсер имён из первого — и «детерминированная» сборка зависела
    бы от порядка вызовов в процессе.
    """
    builder_path = root / NORM_INDEX_BUILDER
    if not builder_path.is_file():
        raise ProvisionError(
            "NORM_INDEX_BUILDER_MISSING",
            f"{NORM_INDEX_BUILDER} не найден в {root} — детерминированно строить "
            "индекс нечем, а собственной копии правил классификации у provision нет",
        )
    module_name = "ci_provision_norms__build_status_index"
    saved_path = list(sys.path)
    saved_modules = {
        name: sys.modules.get(name)
        for name in ("parse_filename", module_name)
    }
    spec = importlib.util.spec_from_file_location(module_name, builder_path)
    if spec is None or spec.loader is None:  # pragma: no cover — только на битом файле
        raise ProvisionError(
            "NORM_INDEX_BUILD_FAILED", f"не удалось загрузить {builder_path}"
        )
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise ProvisionError(
            "NORM_INDEX_BUILD_FAILED",
            f"{NORM_INDEX_BUILDER} не импортируется: {type(exc).__name__}: {exc}",
        ) from exc
    finally:
        sys.path[:] = saved_path
        for name, previous in saved_modules.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
    return module


def _atomic_write(target: Path, payload: str) -> None:
    """Запись через временный файл + rename: недописанного файла на диске не остаётся.

    Индекс читают другие процессы (`norms/external_provider.py` и стадии
    конвейера). Оборванная запись превратилась бы для них в невалидный JSON —
    отказ, который выглядит как порча данных, а не как прерванный провижининг.
    """
    tmp = target.with_name(target.name + ".provision.tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, target)


def build_status_index(root: Path = ROOT) -> dict[str, Any]:
    """Построить `status_index.json` детерминированно. Требует сверенный checksum.

    §3.3 задаёт порядок дословно: «получает versioned artifact, проверяет SHA-256
    и затем детерминированно строит индекс». Порядок — часть смысла: индекс,
    собранный над неподтверждённым деревом, выглядит легитимным производным
    артефактом, но не является им. Поэтому обхода «собрать без сверки» здесь нет.
    """
    state = corpus_state(root)
    if not state["checksum_verified"]:
        raise ProvisionError(str(state["reason_code"]), state["detail"])

    builder = _load_index_builder(root)
    # Сборщик и контракт обязаны показывать на одни и те же файлы. Если пути
    # разъехались, «производный индекс» окажется производным не от того дерева.
    expected_vault = (root / NORM_VAULT_DIR).resolve()
    expected_output = (root / NORM_STATUS_INDEX).resolve()
    if Path(builder.VAULT).resolve() != expected_vault:
        raise ProvisionError(
            "NORM_INDEX_BUILD_FAILED",
            f"сборщик читает {builder.VAULT}, а контракт (§3.3) — {expected_vault}",
        )
    if Path(builder.OUTPUT_PATH).resolve() != expected_output:
        raise ProvisionError(
            "NORM_INDEX_BUILD_FAILED",
            f"сборщик пишет {builder.OUTPUT_PATH}, а контракт (§3.3) — {expected_output}",
        )

    try:
        index = builder.build_index()
    except Exception as exc:
        raise ProvisionError(
            "NORM_INDEX_BUILD_FAILED",
            f"{NORM_INDEX_BUILDER}.build_index() упал: {type(exc).__name__}: {exc}",
        ) from exc

    meta = index.get("meta")
    if not isinstance(meta, dict):  # pragma: no cover — контракт сборщика
        raise ProvisionError(
            "NORM_INDEX_BUILD_FAILED", "сборщик вернул индекс без секции meta"
        )
    # Нормализация ровно двух невоспроизводимых полей (см. шапку модуля).
    meta["indexed_at"] = _deterministic_indexed_at()
    meta["vault_path"] = NORM_VAULT_DIR

    # Формат сериализации совпадает со сборщиком байт в байт: провижининг
    # отвечает за воспроизводимость, а не за смену формата производного файла.
    payload = json.dumps(index, ensure_ascii=False, indent=2)
    _atomic_write(expected_output, payload)
    return {
        "path": str(expected_output),
        "status_index_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        "total": meta.get("total"),
        "indexed_at": meta["indexed_at"],
        "normalized_fields": list(INDEX_NORMALIZED_FIELDS),
        "builder": NORM_INDEX_BUILDER,
    }


# ---------------------------------------------------------------------------
# Отчёт
# ---------------------------------------------------------------------------


def _vault_file_count(root: Path) -> int | None:
    vault = root / NORM_VAULT_DIR
    if not vault.is_dir():
        return None
    return sum(1 for p in vault.rglob("*") if p.is_file())


def _sha256_of(path: Path) -> str | None:
    return probe.sha256_file(path) if path.is_file() else None


def provision(
    *,
    root: Path = ROOT,
    action: str = ACTION_CHECK,
    enforce: bool = False,
) -> dict[str, Any]:
    """Выполнить запрошенное действие и вернуть машиночитаемый отчёт."""
    started = time.time()
    build_report: dict[str, Any] | None = None
    build_error: dict[str, str] | None = None

    if action == ACTION_BUILD_INDEX:
        try:
            build_report = build_status_index(root)
        except ProvisionError as exc:
            build_error = {"reason_code": exc.reason_code, "detail": exc.detail}

    state = corpus_state(root)
    reason_code = state["reason_code"]
    corpus_absent = reason_code == "OPTIONAL_NORM_CORPUS_ABSENT"

    # Одно правило кода возврата (см. шапку модуля).
    if state["provisioned"]:
        ok = True
    elif enforce:
        ok = False
    else:
        ok = corpus_absent

    failure_reason_code: str | None = None
    if not ok:
        # Отказ сборки объясняет провал точнее, чем итоговое состояние: он
        # называет ПЕРВОЕ, что помешало. Поэтому он имеет приоритет.
        failure_reason_code = (
            build_error["reason_code"] if build_error is not None else reason_code
        )
        # В enforce «набор не выбран» не имеет смысла: skip запрещён, а отсутствие
        # артефакта §3.3 называет setup failure — отсюда подмена кода.
        if enforce and failure_reason_code == "OPTIONAL_NORM_CORPUS_ABSENT":
            failure_reason_code = "NORM_ARTIFACT_MISSING"

    report: dict[str, Any] = {
        "tool": "ci_provision_norms",
        "provision_version": PROVISION_VERSION,
        "contract_id": CONTRACT_ID,
        "contract_version": CONTRACT_VERSION,
        "contract_doc": CONTRACT_DOC,
        "contract_ref": CONTRACT_REF,
        "mode": "enforce" if enforce else "local",
        "action": action,
        "root": str(root),
        # Реальное время работы провижининга живёт ЗДЕСЬ, а не в индексе:
        # индекс обязан быть побайтово воспроизводимым.
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started)),
        "state": state,
        "reason_text": REASON_CODES.get(reason_code or "", ""),
        "checksum_source": expected_checksum(root)[1],
        "vault_file_count": _vault_file_count(root),
        "status_index_sha256": _sha256_of(root / NORM_STATUS_INDEX),
        "index_built": build_report is not None,
        "index_build": build_report,
        "index_build_error": build_error,
        # §3.3: прогон без выбранного набора не создаёт baseline и не считается
        # G0 receipt. Это же условие проверяет ci_regression_gate.py --record.
        "baseline_allowed": bool(state["provisioned"]),
        "skip_policy": (
            "§3.3/§6.4: в enforce CI norms/vault не optional — отсутствие артефакта "
            "или checksum это setup failure, а не skip. Локально допустим только "
            "явный test-level skip с reason code OPTIONAL_NORM_CORPUS_ABSENT."
        ),
        "result": "ok" if ok else "setup_failure",
        "failure_reason_code": failure_reason_code,
        "failure_reason_text": REASON_CODES.get(failure_reason_code or "", ""),
        "exit_code": EXIT_OK if ok else EXIT_SETUP_FAILURE,
    }
    return report


def render_text(report: dict[str, Any]) -> str:
    state = report["state"]
    lines: list[str] = []
    add = lines.append
    add(
        f"[norms] {report['contract_id']} v{report['contract_version']} "
        f"(provision {report['provision_version']}) | action={report['action']} "
        f"| mode={report['mode']}"
    )
    add(f"[norms] дерево: {report['root']}")
    add(
        f"[norms] vault={NORM_VAULT_DIR} present={state['vault_present']} "
        f"files={report['vault_file_count']}"
    )
    add(
        f"[norms] checksum: verified={state['checksum_verified']} "
        f"source={report['checksum_source']} sha256={state['norm_artifact_sha256']}"
    )
    add(
        f"[norms] индекс: {NORM_STATUS_INDEX} present={state['status_index_present']} "
        f"sha256={report['status_index_sha256']}"
    )
    if report["index_built"]:
        build = report["index_build"]
        add(
            f"[norms] индекс собран детерминированно: записей={build['total']}, "
            f"sha256={build['status_index_sha256'][:16]}…, "
            f"нормализованы поля {', '.join(build['normalized_fields'])}"
        )
    if report["index_build_error"]:
        err = report["index_build_error"]
        add(f"[norms] сборка индекса ОТКЛОНЕНА [{err['reason_code']}]: {err['detail']}")
    add("")
    add(f"[norms] provisioned={state['provisioned']} reason={state['reason_code'] or '-'}")
    add(f"[norms] {state['detail']}")
    add(
        f"[norms] baseline/G0 receipt разрешён: {report['baseline_allowed']} "
        "(§3.3: прогон без корпуса не создаёт baseline)"
    )
    add("")
    if report["result"] == "ok":
        add(f"[norms] РЕЗУЛЬТАТ: OK. exit={report['exit_code']}")
    else:
        add(
            f"[norms] РЕЗУЛЬТАТ: SETUP FAILURE [{report['failure_reason_code']}] — "
            f"{report['failure_reason_text']}"
        )
        add(f"[norms] {report['skip_policy']}")
        add(f"[norms] exit={report['exit_code']}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ci_provision_norms.py",
        description=(
            "Provisioning norm corpus по quality-runtime/v1 §3.3: сверка versioned "
            "artifact по SHA-256 и детерминированная сборка status_index.json. "
            "В enforce CI отсутствие artifact/checksum — setup failure, не skip."
        ),
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="проверить состояние корпуса, ничего не меняя (по умолчанию)",
    )
    mode.add_argument(
        "--build-index",
        action="store_true",
        dest="build_index",
        help="детерминированно собрать norms/tools/status_index.json "
        "(только после успешной сверки SHA-256)",
    )
    parser.add_argument(
        "--enforce",
        action="store_true",
        help="режим enforce CI: не provisioned корпус — setup failure",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="машиночитаемый отчёт на stdout (поля пригодны для receipt §8)",
    )
    parser.add_argument(
        "--root",
        default=str(ROOT),
        help="корень дерева (по умолчанию корень репозитория); нужен тестам, "
        "чтобы работать на временной копии",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"[norms] --root не каталог: {root}", file=sys.stderr)
        return EXIT_USAGE
    # `--check` — умолчание, поэтому отдельной ветки у него нет: флаг существует,
    # чтобы намерение «ничего не менять» можно было написать явно.
    action = ACTION_BUILD_INDEX if args.build_index else ACTION_CHECK
    report = provision(root=root, action=action, enforce=args.enforce)
    if args.as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=False))
    else:
        print(render_text(report))
    return int(report["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
