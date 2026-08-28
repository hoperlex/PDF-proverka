"""Интеграционные тесты журнала действий на полном приложении.

Проверяют: middleware пишет события реальных запросов, /api/action-log отдаёт
их с фильтрами, /api/action-log/stats считает сводку. ACTION_LOG_DIR изолирован
autouse-фикстурой _isolate_action_log (tmp_path / "actions_log").

Журнал разделён на каналы (P-13): durable audit — actions-*.jsonl (фиксированная
схема-allowlist), diagnostic — diag-*.jsonl (непроверенный ввод после redaction).
GET /api/action-log читает durable audit — так же, как читал до разделения."""
import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from backend.app.main import app
    # Без context-manager → lifespan (pipeline manager) не запускается.
    return TestClient(app, raise_server_exceptions=False)


def _read(tmp_path, pattern):
    log_dir = tmp_path / "actions_log"
    events = []
    if log_dir.exists():
        for path in sorted(log_dir.glob(pattern)):
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    events.append(json.loads(line))
    return events


def _events(tmp_path):
    """Durable audit."""
    return _read(tmp_path, "actions-*.jsonl")


def _diag(tmp_path):
    """Диагностический канал."""
    return _read(tmp_path, "diag-*.jsonl")


def test_middleware_logs_real_requests(client, tmp_path):
    resp = client.get("/api/projects")
    assert resp.status_code == 200
    # durable audit держит ШАБЛОН маршрута; сырой path — в диагностике.
    api_events = [e for e in _events(tmp_path) if e["kind"] == "api"]
    assert any(e["route"] == "/api/projects" and e["status"] == 200 for e in api_events)
    assert all("path" not in e for e in api_events)
    assert any(d.get("path") == "/api/projects" for d in _diag(tmp_path))


def test_middleware_skips_api_info_noise(client, tmp_path):
    assert client.get("/api/info").status_code == 200
    assert not [e for e in _events(tmp_path) if e.get("route") == "/api/info"]
    assert not [d for d in _diag(tmp_path) if d.get("path") == "/api/info"]


def test_middleware_logs_404(client, tmp_path):
    assert client.get("/api/definitely-nonexistent-endpoint").status_code == 404
    events = [e for e in _events(tmp_path) if e.get("status") == 404]
    assert len(events) == 1
    # Маршрут не сматчился — шаблона нет, и выдумывать его durable audit не
    # станет: сам путь несопоставленного запроса живёт в диагностике.
    assert "route" not in events[0] and "path" not in events[0]
    diag = [d for d in _diag(tmp_path) if d.get("eid") == events[0]["eid"]]
    assert diag[0]["path"] == "/api/definitely-nonexistent-endpoint"


def test_action_log_api_roundtrip(client, tmp_path):
    from backend.app.core import action_log

    action_log.log_event("pipeline", project_id="ЭОМ/К1", stage="excel",
                         status="error", error="сбой отчёта")
    action_log.log_event("api", actor="ivan", method="POST",
                         route="/api/audit/{project_id}/full-audit",
                         path="/api/audit/ЭОМ/К1/full-audit", status=200, dur_ms=15)

    resp = client.get("/api/action-log", params={"limit": 100})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    kinds = [e["kind"] for e in data["items"]]
    assert "pipeline" in kinds and "api" in kinds
    assert "persons" in data

    # Фильтр ошибок работает по СТАТУСУ, а не по тексту ошибки: pipeline error
    # попадает, api 200 — нет. Сам текст ошибки живёт в диагностике.
    resp = client.get("/api/action-log", params={"errors_only": "true", "kind": "pipeline"})
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["stage"] == "excel" and items[0]["status"] == "error"
    assert "error" not in items[0]
    assert [d["error"] for d in _diag(tmp_path) if d["eid"] == items[0]["eid"]] \
        == ["сбой отчёта"]

    # Поиск подстрокой — по шаблону маршрута в durable audit.
    resp = client.get("/api/action-log", params={"q": "full-audit"})
    assert len(resp.json()["items"]) == 1


def test_action_log_stats_endpoint(client, tmp_path):
    from backend.app.core import action_log

    action_log.log_event("api", actor="ivan", method="GET", path="/api/x", status=200)
    resp = client.get("/api/action-log/stats", params={"days": 3})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["totals"]["events"] >= 1
    assert data["days"]


def test_action_log_query_validation(client):
    assert client.get("/api/action-log", params={"limit": 0}).status_code == 422
    assert client.get("/api/action-log", params={"limit": 5000}).status_code == 422
    # Кривые даты — явный 422, а не тихий пустой/неотфильтрованный результат.
    assert client.get("/api/action-log", params={"date_from": "2026-7-5"}).status_code == 422
    assert client.get("/api/action-log", params={"date_to": "вчера"}).status_code == 422
    assert client.get("/api/action-log", params={"date_from": "2026-07-05"}).status_code == 200


def test_secret_in_real_request_reaches_no_file(client, tmp_path):
    """Сквозная проверка на полном приложении: секрет из query не ложится на диск."""
    client.get("/api/projects", params={
        "access_token": "Sup3rSecretValue42",
        "src": "https://s3.example.com/b/o.pdf?X-Amz-Signature=DEADbeef1234",
        "q": "коммерческая тайна",
        "limit": "5",
    })
    log_dir = tmp_path / "actions_log"
    raw = "\n".join(p.read_text(encoding="utf-8") for p in sorted(log_dir.glob("*.jsonl")))
    assert "Sup3rSecretValue42" not in raw
    assert "DEADbeef1234" not in raw
    assert "коммерческая тайна" not in raw
    query = next(d["query"] for d in _diag(tmp_path) if d.get("query"))
    assert "access_token=[redacted]" in query and "limit=5" in query


def test_root_logger_bridge_does_not_reach_durable_audit(client, tmp_path):
    """Мост root-логгера: logger.error() любого модуля больше не пишет в вечный
    журнал дословно — текст уходит только в диагностику, после redaction."""
    import logging

    from backend.app.core import action_log

    action_log.uninstall_logging_bridge()
    action_log.install_logging_bridge()
    try:
        logging.getLogger("backend.some.module").error(
            "не смог выгрузить: token=Sup3rSecretValue42"
        )
    finally:
        action_log.uninstall_logging_bridge()

    audit = [e for e in _events(tmp_path) if e["kind"] == "app_log"]
    assert len(audit) == 1
    assert audit[0]["logger"] == "backend.some.module" and audit[0]["level"] == "ERROR"
    assert "message" not in audit[0]
    raw = "\n".join(
        p.read_text(encoding="utf-8")
        for p in sorted((tmp_path / "actions_log").glob("*.jsonl"))
    )
    assert "Sup3rSecretValue42" not in raw
    diag = [d for d in _diag(tmp_path) if d["kind"] == "app_log"]
    assert diag[0]["message"] == "не смог выгрузить: token=[redacted]"
