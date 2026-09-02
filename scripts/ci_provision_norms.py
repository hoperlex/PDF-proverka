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

    Защитные лимиты — ОТДЕЛЬНАЯ группа переменных, см. «Защитные лимиты»:

        QR_NORM_ARTIFACT_MAX_BYTES           потолок скачиваемого артефакта
        QR_NORM_ARTIFACT_MAX_UNPACKED_BYTES  потолок фактически записанного
        QR_NORM_ARTIFACT_MAX_FILES           потолок числа файлов

    Состояние «источник не сконфигурирован» — ОТДЕЛЬНОЕ и не смешивается с
    отказом: пока ни одна переменная не задана, поведение ровно прежнее
    (локально `OPTIONAL_NORM_CORPUS_ABSENT` и exit 0, в enforce
    `NORM_ARTIFACT_MISSING` и setup failure). Как только источник ЗАДАН,
    любой сбой получения — setup failure, а не warning и не skip:
    недоступность (`NORM_ARTIFACT_SOURCE_UNAVAILABLE`), негодная конфигурация
    (`NORM_ARTIFACT_SOURCE_MISCONFIGURED`), нераспаковываемый, небезопасный или
    неверно разложенный архив (`NORM_ARTIFACT_UNPACK_FAILED`), превышение
    защитных лимитов (`NORM_ARTIFACT_TOO_LARGE`), отсутствие эталона
    (`NORM_CHECKSUM_MANIFEST_MISSING`), несовпадение SHA-256
    (`NORM_ARTIFACT_CHECKSUM_MISMATCH`).

Неизменяемость версии (форма приёмки, поле 5):
    `QR_NORM_ARTIFACT_VERSION` обязана быть неизменяемым идентификатором
    сборки. Изменяемые указатели (`latest`, `main`, `head`, …) отвергаются ДО
    первого обращения к источнику — см. `MUTABLE_VERSION_IDENTIFIERS` и
    `_validate_source`. Причина в том, что вся конструкция §3.3 держится на
    паре «версия ↔ SHA-256»: артефакт, который завтра другой при той же
    версии, превращает совпадение суммы в случайность — сегодня она сошлась,
    завтра тот же вход даёт `NORM_ARTIFACT_CHECKSUM_MISMATCH`, и ни один из
    двух исходов ничего не доказывает о содержимом корпуса.

Раскладка корпуса (форма приёмки, §2):
    сборщик индекса читает РОВНО `vault/*.md` в одном корне
    (`norms/tools/build_status_index.py:177`, `sorted(VAULT.glob("*.md"))`), а
    правило checksum считает дерево целиком, рекурсивно. Разность этих двух
    множеств — самое опасное состояние всего пакета: «зелёный provisioning,
    неполный индекс». Поэтому после распаковки и снятия одиночного корня
    проверяется равенство числа файлов корпуса и числа файлов, которые увидит
    сборщик (`_index_visibility`); расхождение — `NORM_ARTIFACT_UNPACK_FAILED`.
    Вложенность отвергается не сама по себе, а как частный случай этого
    равенства: запрет одной лишь вложенности пропустил бы `vault/notes.txt` и
    `vault/схема.png` — они тоже входят в checksum и тоже невидимы индексу.

Защитные лимиты:
    перед подключением внешнего архива ограничены три величины: размер
    скачиваемого файла, СУММАРНЫЙ ФАКТИЧЕСКИ ЗАПИСАННЫЙ объём распаковки и
    число файлов (`MAX_ARTIFACT_BYTES`, `MAX_UNPACKED_BYTES`,
    `MAX_UNPACKED_FILES`). Проверяется именно записанное, а не заявленное:
    zip-bomb заявляет несколько килобайт и разворачивается в гигабайты, так что
    доверять заголовку архива значит не иметь защиты вовсе. Превышение —
    `NORM_ARTIFACT_TOO_LARGE`, то есть внятный отказ вместо OOM или забитого
    диска раннера, у которых нет ни кода причины, ни владельца.

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
#: 3 — форма приёмки и валидация сведены: отвергается изменяемая версия
#: (поле 5), проверяется схема Authorization (поле 12), раскладка корпуса
#: сверяется с тем, что реально прочитает сборщик индекса, и добавлены
#: защитные лимиты объёма/числа файлов (`NORM_ARTIFACT_TOO_LARGE`).
PROVISION_VERSION = "3"

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
        "артефакт получен, но не разворачивается в годный norms/vault: битый или "
        "небезопасный архив либо раскладка, часть которой не увидит сборщик индекса"
    ),
    "NORM_ARTIFACT_TOO_LARGE": (
        "артефакт превысил защитный лимит объёма или числа файлов"
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
#: `auth-scheme` по RFC 7235 §2.1 — это `token` из RFC 7230 §3.2.6. Проверяется
#: строго, потому что значение подставляется в заголовок `Authorization` как
#: есть: пробел внутри схемы разорвал бы заголовок на «схему» и «мусор», а
#: `\r`/`\n` — это классическая инъекция ещё одного заголовка в запрос с
#: credential. Пустое значение схемой НЕ считается: у незаданной переменной
#: репозитория GitHub подставляет пустую строку, поэтому «пусто» обязано
#: означать «по умолчанию Bearer», а не отказ.
AUTH_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9!#$%&'*+.^_`|~-]*$")

#: Изменяемые указатели, которые НЕ являются версией артефакта (поле 5 формы
#: приёмки). Регистр не важен: `Latest` ничем не лучше `latest`.
#:
#: Список закрытый и намеренно короткий — это не эвристика «похоже на ветку», а
#: перечень общеупотребительных подвижных указателей. Расширять его нужно
#: сознательно и вместе с формой приёмки.
MUTABLE_VERSION_IDENTIFIERS = frozenset(
    {"latest", "main", "master", "head", "dev", "stable", "current", "newest"}
)

# ---------------------------------------------------------------------------
# Защитные лимиты (см. «Защитные лимиты» в шапке модуля)
# ---------------------------------------------------------------------------
#
# Откуда числа. Ожидаемый порядок корпуса задан самим норм-пакетом:
# `norms/tools/README.md` показывает реальный `status_index.json` с
# `"total": 337` записей, то есть vault — это СОТНИ файлов `.md`, а не десятки
# тысяч; внутренняя норм-база проекта (`norms/norms_db.json`) знает 1252 кода —
# это верхняя правдоподобная граница даже при полном покрытии. Тексты норм —
# markdown, единицы сотен килобайт на документ.
#
# Лимиты поставлены не «впритык к ожиданию» (иначе первый же законный рост
# корпуса красит CI), а на порядок выше него и при этом заведомо ниже того, что
# ломает раннер: у GitHub-hosted ubuntu-раннера свободно ~14 ГБ диска, и любой
# из трёх потолков ниже него в разы.

#: Потолок СКАЧИВАЕМОГО артефакта. Оценка: 337 файлов × ~800 КБ ≈ 270 МБ
#: несжатого текста, markdown жмётся 4–5× → ~55–70 МБ в `.tar.gz`. 256 МиБ —
#: примерно четырёхкратный запас над этой оценкой.
MAX_ARTIFACT_BYTES = 256 * 1024 * 1024
#: Потолок ФАКТИЧЕСКИ ЗАПИСАННОГО при распаковке. 1 ГиБ — примерно
#: четырёхкратный запас над теми же 270 МБ несжатого корпуса. Считается по ходу
#: записи, а не по заголовкам архива: заявленный размер у zip-bomb честный ровно
#: до момента разворачивания.
MAX_UNPACKED_BYTES = 1024 * 1024 * 1024
#: Потолок числа файлов. 10 000 — это ×8 к 1252 известным кодам норм и ×30 к
#: реальным 337 записям индекса. Отдельный от объёма лимит нужен потому, что
#: «миллион пустых файлов» не превышает байтовый потолок, но убивает и
#: файловую систему раннера, и последующий обход дерева.
MAX_UNPACKED_FILES = 10_000

#: Переопределение лимитов конфигурацией. Оно нужно: потолок — это свойство
#: РАННЕРА и размера конкретного корпуса, а не контракта, и владелец корпуса не
#: обязан ради роста набора править код и ждать релиза скрипта.
NORM_MAX_ARTIFACT_BYTES_ENV = "QR_NORM_ARTIFACT_MAX_BYTES"
NORM_MAX_UNPACKED_BYTES_ENV = "QR_NORM_ARTIFACT_MAX_UNPACKED_BYTES"
NORM_MAX_FILES_ENV = "QR_NORM_ARTIFACT_MAX_FILES"

#: Переменные лимитов НАМЕРЕННО не входят в `NORM_SOURCE_ENV_VARS`: они не
#: называют источник. Иначе заданный на раннере потолок сам по себе переводил бы
#: дерево из состояния «набор не выбран» в «источник сконфигурирован частично»,
#: то есть настройка безопасности ломала бы прогон без всякого источника.
NORM_LIMIT_ENV_VARS: tuple[str, ...] = (
    NORM_MAX_ARTIFACT_BYTES_ENV,
    NORM_MAX_UNPACKED_BYTES_ENV,
    NORM_MAX_FILES_ENV,
)

#: Размер куска потокового чтения. Один и тот же для скачивания и распаковки:
#: лимит обязан срабатывать с одинаковой точностью на обоих путях.
COPY_CHUNK_BYTES = 1 << 20

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


def source_limits(env: dict[str, str] | None = None) -> dict[str, int]:
    """Действующие защитные лимиты: умолчания, переопределённые конфигурацией.

    Негодное значение — отказ, а не молчаливый возврат к умолчанию. Опечатка в
    потолке («256MB» вместо числа) иначе выглядела бы как применённая настройка,
    хотя защита работала бы совсем на другом числе: лимит, о котором нельзя
    сказать, какой он сейчас, защитой не является.
    """
    src = os.environ if env is None else env
    defaults = {
        NORM_MAX_ARTIFACT_BYTES_ENV: MAX_ARTIFACT_BYTES,
        NORM_MAX_UNPACKED_BYTES_ENV: MAX_UNPACKED_BYTES,
        NORM_MAX_FILES_ENV: MAX_UNPACKED_FILES,
    }
    keys = {
        NORM_MAX_ARTIFACT_BYTES_ENV: "artifact_bytes",
        NORM_MAX_UNPACKED_BYTES_ENV: "unpacked_bytes",
        NORM_MAX_FILES_ENV: "files",
    }
    limits: dict[str, int] = {}
    for name, default in defaults.items():
        raw = (src.get(name) or "").strip()
        if not raw:
            limits[keys[name]] = default
            continue
        if not raw.isdigit() or int(raw) <= 0:
            raise ProvisionError(
                "NORM_ARTIFACT_SOURCE_MISCONFIGURED",
                f"{name}={raw!r} не является положительным целым числом. Лимит "
                "задаётся в байтах (для числа файлов — штуках) десятичным целым; "
                "суффиксы вроде «MB» не поддерживаются намеренно, чтобы у потолка "
                "не было двух прочтений",
            )
        limits[keys[name]] = int(raw)
    return limits


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


def _auth_scheme_defect(value: str) -> str:
    """Назвать дефект схемы авторизации, НЕ печатая её значение.

    Правило P-13 в чистом виде: публикуется признанное безопасным. Самая частая
    форма ошибки в поле 12 — вставленный целиком заголовок «Bearer <token>», то
    есть в негодном значении лежит credential. Печатать его в тексте отказа
    значило бы нарушить обещание «значение токена не печатается ни при каком
    исходе» именно там, где оно нужнее всего — на пути отказа, который попадает
    в логи CI.
    """
    if not value:  # pragma: no cover — пустое значение уходит в умолчание
        return "пустое значение"
    if any(char in value for char in "\r\n"):
        return "содержит перевод строки — это инъекция ещё одного заголовка"
    if any(char in value for char in " \t"):
        return "содержит пробел или табуляцию — заголовок разорвался бы на схему и мусор"
    first = value[0]
    if not (first.isascii() and first.isalpha()):
        return "начинается не с латинской буквы"
    return "содержит символ, недопустимый в auth-scheme"


def _validate_source(cfg: dict[str, Any]) -> None:
    """Отказать до первого сетевого действия, если конфигурация неполна/негодна.

    Проверяется ровно то, что обещает форма приёмки
    (`docs/ops/NORM_ARTIFACT_SOURCE.md`), — иначе форма и код расходятся, и
    «поле заполнено правильно» перестаёт что-либо значить:

    * поля 1, 4, 5 заданы (половина конфигурации опаснее её отсутствия);
    * схема транспорта — только `https://` или `file://` (поле 4);
    * версия — НЕИЗМЕНЯЕМЫЙ идентификатор сборки (поле 5). Почему это не
      придирка: §3.3 доказывает годность корпуса единственным способом —
      совпадением SHA-256 с эталоном, который владелец посчитал ОДИН раз для
      ОДНОЙ версии. Изменяемая версия разрывает эту пару: артефакт, который
      завтра другой при той же версии, делает совпадение суммы случайностью.
      Сегодня «checksum сошёлся» — потому что источник ещё не переехал; завтра
      тот же вход даёт `NORM_ARTIFACT_CHECKSUM_MISMATCH` — и ни один из двух
      исходов ничего не говорит о содержимом корпуса. Проверяется и сама
      версия, и сегменты адреса: `…/releases/latest/download/vault.tar.gz` —
      изменяемый указатель ровно в той же мере, даже когда поле 5 заполнено
      номером;
    * схема авторизации — `token` по RFC 7235 (поле 12). Значение уходит в
      заголовок `Authorization` как есть, поэтому мусор в нём — это либо
      порванный заголовок, либо инъекция второго заголовка в запрос,
      несущий credential.

    Всё это — ДО первого обращения к источнику: отказ после скачивания уже
    означал бы, что негодная конфигурация успела сходить наружу с credential.
    """
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
    resolved = _resolved_url(cfg)
    scheme = urllib.parse.urlsplit(resolved).scheme.lower()
    if scheme not in ALLOWED_SOURCE_SCHEMES:
        raise ProvisionError(
            "NORM_ARTIFACT_SOURCE_MISCONFIGURED",
            f"схема {scheme or '(пусто)'} не поддерживается; допустимы "
            + ", ".join(f"{s}://" for s in ALLOWED_SOURCE_SCHEMES)
            + ". http:// исключён намеренно: по нему credential уходит открытым "
            "текстом, а артефакт подменяется на пути",
        )

    version = cfg["version"]
    if version.strip().lower() in MUTABLE_VERSION_IDENTIFIERS:
        raise ProvisionError(
            "NORM_ARTIFACT_SOURCE_MISCONFIGURED",
            f"{NORM_SOURCE_VERSION_ENV}={version!r} — изменяемый указатель, а не "
            "версия артефакта. Форма приёмки, поле 5, требует НЕИЗМЕНЯЕМЫЙ "
            "идентификатор сборки: §3.3 доказывает годность корпуса совпадением "
            "SHA-256 с эталоном, посчитанным один раз для одной версии. Артефакт, "
            "который завтра другой при той же версии, превращает это совпадение в "
            "случайность — сумма сходится, пока источник не переехал, и перестаёт "
            "сходиться без единого изменения конфигурации. Отвергнуты (регистр не "
            "важен): " + ", ".join(sorted(MUTABLE_VERSION_IDENTIFIERS)),
        )

    mutable_segments = [
        segment
        for segment in PurePosixPath(urllib.parse.urlsplit(resolved).path or "").parts
        if segment.strip().lower() in MUTABLE_VERSION_IDENTIFIERS
    ]
    if mutable_segments:
        raise ProvisionError(
            "NORM_ARTIFACT_SOURCE_MISCONFIGURED",
            f"адрес артефакта содержит изменяемый сегмент «{mutable_segments[0]}» "
            f"({NORM_SOURCE_URL_ENV}). Это тот же дефект, что и изменяемая версия, "
            "только спрятанный в путь: `…/releases/latest/download/vault.tar.gz` "
            "отдаёт завтра другой файл при неизменной конфигурации, и совпадение "
            "SHA-256 перестаёт что-либо доказывать. Форма приёмки, поле 4: адрес "
            "обязан указывать на конкретную сборку",
        )

    auth_scheme = cfg["auth_scheme"]
    if not AUTH_SCHEME_RE.match(auth_scheme):
        raise ProvisionError(
            "NORM_ARTIFACT_SOURCE_MISCONFIGURED",
            f"{NORM_SOURCE_AUTH_SCHEME_ENV} не является схемой авторизации: "
            f"{_auth_scheme_defect(auth_scheme)} (длина {len(auth_scheme)}). "
            "Допустим один токен по RFC 7235 (`Bearer`, `token`, `Basic`): "
            "латинская буква в начале, без пробелов, переводов строки и служебных "
            "символов. Заголовок Authorization собирается из этого значения "
            "буквально, а из мусора он собирается либо порванным, либо с лишним "
            "заголовком внутри. Само значение здесь НЕ печатается: самая частая "
            "форма этой ошибки — вставленный целиком «Bearer <token>», то есть в "
            "негодной схеме лежит credential. Пустое значение ошибкой не является: "
            "незаданной переменной репозитория соответствует пустая строка, и она "
            f"означает умолчание {DEFAULT_AUTH_SCHEME}",
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


def _download(
    url: str, dest: Path, cfg: dict[str, Any], token: str, limits: dict[str, int]
) -> int:
    """Скачать артефакт в `dest`. Возвращает число байт.

    Чтение потоковое: артефакт нормативного корпуса — это сотни мегабайт, и
    `read()` целиком превратил бы провижининг в отказ по памяти на маленьком
    раннере.

    Потолок проверяется дважды и по-разному. Заявленный `Content-Length` — до
    первого байта: если источник честно объявил слишком много, качать это
    бессмысленно. Фактически записанное — по ходу: `Content-Length` не
    обязателен, при `chunked` его нет вовсе, а у недоброжелательного источника
    он ещё и не обязан быть правдой. Один только заявленный размер защитой не
    является.
    """
    request = urllib.request.Request(url, method="GET")
    request.add_header("Accept", "application/octet-stream")
    request.add_header("User-Agent", "ci_provision_norms/" + PROVISION_VERSION)
    if token:
        # ИМЕННО unredirected: такие заголовки не переносятся на редирект, а
        # release asset почти всегда редиректит на CDN другого владельца.
        request.add_unredirected_header("Authorization", f"{cfg['auth_scheme']} {token}")
    opener = urllib.request.build_opener(_HTTPSOnlyRedirectHandler)
    budget = limits["artifact_bytes"]
    written = 0
    with opener.open(request, timeout=SOURCE_TIMEOUT_SEC) as response:
        declared = (response.headers.get("Content-Length") or "").strip()
        if declared.isdigit() and int(declared) > budget:
            raise ProvisionError(
                "NORM_ARTIFACT_TOO_LARGE",
                f"источник объявил артефакт в {int(declared)} байт при потолке "
                f"{budget} ({NORM_MAX_ARTIFACT_BYTES_ENV}); не скачивается",
            )
        with dest.open("wb") as handle:
            while True:
                chunk = response.read(COPY_CHUNK_BYTES)
                if not chunk:
                    break
                written += len(chunk)
                if written > budget:
                    raise ProvisionError(
                        "NORM_ARTIFACT_TOO_LARGE",
                        f"артефакт превысил потолок скачивания {budget} байт "
                        f"({NORM_MAX_ARTIFACT_BYTES_ENV}); загрузка прервана, а не "
                        "доведена до конца ради точного числа — точное число "
                        "стоило бы ровно того диска, который потолок и защищает",
                    )
                handle.write(chunk)
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


class _Budget:
    """Счётчик распаковки с двумя потолками: записанные байты и число файлов.

    Считается ФАКТИЧЕСКИ ЗАПИСАННОЕ. Заявленные в заголовках архива размеры
    (`ZipInfo.file_size`, `TarInfo.size`) здесь не используются намеренно: у
    zip-bomb они честны ровно до разворачивания, и защита, построенная на них,
    существует только на добросовестных архивах — то есть там, где она не нужна.
    """

    def __init__(self, limits: dict[str, int]) -> None:
        self.max_bytes = limits["unpacked_bytes"]
        self.max_files = limits["files"]
        self.bytes = 0
        self.files = 0

    def add_file(self, name: str) -> None:
        self.files += 1
        if self.files > self.max_files:
            raise ProvisionError(
                "NORM_ARTIFACT_TOO_LARGE",
                f"в артефакте больше {self.max_files} файлов "
                f"({NORM_MAX_FILES_ENV}); распаковка прервана на «{name}». Корпус "
                "норм — это сотни файлов (norms/tools/README.md), поэтому такое "
                "число означает не корпус, а что-то другое",
            )

    def add_bytes(self, count: int, name: str) -> None:
        self.bytes += count
        if self.bytes > self.max_bytes:
            raise ProvisionError(
                "NORM_ARTIFACT_TOO_LARGE",
                f"распаковка превысила потолок {self.max_bytes} байт "
                f"({NORM_MAX_UNPACKED_BYTES_ENV}) на элементе «{name}». Считается "
                "фактически записанное, а не заявленный размер: именно так и "
                "выглядит zip-bomb — несколько килобайт архива, гигабайты на диске",
            )


def _write_member(
    target: Path, source, budget: _Budget, name: str, mode: int = 0o644
) -> None:
    """Записать один элемент архива, соблюдая потолок распаковки.

    Копирование кусками, а не `shutil.copyfileobj` целиком: потолок обязан
    останавливать запись В ПРОЦЕССЕ. Проверка «после файла» на bomb-е из одного
    члена не сработала бы вовсе — диск кончился бы раньше проверки.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as handle:
        while True:
            chunk = source.read(COPY_CHUNK_BYTES)
            if not chunk:
                break
            budget.add_bytes(len(chunk), name)
            handle.write(chunk)
    os.chmod(target, mode)


def _unpack(archive: Path, fmt: str, dest: Path, limits: dict[str, int]) -> _Budget:
    """Развернуть архив в `dest`. Возвращает счётчик записанного.

    Извлекаются ТОЛЬКО обычные файлы. Симлинки, hardlink'и, устройства и fifo
    отвергаются: корпус норм — это набор текстов, а любой другой тип элемента
    в нём означает либо испорченный архив, либо попытку выйти за staging.
    """
    dest.mkdir(parents=True, exist_ok=True)
    budget = _Budget(limits)
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
                    budget.add_file(info.filename)
                    with zf.open(info) as source:
                        _write_member(dest / target, source, budget, info.filename)
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
                    budget.add_file(member.name)
                    with source:
                        _write_member(dest / target, source, budget, member.name)
    except ProvisionError:
        raise
    except (tarfile.TarError, zipfile.BadZipFile, OSError, EOFError) as exc:
        raise ProvisionError(
            "NORM_ARTIFACT_UNPACK_FAILED",
            f"архив не разворачивается: {type(exc).__name__}: "
            f"{ci_redaction.redact_text(str(exc))}",
        ) from exc
    if budget.files == 0:
        raise ProvisionError(
            "NORM_ARTIFACT_UNPACK_FAILED",
            "в артефакте нет ни одного файла — пустой корпус не отличим от "
            "неудачной сборки на стороне источника",
        )
    return budget


def _copy_tree_bounded(src: Path, dest: Path, limits: dict[str, int]) -> _Budget:
    """Скопировать уже разложенный каталог под теми же потолками, что и архив.

    Ветка `file://` на каталог существует для случая «артефакт разложен на
    раннере отдельным шагом», и без этой функции она была бы дырой в защите:
    `shutil.copytree` копирует что дали и сколько дали. Потолок обязан быть
    свойством провижининга, а не формата, в котором артефакт приехал.
    """
    budget = _Budget(limits)
    dest.mkdir(parents=True, exist_ok=True)
    for path in sorted(src.rglob("*")):
        relative = path.relative_to(src)
        if path.is_symlink() or (not path.is_dir() and not path.is_file()):
            raise ProvisionError(
                "NORM_ARTIFACT_UNPACK_FAILED",
                f"элемент «{relative}» не обычный файл (симлинк/устройство) — "
                "корпус норм это набор текстов",
            )
        if path.is_dir():
            (dest / relative).mkdir(parents=True, exist_ok=True)
            continue
        budget.add_file(str(relative))
        with path.open("rb") as source:
            _write_member(dest / relative, source, budget, str(relative))
    if budget.files == 0:
        raise ProvisionError(
            "NORM_ARTIFACT_UNPACK_FAILED",
            "в каталоге источника нет ни одного файла — пустой корпус не отличим "
            "от неудачной сборки на стороне источника",
        )
    return budget


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


#: Что РЕАЛЬНО читает сборщик индекса. Зеркало одной строки
#: `norms/tools/build_status_index.py:177` — `sorted(VAULT.glob("*.md"))` плюс
#: `if md.name.startswith("MOC - "): continue` строкой ниже.
#:
#: Зеркало, а не догадка: `glob` (не `rglob`) означает ОДИН корень без
#: вложенности, а расширение сравнивается регистрозависимо, потому что именно
#: так ведёт себя `glob` на файловой системе раннера. Расхождение этого зеркала
#: с сборщиком ловится тестом
#: `test_index_visibility_mirrors_the_real_builder`: он спрашивает не наше
#: правило, а настоящий сборщик.
INDEX_BUILDER_SUFFIX = ".md"
INDEX_BUILDER_SKIP_PREFIX = "MOC - "


def _index_visibility(tree: Path) -> dict[str, Any]:
    """Разложить дерево корпуса на «увидит индекс» и «не увидит».

    Три множества, и различать их обязательно:

    * `indexed` — файлы, которые сборщик прочитает и превратит в записи;
    * `skipped_moc` — `MOC - *.md` в корне: сборщик пропускает их СОЗНАТЕЛЬНО
      (`norms/tools/README.md`: «vault/*.md — тексты нормативных документов
      (кроме `MOC - *.md`)»), это карты содержания Obsidian, а не нормы;
    * `invisible` — всё остальное: вложенные файлы и не-`.md` в корне. Они
      входят в SHA-256, но в индекс не попадают ни при каких условиях.

    Непустое `invisible` — это ровно то состояние, ради которого функция и
    написана: checksum сходится, provisioning зелёный, а часть корпуса в индексе
    отсутствует, и узнать об этом неоткуда.
    """
    corpus = sorted(
        p.relative_to(tree).as_posix() for p in tree.rglob("*") if p.is_file()
    )
    indexed: list[str] = []
    skipped_moc: list[str] = []
    invisible: list[str] = []
    for relative in corpus:
        if "/" in relative:  # вложенность: `glob("*.md")` туда не заглядывает
            invisible.append(relative)
        elif not relative.endswith(INDEX_BUILDER_SUFFIX):
            invisible.append(relative)
        elif relative.startswith(INDEX_BUILDER_SKIP_PREFIX):
            skipped_moc.append(relative)
        else:
            indexed.append(relative)
    return {
        "corpus_files": len(corpus),
        "indexed_files": len(indexed),
        "skipped_moc_files": len(skipped_moc),
        "invisible_files": invisible,
    }


def _require_flat_indexable_layout(tree: Path, where: str) -> dict[str, Any]:
    """Отказать, если число файлов корпуса не сходится с числом видимых индексу.

    ПОЧЕМУ равенство, а не запрет вложенности. Форма приёмки требует плоскую
    раскладку, а сборщик читает `vault/*.md` — но «зелёный provisioning,
    неполный индекс» получается не только от вложенности: `vault/notes.txt`,
    `vault/схема.png`, `vault/ГОСТ.MD` дают ровно тот же исход. Запрет одной
    вложенности закрыл бы известный случай и оставил открытым класс. Равенство
    закрывает класс целиком и формулируется одной проверяемой фразой: КАЖДЫЙ
    файл, вошедший в checksum, обязан быть файлом, который прочитает сборщик
    (единственное исключение — `MOC - *.md`, которые сборщик пропускает по
    собственному правилу).

    Код `NORM_ARTIFACT_UNPACK_FAILED`, а не `..._SOURCE_MISCONFIGURED`, выбран
    по владельцу починки: конфигурация здесь верна, негоден сам артефакт, и
    чинит его владелец источника пересборкой — это в точности тот адресат,
    который §5 формы приёмки закрепил за `UNPACK_FAILED`.
    """
    visibility = _index_visibility(tree)
    invisible = visibility["invisible_files"]
    if invisible:
        sample = ", ".join(f"«{name}»" for name in invisible[:5])
        more = f" и ещё {len(invisible) - 5}" if len(invisible) > 5 else ""
        raise ProvisionError(
            "NORM_ARTIFACT_UNPACK_FAILED",
            f"раскладка корпуса ({where}) не сходится с тем, что читает "
            f"{NORM_INDEX_BUILDER}: файлов в корпусе {visibility['corpus_files']}, "
            f"из них увидит индекс {visibility['indexed_files']} "
            f"(+{visibility['skipped_moc_files']} «MOC - *.md», пропускаемых "
            f"сборщиком осознанно). Не попадут в индекс: {sample}{more}. Сборщик "
            f"читает РОВНО `vault/*.md` в одном корне, а SHA-256 считается по "
            "дереву рекурсивно — поэтому такой корпус проходит checksum и молча "
            "оказывается в индексе неполным. Это и есть отказ «зелёный "
            "provisioning, неполный индекс»; форма приёмки (§2) требует плоскую "
            "раскладку `.md` в одном корне — пересоберите артефакт",
        )
    return visibility


def acquire_artifact(root: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    """Получить артефакт из сконфигурированного источника и разложить в vault.

    Порядок §3.3 соблюдается буквально: дерево становится `norms/vault` только
    ПОСЛЕ совпадения SHA-256. Правило суммы — импортированное
    `norm_artifact_digest`, второго правила здесь нет и быть не может.

    После совпадения суммы — и до переименования в `norms/vault` — проверяется
    раскладка (`_require_flat_indexable_layout`). Порядок именно такой: «сумма
    не сошлась» и «сумма сошлась, но половину корпуса не увидит индекс» — разные
    диагнозы, и первый обязан называться первым, иначе владелец источника чинит
    раскладку у артефакта, который вообще не тот.
    """
    _validate_source(cfg)
    limits = source_limits()
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
        "limits": dict(limits),
        "layout": None,
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
            # Раскладка проверяется и на этой ветке: идемпотентный повтор не
            # имеет права быть мягче первого прогона, иначе один и тот же
            # артефакт принимался бы или отвергался в зависимости от того,
            # первый это запуск на раннере или второй.
            report["layout"] = _require_flat_indexable_layout(
                vault, f"уже разложенный {NORM_VAULT_DIR}"
            )
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
                budget = _copy_tree_bounded(local, unpacked, limits)
                report["files"] = budget.files
                report["bytes"] = budget.bytes
            elif local.is_file():
                report["format"] = _artifact_format(url)
                size = local.stat().st_size
                if size > limits["artifact_bytes"]:
                    raise ProvisionError(
                        "NORM_ARTIFACT_TOO_LARGE",
                        f"артефакт на файловой системе занимает {size} байт при "
                        f"потолке {limits['artifact_bytes']} "
                        f"({NORM_MAX_ARTIFACT_BYTES_ENV}); не распаковывается",
                    )
                report["bytes"] = size
                report["files"] = _unpack(
                    local, report["format"], unpacked, limits
                ).files
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
                report["bytes"] = _download(url, archive, cfg, token, limits)
            except ProvisionError:
                # Превышение лимита — собственный диагноз, а не «источник не
                # отдал артефакт»: источник как раз отдал, и слишком много.
                raise
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
            report["files"] = _unpack(
                archive, report["format"], unpacked, limits
            ).files

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
        # Сумма сошлась — значит артефакт ТОТ. Теперь единственный оставшийся
        # способ получить «зелёный provisioning, неполный индекс» — раскладка.
        report["layout"] = _require_flat_indexable_layout(
            tree, f"артефакт {cfg['source_id']} версии {cfg['version']}"
        )
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

    Вторая проверка — раскладка. Она стоит здесь, а не только в `acquire`,
    потому что vault может приехать и другим путём (распакован соседним шагом,
    смонтирован, разложен вручную), а неполный индекс от этого не становится
    менее неполным. Правило одно и то же, вход у него — уже СВЕРЕННОЕ дерево.
    """
    state = corpus_state(root)
    if not state["checksum_verified"]:
        raise ProvisionError(str(state["reason_code"]), state["detail"])
    _require_flat_indexable_layout(root / NORM_VAULT_DIR, NORM_VAULT_DIR)

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

    # Действующие потолки публикуются в расписке: «лимит сработал» и «лимит был
    # переопределён» обязаны читаться из отчёта, а не из кода. Негодное значение
    # переменной здесь НЕ обваливает прогон само по себе — оно обваливает
    # получение (там же и код `NORM_ARTIFACT_SOURCE_MISCONFIGURED`); без
    # названного источника ограничивать нечего, и правило «источник не назван —
    # поведение ровно прежнее» остаётся ненарушенным.
    limits_report: dict[str, int] | None
    limits_error: dict[str, str] | None
    try:
        limits_report = source_limits()
        limits_error = None
    except ProvisionError as exc:
        limits_report = None
        limits_error = {"reason_code": exc.reason_code, "detail": exc.detail}

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
            # Публикуется ТОЛЬКО прошедшее валидацию значение (P-13,
            # publish-by-allowlist). Годная схема — это документированное
            # не-секретное поле 12 из `vars`, и знать её нужно для разбора 401.
            # Негодная — с высокой вероятностью вставленный «Bearer <token>»,
            # поэтому вместо неё публикуется факт негодности.
            "auth_scheme": (
                cfg["auth_scheme"]
                if AUTH_SCHEME_RE.match(cfg["auth_scheme"])
                else "(негодная схема, значение не публикуется)"
            ),
            "env_vars": list(NORM_SOURCE_ENV_VARS),
        },
        # Защитные лимиты — часть расписки: без них «артефакт принят» не говорит,
        # под каким потолком он принят, и следующий раннер с другим потолком
        # получил бы другой исход на том же входе.
        "limits": limits_report,
        "limits_env_vars": list(NORM_LIMIT_ENV_VARS),
        "limits_error": limits_error,
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
    if report["limits"]:
        lim = report["limits"]
        add(
            f"[norms] защитные лимиты: артефакт≤{lim['artifact_bytes']} Б, "
            f"распаковка≤{lim['unpacked_bytes']} Б, файлов≤{lim['files']} "
            f"(переопределяются {', '.join(report['limits_env_vars'])})"
        )
    if report["limits_error"]:
        err = report["limits_error"]
        add(f"[norms] лимиты ЗАДАНЫ НЕГОДНО [{err['reason_code']}]: {err['detail']}")
    if report["acquire"]:
        acq = report["acquire"]
        add(
            f"[norms] артефакт получен ({acq['outcome']}): файлов={acq['files']}, "
            f"байт={acq['bytes']}, sha256={(acq.get('norm_artifact_sha256') or '')[:16]}…"
        )
        layout = acq.get("layout")
        if layout:
            add(
                f"[norms] раскладка: файлов корпуса={layout['corpus_files']}, "
                f"увидит индекс={layout['indexed_files']}, "
                f"пропущено «MOC - *.md»={layout['skipped_moc_files']}"
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
