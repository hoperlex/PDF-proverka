"""Общие помощники тестов распределённых воркеров.

`SyncASGITransport` позволяет гонять НАСТОЯЩЕГО синхронного агента против
НАСТОЯЩЕГО FastAPI-приложения без сокетов и портов: каждый запрос исполняется
ASGI-приложением в собственном event loop.

Зачем свой транспорт, а не httpx.ASGITransport: тот асинхронный (aclose), а
агент по проекту синхронный — он живёт в потоках, а не в event loop.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from typing import Any

import httpx


def issue_test_registration_token(settings, instance_id: str, *, ttl_sec: int = 300) -> str:
    """Issue the same scoped token as production bootstrap, for test fixtures."""
    from backend.app.services.worker_bootstrap import store
    from backend.app.services.worker_bootstrap.models import (
        BootstrapOperation,
        BootstrapRequest,
    )

    nonce = uuid.uuid4().hex
    request = BootstrapRequest(
        host=f"worker-{nonce[:8]}.example",
        ssh_user="audit-worker",
        ssh_auth_ref=f"secret-store:test-{nonce}",
        expected_host_fingerprint="SHA256:" + "A" * 32,
        install_root=f"/opt/audit-worker/releases/test-{nonce[:8]}",
        center_url="https://auditmanager.app",
        display_name="test worker",
        bootstrap_instance_id=instance_id,
    )
    session = store.create_session(
        operation=BootstrapOperation.INSTALL,
        request=request,
        idempotency_key=f"test-{nonce}",
        settings=settings,
    )
    return store.issue_registration_token(
        session["session_id"],
        expected_instance_id=instance_id,
        ttl_sec=ttl_sec,
        settings=settings,
    )


class SyncASGITransport(httpx.BaseTransport):
    """Синхронный мост к ASGI-приложению."""

    def __init__(self, app: Any):
        self.app = app

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        body = request.read()
        rebuilt = httpx.Request(
            request.method,
            request.url,
            headers=request.headers,
            content=body,
        )

        async def run() -> httpx.Response:
            transport = httpx.ASGITransport(app=self.app)
            response = await transport.handle_async_request(rebuilt)
            try:
                payload = await response.aread()
            finally:
                await response.aclose()
            return httpx.Response(
                response.status_code,
                headers=response.headers,
                content=payload,
                request=request,
            )

        return asyncio.run(run())

    def close(self) -> None:  # httpx.Client.close() зовёт именно это
        return None


def make_center_app():
    """Приложение центра только с роутерами подсистемы (без остального портала)."""
    from fastapi import FastAPI

    from backend.app.api.routers import audit_worker_agent, audit_workers_admin

    app = FastAPI()
    app.include_router(audit_workers_admin.status_router)
    app.include_router(audit_worker_agent.router)
    app.include_router(audit_workers_admin.router)
    return app


def make_disabled_center_app():
    """Сборка при ВЫКЛЮЧЕННОМ флаге — ровно как в main.py: только status."""
    from fastapi import FastAPI

    from backend.app.api.routers import audit_workers_admin

    app = FastAPI()
    app.include_router(audit_workers_admin.status_router)
    return app


# ─── Портальная аутентификация и роли подсистемы ─────────────────────────────
# С пред-пайплайнового этапа операторский контур закрыт ролевой моделью, и
# анонимный клиент больше не может ничего изменить. Тесты поэтому ходят так же,
# как настоящий оператор: с портальной session-cookie реального пользователя.
# Отдельного «тестового обхода» нет намеренно — он и был бы той самой дырой,
# которую этот этап закрывает.
ADMIN_USER = "dw-admin"
OPERATOR_USER = "dw-operator"
VIEWER_USER = "dw-viewer"
STRANGER_USER = "dw-stranger"          # аутентифицирован, но роли не имеет
PORTAL_PASSWORD = "dw-test-password"
PORTAL_SECRET = "test-portal-session-secret-0123456789abcdef"

_PASSWORD_HASH: str | None = None


def password_hash() -> str:
    """pbkdf2 считается один раз на процесс: он намеренно медленный."""
    global _PASSWORD_HASH
    if _PASSWORD_HASH is None:
        from backend.app.core import portal_auth

        _PASSWORD_HASH = portal_auth.hash_password(PORTAL_PASSWORD)
    return _PASSWORD_HASH


def enable_portal_roles(
    monkeypatch,
    *,
    admins: tuple[str, ...] = (ADMIN_USER,),
    operators: tuple[str, ...] = (OPERATOR_USER,),
    viewers: tuple[str, ...] = (VIEWER_USER,),
    users: tuple[str, ...] = (ADMIN_USER, OPERATOR_USER, VIEWER_USER, STRANGER_USER),
) -> None:
    """Включить портальную аутентификацию и роли подсистемы для теста."""
    from backend.app.services.distributed_workers import authorization

    monkeypatch.setenv("PORTAL_AUTH_ENABLED", "true")
    monkeypatch.setenv(
        "PORTAL_AUTH_USERS",
        ",".join(f"{name}:{password_hash()}" for name in users),
    )
    monkeypatch.setenv("PORTAL_SESSION_SECRET", PORTAL_SECRET)
    monkeypatch.setenv(authorization.ENV_ADMINS, ",".join(admins))
    monkeypatch.setenv(authorization.ENV_OPERATORS, ",".join(operators))
    monkeypatch.setenv(authorization.ENV_VIEWERS, ",".join(viewers))


def portal_role_env(
    *,
    admins: tuple[str, ...] = (ADMIN_USER,),
    operators: tuple[str, ...] = (OPERATOR_USER,),
    viewers: tuple[str, ...] = (VIEWER_USER,),
    users: tuple[str, ...] = (ADMIN_USER, OPERATOR_USER, VIEWER_USER, STRANGER_USER),
) -> dict[str, str]:
    """Те же переменные окружения — для ОТДЕЛЬНОГО процесса (uvicorn, smoke)."""
    from backend.app.services.distributed_workers import authorization

    return {
        "PORTAL_AUTH_ENABLED": "true",
        "PORTAL_AUTH_USERS": ",".join(f"{n}:{password_hash()}" for n in users),
        "PORTAL_SESSION_SECRET": PORTAL_SECRET,
        authorization.ENV_ADMINS: ",".join(admins),
        authorization.ENV_OPERATORS: ",".join(operators),
        authorization.ENV_VIEWERS: ",".join(viewers),
    }


def session_cookie(username: str) -> str:
    """Настоящий подписанный токен сессии портала (тот же код, что в проде)."""
    from backend.app.core import portal_auth

    return portal_auth.issue_token(username, portal_auth.get_settings())


def portal_client(app, *, username: str = ADMIN_USER, base_url: str = "http://center"):
    """httpx-клиент с сессией конкретного пользователя и заголовком намерения."""
    import httpx

    from backend.app.core import portal_auth

    settings = portal_auth.get_settings()
    client = httpx.Client(
        transport=SyncASGITransport(app),
        base_url=base_url,
        headers={"X-Requested-With": "audit-workers"},
    )
    client.cookies.set(settings.cookie_name, session_cookie(username))
    return client


# ─── Опорный хост для тестов жизненного цикла процессов ──────────────────────
#: Число ядер и загрузка «опорного» хоста, которые видит capacity policy
#: воркера в тестах настоящих процессов. Значения выбраны не «побольше», а по
#: нормативу §3.1 quality/runtime contract: CI-образ `ubuntu-24.04` даёт
#: четыре ядра, а «спокойный» раннер — LA около нуля. Тест обязан наблюдать
#: ОДНУ И ТУ ЖЕ ёмкость на любом хосте, иначе он проверяет не свой предмет.
REFERENCE_HOST_CORES = 4
REFERENCE_HOST_LOADAVG = (0.0, 0.0, 0.0)

_PSUTIL_SHIM = 'raise ImportError("isolated process-lifecycle test")\n'

#: `sitecustomize` подхватывается интерпретатором ЛЮБОГО дочернего процесса,
#: которому этот каталог попал в PYTHONPATH, — то есть агентом, исполнителем и
#: процессом аудита, но НЕ центром: центру каталог не передаётся.
_LOADAVG_SHIM = '''\
"""Опорный хост для дочерних процессов теста (только тесты, не прод).

ЗАЧЕМ. `audit_worker.resource_monitor` считает свободные слоты по телеметрии
хоста, и телеметрия приходит из ДВУХ независимых источников:

  * `psutil` — RAM и своп (`s_ram`);
  * stdlib `os` — `getloadavg()` (`s_la`) и `cpu_count()` (`s_cpu`).

Прежняя изоляция подменяла только ПЕРВЫЙ источник (шим `psutil`), и этого
недостаточно. Измерено на восьмиядерной машине с шимом psutil: при LA5 = 25.8
монитор отдаёт `calculated_free = 0` с `binding_constraint = "s_la"`, потому
что `s_la` считается как LA5/ядро и при значении >= 1.0 срезает ёмкость до
`configured_max - 1`, а при >= 1.5 — до нуля. Гистерезис роста (120 с)
после этого удерживает заниженное значение дольше, чем длится ожидание теста.
Тест «два процесса одновременно» в такой момент не может пройти НИКОГДА, и
дело не в сроке ожидания: центр просто не выдаёт второе задание, потому что
воркер честно объявил один свободный слот.

ЧТО ДЕЛАЕМ. Даём политике ёмкости видеть ОПОРНЫЙ хост вместо живого. Сама
политика не трогается: пороги, гистерезис и формула §17.2 работают как в
проде — им меняется только вход телеметрии, ровно как это уже сделано для
psutil.

ГРАНИЦЫ ПОДМЕНЫ. В дереве `audit_worker` `os.getloadavg` вызывается ровно в
одном месте (`resource_monitor.loadavg`), а `os.cpu_count` — в
`resource_monitor.snapshot` и в справке о хосте `config.py`. Процесс аудита
(`audit_worker/test_process.py`) не использует ни то, ни другое. Пакет
`backend` в дочерних процессах воркера не импортируется. Поэтому подмена
адресует политику ёмкости и ничего кроме неё.
"""
import importlib.util
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))

# Наш файл стоит в PYTHONPATH раньше платформенного sitecustomize и молча
# отменил бы его. Отдаём слово платформе явно, до собственной подмены.
for _entry in list(sys.path):
    if not _entry:
        continue
    try:
        if os.path.abspath(_entry) == _HERE:
            continue
        _candidate = os.path.join(_entry, "sitecustomize.py")
        if not os.path.isfile(_candidate):
            continue
    except OSError:
        continue
    _spec = importlib.util.spec_from_file_location("_platform_sitecustomize", _candidate)
    if _spec is not None and _spec.loader is not None:
        try:
            _spec.loader.exec_module(importlib.util.module_from_spec(_spec))
        except Exception:  # noqa: BLE001 — чужой хук не обязан быть исправным
            pass
    break

_REFERENCE_LOADAVG = {loadavg!r}
_REFERENCE_CORES = {cores!r}

os.getloadavg = lambda: _REFERENCE_LOADAVG
os.cpu_count = lambda: _REFERENCE_CORES
'''


def isolate_host_capacity_policy(shim_dir, *, repo_root) -> str:
    """Отвязать capacity policy воркера от ЖИВОГО состояния этой машины.

    Тесты настоящих процессов доказывают семантику слотов и процессов, а не
    текущее давление на память и не пятиминутную загрузку хоста. Пока хоть
    один вход телеметрии читается «как есть», исход теста — функция от того,
    что ещё крутится на машине; именно так полоса `network` и становилась
    недетерминированной.

    Возвращает значение `PYTHONPATH` для дочерних процессов: каталог шимов
    ПЕРЕД корнем репозитория.
    """
    shim_dir = Path(shim_dir)
    shim_dir.mkdir(parents=True, exist_ok=True)
    (shim_dir / "psutil.py").write_text(_PSUTIL_SHIM, encoding="utf-8")
    (shim_dir / "sitecustomize.py").write_text(
        _LOADAVG_SHIM.format(
            loadavg=REFERENCE_HOST_LOADAVG, cores=REFERENCE_HOST_CORES
        ),
        encoding="utf-8",
    )
    return os.pathsep.join((str(shim_dir), str(repo_root)))
