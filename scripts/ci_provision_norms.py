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

    python scripts/ci_provision_norms.py [--check | --build-index] [--acquire]
                                         [--enforce | --enforce-if-configured]
                                         [--json] [--root PATH]
    python scripts/ci_provision_norms.py --digest PATH

    --check        (по умолчанию) сообщить состояние, ничего не меняя
    --build-index  детерминированно собрать `norms/tools/status_index.json`
    --acquire      получить артефакт из СКОНФИГУРИРОВАННОГО внешнего источника
                   и разложить в `norms/vault` (см. «Источник артефакта»)
    --enforce      режим enforce CI: не provisioned → setup failure (не skip)
    --enforce-if-configured
                   enforce ровно тогда, когда источник сконфигурирован; пока
                   владелец его не назвал — прежний локальный профиль
    --json         машиночитаемый отчёт на stdout
    --root         корень дерева (по умолчанию корень репозитория); существует,
                   чтобы тесты работали на временной копии и не пачкали живое
                   дерево
    --digest PATH  напечатать SHA-256 дерева тем же правилом, которым его
                   сверяет CI (нужно владельцу источника, чтобы посчитать
                   эталон, а не изобрести второе правило)

Источник артефакта (§3.3 «provision получает versioned artifact»):
    источник задаётся ТОЛЬКО конфигурацией, скрипт не знает ни одного адреса
    по умолчанию — это сознательно: зашитый источник превращается в
    неотзываемое доверие. Переменные окружения (в CI — variables и secrets):

        QR_NORM_ARTIFACT_SOURCE_ID  имя/владелец источника (обязательно)
        QR_NORM_ARTIFACT_URL        адрес; допускается подстановка {version}
        QR_NORM_ARTIFACT_VERSION    версия/тег артефакта (обязательно)
        QR_NORM_ARTIFACT_SHA256     ожидаемый SHA-256 дерева (обязательно)
        QR_NORM_ARTIFACT_TOKEN      credential, если источник закрытый
        QR_NORM_ARTIFACT_AUTH_SCHEME  схема Authorization, по умолчанию Bearer

    Состояние «источник не сконфигурирован» — ОТДЕЛЬНОЕ и не смешивается с
    отказом: пока ни одна переменная не задана, поведение ровно прежнее
    (локально `OPTIONAL_NORM_CORPUS_ABSENT` и exit 0, в enforce
    `NORM_ARTIFACT_MISSING` и setup failure). Как только источник ЗАДАН,
    любой сбой получения — setup failure, а не warning и не skip:
    недоступность (`NORM_ARTIFACT_SOURCE_UNAVAILABLE`), негодная конфигурация
    (`NORM_ARTIFACT_SOURCE_MISCONFIGURED`), нераспаковываемый или небезопасный
    архив (`NORM_ARTIFACT_UNPACK_FAILED`), отсутствие эталона
    (`NORM_CHECKSUM_MANIFEST_MISSING`), несовпадение SHA-256
    (`NORM_ARTIFACT_CHECKSUM_MISMATCH`).

    Порядок §3.3 соблюдён буквально: полученное дерево становится
    `norms/vault` ТОЛЬКО после совпадения SHA-256. Распаковка идёт в
    staging рядом, и несовпавшее дерево не превращается в корпус вовсе —
    иначе следующий шаг работал бы с подделанным входом, о котором
    «уже сообщили».

Credentials:
    значение токена не печатается ни при каком исходе. В отчёт попадает
    только факт `auth: token|none`. Адрес публикуется структурно —
    `scheme://host/<basename>`, без query, fragment и userinfo: у presigned
    URL секрет лежит именно в query. Это правило P-13 (`scripts/ci_redaction.py`):
    публикуется то, что признано безопасным, а не то, что не узнал denylist.
    Тексты чужих исключений (urllib кладёт в них полный URL) проходят
    `redact_text` как эшелонированная защита.

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
    без `--acquire` наружу скрипт не ходит: только чтение дерева и запись
    одного файла. С `--acquire` он обращается РОВНО по одному адресу — тому,
    что задан конфигурацией, — и только по `https://` или `file://`.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sys
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    # Сосед по каталогу: правило digest и коды причин обязаны быть ОДНИ.
    sys.path.insert(0, str(_SCRIPTS_DIR))

import ci_redaction  # noqa: E402
import ci_runtime_probe as probe  # noqa: E402

# ---------------------------------------------------------------------------
# Контрактные константы — все до одной переиспользованы у probe
# ---------------------------------------------------------------------------

CONTRACT_ID = probe.CONTRACT_ID
CONTRACT_VERSION = probe.CONTRACT_VERSION
CONTRACT_DOC = probe.CONTRACT_DOC
CONTRACT_REF = "§3.3, §6 (правило 4)"
#: Версия самого provisioning-скрипта: меняется вместе с набором проверок/кодов.
#: 2 — добавлено получение артефакта из именованного внешнего источника
#: (`--acquire`) и профиль `--enforce-if-configured`.
PROVISION_VERSION = "2"

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
#:
#: Почему для сбоев источника заведены СВОИ коды, а не переиспользован
#: `NORM_ARTIFACT_MISSING`: этим кодом уже называется состояние «источник не
#: назван вовсе». Если им же называть «источник назван, но недоступен», два
#: принципиально разных состояния станут неразличимы по коду — а именно
#: различимость и требуется: первое ждёт владельца, второе ждёт починки
#: доступа. Сбои получения при этом НЕ переопределяют существующие коды §3.3:
#: несовпадение SHA-256 остаётся `NORM_ARTIFACT_CHECKSUM_MISMATCH`,
#: отсутствие эталона — `NORM_CHECKSUM_MANIFEST_MISSING`.
EXTRA_REASON_CODES: dict[str, str] = {
    "NORM_INDEX_BUILDER_MISSING": (
        f"{NORM_INDEX_BUILDER} отсутствует — строить индекс нечем"
    ),
    "NORM_INDEX_BUILD_FAILED": "сборка status_index.json не удалась",
    "NORM_ARTIFACT_SOURCE_MISCONFIGURED": (
        "конфигурация источника norm artifact задана не полностью или негодна"
    ),
    "NORM_ARTIFACT_SOURCE_UNAVAILABLE": (
        "сконфигурированный источник norm artifact не отдал артефакт"
    ),
    "NORM_ARTIFACT_UNPACK_FAILED": (
        "артефакт получен, но не разворачивается в norms/vault"
    ),
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

# ---------------------------------------------------------------------------
# Конфигурация внешнего источника артефакта (§3.3 «versioned artifact»)
# ---------------------------------------------------------------------------

#: Имя и владелец источника. Обязательно: §3.3 требует ИМЕНОВАННЫЙ источник, а
#: расписка без имени не позволяет спросить с кого-либо за содержимое корпуса.
NORM_SOURCE_ID_ENV = "QR_NORM_ARTIFACT_SOURCE_ID"
#: Адрес артефакта. Допускается подстановка `{version}`.
NORM_SOURCE_URL_ENV = "QR_NORM_ARTIFACT_URL"
#: Версия/тег артефакта. Обязательно: «versioned» — это про воспроизводимость,
#: а безымянный «последний» артефакт делает checksum необъяснимым.
NORM_SOURCE_VERSION_ENV = "QR_NORM_ARTIFACT_VERSION"
#: Credential для закрытого источника. ЗНАЧЕНИЕ не печатается никогда.
NORM_SOURCE_TOKEN_ENV = "QR_NORM_ARTIFACT_TOKEN"
#: Схема заголовка Authorization (Bearer | token | Basic …).
NORM_SOURCE_AUTH_SCHEME_ENV = "QR_NORM_ARTIFACT_AUTH_SCHEME"
DEFAULT_AUTH_SCHEME = "Bearer"

#: Все переменные конфигурации источника. Заданной считается конфигурация, в
#: которой задана хотя бы одна из них, — тогда неполнота становится ОТКАЗОМ, а
#: не тихим возвратом к состоянию «источник не выбран». Половина конфигурации
#: опаснее её отсутствия: она выглядит как подключённый источник.
NORM_SOURCE_ENV_VARS: tuple[str, ...] = (
    NORM_SOURCE_ID_ENV,
    NORM_SOURCE_URL_ENV,
    NORM_SOURCE_VERSION_ENV,
    NORM_SOURCE_TOKEN_ENV,
    NORM_SOURCE_AUTH_SCHEME_ENV,
)

#: Только эти схемы. `http://` отсутствует намеренно: по нему credential уходит
#: открытым текстом, а артефакт подменяется на пути.
ALLOWED_SOURCE_SCHEMES = ("https", "file")
#: Поддерживаемые форматы. Каталог — для случая, когда артефакт уже разложен
#: на раннере отдельным шагом (`actions/download-artifact`, смонтированный том).
ARCHIVE_SUFFIXES = (".tar.gz", ".tgz", ".tar", ".zip")
#: Бюджет сетевой операции. Источник, не уложившийся в него, считается
#: недоступным: висящий provisioning ничем не лучше упавшего, но диагностируется
#: он на порядок хуже.
SOURCE_TIMEOUT_SEC = 300
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
#: Предел «раздевания» одиночного корневого каталога архива (см. `_strip_root`).
MAX_ROOT_STRIP_DEPTH = 4


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
# Получение артефакта из именованного внешнего источника
# ---------------------------------------------------------------------------


def source_config(env: dict[str, str] | None = None) -> dict[str, Any]:
    """Конфигурация источника из окружения. Значение токена НЕ возвращается.

    Возвращается только факт наличия credential (`has_token`): дальше это
    значение живёт в одном заголовке одного запроса и больше нигде — ни в
    отчёте, ни в тексте отказа, ни в исключении.
    """
    src = os.environ if env is None else env

    def get(name: str) -> str:
        return (src.get(name) or "").strip()

    cfg: dict[str, Any] = {
        "source_id": get(NORM_SOURCE_ID_ENV),
        "url": get(NORM_SOURCE_URL_ENV),
        "version": get(NORM_SOURCE_VERSION_ENV),
        "auth_scheme": get(NORM_SOURCE_AUTH_SCHEME_ENV) or DEFAULT_AUTH_SCHEME,
        "has_token": bool(get(NORM_SOURCE_TOKEN_ENV)),
    }
    cfg["configured"] = any(get(name) for name in NORM_SOURCE_ENV_VARS)
    return cfg


def _publishable_url(url: str) -> str:
    """Адрес в виде, безопасном по построению: `scheme://host/<basename>`.

    Publish-by-allowlist, а не redact-by-denylist (P-13, см. `ci_redaction`).
    У presigned URL секрет лежит в query, у некоторых источников — в userinfo;
    полный путь тоже способен нести идентификатор арендатора. Поэтому
    публикуется ровно то, что нужно для диагностики «куда ходили»: схема, host
    и имя файла.
    """
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return "[unparsable-url]"
    host = parts.hostname or ""
    name = PurePosixPath(parts.path or "").name
    if parts.scheme == "file":
        return f"file://…/{name}" if name else "file://…"
    return f"{parts.scheme}://{host}/{name}" if name else f"{parts.scheme}://{host}"


def _resolved_url(cfg: dict[str, Any]) -> str:
    """URL с подставленной версией. Шаблон без `{version}` допустим."""
    url = cfg["url"]
    if "{version}" in url:
        return url.replace("{version}", urllib.parse.quote(cfg["version"], safe=""))
    return url


def _validate_source(cfg: dict[str, Any]) -> None:
    """Отказать до первого сетевого действия, если конфигурация неполна/негодна."""
    missing = [
        name
        for name, key in (
            (NORM_SOURCE_ID_ENV, "source_id"),
            (NORM_SOURCE_URL_ENV, "url"),
            (NORM_SOURCE_VERSION_ENV, "version"),
        )
        if not cfg[key]
    ]
    if missing:
        raise ProvisionError(
            "NORM_ARTIFACT_SOURCE_MISCONFIGURED",
            "конфигурация источника задана частично: не заданы "
            + ", ".join(missing)
            + ". Половина конфигурации опаснее её отсутствия — она выглядит как "
            "подключённый источник, поэтому это отказ, а не возврат к состоянию "
            "«набор не выбран». Форма приёмки — docs/ops/NORM_ARTIFACT_SOURCE.md",
        )
    scheme = urllib.parse.urlsplit(_resolved_url(cfg)).scheme.lower()
    if scheme not in ALLOWED_SOURCE_SCHEMES:
        raise ProvisionError(
            "NORM_ARTIFACT_SOURCE_MISCONFIGURED",
            f"схема {scheme or '(пусто)'} не поддерживается; допустимы "
            + ", ".join(f"{s}://" for s in ALLOWED_SOURCE_SCHEMES)
            + ". http:// исключён намеренно: по нему credential уходит открытым "
            "текстом, а артефакт подменяется на пути",
        )


def _artifact_format(url: str) -> str:
    """Формат артефакта по имени файла. Неизвестное расширение — отказ."""
    name = PurePosixPath(urllib.parse.urlsplit(url).path or "").name.lower()
    for suffix in ARCHIVE_SUFFIXES:
        if name.endswith(suffix):
            return suffix
    raise ProvisionError(
        "NORM_ARTIFACT_SOURCE_MISCONFIGURED",
        f"по имени артефакта «{name or '(пусто)'}» не определён формат; "
        "поддерживаются " + ", ".join(ARCHIVE_SUFFIXES) + " либо file:// на "
        "уже разложенный каталог",
    )


class _HTTPSOnlyRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Редирект допускается только на `https`.

    Credential на редирект не уезжает и без этого: он добавлен
    `add_unredirected_header`, а `HTTPRedirectHandler` переносит только
    `req.headers`. Этот обработчик закрывает вторую половину — понижение
    транспорта до открытого при получении самого артефакта.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        if urllib.parse.urlsplit(newurl).scheme.lower() != "https":
            raise urllib.error.HTTPError(
                newurl, code, "редирект на не-https запрещён", headers, fp
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _download(url: str, dest: Path, cfg: dict[str, Any], token: str) -> int:
    """Скачать артефакт в `dest`. Возвращает число байт.

    Чтение потоковое: артефакт нормативного корпуса — это сотни мегабайт, и
    `read()` целиком превратил бы провижининг в отказ по памяти на маленьком
    раннере.
    """
    request = urllib.request.Request(url, method="GET")
    request.add_header("Accept", "application/octet-stream")
    request.add_header("User-Agent", "ci_provision_norms/" + PROVISION_VERSION)
    if token:
        # ИМЕННО unredirected: такие заголовки не переносятся на редирект, а
        # release asset почти всегда редиректит на CDN другого владельца.
        request.add_unredirected_header("Authorization", f"{cfg['auth_scheme']} {token}")
    opener = urllib.request.build_opener(_HTTPSOnlyRedirectHandler)
    written = 0
    with opener.open(request, timeout=SOURCE_TIMEOUT_SEC) as response:
        with dest.open("wb") as handle:
            while True:
                chunk = response.read(1 << 20)
                if not chunk:
                    break
                handle.write(chunk)
                written += len(chunk)
    return written


def _member_target(name: str) -> PurePosixPath | None:
    """Безопасный относительный путь элемента архива либо None.

    Проверяется до записи, а не после: `..` и абсолютный путь внутри архива —
    это выход за staging, то есть запись куда угодно на раннере правами CI.
    """
    if not name or name.startswith(("/", "\\")):
        return None
    if ":" in name.split("/", 1)[0]:  # диск Windows
        return None
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in ("..", "") for part in path.parts):
        return None
    return path


def _write_member(target: Path, source, mode: int = 0o644) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as handle:
        shutil.copyfileobj(source, handle)
    os.chmod(target, mode)


def _unpack(archive: Path, fmt: str, dest: Path) -> int:
    """Развернуть архив в `dest`. Возвращает число файлов.

    Извлекаются ТОЛЬКО обычные файлы. Симлинки, hardlink'и, устройства и fifo
    отвергаются: корпус норм — это набор текстов, а любой другой тип элемента
    в нём означает либо испорченный архив, либо попытку выйти за staging.
    """
    dest.mkdir(parents=True, exist_ok=True)
    files = 0
    try:
        if fmt == ".zip":
            with zipfile.ZipFile(archive) as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    if (info.external_attr >> 16) & 0o170000 == 0o120000:
                        raise ProvisionError(
                            "NORM_ARTIFACT_UNPACK_FAILED",
                            f"в архиве симлинк «{info.filename}» — не распаковывается",
                        )
                    target = _member_target(info.filename)
                    if target is None:
                        raise ProvisionError(
                            "NORM_ARTIFACT_UNPACK_FAILED",
                            f"небезопасный путь в архиве: «{info.filename}»",
                        )
                    with zf.open(info) as source:
                        _write_member(dest / target, source)
                    files += 1
        else:
            mode = "r:gz" if fmt in (".tar.gz", ".tgz") else "r:"
            with tarfile.open(archive, mode) as tf:
                for member in tf:
                    if member.isdir():
                        continue
                    if not member.isfile():
                        raise ProvisionError(
                            "NORM_ARTIFACT_UNPACK_FAILED",
                            f"элемент «{member.name}» не обычный файл "
                            "(симлинк/устройство) — не распаковывается",
                        )
                    target = _member_target(member.name)
                    if target is None:
                        raise ProvisionError(
                            "NORM_ARTIFACT_UNPACK_FAILED",
                            f"небезопасный путь в архиве: «{member.name}»",
                        )
                    source = tf.extractfile(member)
                    if source is None:  # pragma: no cover — только на битом архиве
                        raise ProvisionError(
                            "NORM_ARTIFACT_UNPACK_FAILED",
                            f"элемент «{member.name}» не читается",
                        )
                    with source:
                        _write_member(dest / target, source)
                    files += 1
    except ProvisionError:
        raise
    except (tarfile.TarError, zipfile.BadZipFile, OSError, EOFError) as exc:
        raise ProvisionError(
            "NORM_ARTIFACT_UNPACK_FAILED",
            f"архив не разворачивается: {type(exc).__name__}: "
            f"{ci_redaction.redact_text(str(exc))}",
        ) from exc
    if files == 0:
        raise ProvisionError(
            "NORM_ARTIFACT_UNPACK_FAILED",
            "в артефакте нет ни одного файла — пустой корпус не отличим от "
            "неудачной сборки на стороне источника",
        )
    return files


def _strip_root(unpacked: Path) -> Path:
    """Спуститься в одиночный корневой каталог архива.

    Артефакты почти всегда упакованы с корнем (`vault/…`, `norms-vault-1.2/…`),
    а SHA-256 считается от путей ОТНОСИТЕЛЬНО корня корпуса. Правило
    детерминированное и описано в форме приёмки: спускаемся, пока каталог
    содержит ровно один подкаталог и ни одного файла.
    """
    current = unpacked
    for _ in range(MAX_ROOT_STRIP_DEPTH):
        entries = list(current.iterdir())
        if len(entries) == 1 and entries[0].is_dir():
            current = entries[0]
            continue
        return current
    return current


def acquire_artifact(root: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    """Получить артефакт из сконфигурированного источника и разложить в vault.

    Порядок §3.3 соблюдается буквально: дерево становится `norms/vault` только
    ПОСЛЕ совпадения SHA-256. Правило суммы — импортированное
    `norm_artifact_digest`, второго правила здесь нет и быть не может.
    """
    _validate_source(cfg)
    expected, checksum_source = expected_checksum(root)
    if not expected:
        raise ProvisionError(
            "NORM_CHECKSUM_MANIFEST_MISSING",
            f"источник {cfg['source_id']} задан, но эталона нет: не заданы ни "
            f"{NORM_CHECKSUM_ENV}, ни " + " / ".join(NORM_CHECKSUM_FILES)
            + ". Скачать артефакт, который не с чем сверить, значит доверять "
            "источнику на слово — §3.3 этого не разрешает",
        )
    expected = expected.strip().lower()
    if not _SHA256_RE.match(expected):
        raise ProvisionError(
            "NORM_ARTIFACT_SOURCE_MISCONFIGURED",
            f"ожидаемый SHA-256 (источник {checksum_source}) не похож на "
            "SHA-256: нужны ровно 64 шестнадцатеричных символа",
        )

    url = _resolved_url(cfg)
    published = _publishable_url(url)
    report: dict[str, Any] = {
        "source_id": cfg["source_id"],
        "version": cfg["version"],
        "url": published,
        "scheme": urllib.parse.urlsplit(url).scheme.lower(),
        "auth": "token" if cfg["has_token"] else "none",
        "expected_checksum_source": checksum_source,
        "bytes": None,
        "files": None,
        "outcome": "downloaded",
    }

    vault = root / NORM_VAULT_DIR
    if vault.is_dir():
        # Повторный прогон на том же раннере не обязан ходить в сеть, но и
        # молча заменять уже лежащий корпус нельзя: если он не совпал с
        # эталоном, это состояние обязано быть НАЗВАНО, а не затёрто.
        actual = norm_artifact_digest(vault)
        if actual == expected:
            report["outcome"] = "already_present"
            report["norm_artifact_sha256"] = actual
            report["files"] = _vault_file_count(root)
            return report
        raise ProvisionError(
            "NORM_ARTIFACT_CHECKSUM_MISMATCH",
            f"{NORM_VAULT_DIR} уже существует и не совпадает с эталоном "
            f"{expected[:16]}… (получен {actual[:16]}…). Acquire не перезаписывает "
            "чужое дерево молча: удалите его сознательно и повторите",
        )

    staging = root / "norms" / f".vault.staging.{os.getpid()}"
    shutil.rmtree(staging, ignore_errors=True)
    try:
        staging.mkdir(parents=True)
        unpacked = staging / "unpacked"
        parts = urllib.parse.urlsplit(url)
        if parts.scheme == "file":
            local = Path(urllib.parse.unquote(parts.path))
            if local.is_dir():
                report["format"] = "directory"
                shutil.copytree(local, unpacked)
            elif local.is_file():
                report["format"] = _artifact_format(url)
                report["bytes"] = local.stat().st_size
                report["files"] = _unpack(local, report["format"], unpacked)
            else:
                raise ProvisionError(
                    "NORM_ARTIFACT_SOURCE_UNAVAILABLE",
                    f"источник {cfg['source_id']} версии {cfg['version']} "
                    f"({published}) не найден на файловой системе раннера",
                )
        else:
            report["format"] = _artifact_format(url)
            archive = staging / "artifact"
            token = (os.environ.get(NORM_SOURCE_TOKEN_ENV) or "").strip()
            try:
                report["bytes"] = _download(url, archive, cfg, token)
            except (urllib.error.URLError, OSError, ValueError) as exc:
                # Текст чужого исключения несёт полный URL (а с ним и presigned
                # query). Через redact_text — эшелонированная защита поверх
                # публикации адреса по allowlist.
                raise ProvisionError(
                    "NORM_ARTIFACT_SOURCE_UNAVAILABLE",
                    f"источник {cfg['source_id']} версии {cfg['version']} "
                    f"({published}) не отдал артефакт: {type(exc).__name__}: "
                    f"{ci_redaction.redact_text(str(exc))}",
                ) from exc
            report["files"] = _unpack(archive, report["format"], unpacked)

        tree = _strip_root(unpacked)
        actual = norm_artifact_digest(tree)
        report["norm_artifact_sha256"] = actual
        if actual != expected:
            raise ProvisionError(
                "NORM_ARTIFACT_CHECKSUM_MISMATCH",
                f"артефакт {cfg['source_id']} версии {cfg['version']} не совпал "
                f"с эталоном (источник {checksum_source}): ожидался "
                f"{expected[:16]}…, получен {actual[:16]}…. Дерево НЕ разложено в "
                f"{NORM_VAULT_DIR} — несверенный корпус не становится корпусом",
            )
        report["files"] = sum(1 for p in tree.rglob("*") if p.is_file())
        vault.parent.mkdir(parents=True, exist_ok=True)
        tree.rename(vault)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return report


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
    acquire: bool = False,
    enforce_if_configured: bool = False,
) -> dict[str, Any]:
    """Выполнить запрошенное действие и вернуть машиночитаемый отчёт.

    `enforce_if_configured` привязывает строгость к факту наличия источника, а
    не к календарю: пока владелец источник не назвал, профиль ровно прежний
    (это состояние §3.3 разрешает), а как только назвал — любой сбой получения
    обязан быть setup failure. Так шаг CI перестаёт быть маскировкой, ничего
    при этом не переводя в enforce досрочно.
    """
    started = time.time()
    build_report: dict[str, Any] | None = None
    build_error: dict[str, str] | None = None
    acquire_report: dict[str, Any] | None = None
    acquire_error: dict[str, str] | None = None

    cfg = source_config()
    source_configured = bool(cfg["configured"])
    if enforce_if_configured and source_configured:
        enforce = True

    if acquire and source_configured:
        try:
            acquire_report = acquire_artifact(root, cfg)
        except ProvisionError as exc:
            acquire_error = {"reason_code": exc.reason_code, "detail": exc.detail}

    # Собирать индекс над деревом, которое не удалось получить, бессмысленно:
    # ошибка сборки перекрыла бы настоящую причину — отказ источника.
    if action == ACTION_BUILD_INDEX and acquire_error is None:
        try:
            build_report = build_status_index(root)
        except ProvisionError as exc:
            build_error = {"reason_code": exc.reason_code, "detail": exc.detail}

    state = corpus_state(root)
    reason_code = state["reason_code"]
    corpus_absent = reason_code == "OPTIONAL_NORM_CORPUS_ABSENT"

    # Одно правило кода возврата (см. шапку модуля).
    if acquire_error is not None:
        # Сконфигурированный источник, который не отдал годный артефакт, — это
        # setup failure В ЛЮБОМ профиле. Локальное послабление §3.3 покрывает
        # ровно «набор не выбран», а здесь он выбран и не приехал.
        ok = False
    elif state["provisioned"]:
        ok = True
    elif enforce:
        ok = False
    else:
        ok = corpus_absent

    failure_reason_code: str | None = None
    if not ok:
        # Отказ называет ПЕРВОЕ, что помешало, — поэтому приоритет у отказа
        # получения, затем у отказа сборки, и лишь затем итоговое состояние.
        if acquire_error is not None:
            failure_reason_code = acquire_error["reason_code"]
        elif build_error is not None:
            failure_reason_code = build_error["reason_code"]
        else:
            failure_reason_code = reason_code
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
        # Состояние источника — отдельная, машиночитаемая величина: «не назван»
        # и «назван, но не приехал» обязаны различаться в расписке §8.
        "source_configured": source_configured,
        "source": {
            "source_id": cfg["source_id"] or None,
            "version": cfg["version"] or None,
            "url": _publishable_url(_resolved_url(cfg)) if cfg["url"] else None,
            "auth": "token" if cfg["has_token"] else "none",
            "env_vars": list(NORM_SOURCE_ENV_VARS),
        },
        "acquire_requested": bool(acquire),
        "acquired": acquire_report is not None,
        "acquire": acquire_report,
        "acquire_error": acquire_error,
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
    source = report["source"]
    if report["source_configured"]:
        add(
            f"[norms] источник: {source['source_id']} версия {source['version']} "
            f"({source['url']}), auth={source['auth']}"
        )
    else:
        add(
            "[norms] источник НЕ сконфигурирован: не задана ни одна из "
            + ", ".join(report["source"]["env_vars"])
            + ". Форма приёмки — docs/ops/NORM_ARTIFACT_SOURCE.md"
        )
    if report["acquire"]:
        acq = report["acquire"]
        add(
            f"[norms] артефакт получен ({acq['outcome']}): файлов={acq['files']}, "
            f"байт={acq['bytes']}, sha256={(acq.get('norm_artifact_sha256') or '')[:16]}…"
        )
    if report["acquire_error"]:
        err = report["acquire_error"]
        add(f"[norms] получение артефакта ОТКЛОНЕНО [{err['reason_code']}]: {err['detail']}")
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
    if report["acquire_error"]:
        # Без этой оговорки вывод противоречит сам себе: состояние дерева
        # честно сообщает «набор не выбран», хотя набор выбран и не приехал.
        # Действующая причина — отказ получения, и лечится он не тем действием.
        add(
            "[norms] ВНИМАНИЕ: строки выше описывают дерево ПОСЛЕ отказанного "
            f"получения. Источник {report['source']['source_id']} сконфигурирован; "
            "действующая причина — отказ получения, а не «набор не выбран»."
        )
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
        "--acquire",
        action="store_true",
        help="получить артефакт из сконфигурированного внешнего источника "
        f"({', '.join(NORM_SOURCE_ENV_VARS)}) и разложить в norms/vault; "
        "если источник не сконфигурирован — не делает ничего",
    )
    strictness = parser.add_mutually_exclusive_group()
    strictness.add_argument(
        "--enforce",
        action="store_true",
        help="режим enforce CI: не provisioned корпус — setup failure",
    )
    strictness.add_argument(
        "--enforce-if-configured",
        action="store_true",
        dest="enforce_if_configured",
        help="enforce ровно тогда, когда источник сконфигурирован; пока "
        "владелец его не назвал — прежний локальный профиль",
    )
    parser.add_argument(
        "--digest",
        metavar="PATH",
        help="напечатать SHA-256 дерева тем же правилом, которым его сверяет "
        "CI, и выйти (нужно владельцу источника для расчёта эталона)",
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
    if args.digest:
        # Отдельный режим: владельцу источника нужен ТОТ ЖЕ digest, которым
        # сверяет CI. Без этой команды он посчитал бы сумму своим способом —
        # то самое второе правило checksum, которого проект избегает.
        target = Path(args.digest).resolve()
        if not target.is_dir():
            print(f"[norms] --digest не каталог: {target}", file=sys.stderr)
            return EXIT_USAGE
        print(norm_artifact_digest(target))
        return EXIT_OK
    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"[norms] --root не каталог: {root}", file=sys.stderr)
        return EXIT_USAGE
    # `--check` — умолчание, поэтому отдельной ветки у него нет: флаг существует,
    # чтобы намерение «ничего не менять» можно было написать явно.
    action = ACTION_BUILD_INDEX if args.build_index else ACTION_CHECK
    report = provision(
        root=root,
        action=action,
        enforce=args.enforce,
        acquire=args.acquire,
        enforce_if_configured=args.enforce_if_configured,
    )
    if args.as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=False))
    else:
        print(render_text(report))
    return int(report["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
