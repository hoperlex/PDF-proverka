"""Тесты ядра журнала действий (backend/app/core/action_log.py)."""
import json
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.core import action_log
from backend.app.core import config as cfg


def _read(log_dir, pattern):
    events = []
    for path in sorted(log_dir.glob(pattern)):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(json.loads(line))
    return events


def _events(log_dir):
    """События durable audit (actions-*.jsonl), старые → новые."""
    return _read(log_dir, "actions-*.jsonl")


def _diag(log_dir):
    """События диагностического канала (diag-*.jsonl), старые → новые."""
    return _read(log_dir, "diag-*.jsonl")


def _raw_text(log_dir):
    """Всё, что реально легло на диск обоими каналами, одной строкой."""
    return "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(log_dir.glob("*.jsonl"))
    )


@pytest.fixture
def log_dir(tmp_path, monkeypatch):
    d = tmp_path / "actions_log"
    monkeypatch.setattr(cfg, "ACTION_LOG_DIR", d, raising=False)
    monkeypatch.setattr(cfg, "ACTION_LOG_ENABLED", True, raising=False)
    return d


# ─── Писатель ────────────────────────────────────────────────────────────────
def test_log_event_roundtrip(log_dir):
    action_log.log_event("api", actor="ivan", status=200, skipped=None)
    events = _events(log_dir)
    assert len(events) == 1
    e = events[0]
    assert e["kind"] == "api"
    assert e["actor"] == "ivan"
    assert e["status"] == 200
    assert "skipped" not in e  # None-поля отбрасываются
    assert e["ts"]  # timestamp проставлен


def test_log_event_disabled(log_dir, monkeypatch):
    monkeypatch.setattr(cfg, "ACTION_LOG_ENABLED", False, raising=False)
    action_log.log_event("api", actor="ivan")
    assert not log_dir.exists() or not _events(log_dir)


def test_log_event_never_raises(tmp_path, monkeypatch):
    # Директория недоступна для записи (файл вместо папки) → fail-soft.
    bad = tmp_path / "not_a_dir"
    bad.write_text("x", encoding="utf-8")
    monkeypatch.setattr(cfg, "ACTION_LOG_DIR", bad / "sub", raising=False)
    action_log.log_event("api", actor="ivan")  # не должно бросить


def test_retention_cleanup(log_dir, monkeypatch):
    from datetime import date, timedelta
    monkeypatch.setattr(cfg, "ACTION_LOG_RETENTION_DAYS", 30, raising=False)
    log_dir.mkdir(parents=True)
    fresh = (date.today() - timedelta(days=3)).isoformat()
    (log_dir / "actions-2020-01-01.jsonl").write_text("{}\n", encoding="utf-8")
    (log_dir / "actions-2020-01-02.jsonl").write_text("{}\n", encoding="utf-8")
    (log_dir / f"actions-{fresh}.jsonl").write_text("{}\n", encoding="utf-8")
    # Смена (dir, day) → триггер чистки при первой записи.
    action_log.log_event("system", event="test")
    names = sorted(p.name for p in log_dir.glob("actions-*.jsonl"))
    # retention=30 дней: файлы 2020 года удалены, свежие (3 дня + сегодня) живут
    assert names == [f"actions-{fresh}.jsonl", f"actions-{date.today().isoformat()}.jsonl"]


def test_writer_self_heals_after_dir_removal(log_dir):
    """Пропажа директории посреди дня не должна убивать журнал до конца дня."""
    import shutil
    action_log.log_event("system", event="one")
    shutil.rmtree(log_dir)
    action_log.log_event("system", event="two")   # падает → сброс ключа
    action_log.log_event("system", event="three")  # самолечение: mkdir заново
    events = _events(log_dir)
    assert [e["event"] for e in events] == ["three"]


def test_day_cap_stops_writes(log_dir, monkeypatch):
    # Потолок считается по КАЖДОМУ каналу отдельно, поэтому событие берём
    # чисто audit-овое (поле event в allowlist, диагностики не порождает).
    monkeypatch.setattr(cfg, "ACTION_LOG_MAX_DAY_BYTES", 200, raising=False)
    action_log.log_event("system", event="one")            # ~75 байт — влезает
    action_log.log_event("system", event="y" * 200)        # превысит потолок
    action_log.log_event("system", event="three")          # уже за потолком
    events = _events(log_dir)
    # первое событие + один маркер day_cap_reached; дальше — тишина
    assert len(events) == 2
    assert events[0]["kind"] == "system" and events[0]["event"] == "one"
    assert events[1]["kind"] == "system" and events[1]["event"] == "day_cap_reached"


# ─── Шум-фильтр ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("path", [
    "/static/js/app.js",
    "/api/info",
    "/api/auth/me",
    "/api/audit/live-status",
    "/api/audit/batch/status",
    "/api/audit/pause/status",
    "/api/audit/ЭОМ/13АВ-РД-ЭМ-К1/status",
    "/api/audit/ЭОМ/13АВ-РД-ЭМ-К1/log",
    "/api/audit/prepare-data/queue",
    "/api/usage/counters",
    "/api/usage/global",
    "/api/lms/health",
    "/api/document/ЭОМ/К1/page/12",
    "/api/tiles/ЭОМ/К1/blocks/image/6L97",
    "/api/stage-comparison/sessions/s1/pairs/p1/page-svg",
])
def test_noise_paths(path):
    assert action_log.is_noise_path(path), path


@pytest.mark.parametrize("path", [
    "/",
    "/login",
    "/api/projects",
    "/api/audit/ЭОМ/13АВ-РД-ЭМ-К1/full-audit",
    "/api/findings/ЭОМ/13АВ-РД-ЭМ-К1",
    "/api/document/ЭОМ/К1/pdf",
    "/api/knowledge-base/expert-review/ЭОМ/К1",
    "/api/stage-comparison/sessions",
    "/api/action-log",
])
def test_non_noise_paths(path):
    assert not action_log.is_noise_path(path), path


def test_noise_extra_from_config(monkeypatch):
    monkeypatch.setattr(cfg, "ACTION_LOG_NOISE_EXTRA", [r"^/api/custom-poll$"], raising=False)
    assert action_log.is_noise_path("/api/custom-poll")
    monkeypatch.setattr(cfg, "ACTION_LOG_NOISE_EXTRA", [], raising=False)
    assert not action_log.is_noise_path("/api/custom-poll")


# ─── Middleware ──────────────────────────────────────────────────────────────
@pytest.fixture
def mw_client(log_dir):
    app = FastAPI()

    @app.get("/api/ok")
    async def ok():
        return {"ok": True}

    @app.post("/api/info")
    async def info_post():
        return {"ok": True}

    @app.get("/api/info")
    async def info_get():
        return {"ok": True}

    @app.get("/api/boom")
    async def boom():
        raise RuntimeError("взрыв в endpoint")

    @app.get("/api/projects/{project_id:path}/card")
    async def card(project_id: str):
        return {"project_id": project_id}

    app.add_middleware(action_log.ActionLogMiddleware)
    return TestClient(app, raise_server_exceptions=False)


def test_middleware_logs_ok_request(mw_client, log_dir):
    resp = mw_client.get("/api/ok", params={"limit": "1"})
    assert resp.status_code == 200
    events = _events(log_dir)
    assert len(events) == 1
    e = events[0]
    assert e["kind"] == "api"
    assert e["method"] == "GET"
    assert e["route"] == "/api/ok"     # ШАБЛОН маршрута — durable audit
    assert e["status"] == 200
    assert "path" not in e and "query" not in e and "dur_ms" not in e

    d = _diag(log_dir)
    assert len(d) == 1
    assert d[0]["eid"] == e["eid"]     # каналы связаны correlation id
    assert d[0]["path"] == "/api/ok"
    assert d[0]["query"] == "limit=1"  # limit — из allowlist параметров
    assert isinstance(d[0]["dur_ms"], int)


def test_middleware_skips_noisy_get_but_logs_post(mw_client, log_dir):
    assert mw_client.get("/api/info").status_code == 200
    assert not _events(log_dir)  # шумовой GET не пишется
    assert mw_client.post("/api/info").status_code == 200
    events = _events(log_dir)
    assert len(events) == 1  # мутирующий запрос пишется всегда
    assert events[0]["method"] == "POST"


def test_middleware_logs_error_status(mw_client, log_dir):
    resp = mw_client.get("/api/nonexistent")
    assert resp.status_code == 404
    events = _events(log_dir)
    assert len(events) == 1
    assert events[0]["status"] == 404


def test_middleware_logs_exception_with_traceback(mw_client, log_dir):
    resp = mw_client.get("/api/boom")
    assert resp.status_code == 500
    events = _events(log_dir)
    assert len(events) == 1
    # Текст исключения и traceback — непроверенный ввод: durable audit их не
    # хранит, там остаётся факт «маршрут ответил 500».
    assert events[0]["status"] == 500
    assert "error" not in events[0] and "traceback" not in events[0]

    d = _diag(log_dir)
    assert len(d) == 1
    assert "RuntimeError" in d[0]["error"]
    assert "взрыв" in d[0]["error"]
    assert "traceback" in d[0]


def test_middleware_extracts_project_id(mw_client, log_dir):
    mw_client.get("/api/projects/ЭОМ/13АВ-РД-ЭМ-К1/card")
    events = _events(log_dir)
    assert events[0]["project_id"] == "ЭОМ/13АВ-РД-ЭМ-К1"


def test_middleware_resolves_actor_from_cookie(mw_client, log_dir, monkeypatch):
    from backend.app.core import portal_auth
    monkeypatch.setenv("PORTAL_AUTH_USERS", "ivan:x-hash")
    monkeypatch.setenv("PORTAL_SESSION_SECRET", "test-secret")
    token = portal_auth.issue_token("ivan", portal_auth.get_settings())
    mw_client.cookies.set("portal_session", token)
    mw_client.get("/api/ok")
    events = _events(log_dir)
    assert events[0]["actor"] == "ivan"


def test_middleware_disabled_by_flag(mw_client, log_dir, monkeypatch):
    monkeypatch.setattr(cfg, "ACTION_LOG_HTTP_ENABLED", False, raising=False)
    mw_client.get("/api/ok")
    assert not _events(log_dir)


# ─── Хук конвейера ───────────────────────────────────────────────────────────
def test_log_pipeline_event(log_dir):
    action_log.log_pipeline_event(
        "ЭОМ/К1", "block_analysis", "error", message="", error="упало", duration_sec=12,
    )
    events = _events(log_dir)
    assert len(events) == 1
    e = events[0]
    assert e["kind"] == "pipeline"
    assert e["project_id"] == "ЭОМ/К1"
    assert e["stage"] == "block_analysis"
    assert e["status"] == "error"
    assert e["duration_sec"] == 12
    assert "error" not in e    # текст ошибки — диагностика, не durable audit
    assert "message" not in e  # пустая строка не пишется

    d = _diag(log_dir)
    assert len(d) == 1 and d[0]["error"] == "упало" and d[0]["eid"] == e["eid"]
    assert "message" not in d[0]


def test_pipeline_hook_via_audit_logger(log_dir, tmp_path, monkeypatch):
    """update_pipeline_log → событие kind=pipeline в журнале."""
    from backend.app.services.common import audit_logger
    out_dir = tmp_path / "_output"
    monkeypatch.setattr(audit_logger, "_project_output_dir", lambda pid: out_dir)
    audit_logger.update_pipeline_log("ЭОМ/К1", "text_analysis", "running", message="старт")
    events = [e for e in _events(log_dir) if e["kind"] == "pipeline"]
    assert len(events) == 1
    assert events[0]["stage"] == "text_analysis"
    assert events[0]["status"] == "running"


def test_pipeline_disabled_by_flag(log_dir, monkeypatch):
    monkeypatch.setattr(cfg, "ACTION_LOG_PIPELINE_ENABLED", False, raising=False)
    action_log.log_pipeline_event("ЭОМ/К1", "excel", "done")
    assert not _events(log_dir)


# ─── Мост logging ────────────────────────────────────────────────────────────
def test_logging_bridge(log_dir):
    root = logging.getLogger()
    added_before = [h for h in root.handlers if isinstance(h, action_log._ActionLogHandler)]
    for h in added_before:
        root.removeHandler(h)
    try:
        action_log.install_logging_bridge()
        action_log.install_logging_bridge()  # идемпотентно
        handlers = [h for h in root.handlers if isinstance(h, action_log._ActionLogHandler)]
        assert len(handlers) == 1

        logging.getLogger("backend.test.module").warning("тестовое предупреждение %s", 42)
        logging.getLogger("backend.test.module").info("info не пишется")
        events = [e for e in _events(log_dir) if e["kind"] == "app_log"]
        assert len(events) == 1
        e = events[0]
        assert e["level"] == "WARNING"
        assert e["logger"] == "backend.test.module"
        # ГЛАВНАЯ ДЫРА: текст произвольного logger.warning() из любого модуля
        # backend больше не попадает в вечный журнал дословно.
        assert "message" not in e
        diag = [d for d in _diag(log_dir) if d["kind"] == "app_log"]
        assert len(diag) == 1
        assert diag[0]["message"] == "тестовое предупреждение 42"
        assert diag[0]["eid"] == e["eid"]
    finally:
        for h in [h for h in root.handlers if isinstance(h, action_log._ActionLogHandler)]:
            root.removeHandler(h)


def test_uninstall_logging_bridge(log_dir):
    root = logging.getLogger()
    action_log.install_logging_bridge()
    assert any(isinstance(h, action_log._ActionLogHandler) for h in root.handlers)
    action_log.uninstall_logging_bridge()
    assert not any(isinstance(h, action_log._ActionLogHandler) for h in root.handlers)
    action_log.uninstall_logging_bridge()  # идемпотентно


def test_applog_rate_limit(log_dir, monkeypatch):
    monkeypatch.setattr(cfg, "ACTION_LOG_APPLOG_MAX_PER_MIN", 3, raising=False)
    monkeypatch.setattr(
        action_log, "_APPLOG_WINDOW", {"minute": None, "count": 0, "suppressed": 0},
    )
    handler = action_log._ActionLogHandler(level=logging.WARNING)
    logger = logging.getLogger("backend.test.flood")
    logger.addHandler(handler)
    logger.propagate = False
    try:
        for i in range(10):
            logger.warning("шторм %s", i)
        events = [e for e in _events(log_dir) if e["kind"] == "app_log"]
        # лимит 3/мин: первые 3 записаны, остальные 7 подавлены
        assert len(events) == 3
        assert action_log._APPLOG_WINDOW["suppressed"] == 7
    finally:
        logger.removeHandler(handler)
        logger.propagate = True


def test_logging_bridge_captures_exc_info(log_dir):
    handler = action_log._ActionLogHandler(level=logging.WARNING)
    logger = logging.getLogger("backend.test.exc")
    logger.addHandler(handler)
    logger.propagate = False
    try:
        try:
            raise ValueError("детали ошибки")
        except ValueError:
            logger.exception("поймано")
        events = [e for e in _events(log_dir) if e["kind"] == "app_log"]
        assert len(events) == 1
        assert events[0]["level"] == "ERROR"
        assert "exc" not in events[0]  # traceback — только диагностика
        diag = [d for d in _diag(log_dir) if d["kind"] == "app_log"]
        assert "ValueError" in diag[0]["exc"]
    finally:
        logger.removeHandler(handler)
        logger.propagate = True


# ─── Чтение ──────────────────────────────────────────────────────────────────
def _write_day(log_dir, day, events):
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"actions-{day}.jsonl"
    with open(path, "a", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def test_read_events_filters(log_dir):
    _write_day(log_dir, "2026-07-14", [
        {"ts": "2026-07-14T10:00:00", "kind": "api", "actor": "ivan", "path": "/api/projects", "status": 200},
        {"ts": "2026-07-14T11:00:00", "kind": "api", "actor": "petr", "path": "/api/audit/x/full-audit", "status": 500},
    ])
    _write_day(log_dir, "2026-07-15", [
        {"ts": "2026-07-15T09:00:00", "kind": "pipeline", "project_id": "ЭОМ/К1", "stage": "excel", "status": "done"},
        {"ts": "2026-07-15T09:30:00", "kind": "pipeline", "project_id": "ЭОМ/К1", "stage": "norm_verify", "status": "error", "error": "сбой"},
    ])

    all_events = action_log.read_events(limit=100)
    assert len(all_events["items"]) == 4
    # новые → старые
    assert all_events["items"][0]["ts"] == "2026-07-15T09:30:00"
    assert all_events["items"][-1]["ts"] == "2026-07-14T10:00:00"

    assert len(action_log.read_events(kind="api")["items"]) == 2
    assert len(action_log.read_events(actor="ivan")["items"]) == 1

    errors = action_log.read_events(errors_only=True)["items"]
    assert {e.get("status") for e in errors} == {500, "error"}

    q = action_log.read_events(q="full-audit")["items"]
    assert len(q) == 1 and q[0]["actor"] == "petr"

    day1 = action_log.read_events(date_from="2026-07-15")["items"]
    assert len(day1) == 2
    day0 = action_log.read_events(date_to="2026-07-14")["items"]
    assert len(day0) == 2

    page = action_log.read_events(limit=2)
    assert page["truncated"] is True
    page2 = action_log.read_events(limit=2, offset=2)
    assert [e["ts"] for e in page2["items"]] == ["2026-07-14T11:00:00", "2026-07-14T10:00:00"]


def test_read_events_skips_broken_lines(log_dir):
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "actions-2026-07-15.jsonl").write_text(
        '{"ts": "1", "kind": "api"}\nНЕ JSON\n{"ts": "2", "kind": "api"}\n',
        encoding="utf-8",
    )
    assert len(action_log.read_events()["items"]) == 2


def test_readers_survive_broken_utf8(log_dir):
    """Оборванный посреди многобайтового символа файл не кладёт чтение."""
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "actions-2026-07-15.jsonl"
    with open(path, "wb") as f:
        f.write(b'{"ts": "1", "kind": "api", "status": 200}\n')
        f.write('{"ts": "2", "kind": "api", "path": "/про'.encode("utf-8")[:-1])
    assert len(action_log.read_events()["items"]) == 1
    assert action_log.stats(days=366)["totals"]["events"] == 1


def test_stats_days_are_calendar_days(log_dir):
    """stats(days=N) — последние N календарных дней, а не N файлов."""
    from datetime import date, timedelta
    old_day = (date.today() - timedelta(days=30)).isoformat()
    _write_day(log_dir, old_day, [{"ts": "t", "kind": "api", "status": 200}])
    _write_day(log_dir, date.today().isoformat(), [{"ts": "t", "kind": "api", "status": 200}])
    result = action_log.stats(days=3)
    assert [d["day"] for d in result["days"]] == [date.today().isoformat()]
    assert result["totals"]["events"] == 1


def test_stats(log_dir):
    # День БЕРЁТСЯ ОТ СЕГОДНЯ: stats(days=7) смотрит последние 7 КАЛЕНДАРНЫХ
    # дней, поэтому прибитая в код дата делает тест бомбой замедленного
    # действия — ровно так он и падал до этой правки.
    from datetime import date
    today = date.today().isoformat()
    _write_day(log_dir, today, [
        {"ts": "t", "kind": "api", "actor": "ivan", "method": "POST", "path": "/api/x", "status": 200},
        {"ts": "t", "kind": "api", "actor": "ivan", "method": "GET", "path": "/api/x", "status": 404},
        {"ts": "t", "kind": "pipeline", "project_id": "ЭОМ/К1", "stage": "excel", "status": "error"},
    ])
    result = action_log.stats(days=7)
    assert result["totals"]["events"] == 3
    assert result["totals"]["errors"] == 2
    day = result["days"][0]
    assert day["day"] == today
    assert day["by_kind"] == {"api": 2, "pipeline": 1}
    assert day["actors"] == {"ivan": 2}
    assert day["pipeline_errors"] == {"ЭОМ/К1:excel": 1}


# ─── Контракт redaction и разделение каналов (P-13) ──────────────────────────
# Проверяется ровно то, что требует принцип: чувствительные значения,
# query-параметры, presigned URL, cookies, токены, секреты и ПДн не попадают НИ
# В ОДИН канал по умолчанию; текст исключения и traceback проходят ту же
# обработку; durable audit имеет фиксированную схему-allowlist.

SECRETS = {
    "presigned_url": (
        "PUT https://s3.example.com/bucket/report.pdf"
        "?X-Amz-Credential=AKIAIOSFODNN7EXAMPLE%2F20260828%2Fus-east-1"
        "&X-Amz-Signature=1a2b3c4dE5f6A7b8C9d0e1f2A3b4C5d6E7f8A9b0c1d2E3f4",
        "1a2b3c4dE5f6A7b8C9d0e1f2A3b4C5d6E7f8A9b0c1d2E3f4",
    ),
    "cookie": (
        "заголовок Cookie: portal_session=eyJhbGciOiJIUzI1NiJ9."
        "eyJzdWIiOiJpdmFuIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV",
        "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV",
    ),
    "bearer": (
        "Authorization: Bearer sk-ant-api03-AbCdEf1234GhIjKl5678",
        "sk-ant-api03-AbCdEf1234GhIjKl5678",
    ),
    "token_kv": ("не смог обновить token=Sup3rSecretValue42 у воркера",
                 "Sup3rSecretValue42"),
    "password_kv": ('конфиг DB_PASSWORD="Pa55wordZZ" не подошёл', "Pa55wordZZ"),
    "opaque_blob": ("ключ AKIAIOSFODNN7EXAMPLEwJalrXUtnFEMIK7MDENGbPxRfiCY",
                    "AKIAIOSFODNN7EXAMPLEwJalrXUtnFEMIK7MDENGbPxRfiCY"),
    "email": ("письмо не ушло на ivan.petrov@example.com", "ivan.petrov@example.com"),
}


@pytest.mark.parametrize("case", sorted(SECRETS))
def test_secret_in_message_reaches_neither_channel(log_dir, case):
    """Секрет в message моста логгера не ложится на диск ни в одном канале."""
    text, secret = SECRETS[case]
    action_log.log_event("app_log", level="ERROR", logger="backend.x", message=text)
    assert secret not in _raw_text(log_dir), case
    assert "[redacted" in _diag(log_dir)[0]["message"], case


@pytest.mark.parametrize("case", sorted(SECRETS))
def test_secret_in_error_and_traceback_reaches_neither_channel(log_dir, case):
    """Текст исключения и traceback — непроверенный ввод, обработка та же."""
    text, secret = SECRETS[case]
    action_log.log_event("api", method="GET", route="/api/x", status=500,
                         error=f"RuntimeError: {text}",
                         traceback=f"Traceback (most recent call last):\n  {text}\n")
    assert secret not in _raw_text(log_dir), case


def test_secret_in_query_reaches_neither_channel(mw_client, log_dir):
    """Секрет в query-строке HTTP-запроса не ложится на диск."""
    mw_client.get("/api/ok", params={"access_token": "Sup3rSecretValue42",
                                     "q": "коммерческая тайна", "limit": "50"})
    raw = _raw_text(log_dir)
    assert "Sup3rSecretValue42" not in raw
    assert "коммерческая тайна" not in raw
    query = _diag(log_dir)[0]["query"]
    # Имя параметра — из схемы API, его видно; значение — только по allowlist.
    assert "access_token=[redacted]" in query
    assert "q=[redacted]" in query
    assert "limit=50" in query


def test_presigned_url_in_query_loses_its_signature(mw_client, log_dir):
    mw_client.get("/api/ok", params={
        "src": "https://s3.example.com/b/o.pdf?X-Amz-Signature=DEADbeef1234",
    })
    assert "DEADbeef1234" not in _raw_text(log_dir)


def test_traceback_is_truncated_and_anonymized(log_dir):
    """traceback усечён и обезличен, но хвост с текстом исключения сохранён."""
    from backend.app.core import config as real_cfg

    frame = (f'  File "{real_cfg.ROOT_DIR}/backend/app/services/x.py", '
             f'line 7, in run\n    raise ValueError\n')
    raw = "Traceback (most recent call last):\n" + frame * 200 + "ValueError: ХВОСТ\n"
    action_log.log_event("app_log", level="ERROR", logger="backend.x", exc=raw)

    exc = _diag(log_dir)[0]["exc"]
    assert len(exc) < len(raw) and len(exc) <= 3000       # усечён
    assert "усечено" in exc                                # усечение помечено
    assert "ValueError: ХВОСТ" in exc                      # хвост сохранён
    assert str(real_cfg.ROOT_DIR) not in exc               # обезличен
    assert "<root>/backend/app/services/x.py" in exc


def test_absolute_paths_are_anonymized_everywhere(log_dir):
    action_log.log_event("pipeline", project_id="AR/K1", stage="excel", status="error",
                         error="нет файла /root/projects/secret-install/projects/AR/x.pdf")
    raw = _raw_text(log_dir)
    assert "/root/projects/secret-install" not in raw
    assert "<home>" in _diag(log_dir)[0]["error"]


def test_durable_audit_holds_only_allowlisted_fields(log_dir):
    """Фиксированная схема: в durable audit нет ничего сверх allowlist."""
    action_log.log_event(
        "api", actor="ivan", method="GET", route="/api/audit/{project_id}/log",
        path="/api/audit/AR/13АВ-РД/log", query="q=секрет", project_id="AR/13АВ-РД",
        status=200, dur_ms=42, ip="10.20.30.40", error="боль", traceback="стек",
    )
    e = _events(log_dir)[0]
    allowed = set(action_log._AUDIT_FIELDS) | {"ts", "kind", "eid"}
    assert set(e) <= allowed, set(e) - allowed
    assert set(e) == {"ts", "kind", "eid", "actor", "method", "route",
                      "project_id", "status"}


def test_unknown_field_does_not_leak_into_durable_audit(log_dir):
    """Поле, которого нет в allowlist, в вечный журнал не попадает никогда."""
    action_log.log_event("api", status=200, route="/api/x",
                         customer_inn="7701234567", free_text="произвольный ввод")
    e = _events(log_dir)[0]
    assert "customer_inn" not in e and "free_text" not in e
    # но и не теряется молча — уходит в диагностику под redaction
    d = _diag(log_dir)[0]
    assert d["customer_inn"] == "7701234567"
    assert d["free_text"] == "произвольный ввод"


def test_unknown_field_with_sensitive_name_is_redacted(log_dir):
    action_log.log_event("worker", event="x", api_key="AbCd1234", session_id="s-42")
    raw = _raw_text(log_dir)
    assert "AbCd1234" not in raw and "s-42" not in raw
    d = _diag(log_dir)[0]
    assert d["api_key"] == "[redacted]" and d["session_id"] == "[redacted]"


def test_audit_allowlist_extends_only_explicitly(log_dir, monkeypatch):
    """«Попадание регулируется явным allowlist поля, а не отсутствием запрета»."""
    action_log.log_event("worker", event="x", tenant="ООО Ромашка")
    assert "tenant" not in _events(log_dir)[0]

    monkeypatch.setattr(cfg, "ACTION_LOG_AUDIT_EXTRA_FIELDS", ["tenant"], raising=False)
    action_log.log_event("worker", event="y", tenant="ООО Ромашка")
    assert _events(log_dir)[1]["tenant"] == "ООО Ромашка"


def test_worker_security_event_stays_in_durable_audit(log_dir):
    """Отказ в праве — событие безопасности: коды остаются в вечном журнале."""
    action_log.log_event(
        "worker", event="permission_denied", actor="anonymous", severity="security",
        path="/api/v1/worker/jobs", method="POST", required_permission="worker.claim",
        reason="unknown_token", role="worker", auth_enabled=True,
    )
    e = _events(log_dir)[0]
    assert e["event"] == "permission_denied" and e["severity"] == "security"
    assert e["required_permission"] == "worker.claim" and e["reason"] == "unknown_token"
    assert e["role"] == "worker" and e["auth_enabled"] is True
    assert "path" not in e                       # сырой путь — диагностика
    assert _diag(log_dir)[0]["path"] == "/api/v1/worker/jobs"


def test_ip_is_reduced_to_subnet(log_dir):
    """IP — ПДн: в журнале остаётся подсеть, а не хост."""
    action_log.log_event("api", route="/api/x", status=200, ip="10.20.30.40")
    assert "10.20.30.40" not in _raw_text(log_dir)
    assert _diag(log_dir)[0]["ip"] == "10.20.30.x"


def test_middleware_separates_route_from_path(mw_client, log_dir):
    """route (шаблон) → durable audit, сырой path с идентификаторами → диагностика."""
    mw_client.get("/api/projects/ЭОМ/13АВ-РД-ЭМ-К1/card")
    e = _events(log_dir)[0]
    assert e["route"] == "/api/projects/{project_id:path}/card"
    assert e["project_id"] == "ЭОМ/13АВ-РД-ЭМ-К1"   # отдельным структурным полем
    assert "path" not in e
    assert _diag(log_dir)[0]["path"] == "/api/projects/ЭОМ/13АВ-РД-ЭМ-К1/card"


def test_diag_channel_can_be_disabled(log_dir, monkeypatch):
    """Максимум приватности: диагностика не пишется, durable audit цел."""
    monkeypatch.setattr(cfg, "ACTION_LOG_DIAG_ENABLED", False, raising=False)
    action_log.log_event("api", route="/api/x", status=500, error="боль", ip="1.2.3.4")
    assert not list(log_dir.glob("diag-*.jsonl"))
    e = _events(log_dir)[0]
    assert e["status"] == 500 and "error" not in e
    assert "eid" not in e  # связывать не с чем


def test_redaction_kill_switch_restores_legacy_behaviour(log_dir, monkeypatch):
    """ACTION_LOG_REDACTION=0 — аварийный откат к прежнему поведению."""
    monkeypatch.setattr(cfg, "ACTION_LOG_REDACTION", False, raising=False)
    action_log.log_event("api", actor="ivan", path="/api/x", query="token=secret",
                         status=200, ip="10.20.30.40")
    assert not list(log_dir.glob("diag-*.jsonl"))
    e = _events(log_dir)[0]
    assert e["path"] == "/api/x" and e["query"] == "token=secret"
    assert e["ip"] == "10.20.30.40"


def test_diag_channel_has_shorter_retention(log_dir, monkeypatch):
    """Непроверенный ввод не должен лежать 180 дней наравне с audit."""
    from datetime import date, timedelta
    monkeypatch.setattr(cfg, "ACTION_LOG_RETENTION_DAYS", 180, raising=False)
    monkeypatch.setattr(cfg, "ACTION_LOG_DIAG_RETENTION_DAYS", 14, raising=False)
    log_dir.mkdir(parents=True)
    old = (date.today() - timedelta(days=30)).isoformat()
    (log_dir / f"actions-{old}.jsonl").write_text("{}\n", encoding="utf-8")
    (log_dir / f"diag-{old}.jsonl").write_text("{}\n", encoding="utf-8")
    action_log.log_event("system", event="test")   # смена ключа → чистка
    assert (log_dir / f"actions-{old}.jsonl").exists()      # 30 < 180 — жив
    assert not (log_dir / f"diag-{old}.jsonl").exists()     # 30 > 14 — удалён


def test_metrics_labels_carry_no_identifiers(log_dir):
    """Канал метрик: labels только method × route × status, гистограмма dur_ms."""
    action_log.reset_metrics()
    for status, dur in ((200, 12), (200, 900), (500, 5)):
        action_log.log_event("api", method="GET", route="/api/audit/{project_id}/log",
                             path="/api/audit/AR/13АВ-РД/log", project_id="AR/13АВ-РД",
                             status=status, dur_ms=dur, ip="10.20.30.40")
    snap = action_log.metrics_snapshot()
    assert snap["events"]["api"] == 3
    labels = {(r["method"], r["route"], r["status"]) for r in snap["http"]}
    assert labels == {("GET", "/api/audit/{project_id}/log", 200),
                      ("GET", "/api/audit/{project_id}/log", 500)}
    flat = json.dumps(snap, ensure_ascii=False)
    assert "13АВ-РД" not in flat and "10.20.30" not in flat
    ok = next(r for r in snap["http"] if r["status"] == 200)
    assert ok["count"] == 2 and ok["buckets"]["25"] == 1 and ok["buckets"]["1000"] == 1
    action_log.reset_metrics()


def test_metrics_cardinality_is_bounded(log_dir):
    action_log.reset_metrics()
    for i in range(action_log._METRICS_MAX_SERIES + 20):
        action_log.log_event("api", method="GET", route=f"/api/r{i}", status=200)
    snap = action_log.metrics_snapshot()
    assert snap["series"] <= action_log._METRICS_MAX_SERIES + 1
    assert any(r["route"] == "<over-cardinality>" for r in snap["http"])
    action_log.reset_metrics()


def test_diag_channel_is_readable_and_audit_stays_default(log_dir):
    """read_events()/stats() по умолчанию читают durable audit."""
    action_log.log_event("api", actor="ivan", route="/api/x", status=500,
                         path="/api/x", error="боль")
    audit = action_log.read_events()["items"]
    assert len(audit) == 1 and "error" not in audit[0]
    diag = action_log.read_events(channel="diag")["items"]
    assert len(diag) == 1 and diag[0]["error"] == "боль"
    assert diag[0]["eid"] == audit[0]["eid"]
    assert action_log.stats(days=1)["totals"]["events"] == 1
    assert action_log.stats(days=1, channel="diag")["totals"]["events"] == 1


def test_reader_still_understands_pre_split_files(log_dir):
    """Обратная совместимость чтения: файлы до разделения каналов читаются."""
    from datetime import date
    today = date.today().isoformat()
    _write_day(log_dir, today, [
        {"ts": "t", "kind": "api", "actor": "ivan", "method": "GET",
         "path": "/api/audit/AR/K1/full-audit", "status": 500,
         "error": "старый формат", "traceback": "стек"},
    ])
    events = action_log.read_events()["items"]
    assert events[0]["path"] == "/api/audit/AR/K1/full-audit"
    assert events[0]["error"] == "старый формат"
    assert action_log.read_events(errors_only=True)["items"]
    assert action_log.read_events(q="full-audit")["items"]
    day = action_log.stats(days=1)["days"][0]
    assert day["top_paths"] == [("GET /api/audit/AR/K1/full-audit", 1)]


def test_redaction_never_breaks_the_main_flow(log_dir):
    """Fail-soft: незнакомый тип значения не роняет ни журнал, ни вызывающего."""
    class Boom:
        def __str__(self):
            raise RuntimeError("не сериализуюсь")

    action_log.log_event("api", route="/api/x", status=200, weird=Boom())
    action_log.log_event("api", route="/api/x", status=200, actor=Boom())
    # событие могло не записаться, но исключение наружу не вышло
    assert isinstance(_events(log_dir), list)


# ─── Короткие секреты без контекста «имя=значение» ───────────────────────────
# Блоб-правило ловит по длине (40+) и энтропии. Ключ вида AKIA + 16 заглавных
# (всего 20 символов) под него не подпадает: без правила по вендорскому
# префиксу он протекал в diagnostic 20 раз из 20.
CREDENTIALS = {
    "aws_access_key": "AKIAIOSFODNN7EXAMPLE",              # 20 символов — короче порога блоба
    "aws_session_key": "ASIAY34FZKBOKMUTVV7A",
    "github_pat": "ghp_16C7e42F292c6912E7710c838347Ae178B4a",
    "github_fine_grained": "github_pat_11ABCDEFG0abcdefghijkl_qwertyuiop",
    "slack_bot": "xoxb-123456789012-1234567890123-AbCdEfGhIjKlMnOpQrSt",
    "slack_user": "xoxp-000000000000-0000000000000-ZzYyXxWwVvUuTtSsRrQq",
    "openrouter": "sk-or-v1-0123456789abcdef0123456789abcdef",
    "anthropic": "sk-ant-api03-AbCdEf1234GhIjKlMnOp5678QrStUvWx",
    "google": "AIzaSyD-9tSrke72PouQMnMX-a7eZSW0jkFMBWY",
    "gitlab": "glpat-ABCdef123456789012345",
}


@pytest.mark.parametrize("case", sorted(CREDENTIALS))
def test_credential_prefix_is_redacted_without_key_name(log_dir, case):
    """Учётные данные без обёртки «имя=значение» и без нужной длины/энтропии."""
    key = CREDENTIALS[case]
    action_log.log_event("app_log", level="ERROR", logger="backend.x",
                         message=f"не смог авторизоваться, ключ {key}")
    action_log.log_event("api", method="GET", route="/api/x", status=500,
                         error=f"AuthError: {key}",
                         traceback=f"  raise AuthError({key})\n")
    assert key not in _raw_text(log_dir), case
    assert "[redacted" in _diag(log_dir)[0]["message"], case


def test_long_credential_is_redacted_whole_not_just_prefix(log_dir):
    """Порядок правил: блоб-правило раньше префиксного.

    AKIA<id><secret> одним куском должен исчезнуть целиком. Сработай префиксное
    правило первым — оно отрезало бы только голову и оставило секретный хвост.
    """
    pair = "AKIAIOSFODNN7EXAMPLEwJalrXUtnFEMIK7MDENGbPxRfiCY"
    action_log.log_event("app_log", level="ERROR", logger="backend.x", message=pair)
    raw = _raw_text(log_dir)
    assert pair not in raw
    assert "wJalrXUtnFEMIK7MDENGbPxRfiCY" not in raw   # хвост тоже
    assert _diag(log_dir)[0]["message"] == "[redacted:blob]"


@pytest.mark.parametrize("text", [
    "/api/audit/AR/13АВ-РД/log",
    "stage skip-analysis завершён",
    "регион ASIA обработан",
    "проверка sk-без-цифр-совсем-длинная-строка",
    "обычный русский текст без секретов",
])
def test_credential_rule_does_not_eat_ordinary_text(text):
    """Ложные срабатывания: единственный неоднозначный префикс sk- требует цифру."""
    assert action_log._scrub(text) == text


# ─── Суточный бюджет байт ────────────────────────────────────────────────────
def test_day_budget_is_shared_by_both_channels(log_dir, monkeypatch):
    """ACTION_LOG_MAX_DAY_BYTES — потолок НА ОБА канала суммарно.

    Отдельный бюджет на канал молча удвоил бы настроенный оператором потолок.
    """
    monkeypatch.setattr(cfg, "ACTION_LOG_MAX_DAY_BYTES", 400, raising=False)
    # Каждое событие пишет две строки: audit (тонкая) + diag (толстая).
    for i in range(20):
        action_log.log_event("api", method="GET", route="/api/x", status=200,
                             path="/api/x/" + "п" * 60, ip="10.1.2.3")
    written = sum(p.stat().st_size for p in log_dir.glob("*.jsonl"))
    assert written <= 400 + 200, written  # 200 — запас на маркер day_cap_reached
    # Обрыв виден в обоих файлах, которые читают.
    assert any(e.get("event") == "day_cap_reached" for e in _events(log_dir))
    assert any(e.get("event") == "day_cap_reached" for e in _diag(log_dir))


def test_durable_audit_wins_at_the_budget_boundary(log_dir, monkeypatch):
    """На границе бюджета выигрывает audit: он пишется первым."""
    monkeypatch.setattr(cfg, "ACTION_LOG_MAX_DAY_BYTES", 200, raising=False)
    action_log.log_event("api", method="GET", route="/api/x", status=200,
                         path="/api/x", ip="10.1.2.3")
    audit = [e for e in _events(log_dir) if e["kind"] == "api"]
    assert len(audit) == 1                      # запись durable audit прошла
    assert not [d for d in _diag(log_dir) if d["kind"] == "api"]   # диагностика — нет


def test_day_budget_survives_restart_mid_day(log_dir, monkeypatch):
    """Рестарт посреди дня не обнуляет потолок: бюджет считается по файлам."""
    monkeypatch.setattr(cfg, "ACTION_LOG_MAX_DAY_BYTES", 300, raising=False)
    action_log.log_event("system", event="a" * 150)
    # Эмуляция рестарта процесса: состояние писателя сброшено, файлы на месте.
    monkeypatch.setattr(action_log, "_DAY_BUDGET", {"key": None, "bytes": 0})
    monkeypatch.setattr(action_log, "_LAST_WRITE_KEY", {})
    action_log.log_event("system", event="b" * 150)
    events = _events(log_dir)
    assert [e["event"] for e in events][:1] == ["a" * 150]
    assert events[-1]["event"] == "day_cap_reached"
