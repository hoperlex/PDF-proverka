#!/usr/bin/env python3
"""Безопасная публикация командных строк для CI-harness (P-13 ADR Bible).

Зачем модуль
────────────
`scripts/ci_timeout_plugin.py` читает `/proc/<pid>/cmdline` дочерних процессов
и публикует его в трёх артефактах: JUnit, журнал событий и диагностику
таймаута. Командная строка — типичное место секрета, а P-13 формулирует
правило дословно: «Попадание регулируется явным allowlist поля, а не
отсутствием запрета».

Почему первая редакция была неправильной
────────────────────────────────────────
Она вырезала ИЗВЕСТНЫЕ формы секрета: имена флагов (`--token`, `--api-key`),
presigned URL, JWT, ключи с вендорскими префиксами, длинные блобы. Это
denylist, и он проваливается на всём, чего не знает:

    app --payload SHORT_PRIVATE_SENTINEL     → секрет публиковался
    app --value=SHORT_PRIVATE_SENTINEL       → секрет публиковался
    app SHORT_PRIVATE_SENTINEL               → секрет публиковался

Значение попадало в артефакт не потому, что было признано безопасным, а
потому, что регулярное выражение его не узнало. Это ровно то, что P-13
запрещает: разница между «не запрещено» и «разрешено».

Что публикуется теперь
──────────────────────
Только структура, безопасная по построению:

  * исполняемый файл (argv[0]) — с маскировкой домашнего каталога;
  * ИМЕНА флагов, без значений;
  * значения — исключительно для короткого явного списка флагов
    (`SAFE_VALUE_FLAGS`) и только если значение подходит под домен ИМЕННО
    ЭТОГО флага: число для `--port`, loopback для `--host`, перечисление для
    `--log-level`, имя модуля для `-m`;
  * КОЛИЧЕСТВО позиционных аргументов — но никогда их содержимое, потому что
    именно позиционный аргумент чаще всего и оказывается секретом;
  * SHA-256 исходного argv — чтобы два прогона можно было сличить, не
    раскрывая содержимого.

Всё остальное не публикуется вовсе. Неизвестная форма значения — причина
отказать в публикации, а не разрешить её.

Denylist остался, но сменил роль
────────────────────────────────
`redact_text()` больше не является защитой командной строки. Он применяется
как эшелонированная защита к тем немногим свободным полям, которые всё же
публикуются (путь исполняемого файла), — на случай, если секрет попал внутрь
пути. Основную гарантию даёт allowlist, а не он.

Цена решения названа честно: диагностика беднее. По `cmdline` больше нельзя
прочитать, какой файл обрабатывал зависший процесс. Взамен остаются
исполняемый файл, набор флагов, число аргументов и отпечаток — этого хватает,
чтобы опознать процесс, и не хватает, чтобы утечь.
"""
from __future__ import annotations

import hashlib
import os
import re
from typing import Callable

REDACTED = "[redacted]"

# Значения публикуются по КАРТЕ «флаг → проверка значения». Одной общей формы
# оказалось мало: первая редакция allowlist разрешала «короткий идентификатор»,
# и под него подпал `SHORT_PRIVATE_SENTINEL` — секрет уехал в отчёт через
# `--port` и `--log-level`. Поймано собственным тестом. Домен значения у
# каждого флага свой и узкий, поэтому и проверка своя.

_NUMBER_RE = re.compile(r"^\d{1,7}(?:\.\d{1,3})?$")
_LOOPBACK = frozenset({"127.0.0.1", "0.0.0.0", "localhost", "::1"})
_LOG_LEVELS = frozenset({
    "critical", "fatal", "error", "warning", "warn", "info", "debug",
    "trace", "notset",
})
_LANES = frozenset({"unit", "contract", "integration", "network", "chaos"})

#: Имя импортируемого модуля: точечный идентификатор, по соглашению PEP 8 —
#: без заглавных букв. Ограничение по регистру не косметика: именно оно
#: отделяет `uvicorn` и `backend.app.main:app` от строки вида
#: `SHORT_PRIVATE_SENTINEL`.
_MODULE_RE = re.compile(
    r"^[a-z_][a-z0-9_]{0,31}(?:\.[a-z_][a-z0-9_]{0,31}){0,7}"
    r"(?::[a-z_][a-z0-9_]{0,31})?$"
)


def _is_number(value: str) -> bool:
    return bool(_NUMBER_RE.match(value))


def _is_loopback(value: str) -> bool:
    host, _, port = value.rpartition(":")
    if host and _is_number(port):
        return host.strip("[]") in _LOOPBACK
    return value in _LOOPBACK


def _is_log_level(value: str) -> bool:
    return value.lower() in _LOG_LEVELS


def _is_lane(value: str) -> bool:
    return value in _LANES


def _is_module(value: str) -> bool:
    return bool(_MODULE_RE.match(value))


#: Флаги, значения которых разрешено публиковать, и проверка для каждого.
#: Список намеренно короткий: каждый пункт — осознанное решение, а не «на
#: всякий случай». Добавлять сюда флаг можно, только назвав узкий домен его
#: значения и написав для него проверку.
SAFE_VALUE_FLAGS: dict[str, "Callable[[str], bool]"] = {
    "-m": _is_module,
    "--port": _is_number,
    "--workers": _is_number,
    "--timeout": _is_number,
    "--per-test-timeout": _is_number,
    "--lane-budget": _is_number,
    "--host": _is_loopback,
    "--bind": _is_loopback,
    "--log-level": _is_log_level,
    "--lane": _is_lane,
    "--profile": _is_lane,
}


def value_is_publishable(flag: str, value: str) -> bool:
    """Разрешено ли публиковать значение этого флага.

    Два условия, оба обязательны: флаг перечислен явно И значение подходит под
    домен ИМЕННО ЭТОГО флага. Достаточно одного `--port $(cat /run/secrets/db)`,
    чтобы понять, зачем нужно второе.
    """
    check = SAFE_VALUE_FLAGS.get(flag)
    return bool(check and check(value))


#: Форма имени флага. Имя — структура, а не данные, и публиковать его
#: разрешено. Но «начинается с дефиса» ещё не делает токен именем флага:
#: `app --SHORT_PRIVATE_SENTINEL` публиковал секрет как имя флага. Поэтому
#: форма сужена до конвенции: короткий флаг — один символ, длинный — строчные
#: буквы, цифры и дефисы. Заглавные и подчёркивания в длинных флагах
#: встречаются редко, а секрет выглядит именно так; цена ошибки несимметрична.
#: Не подошедший под форму токен считается позиционным и не публикуется.
SAFE_FLAG_RE = re.compile(r"^(?:-[A-Za-z0-9]|--[a-z0-9][a-z0-9-]{0,31})$")

#: Управляющие символы: в артефакте CI не нужны и ломают XML.
CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# ---------------------------------------------------------------------------
# Эшелонированная защита свободных полей (НЕ основная гарантия)
# ---------------------------------------------------------------------------

_SENSITIVE_NAME_RE = re.compile(
    r"(?i)(token|secret|password|passwd|\bpwd\b|cookie|authorization|credential|"
    r"api[_-]?key|access[_-]?key|private[_-]?key|signature|\bsig\b|\bsas\b|"
    r"session|\botp\b|\bpin\b|nonce|\bsalt\b|bearer|x-amz-)"
)
_KV_SECRET_RE = re.compile(
    r"(?i)([A-Za-z0-9_.\-]*(?:token|secret|password|passwd|pwd|cookie|"
    r"authorization|credential|api[_-]?key|access[_-]?key|private[_-]?key|"
    r"signature|sig|sas|session|otp|salt|nonce)[A-Za-z0-9_.\-]*)"
    r"(\"?\s*[=:]\s*\"?)([^\s,;&)}\]\"']+)"
)
_URL_QUERY_RE = re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://[^\s\"'<>]*?)\?[^\s\"'<>]*")
_URL_USERINFO_RE = re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)[^/\s:@\"']+:[^/\s@\"']+@")
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_\-]{6,}\.[A-Za-z0-9_\-]{4,}\.[A-Za-z0-9_\-]{4,}")
_BEARER_RE = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._\-+/=]{6,}")
_BLOB_RE = re.compile(r"[A-Za-z0-9+/_=\-]{40,}")
_CREDENTIAL_PREFIX_RE = re.compile(
    r"\b(?:"
    r"(?:AKIA|ASIA)[A-Z0-9]{12,}"
    r"|(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{16,}"
    r"|github_pat_[A-Za-z0-9_]{20,}"
    r"|xox[abprs]-[A-Za-z0-9-]{8,}|xapp-[A-Za-z0-9-]{8,}"
    r"|AIza[A-Za-z0-9_\-]{20,}"
    r"|glpat-[A-Za-z0-9_\-]{16,}"
    r"|sk-[A-Za-z0-9]{16,}|sk-ant-[A-Za-z0-9_\-]{16,}"
    r")"
)


def _blob_is_opaque(value: str) -> bool:
    """Длинная строка — ключ или обычный путь?"""
    if "/" in value or "\\" in value:
        return False
    return (
        any(ch.isupper() for ch in value)
        and any(ch.islower() for ch in value)
        and any(ch.isdigit() for ch in value)
    )


def redact_text(text: str) -> str:
    """Вычистить известные формы секрета из свободного текста.

    ЭШЕЛОНИРОВАННАЯ защита, а не основная. Основную даёт allowlist
    `summarize_argv()`: там значение публикуется, только если признано
    безопасным. Здесь — наоборот, вырезается лишь узнанное, и полагаться на
    это как на гарантию нельзя. Применяется к тем немногим свободным полям,
    которые всё же публикуются: путь исполняемого файла.

    Порядок правил повторяет `action_log._scrub`: URL раньше именованных
    секретов, bearer раньше «имя=значение», блоб раньше вендорского префикса.
    """
    value = CTRL_RE.sub(" ", str(text))
    value = _URL_USERINFO_RE.sub(r"\1[redacted]@", value)
    value = _URL_QUERY_RE.sub(r"\1?[redacted]", value)
    value = _BEARER_RE.sub(lambda m: f"{m.group(1)} {REDACTED}", value)
    value = _KV_SECRET_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", value)
    value = _JWT_RE.sub("[redacted:jwt]", value)
    value = _BLOB_RE.sub(
        lambda m: "[redacted:blob]" if _blob_is_opaque(m.group()) else m.group(), value
    )
    return _CREDENTIAL_PREFIX_RE.sub("[redacted:credential]", value)


def mask_home(path: str) -> str:
    """Заменить домашний каталог на `<home>`.

    Путь к исполняемому файлу публикуется, а он несёт имя пользователя. Это
    не секрет, но и не то, что обязано лежать в артефакте CI.
    """
    home = os.path.expanduser("~")
    if home and home != "/" and path.startswith(home):
        return "<home>" + path[len(home):]
    return path


# ---------------------------------------------------------------------------
# Allowlist: основная гарантия
# ---------------------------------------------------------------------------


def argv_digest(argv: list[str]) -> str:
    """SHA-256 исходного argv.

    Даёт возможность сличить два процесса или два прогона, не раскрывая
    содержимого: одинаковый отпечаток — одинаковая команда. Разделитель `\\0`
    тот же, что в `/proc/*/cmdline`, поэтому склейка не порождает коллизий
    между `["ab","c"]` и `["a","bc"]`.
    """
    digest = hashlib.sha256()
    for part in argv:
        digest.update(part.encode("utf-8", errors="replace"))
        digest.update(b"\0")
    return digest.hexdigest()


def summarize_argv(argv: list[str]) -> dict[str, object]:
    """Разобрать argv в структуру, безопасную для публикации по построению.

    Правило одно: публикуется только то, что явно разрешено. Значение флага
    попадает в результат, если И флаг перечислен в `SAFE_VALUE_FLAGS`, И само
    значение подходит под `SAFE_VALUE_RE`. Позиционные аргументы не
    публикуются никогда — именно они чаще всего и оказываются секретом
    (`app SHORT_PRIVATE_SENTINEL`).
    """
    if not argv:
        return {
            "executable": "", "flags": [], "positional_count": 0,
            "argc": 0, "argv_sha256": argv_digest([]),
        }

    executable = redact_text(mask_home(CTRL_RE.sub(" ", argv[0])))
    flags: list[str] = []
    positional = 0
    expect_value_for: str | None = None

    for raw in argv[1:]:
        token = CTRL_RE.sub(" ", raw)
        if expect_value_for is not None:
            flag, expect_value_for = expect_value_for, None
            if value_is_publishable(flag, token):
                flags[-1] = f"{flag}={token}"
            # Значение не подошло под безопасную форму — флаг остаётся без него.
            continue

        if token.startswith("-"):
            name, sep, value = token.partition("=")
            if not SAFE_FLAG_RE.match(name):
                # Не похоже на имя флага: считаем позиционным и не публикуем.
                positional += 1
                continue
            if sep:
                if value_is_publishable(name, value):
                    flags.append(f"{name}={value}")
                else:
                    flags.append(name)
            else:
                flags.append(name)
                if name in SAFE_VALUE_FLAGS:
                    expect_value_for = name
            continue

        positional += 1

    return {
        "executable": executable,
        "flags": flags,
        "positional_count": positional,
        "argc": len(argv),
        "argv_sha256": argv_digest(argv),
    }


def render_argv_summary(summary: dict[str, object]) -> str:
    """Собрать человекочитаемую строку из безопасной структуры.

    Формат намеренно сообщает, что часть сведений НЕ показана: `[N позиционных]`
    и отпечаток видны сразу, поэтому читающий не примет краткость за полноту.
    """
    parts: list[str] = []
    executable = str(summary.get("executable") or "")
    if executable:
        parts.append(executable)
    parts.extend(str(flag) for flag in summary.get("flags") or [])
    positional = int(summary.get("positional_count") or 0)
    if positional:
        parts.append(f"[{positional} позиционных]")
    digest = str(summary.get("argv_sha256") or "")
    if digest:
        parts.append(f"argv:{digest[:16]}")
    return " ".join(parts)


def safe_cmdline(argv: list[str]) -> str:
    """Готовая к публикации строка команды. Точка входа для инвентаря."""
    return render_argv_summary(summarize_argv(argv))
