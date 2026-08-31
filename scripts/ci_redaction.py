#!/usr/bin/env python3
"""Redaction командных строк для CI-harness (P-13 ADR Bible).

Зачем отдельный модуль
──────────────────────
`scripts/ci_timeout_plugin.py` читает `/proc/<pid>/cmdline` дочерних процессов
и публикует его в трёх артефактах: JUnit, журнал событий и диагностику
таймаута. Командная строка — типичное место секрета (`--token=…`,
`--api-key …`, presigned URL с подписью в query), а P-13 объявляет redaction
контрактом, а не соглашением: токены, presigned URL, cookies, ПДн и текст
исключения не попадают ни в один канал по умолчанию.

Почему правило своё, а не импортированное из `backend/app/core/action_log.py`
────────────────────────────────────────────────────────────────────────────
Там такое правило уже есть и отлажено задачей `W0-LOG-01`, и переиспользовать
его было бы правильно — как переиспользовано правило digest из probe. Но его
импорт загружает `.env` и добавляет в окружение процесса десять переменных,
включая боевой provider-секрет: это ровно находка OPS03-F1. Плагин, который
ради защиты от утечки секрета сам затаскивает секрет в процесс pytest, —
нерабочее решение.

Поэтому реализация здесь локальная, а согласованность двух правил
доказывается тестом: `tests/test_ci_timeout_plugin.py` прогоняет один корпус
секретов через оба и требует, чтобы ни один не пережил ни одно из них.

Одно отличие сознательное и в сторону строгости. argv — это
ПОСЛЕДОВАТЕЛЬНОСТЬ токенов с известными границами, поэтому здесь ловится
форма `--token SECRET` через пробел. Правило для свободного текста её
пропускает: оно требует `=` или `:`, а границы аргументов в склеенной строке
уже потеряны.

Принцип разрешения сомнений — fail-closed: при известном имени флага значение
вырезается независимо от его формы. Потерять диагностику дешевле, чем
опубликовать секрет в артефакте CI, который переживёт и job, и разбор
инцидента.

Известное перередактирование
────────────────────────────
`--design-output=plan.png` теряет значение: подстрока `sig` внутри слова
`design` подпадает под правило «имя=значение». Это поведение общее с правилом
репозитория (проверено на нём же), и расходиться с ним ради одного слова
дороже, чем терпеть: два правила, отличающиеся в мелочах, разъедутся дальше.
Форма «через пробел» такой ошибки не делает — там границы слова расставлены.
"""
from __future__ import annotations

import re

REDACTED = "[redacted]"

#: Имя флага/переменной, которое само по себе означает секрет.
#:
#: Короткие многозначные слова обрамлены границами слова — иначе `sig` внутри
#: `--design-output` и `pin` внутри `--spin-up` вырезали бы совершенно
#: безобидные значения. Измерено: без границ `--spin-up worker` превращался в
#: `--spin-up [redacted]`. Перередактирование здесь не безобидно: инвентарь
#: снимают, чтобы узнать, ЧТО за процесс висел, и вычищенный ответ равносилен
#: отсутствию ответа. Тот же приём и по той же причине применён в
#: `action_log._SENSITIVE_NAME_RE`.
SENSITIVE_NAME_RE = re.compile(
    r"(?i)(token|secret|password|passwd|\bpwd\b|cookie|authorization|credential|"
    r"api[_-]?key|access[_-]?key|private[_-]?key|signature|\bsig\b|\bsas\b|"
    r"session|\botp\b|\bpin\b|nonce|\bsalt\b|bearer|x-amz-)"
)

#: Присвоение секрета внутри одного токена: `--token=…`, `SECRET_KEY=…`.
KV_SECRET_RE = re.compile(
    r"(?i)([A-Za-z0-9_.\-]*(?:token|secret|password|passwd|pwd|cookie|"
    r"authorization|credential|api[_-]?key|access[_-]?key|private[_-]?key|"
    r"signature|sig|sas|session|otp|salt|nonce)[A-Za-z0-9_.\-]*)"
    r"(\"?\s*[=:]\s*\"?)([^\s,;&)}\]\"']+)"
)

#: Presigned URL: подпись, срок и креденшл живут в query — сносим query целиком.
URL_QUERY_RE = re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://[^\s\"'<>]*?)\?[^\s\"'<>]*")
URL_USERINFO_RE = re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)[^/\s:@\"']+:[^/\s@\"']+@")
JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_\-]{6,}\.[A-Za-z0-9_\-]{4,}\.[A-Za-z0-9_\-]{4,}")
BEARER_RE = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._\-+/=]{6,}")

#: Непрозрачный блоб (ключ/подпись/хэш). Латиница + цифры + оба регистра,
#: поэтому обычные слова и кириллица под правило не подпадают.
BLOB_RE = re.compile(r"[A-Za-z0-9+/_=\-]{40,}")

#: Учётные данные с известным вендорским префиксом — защита в глубину рядом с
#: BLOB_RE: короткий ключ вида AKIA + 16 символов под правило длины не подпадает.
CREDENTIAL_PREFIX_RE = re.compile(
    r"\b(?:"
    r"(?:AKIA|ASIA)[A-Z0-9]{12,}"
    r"|(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{16,}"
    r"|github_pat_[A-Za-z0-9_]{20,}"
    r"|xox[abprs]-[A-Za-z0-9-]{8,}|xapp-[A-Za-z0-9-]{8,}"
    r"|AIza[A-Za-z0-9_\-]{20,}"
    r"|glpat-[A-Za-z0-9_\-]{16,}"
    r"|sk-[A-Za-z0-9]{16,}"
    r"|sk-ant-[A-Za-z0-9_\-]{16,}"
    r")"
)

#: Управляющие символы: в артефакт CI они не нужны и ломают XML.
CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def blob_is_opaque(value: str) -> bool:
    """Длинная строка — это ключ или обычный путь?

    Путь и имя модуля состоят из слов, разделённых `/`, `.` или `_`; ключ —
    сплошной набор символов обоих регистров с цифрами. Без этой проверки под
    правило попадал бы каждый длинный путь к файлу, и диагностика перестала бы
    показывать, ЧТО за процесс висел, — то есть redaction съела бы саму
    причину, ради которой инвентарь и снимается.
    """
    if "/" in value or "\\" in value:
        return False
    has_upper = any(ch.isupper() for ch in value)
    has_lower = any(ch.islower() for ch in value)
    has_digit = any(ch.isdigit() for ch in value)
    return has_upper and has_lower and has_digit


def redact_text(text: str) -> str:
    """Вычистить секреты из свободного текста.

    Порядок правил значим и повторяет порядок из `action_log._scrub`:
    URL раньше именованных секретов (иначе от presigned URL остаётся хвост),
    bearer раньше «имя=значение» (иначе слово Bearer съедается как значение
    заголовка, а сам токен остаётся), блоб раньше вендорского префикса (иначе
    префиксное правило отрежет голову и оставит секретную часть).
    """
    value = CTRL_RE.sub(" ", str(text))
    value = URL_USERINFO_RE.sub(r"\1[redacted]@", value)
    value = URL_QUERY_RE.sub(r"\1?[redacted]", value)
    value = BEARER_RE.sub(lambda m: f"{m.group(1)} {REDACTED}", value)
    value = KV_SECRET_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", value)
    value = JWT_RE.sub("[redacted:jwt]", value)
    value = BLOB_RE.sub(
        lambda m: "[redacted:blob]" if blob_is_opaque(m.group()) else m.group(), value
    )
    return CREDENTIAL_PREFIX_RE.sub("[redacted:credential]", value)


def redact_cmdline(argv: list[str]) -> str:
    """Собрать безопасную для публикации командную строку из argv.

    Работает по ТОКЕНАМ, а не по склеенной строке: границы аргументов известны
    только здесь, и только зная их можно вырезать значение из формы
    `--token SECRET`. После склейки эта форма неотличима от двух обычных слов.
    """
    out: list[str] = []
    redact_next = False
    for raw in argv:
        token = CTRL_RE.sub(" ", raw)
        if redact_next:
            out.append(REDACTED)
            redact_next = False
            continue
        # Флаг с секретным именем и БЕЗ значения внутри себя: значение —
        # следующий токен. Fail-closed: вырезаем его, не разбирая форму.
        if token.startswith("-") and "=" not in token and SENSITIVE_NAME_RE.search(token):
            out.append(token)
            redact_next = True
            continue
        out.append(redact_text(token))
    # Флаг оказался последним токеном: значение не пришло, но и терять нечего.
    return " ".join(out)
