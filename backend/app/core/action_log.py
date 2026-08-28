"""
Журнал действий (action log) — сквозная запись всех действий в системе.

Зачем: постоянная летопись «кто, что, когда сделал и чем закончилось», по
которой потом можно разбирать ошибки (какие действия предшествовали сбою,
какие запросы падали, какие этапы конвейера рушились и почему).

Источники событий:
  * kind="api"      — HTTP-запросы портала (ActionLogMiddleware): метод, логин
                      инженера, шаблон маршрута, статус, длительность. Шумовые
                      поллинговые GET отфильтрованы, но любой ответ >=400 и
                      любое исключение пишутся всегда.
  * kind="pipeline" — переходы этапов конвейера (хук в
                      audit_logger.update_pipeline_log — единая воронка всех
                      stage-статусов).
  * kind="app_log"  — WARNING/ERROR из стандартного logging всех модулей
                      backend (мост install_logging_bridge на root-логгере).
  * kind="system"   — старт/остановка сервера (lifespan).
  * kind="worker"   — решения безопасности распределённого контура.

ТРИ КАНАЛА С РАЗНЫМИ ГАРАНТИЯМИ (ADR_BIBLE, принцип P-13) — подробный разбор
контракта ниже, у _AUDIT_FIELDS:

  1. durable audit — ACTION_LOG_DIR/actions-YYYY-MM-DD.jsonl. Append-only,
     ФИКСИРОВАННАЯ схема (allowlist _AUDIT_FIELDS), ретеншн
     ACTION_LOG_RETENTION_DAYS (180 дней). Потеря записи — инцидент.
  2. diagnostic   — ACTION_LOG_DIR/diag-YYYY-MM-DD.jsonl. Непроверенный ввод
     (path, query, message, error, traceback, exc, ip) ПОСЛЕ обязательной
     redaction; допускает потерю и семплирование, ретеншн
     ACTION_LOG_DIAG_RETENTION_DAYS (14 дней).
  3. метрики      — in-process реестр, labels только method × route × status
     плюс гистограмма dur_ms; идентификаторов в labels нет. metrics_snapshot().

Записи каналов 1 и 2 связаны correlation id "eid".

Всё fail-soft: ни одна ошибка журнала не должна ломать основной поток.
Чтение — read_events()/stats() (используются /api/action-log и
scripts/analyze_action_log.py); оба принимают channel="audit"|"diag" и по
умолчанию читают durable audit, включая файлы, записанные до введения каналов.
"""
from __future__ import annotations

import bisect
import json
import logging
import re
import sys
import threading
import time
import traceback
import uuid
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qsl

from backend.app.core import config

_LOCK = threading.Lock()
# Префиксы суточных файлов двух файловых каналов. Имя actions-* НЕ меняется:
# на него завязаны read_events()/stats(), GET /api/action-log и
# scripts/analyze_action_log.py, включая файлы, записанные до этого изменения.
_AUDIT_PREFIX = "actions-"
_DIAG_PREFIX = "diag-"

# (директория, день) последней записи КАЖДОГО канала — для mkdir и запуска
# ретеншн-чистки на смене дня.
_LAST_WRITE_KEY: dict[str, tuple[str, str]] = {}
# Однократное предупреждение о невозможности писать журнал (не спамить stderr).
_WRITE_FAILED_WARNED = False
# Суточный бюджет байт ОБЩИЙ НА ОБА КАНАЛА: ACTION_LOG_MAX_DAY_BYTES означает
# ровно то же, что означал до разделения каналов, — сколько журнал в сумме
# вправе занять за сутки. Отдельный бюджет на канал молча удвоил бы настроенный
# оператором потолок (256 МБ → 512 МБ/сут), а это изменение семантики флага.
# На границе бюджета выигрывает durable audit: он пишется первым (см. log_event),
# потеря его записи — инцидент, потеря диагностики допустима.
_DAY_BUDGET: dict = {"key": None, "bytes": 0}
# Маркер day_cap_reached ставится в КАЖДЫЙ файл отдельно, чтобы обрыв был виден
# в том канале, который читают.
_DAY_CAP_MARKED: dict[str, bool] = {}


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def _today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _log_dir() -> Path:
    # Через атрибут модуля (не from-import), чтобы monkeypatch в тестах работал.
    return Path(config.ACTION_LOG_DIR)


def _cleanup_prefix(log_dir: Path, prefix: str, retention: int) -> None:
    """Удалить суточные файлы канала старше retention дней. Fail-soft."""
    if retention <= 0:
        return
    cutoff = (datetime.now() - timedelta(days=retention)).strftime("%Y-%m-%d")
    for path in log_dir.glob(f"{prefix}*.jsonl"):
        # Дата из имени; лексикографическое сравнение == хронологическое.
        day = path.name[len(prefix):-len(".jsonl")]
        if day < cutoff:
            try:
                path.unlink()
            except OSError:
                pass


def _cleanup_old_files(log_dir: Path) -> None:
    """Ретеншн обоих каналов. У каждого свой срок. Fail-soft.

    Диагностический канал живёт заметно меньше durable audit: именно в нём
    оседает непроверенный ввод, и хранить его 180 дней — ровно та проблема,
    ради которой каналы разделены.
    """
    try:
        _cleanup_prefix(
            log_dir, _AUDIT_PREFIX,
            int(getattr(config, "ACTION_LOG_RETENTION_DAYS", 180)),
        )
    except Exception:
        pass
    try:
        _cleanup_prefix(
            log_dir, _DIAG_PREFIX,
            int(getattr(config, "ACTION_LOG_DIAG_RETENTION_DAYS", 14)),
        )
    except Exception:
        pass


# ═══ Контракт redaction и разделение каналов (ADR_BIBLE, P-13) ════════════════
#
# Принцип: «Redaction является контрактом, а не соглашением: чувствительные
# значения, query-параметры, presigned URL, cookies, токены, секреты и ПДн не
# попадают ни в один из трёх каналов по умолчанию. Попадание регулируется явным
# allowlist поля, а не отсутствием запрета. Текст исключения и traceback
# считаются непроверенным пользовательским вводом и проходят ту же обработку.»
#
# Отсюда два независимых механизма, и работают они ОБА:
#
#   (1) РАЗДЕЛЕНИЕ КАНАЛОВ по имени поля. durable audit получает только поля из
#       _AUDIT_FIELDS. Имя поля, которого в allowlist нет, в durable audit не
#       попадёт никогда — ни новое поле нового вызова log_event(), ни **extra
#       из чужого модуля, ни поле, которое кто-то добавит завтра. Это закрывает
#       главную дыру: log_event(kind, **fields) принимает произвольные kwargs,
#       а мост install_logging_bridge висит на root-логгере, то есть ЛЮБОЙ
#       logger.error() любого модуля backend раньше попадал в вечный журнал
#       дословно — вместе с тем, что автор вызова туда класть не собирался.
#
#   (2) REDACTION ЗНАЧЕНИЙ. Всё, что уходит в diagnostic, проходит _scrub():
#       presigned URL теряет query, JWT/Bearer/cookie/секрет по имени параметра
#       заменяются заглушкой, непрозрачные блобы вырезаются, абсолютные пути ФС
#       обезличиваются, traceback усекается с сохранением хвоста (там текст
#       исключения). Это применяется и к полям audit-allowlist — defence in
#       depth: allowlist разрешает ИМЯ поля, но не подписывается за значение.
#
# Разделение каналов почти бесплатно даёт middleware: он уже вычисляет и route
# (ШАБЛОН вида /api/audit/{project_id}/log — идентификаторов не несёт), и path
# (несёт project_id у 76 эндпоинтов, session_id у 26, object_id у 11, user_id
# у 3). Раньше route писался только когда отличался от path; теперь наоборот —
# route идёт в durable audit, path в diagnostic.

# Allowlist durable audit: имя поля → предел длины строкового значения
# (None — скаляр пишется как есть).
_AUDIT_FIELDS: dict[str, int | None] = {
    # Кто и над чем — ради этого журнал и существует. project_id вынесен
    # ОТДЕЛЬНЫМ структурным полем вместо того, чтобы вычитываться из path.
    "actor": 200,
    "project_id": 300,
    # Класс C по инвентаризации — идентификаторов и свободного ввода не несут.
    "method": 10,
    "route": 300,
    "status": None,
    "stage": 100,
    "event": 200,
    "level": 20,
    "logger": 200,
    "duration_sec": None,
    # kind="worker" — решения безопасности распределённого контура: коды и
    # перечисления (permission_denied, роль, требуемое право). Это ровно
    # «события безопасности» из определения durable audit.
    "severity": 40,
    "required_permission": 100,
    "reason": 200,
    "role": 60,
    "auth_enabled": None,
    # Служебный маркер самого журнала (day_cap_reached).
    "max_bytes": None,
}

# Класс C, дублируется в diagnostic — чтобы строка диагностики читалась без
# джойна с audit по eid. Идентификаторов и свободного ввода не содержит.
_DIAG_CONTEXT = ("method", "route", "status", "stage", "level", "logger")

# Непроверенный ввод: только diagnostic, только после redaction. Значение —
# предел длины (None — числовой скаляр).
_DIAG_LIMITS: dict[str, int | None] = {
    "path": 500,
    "query": 500,
    "message": 2000,
    "error": 500,
    "exc": 3000,
    "traceback": 3000,
    "ip": 60,
    "dur_ms": None,
}
# Поле, не known ни одному каналу: имя сохраняем (оно из схемы кода, не из
# ввода), значение — под полный контракт и жёсткий предел длины.
_UNKNOWN_FIELD_LIMIT = 300


# ─── Redaction значений ──────────────────────────────────────────────────────
# Имя поля/параметра, которое само по себе означает секрет: значение вырезается
# целиком, не разбираясь.
_SENSITIVE_NAME_RE = re.compile(
    r"(?i)(token|secret|password|passwd|\bpwd\b|cookie|authorization|credential|"
    r"api[_-]?key|access[_-]?key|private[_-]?key|signature|\bsig\b|\bsas\b|"
    r"session|\botp\b|\bpin\b|nonce|\bsalt\b|bearer|x-amz-)"
)
# Присвоение секрета внутри свободного текста: SECRET_KEY=..., "token": "...".
_KV_SECRET_RE = re.compile(
    r"(?i)([A-Za-z0-9_.\-]*(?:token|secret|password|passwd|pwd|cookie|"
    r"authorization|credential|api[_-]?key|access[_-]?key|private[_-]?key|"
    r"signature|sig|sas|session|otp|salt|nonce)[A-Za-z0-9_.\-]*)"
    r"(\"?\s*[=:]\s*\"?)([^\s,;&)}\]\"']+)"
)
# Presigned URL: подпись, срок и креденшл живут в query — сносим query целиком.
_URL_QUERY_RE = re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://[^\s\"'<>]*?)\?[^\s\"'<>]*")
_URL_USERINFO_RE = re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)[^/\s:@\"']+:[^/\s@\"']+@")
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_\-]{6,}\.[A-Za-z0-9_\-]{4,}\.[A-Za-z0-9_\-]{4,}")
_BEARER_RE = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._\-+/=]{6,}")
# Непрозрачный блоб (ключ/подпись/хэш). Латиница + цифры + оба регистра —
# кириллический текст и обычные слова под это не подпадают.
_BLOB_RE = re.compile(r"[A-Za-z0-9+/_=\-]{40,}")
# Учётные данные с ИЗВЕСТНЫМ вендорским префиксом. Защита в глубину рядом с
# _BLOB_RE, а не замена ему: блоб-правило ловит по длине (40+) и энтропии, и
# короткий ключ вида AKIA + 16 заглавных (всего 20 символов) под него не
# подпадает — измерено, протекал в diagnostic 20 раз из 20. Префикс однозначен,
# поэтому ни длина, ни энтропия здесь не нужны.
_CREDENTIAL_PREFIX_RE = re.compile(
    r"\b(?:"
    r"(?:AKIA|ASIA)[A-Z0-9]{12,}"              # AWS access key id
    r"|(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{16,}"   # GitHub token
    r"|github_pat_[A-Za-z0-9_]{20,}"               # GitHub fine-grained PAT
    r"|xox[abprs]-[A-Za-z0-9-]{8,}|xapp-[A-Za-z0-9-]{8,}"  # Slack
    r"|AIza[A-Za-z0-9_\-]{20,}"                    # Google API key
    r"|glpat-[A-Za-z0-9_\-]{16,}"                  # GitLab PAT
    r"|sk-[A-Za-z0-9_\-]{8,}"                      # sk-, sk-ant-, sk-or-, sk-proj-
    r")"
)
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# Управляющие символы (ANSI-эскейпы, подделка строк журнала). \t и \n оставляем:
# без \n traceback нечитаем, а json.dumps их всё равно экранирует.
_CTRL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
# Домашние каталоги: подтверждённая утечка — traceback несёт абсолютные пути ФС.
_HOME_RE = re.compile(
    r"(?:/root|/home/[^/\s\"']+|/Users/[^/\s\"']+|[A-Za-z]:\\Users\\[^\\\s\"']+)"
)

# Корни ФС этой установки → плейсхолдер. Длинные заменяются раньше коротких,
# иначе PROJECTS_DIR внутри ROOT_DIR не отличить.
_FS_ROOT_NAMES = (
    ("PROJECTS_DIR", "<projects>"),
    ("ACTION_LOG_DIR", "<logs>"),
    # ROOT_DIR раньше DATA_DIR: при дефолтной конфигурации они совпадают,
    # и при равной длине выигрывает первый — понятнее <root>, чем <data>.
    ("ROOT_DIR", "<root>"),
    ("DATA_DIR", "<data>"),
)
_ROOTS_CACHE: tuple[tuple[str, str], ...] = ()
_ROOTS_KEY: tuple | None = None


def _fs_roots() -> tuple[tuple[str, str], ...]:
    """[(абсолютный путь, плейсхолдер)]. Кэш по значению конфига."""
    global _ROOTS_CACHE, _ROOTS_KEY
    key = tuple(str(getattr(config, name, "") or "") for name, _ in _FS_ROOT_NAMES)
    if _ROOTS_KEY != key:
        pairs = [
            (path, mark)
            for path, (_, mark) in zip(key, _FS_ROOT_NAMES)
            if path and path not in ("/", ".")
        ]
        _ROOTS_CACHE = tuple(sorted(pairs, key=lambda pair: len(pair[0]), reverse=True))
        _ROOTS_KEY = key
    return _ROOTS_CACHE


def _credential_is_real(value: str) -> bool:
    """Отсечь ложные срабатывания единственного неоднозначного префикса.

    Все вендорские префиксы, кроме "sk-", встречаются только в ключах. "sk-"
    же может оказаться куском обычного слова или сегмента пути, поэтому от него
    дополнительно требуется цифра — в настоящих ключах провайдеров она есть
    всегда (sk-or-v1-…, sk-ant-api03-…, sk-proj-…).
    """
    if value.startswith("sk-"):
        return any(c.isdigit() for c in value)
    return True


def _blob_is_opaque(value: str) -> bool:
    """Длинная строка похожа на ключ/подпись, а не на слово или путь."""
    return (
        any(c.isdigit() for c in value)
        and any(c.isupper() for c in value)
        and any(c.islower() for c in value)
    )


def _scrub(text: str) -> str:
    """Обезличить произвольный текст. Порядок правил значим.

    Сначала пути ФС (иначе плейсхолдер попал бы под правило блоба), потом URL
    (снести query presigned-ссылки целиком), потом именованные секреты, затем
    правила по форме значения и последним — добор по вендорским префиксам.
    """
    try:
        out = str(text)
        for root, mark in _fs_roots():
            if root in out:
                out = out.replace(root, mark)
        out = _HOME_RE.sub("<home>", out)
        out = _CTRL_RE.sub(" ", out)
        out = _URL_USERINFO_RE.sub(r"\1[redacted]@", out)
        out = _URL_QUERY_RE.sub(r"\1?[redacted]", out)
        # Bearer/Basic — раньше правила «имя=значение»: иначе оно съест слово
        # Bearer как значение заголовка Authorization и оставит сам токен.
        out = _BEARER_RE.sub(lambda m: f"{m.group(1)} [redacted]", out)
        # Именованный секрет — раньше точечных правил по форме значения: иначе
        # JWT-правило съест часть, и от cookie останется огрызок.
        out = _KV_SECRET_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}[redacted]", out)
        out = _JWT_RE.sub("[redacted:jwt]", out)
        out = _BLOB_RE.sub(
            lambda m: "[redacted:blob]" if _blob_is_opaque(m.group()) else m.group(), out
        )
        # ПОСЛЕ блоб-правила, не до него: длинный хвост вида
        # AKIA<16>wJalrXUtnFEMI… целиком снимается блоб-правилом, а срабатывание
        # префикса раньше него отрезало бы только голову и оставило секретную
        # часть. Здесь префиксное правило добирает то, что блоб-правило не
        # видит: короткие ключи без нужной длины или энтропии.
        out = _CREDENTIAL_PREFIX_RE.sub(
            lambda m: "[redacted:credential]" if _credential_is_real(m.group())
            else m.group(),
            out,
        )
        return _EMAIL_RE.sub("[redacted:email]", out)
    except Exception:
        # Redaction, которая упала, не имеет права пропустить сырое значение.
        return "[redacted]"


def _shorten(text: str, limit: int | None) -> str:
    """Усечь, сохранив хвост: у traceback именно там текст исключения."""
    if limit is None or len(text) <= limit:
        return text
    head = max(1, limit * 2 // 3)
    tail = max(0, limit - head - 32)
    cut = len(text) - head - tail
    if tail <= 0:
        return text[:limit]
    return f"{text[:head]}\n… [усечено {cut} симв.] …\n{text[-tail:]}"


# Query-параметры, значение которых разрешено писать: структурные, из схемы API,
# пользовательского ввода не несут. Всё остальное (включая свободные q/search/
# query и любой идентификатор) отдаётся как имя=[redacted] — имя видно, значение
# нет. Расширяется через ACTION_LOG_QUERY_ALLOW_EXTRA.
_QUERY_SAFE_PARAMS = frozenset({
    "limit", "offset", "page", "per_page", "days", "kind", "errors_only",
    "format", "sort", "order", "direction", "stage", "status", "level",
    "dry_run", "force", "refresh", "download", "debug", "mode", "tab", "view",
    "version",
})
_QUERY_VALUE_LIMIT = 60


def _redact_query(raw) -> str | None:
    """Query-строка → 'имя=значение' только для allowlist-параметров."""
    try:
        text = str(raw)
        if not text:
            return None
        extra = frozenset(getattr(config, "ACTION_LOG_QUERY_ALLOW_EXTRA", []) or ())
        allowed = _QUERY_SAFE_PARAMS | extra
        parts = []
        for name, value in parse_qsl(text, keep_blank_values=True):
            safe_name = _CTRL_RE.sub("", str(name))[:60]
            if safe_name in allowed and not _SENSITIVE_NAME_RE.search(safe_name):
                parts.append(f"{safe_name}={_scrub(value)[:_QUERY_VALUE_LIMIT]}")
            else:
                parts.append(f"{safe_name}=[redacted]")
        if not parts:
            # Непарсящийся мусор: сохранять нечего, но факт запроса — да.
            return "[redacted]"
        return _shorten("&".join(parts), _DIAG_LIMITS["query"])
    except Exception:
        return "[redacted]"


def _redact_ip(raw) -> str:
    """IP — ПДн: оставляем подсеть (диагностика источника), не хост."""
    try:
        text = str(raw).strip()
        if ":" in text:  # IPv6 → /64
            groups = text.split(":")
            return ":".join(groups[:4]) + "::x" if len(groups) > 4 else text
        octets = text.split(".")
        if len(octets) == 4 and all(o.isdigit() for o in octets):
            return ".".join(octets[:3]) + ".x"
        return _scrub(text)[:60]
    except Exception:
        return "[redacted]"


def _audit_value(key: str, value, limit: int | None):
    """Значение allowlist-поля durable audit. Allowlist разрешает ИМЯ, не значение."""
    if isinstance(value, bool) or isinstance(value, (int, float)):
        return value
    return _shorten(_scrub(value), limit if limit is not None else 200)


def _diag_value(key: str, value):
    """Значение для diagnostic. Всё, что не число, проходит redaction."""
    if key == "ip":
        return _redact_ip(value)
    if key == "query":
        return _redact_query(value)
    if key in _DIAG_LIMITS:
        if isinstance(value, bool) or isinstance(value, (int, float)):
            return value
        return _shorten(_scrub(value), _DIAG_LIMITS[key])
    # Неизвестное поле.
    if _SENSITIVE_NAME_RE.search(str(key)):
        return "[redacted]"
    if isinstance(value, bool) or isinstance(value, (int, float)):
        return value
    return _shorten(_scrub(value), _UNKNOWN_FIELD_LIMIT)


def _split_channels(fields: dict) -> tuple[dict, dict]:
    """Разложить поля события по каналам. None-значения отбрасываются."""
    audit: dict = {}
    diag: dict = {}
    extra_allowed = frozenset(getattr(config, "ACTION_LOG_AUDIT_EXTRA_FIELDS", []) or ())
    for key, value in fields.items():
        if value is None:
            continue
        if key in _AUDIT_FIELDS or key in extra_allowed:
            audit[key] = _audit_value(key, value, _AUDIT_FIELDS.get(key, 200))
            if key in _DIAG_CONTEXT:
                diag[key] = audit[key]
            continue
        diag[key] = _diag_value(key, value)
    # Контекст без собственной диагностики — не повод плодить вторую строку.
    if not any(k not in _DIAG_CONTEXT for k in diag):
        diag = {}
    return audit, diag


# ─── Метрики (канал 3) ───────────────────────────────────────────────────────
# Только низкокардинальные labels: method × route × status. path, project_id,
# actor, query и любой другой идентификатор в labels не попадают — иначе
# реестр взрывается по кардинальности, а идентификаторы утекают третий раз.
_METRICS_LOCK = threading.Lock()
_METRICS_MAX_SERIES = 500
_DUR_BUCKETS_MS = (5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000)
_METRICS: dict[str, dict] = {"http": {}, "events": {}}


def _observe_metrics(kind: str, fields: dict) -> None:
    """Учесть событие в in-process реестре метрик. Fail-soft."""
    try:
        with _METRICS_LOCK:
            _METRICS["events"][kind] = _METRICS["events"].get(kind, 0) + 1
            if kind != "api":
                return
            http = _METRICS["http"]
            status = fields.get("status")
            key = (
                str(fields.get("method") or "-")[:10],
                str(fields.get("route") or "<unmatched>")[:200],
                status if isinstance(status, int) else None,
            )
            if key not in http and len(http) >= _METRICS_MAX_SERIES:
                key = ("-", "<over-cardinality>", None)
            row = http.get(key)
            if row is None:
                row = {"count": 0, "sum_ms": 0.0,
                       "buckets": [0] * (len(_DUR_BUCKETS_MS) + 1)}
                http[key] = row
            row["count"] += 1
            dur = fields.get("dur_ms")
            if isinstance(dur, (int, float)) and not isinstance(dur, bool):
                row["sum_ms"] += float(dur)
                row["buckets"][bisect.bisect_left(_DUR_BUCKETS_MS, dur)] += 1
    except Exception:
        pass


def metrics_snapshot() -> dict:
    """Снимок реестра метрик: счётчики по kind и гистограммы dur_ms по HTTP."""
    labels = [str(b) for b in _DUR_BUCKETS_MS] + ["+Inf"]
    with _METRICS_LOCK:
        return {
            "events": dict(_METRICS["events"]),
            "http": [
                {
                    "method": method, "route": route, "status": status,
                    "count": row["count"], "sum_ms": round(row["sum_ms"], 1),
                    "buckets": dict(zip(labels, row["buckets"])),
                }
                for (method, route, status), row in _METRICS["http"].items()
            ],
            "series": len(_METRICS["http"]),
            "max_series": _METRICS_MAX_SERIES,
        }


def reset_metrics() -> None:
    """Обнулить реестр (тесты, ручной сбор)."""
    with _METRICS_LOCK:
        _METRICS["http"].clear()
        _METRICS["events"].clear()


# ─── Запись ──────────────────────────────────────────────────────────────────
def _redaction_enabled() -> bool:
    return bool(getattr(config, "ACTION_LOG_REDACTION", True))


def _write_record(prefix: str, record: dict) -> None:
    """Дописать строку в суточный файл канала. Бросает — ловит вызывающий."""
    global _WRITE_FAILED_WARNED
    data = json.dumps(record, ensure_ascii=False, default=str) + "\n"
    log_dir = _log_dir()
    day = _today_str()
    with _LOCK:
        write_key = (str(log_dir), day)
        file_path = log_dir / f"{prefix}{day}.jsonl"
        if _LAST_WRITE_KEY.get(prefix) != write_key:
            log_dir.mkdir(parents=True, exist_ok=True)
            _cleanup_old_files(log_dir)
            _LAST_WRITE_KEY[prefix] = write_key
        if _DAY_BUDGET["key"] != write_key:
            # Новый день или директория: пересчитать общий бюджет по ОБОИМ
            # файлам — иначе рестарт посреди дня обнулил бы потолок.
            total = 0
            for known in (_AUDIT_PREFIX, _DIAG_PREFIX):
                try:
                    total += (log_dir / f"{known}{day}.jsonl").stat().st_size
                except OSError:
                    pass
            _DAY_BUDGET["key"] = write_key
            _DAY_BUDGET["bytes"] = total
            _DAY_CAP_MARKED.clear()
        # Потолок суточного объёма: защита диска от штормов событий.
        max_bytes = int(getattr(config, "ACTION_LOG_MAX_DAY_BYTES", 0) or 0)
        encoded = data.encode("utf-8")
        written = _DAY_BUDGET["bytes"]
        if max_bytes > 0 and written + len(encoded) > max_bytes:
            if not _DAY_CAP_MARKED.get(prefix):
                _DAY_CAP_MARKED[prefix] = True
                marker = json.dumps(
                    {"ts": _now_iso(), "kind": "system",
                     "event": "day_cap_reached", "max_bytes": max_bytes},
                    ensure_ascii=False,
                ) + "\n"
                with open(file_path, "a", encoding="utf-8") as f:
                    f.write(marker)
                _DAY_BUDGET["bytes"] = written + len(marker.encode("utf-8"))
            return
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(data)
        _DAY_BUDGET["bytes"] = written + len(encoded)
    # Успешная запись — новая полоса отказов снова даст предупреждение.
    _WRITE_FAILED_WARNED = False


def log_event(kind: str, **fields) -> None:
    """Записать одно событие. Никогда не бросает исключений.

    Поля раскладываются по каналам (см. контракт у _AUDIT_FIELDS): в durable
    audit уходят только имена из _AUDIT_FIELDS, всё прочее — в diagnostic после
    redaction. None-значения отбрасываются, чтобы записи оставались компактными.

    ACTION_LOG_REDACTION=0 возвращает прежнее поведение один-в-один: один файл,
    все поля дословно. Это аварийный откат, а не режим эксплуатации.
    """
    global _LAST_WRITE_KEY, _WRITE_FAILED_WARNED
    try:
        if not getattr(config, "ACTION_LOG_ENABLED", True):
            return
        if not _redaction_enabled():
            legacy = {"ts": _now_iso(), "kind": kind}
            for key, value in fields.items():
                if value is not None:
                    legacy[key] = value
            _write_record(_AUDIT_PREFIX, legacy)
            return

        _observe_metrics(kind, fields)
        audit, diag = _split_channels(fields)
        write_diag = bool(diag) and bool(getattr(config, "ACTION_LOG_DIAG_ENABLED", True))
        ts = _now_iso()
        # correlation id ставится только когда есть что связывать.
        eid = uuid.uuid4().hex[:12] if write_diag else None

        record = {"ts": ts, "kind": kind}
        if eid:
            record["eid"] = eid
        record.update(audit)
        _write_record(_AUDIT_PREFIX, record)

        if write_diag:
            diag_record = {"ts": ts, "kind": kind, "eid": eid}
            diag_record.update(diag)
            _write_record(_DIAG_PREFIX, diag_record)
    except Exception as e:
        # Самолечение: сбросить кэш-ключи, чтобы следующая запись заново сделала
        # mkdir (директорию могли удалить при чистке диска посреди дня).
        _LAST_WRITE_KEY = {}
        _DAY_BUDGET["key"] = None
        if not _WRITE_FAILED_WARNED:
            _WRITE_FAILED_WARNED = True
            try:
                print(f"[action_log] запись журнала не удалась: {e}", file=sys.stderr)
            except Exception:
                pass


# ─── Шум-фильтр HTTP (поллинговые GET фронта) ────────────────────────────────
# Применяется ТОЛЬКО к успешным GET (<400): мутирующие запросы и любые ошибки
# пишутся всегда. Пути с regex-паттернами ниже фронт опрашивает раз в секунды —
# без фильтра журнал превращается в шум и распухает.
_NOISE_PATTERNS = [
    r"^/static/",
    r"^/favicon\.ico$",
    r"^/api/info$",
    r"^/api/auth/me$",
    r"/status$",             # /api/audit/batch/status, {pid}/status, pause/status и т.п.
    r"/live-status$",
    r"/resume-info$",
    r"/health$",
    r"^/api/usage/",         # виджеты расхода токенов опрашиваются постоянно
    r"^/api/audit/prepare-data/queue$",
    r"^/api/audit/.+/log$",  # live-лог аудита тянется в цикле
    r"^/api/document/.+/page/",              # рендер страниц при листании PDF
    r"^/api/tiles/.+/blocks/(image|region-image)/",
    r"/pairs/[^/]+/page-svg$",  # векторные страницы comparison viewer
]

_NOISE_RE: re.Pattern | None = None
_NOISE_RE_KEY: tuple | None = None


def _get_noise_re() -> re.Pattern:
    """Скомпилированный шум-фильтр; пересобирается при смене NOISE_EXTRA (тесты)."""
    global _NOISE_RE, _NOISE_RE_KEY
    extra = tuple(getattr(config, "ACTION_LOG_NOISE_EXTRA", []) or [])
    if _NOISE_RE is None or _NOISE_RE_KEY != extra:
        patterns = list(_NOISE_PATTERNS)
        for pat in extra:
            try:
                re.compile(pat)
                patterns.append(pat)
            except re.error:
                pass
        _NOISE_RE = re.compile("|".join(f"(?:{p})" for p in patterns))
        _NOISE_RE_KEY = extra
    return _NOISE_RE


def is_noise_path(path: str) -> bool:
    return bool(_get_noise_re().search(path))


# ─── HTTP middleware ─────────────────────────────────────────────────────────
class ActionLogMiddleware:
    """Pure-ASGI middleware: пишет kind="api" событие на каждый HTTP-запрос.

    Pure ASGI (не BaseHTTPMiddleware) — не трогает тело запроса/ответа, поэтому
    безопасен для стриминга (chat/stream), загрузок файлов и не добавляет
    задержки. Событие пишется ПОСЛЕ полного ответа (известны статус и
    длительность). Исключение из downstream логируется и пробрасывается дальше
    (наружный ServerErrorMiddleware Starlette по-прежнему вернёт 500).
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not (
            getattr(config, "ACTION_LOG_ENABLED", True)
            and getattr(config, "ACTION_LOG_HTTP_ENABLED", True)
        ):
            await self.app(scope, receive, send)
            return

        start = time.monotonic()
        holder = {"status": None}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                holder["status"] = message.get("status")
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:
            self._log_request(scope, holder["status"] or 500, start, exc=exc)
            raise
        else:
            self._log_request(scope, holder["status"], start)

    def _log_request(self, scope, status, start, exc: Exception | None = None) -> None:
        try:
            path = scope.get("path", "")
            method = scope.get("method", "")
            if (
                exc is None
                and method in ("GET", "HEAD", "OPTIONS")
                and isinstance(status, int)
                and status < 400
                and is_noise_path(path)
            ):
                return

            actor = self._resolve_actor(scope)
            query = (scope.get("query_string") or b"").decode("utf-8", "replace")[:500]
            route_path = getattr(scope.get("route"), "path", None)
            path_params = scope.get("path_params") or {}
            project_id = path_params.get("project_id") or path_params.get("target_project_id")
            client = scope.get("client")

            # Инверсия прежнего правила: route (ШАБЛОН маршрута, идентификаторов
            # не несёт) пишется ВСЕГДА и уходит в durable audit; сырой path
            # уходит в diagnostic. Раньше было наоборот — route писался только
            # когда отличался от path, а идентификаторы жили в path.
            # В режиме отката (ACTION_LOG_REDACTION=0) — прежнее правило.
            if _redaction_enabled():
                route_field = route_path
            else:
                route_field = route_path if route_path and route_path != path else None

            fields = {
                "actor": actor,
                "method": method,
                "path": path[:500],
                "route": route_field,
                "query": query or None,
                "project_id": project_id,
                "status": status,
                "dur_ms": round((time.monotonic() - start) * 1000),
                "ip": client[0] if client else None,
            }
            if exc is not None:
                fields["error"] = f"{type(exc).__name__}: {exc}"[:500]
                fields["traceback"] = traceback.format_exc()[:8000]
            log_event("api", **fields)
        except Exception:
            pass

    @staticmethod
    def _resolve_actor(scope) -> str | None:
        """Логин инженера из session-cookie (портал-auth). Fail-soft."""
        try:
            from starlette.requests import Request

            from backend.app.core import portal_auth

            request = Request(scope)
            return portal_auth.request_username(request, portal_auth.get_settings())
        except Exception:
            return None


# ─── Хук конвейера ───────────────────────────────────────────────────────────
def log_pipeline_event(
    project_id: str,
    stage: str,
    status: str,
    message: str = "",
    error: str = "",
    duration_sec: int | None = None,
) -> None:
    """Событие перехода этапа конвейера. Вызывается из audit_logger. Fail-soft."""
    try:
        if not getattr(config, "ACTION_LOG_PIPELINE_ENABLED", True):
            return
        log_event(
            "pipeline",
            project_id=project_id,
            stage=stage,
            status=status,
            message=(message or None) and str(message)[:1000],
            error=(error or None) and str(error)[:2000],
            duration_sec=duration_sec,
        )
    except Exception:
        pass


# ─── Мост стандартного logging ───────────────────────────────────────────────
# Скользящее окно rate-limit для app_log: логгер, заголосивший WARNING в цикле,
# не должен раздувать журнал. Отдельный лок — log_event берёт _LOCK,
# вложенный захват не-реентерабельного _LOCK из emit дал бы deadlock.
_APPLOG_LOCK = threading.Lock()
_APPLOG_WINDOW = {"minute": None, "count": 0, "suppressed": 0}


def _applog_gate() -> tuple[bool, int]:
    """(писать ли текущее событие, сколько подавлено в закрывшемся окне)."""
    limit = int(getattr(config, "ACTION_LOG_APPLOG_MAX_PER_MIN", 0) or 0)
    if limit <= 0:
        return True, 0
    minute = int(time.time() // 60)
    with _APPLOG_LOCK:
        closed_suppressed = 0
        if _APPLOG_WINDOW["minute"] != minute:
            closed_suppressed = _APPLOG_WINDOW["suppressed"]
            _APPLOG_WINDOW.update(minute=minute, count=0, suppressed=0)
        _APPLOG_WINDOW["count"] += 1
        if _APPLOG_WINDOW["count"] > limit:
            _APPLOG_WINDOW["suppressed"] += 1
            return False, closed_suppressed
        return True, closed_suppressed


class _ActionLogHandler(logging.Handler):
    """WARNING+ из любого модуля backend → событие kind="app_log"."""

    _reentry = threading.local()

    def emit(self, record: logging.LogRecord) -> None:
        if getattr(self._reentry, "active", False):
            return
        self._reentry.active = True
        try:
            allowed, closed_suppressed = _applog_gate()
            if closed_suppressed:
                log_event(
                    "app_log",
                    level="WARNING",
                    logger="action_log",
                    message=f"подавлено {closed_suppressed} событий app_log "
                            f"(лимит ACTION_LOG_APPLOG_MAX_PER_MIN)",
                )
            if not allowed:
                return
            exc_text = None
            if record.exc_info:
                # Грубое ограничение — сырьё для _shorten(): умное усечение
                # (голова + хвост с текстом исключения) делает контракт
                # redaction, здесь только потолок на объём в памяти.
                exc_text = "".join(traceback.format_exception(*record.exc_info))[:8000]
            log_event(
                "app_log",
                level=record.levelname,
                logger=record.name,
                message=record.getMessage()[:2000],
                exc=exc_text,
            )
        except Exception:
            pass
        finally:
            self._reentry.active = False


# Хендлеры, добавленные мостом, — чтобы uninstall снимал ровно их.
_BRIDGE_HANDLERS: list[logging.Handler] = []


def install_logging_bridge() -> None:
    """Подключить мост root-логгера. Идемпотентно; вызывается на старте app.

    Добавление хендлера к root отключает logging.lastResort (WARNING+ → stderr),
    поэтому рядом ставится явный StreamHandler(stderr, WARNING) — прежнее
    поведение server.err.log сохраняется.
    """
    try:
        if not (
            getattr(config, "ACTION_LOG_ENABLED", True)
            and getattr(config, "ACTION_LOG_APPLOG_ENABLED", True)
        ):
            return
        root = logging.getLogger()
        if any(isinstance(h, _ActionLogHandler) for h in root.handlers):
            return
        handler = _ActionLogHandler(level=logging.WARNING)
        root.addHandler(handler)
        _BRIDGE_HANDLERS.append(handler)
        has_stream = any(
            isinstance(h, logging.StreamHandler) and not isinstance(h, _ActionLogHandler)
            for h in root.handlers
        )
        if not has_stream:
            stderr_handler = logging.StreamHandler(sys.stderr)
            stderr_handler.setLevel(logging.WARNING)
            root.addHandler(stderr_handler)
            _BRIDGE_HANDLERS.append(stderr_handler)
    except Exception:
        pass


def uninstall_logging_bridge() -> None:
    """Снять с root ровно те хендлеры, что добавил мост. Идемпотентно, fail-soft.

    Вызывается на shutdown (lifespan): в проде безвредно, а в тестах
    `with TestClient(app)` мост не переживает выход из контекста.
    """
    try:
        root = logging.getLogger()
        for handler in list(_BRIDGE_HANDLERS):
            root.removeHandler(handler)
            _BRIDGE_HANDLERS.remove(handler)
        # Страховка от хендлеров-сирот из чужих install (напр., другой процесс
        # импорта): _ActionLogHandler на root не должен оставаться никогда.
        for handler in list(root.handlers):
            if isinstance(handler, _ActionLogHandler):
                root.removeHandler(handler)
    except Exception:
        pass


# ─── Чтение журнала ──────────────────────────────────────────────────────────
def _is_error_event(event: dict) -> bool:
    if event.get("error") or event.get("exc") or event.get("traceback"):
        return True
    kind = event.get("kind")
    if kind == "api":
        status = event.get("status")
        return isinstance(status, int) and status >= 400
    if kind == "pipeline":
        return event.get("status") in ("error", "interrupted")
    if kind == "app_log":
        return True  # в журнал попадают только WARNING+
    return False


def read_events(
    date_from: str | None = None,
    date_to: str | None = None,
    kind: str | None = None,
    actor: str | None = None,
    q: str | None = None,
    errors_only: bool = False,
    limit: int = 200,
    offset: int = 0,
    channel: str = "audit",
) -> dict:
    """Прочитать события журнала, новые → старые.

    date_from/date_to — 'YYYY-MM-DD' включительно (по имени суточного файла).
    q — подстрока (без учёта регистра) по сырой JSONL-строке события.
    channel — "audit" (default, файлы actions-*.jsonl, включая записанные до
    введения каналов) либо "diag" (файлы diag-*.jsonl).
    """
    limit = max(1, min(int(limit), 2000))
    offset = max(0, min(int(offset), 50_000))
    q_lower = q.lower() if q else None
    prefix = _DIAG_PREFIX if channel == "diag" else _AUDIT_PREFIX

    log_dir = _log_dir()
    try:
        files = sorted(log_dir.glob(f"{prefix}*.jsonl"), reverse=True)
    except OSError:
        files = []

    items: list[dict] = []
    skipped = 0
    days_scanned = 0
    truncated = False

    for file_path in files:
        day = file_path.name[len(prefix):-len(".jsonl")]
        if date_to and day > date_to:
            continue
        if date_from and day < date_from:
            break  # файлы отсортированы по убыванию — дальше только старее
        days_scanned += 1
        # Потоковый проход + deque: память O(offset+limit), а не O(размер файла).
        # Файл хронологический → deque(maxlen) держит НОВЕЙШИЕ совпадения; всё,
        # что он вытеснил, в ответ попасть не может.
        matched: deque = deque(maxlen=offset + limit)
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    if q_lower and q_lower not in line.lower():
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if kind and event.get("kind") != kind:
                        continue
                    if actor and event.get("actor") != actor:
                        continue
                    if errors_only and not _is_error_event(event):
                        continue
                    matched.append(event)
        except OSError:
            continue
        for event in reversed(matched):
            if skipped < offset:
                skipped += 1
                continue
            items.append(event)
            if len(items) >= limit:
                truncated = True
                break
        if truncated:
            break

    return {"items": items, "days_scanned": days_scanned, "truncated": truncated}


def stats(days: int = 7, channel: str = "audit") -> dict:
    """Сводка по последним N КАЛЕНДАРНЫМ дням: объёмы, ошибки, активность.

    channel — "audit" (default) либо "diag"; см. read_events().
    """
    days = max(1, min(int(days), 366))
    cutoff = (datetime.now() - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    prefix = _DIAG_PREFIX if channel == "diag" else _AUDIT_PREFIX
    log_dir = _log_dir()
    try:
        files = [
            p for p in sorted(log_dir.glob(f"{prefix}*.jsonl"), reverse=True)
            if p.name[len(prefix):-len(".jsonl")] >= cutoff
        ][:days]
    except OSError:
        files = []

    day_rows = []
    totals = {"events": 0, "errors": 0, "by_kind": {}}
    for file_path in files:
        day = file_path.name[len(prefix):-len(".jsonl")]
        by_kind: dict[str, int] = {}
        actors: dict[str, int] = {}
        paths: dict[str, int] = {}
        pipeline_errors: dict[str, int] = {}
        errors = 0
        total = 0
        try:
            f = open(file_path, "r", encoding="utf-8", errors="replace")
        except OSError:
            continue
        # Построчная итерация: O(1) памяти вместо read_text() всего файла.
        with f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                total += 1
                k = event.get("kind", "?")
                by_kind[k] = by_kind.get(k, 0) + 1
                if _is_error_event(event):
                    errors += 1
                    if k == "pipeline":
                        # project_id живёт в durable audit; в diagnostic его
                        # нет — не печатать из-за этого ключ "None:stage".
                        key = f"{event.get('project_id') or '-'}:{event.get('stage')}"
                        pipeline_errors[key] = pipeline_errors.get(key, 0) + 1
                a = event.get("actor")
                if a:
                    actors[a] = actors.get(a, 0) + 1
                if k == "api":
                    # route первичен: durable audit хранит ШАБЛОН маршрута.
                    # event.get('path') — совместимость с файлами, записанными
                    # до разделения каналов.
                    p = (f"{event.get('method', '')} "
                         f"{event.get('route') or event.get('path') or '<unmatched>'}")
                    paths[p] = paths.get(p, 0) + 1
        top = lambda d, n=10: sorted(d.items(), key=lambda kv: -kv[1])[:n]  # noqa: E731
        day_rows.append({
            "day": day,
            "total": total,
            "by_kind": by_kind,
            "errors": errors,
            "actors": dict(top(actors)),
            "top_paths": top(paths),
            "pipeline_errors": dict(top(pipeline_errors)),
        })
        totals["events"] += total
        totals["errors"] += errors
        for k, v in by_kind.items():
            totals["by_kind"][k] = totals["by_kind"].get(k, 0) + v

    return {"days": day_rows, "totals": totals}
