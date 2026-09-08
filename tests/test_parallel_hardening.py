"""Три вещи, которые ломались бы именно при параллельных проектах.

Каждая безобидна, пока очередь ведёт один проект, и каждая кусается на пяти.

  1. Выгрузка норм-моделей. Кэш e5-large + bge-reranker (~4,3 ГБ) глобальный
     на процесс. Проект, закончивший норм-этап, обнулял его — и остальные
     получали повторную загрузку и десятки секунд простоя на КАЖДОМ чужом
     завершении. Выгружать имеет право только последний уходящий.
  2. Ожидание rate limit. Метод вызывался на каждый job: пять проектов уходили
     в пять независимых ожиданий и после сброса синхронно били в API, снова
     упираясь в лимит. Нужен общий дедлайн и разбежка пробуждений.
  3. Пул потоков под asyncio.to_thread. По умолчанию ~20 на 16 ядрах, и он
     общий с длинными норм-задачами. Выедается — event loop залипает,
     health-проверка молчит, вотчдог убивает живой аудит.

Run: python -m pytest tests/test_parallel_hardening.py -v
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.app.models.audit import AuditJob, AuditStage, JobStatus  # noqa: E402

# Primary lane §5: unit — только память: ни ФС, ни потоков, ни процессов, ни сокетов.
pytestmark = pytest.mark.unit


# ─── 1. Выгрузка норм-моделей ────────────────────────────────────────────────


def _job(pid: str, stage: AuditStage, status=JobStatus.RUNNING) -> AuditJob:
    return AuditJob(
        job_id=f"j-{pid}", project_id=pid, stage=stage,
        status=status, started_at="2026-08-06T00:00:00",
    )


def test_norm_models_released_only_by_last_project(monkeypatch):
    from backend.app.pipeline.stages.norms import runner as norms_runner
    from backend.app.pipeline import manager as mgr_mod

    active = {}
    monkeypatch.setattr(mgr_mod.pipeline_manager, "active_jobs", active)

    # Один проект на норм-этапе — он же и уходит: выгружать можно.
    active.clear()
    active["A"] = _job("A", AuditStage.NORM_VERIFY)
    assert norms_runner.other_projects_on_norm_stage("A") == 0

    # Рядом ещё два проекта на норм-этапе — выгружать НЕЛЬЗЯ.
    active["B"] = _job("B", AuditStage.NORM_VERIFY)
    active["C"] = _job("C", AuditStage.NORM_FIX)
    assert norms_runner.other_projects_on_norm_stage("A") == 2

    # Проекты на других этапах моделями не пользуются — не считаем.
    active.clear()
    active["A"] = _job("A", AuditStage.NORM_VERIFY)
    active["D"] = _job("D", AuditStage.BLOCK_ANALYSIS)
    active["__BATCH__"] = _job("__BATCH__", AuditStage.PREPARE)
    assert norms_runner.other_projects_on_norm_stage("A") == 0

    # Завершённый сосед тоже не в счёт.
    active["E"] = _job("E", AuditStage.NORM_VERIFY, status=JobStatus.COMPLETED)
    assert norms_runner.other_projects_on_norm_stage("A") == 0


def test_norm_stage_count_is_derived_not_counted():
    """Счётчик «на входе +1» протёк бы на первом же early-return.

    У run_norm_verification много ранних return'ов; ручной счётчик после
    любого из них навсегда остался бы > 0, и модели перестали бы выгружаться
    вообще — это профиль OOM-инцидента 01.07. Поэтому считаем по живому
    состоянию очереди, а модуль не должен держать своей изменяемой переменной.
    """
    from backend.app.pipeline.stages.norms import runner as norms_runner

    assert not hasattr(norms_runner, "_ACTIVE_NORM_STAGES"), (
        "вернулся ручной счётчик — он протекает на early-return"
    )


# ─── 2. Согласованное ожидание rate limit ────────────────────────────────────

# Настоящий sleep захвачен ДО любой подмены: fake-sleep уступает через него
# управление циклу, не завися от того, что подменено дальше.
_REAL_SLEEP = asyncio.sleep


class _AsyncioShim:
    """Прокси настоящего asyncio, подменяющий ровно один атрибут — `sleep`.

    Патчить `asyncio.sleep` на самом модуле нельзя: модуль общий на процесс, и
    подмена видна каждой чужой корутине того же прогона. Здесь подменяется
    только ССЫЛКА `manager.asyncio`; всё остальное проксируется в настоящий
    модуль, поэтому конструктор менеджера и прочий код работают как обычно.
    """

    def __init__(self, sleep):
        self.sleep = sleep

    def __getattr__(self, name):
        return getattr(asyncio, name)


class _FakeRunner:
    def __init__(self, reset_sec):
        self._reset_sec = reset_sec

    def parse_rate_limit_reset(self, _text):
        return self._reset_sec


class _FakeScanner:
    def __init__(self, result):
        self._result = result

    def check_rate_limit(self, _pct):
        return dict(self._result)

    def invalidate_cache(self):
        return None


class _FakeWs:
    async def broadcast_to_project(self, *a, **k):
        return None


# Сканер сообщает «лимит уже свободен»: ветка точного времени сброса не должна
# от него зависеть, и тест обязан это доказывать, а не маскировать.
_SCANNER_FREE = {"can_proceed": True, "wait_seconds": 1,
                 "resets_in_text": "1 мин", "usage_pct": 10, "reason": ""}


async def _anoop_log(*a, **k):
    return None


def _isolate_rate_limit(monkeypatch, mgr_mod, mgr, *, reset_sec,
                        stagger_sec=30, check_interval=60):
    """Изолировать эпизод rate limit, не трогая процессные singleton'ы.

    Заменяются ЦЕЛИКОМ ссылки в namespace менеджера, а не методы на общих
    объектах: подмена метода на `global_scanner`/`claude_runner` переживает
    границу теста ровно настолько, насколько успевает отработать undo, и
    именно это делало прежний тест недоказательным.

    Возвращает список снимков опубликованного дедлайна — по одному на каждую
    итерацию ожидания. Длина списка = число пробуждений, и это наблюдаемое
    позволяет отличить возврат по дедлайну от возврата через scanner fallback.
    """
    monkeypatch.setattr(mgr_mod, "claude_runner", _FakeRunner(reset_sec))
    monkeypatch.setattr(mgr_mod, "global_scanner", _FakeScanner(_SCANNER_FREE))
    monkeypatch.setattr(mgr_mod, "ws_manager", _FakeWs())
    monkeypatch.setattr(mgr_mod, "RATE_LIMIT_STAGGER_SEC", stagger_sec)
    monkeypatch.setattr(mgr_mod, "RATE_LIMIT_CHECK_INTERVAL", check_interval)

    seen: list[float] = []

    async def _sleep(_sec):
        seen.append(mgr._rate_limit_deadline)
        # Уступаем циклу настоящим sleep(0): точка доставки отмены сохраняется,
        # но ожидания по стенным часам нет.
        await _REAL_SLEEP(0)
        return None

    monkeypatch.setattr(mgr_mod, "asyncio", _AsyncioShim(_sleep))
    return seen



def test_rate_limit_state_starts_clean():
    from backend.app.pipeline.manager import PipelineManager

    mgr = PipelineManager()
    assert mgr._rate_limit_deadline == 0.0
    assert mgr._rate_limit_waiters == 0


@pytest.mark.asyncio
async def test_rate_limit_waiters_share_deadline_and_stagger(monkeypatch):
    """Второй ждущий наследует дедлайн первого и просыпается позже него."""
    import backend.app.pipeline.manager as mgr_mod
    from backend.app.pipeline.manager import PipelineManager

    mgr = PipelineManager()

    async def _anoop(*a, **k):
        return None

    mgr._log = _anoop
    monkeypatch.setattr(mgr_mod, "ws_manager", _FakeWs())
    monkeypatch.setattr(mgr_mod, "claude_runner", _FakeRunner(600))
    monkeypatch.setattr(mgr_mod, "global_scanner", _FakeScanner(
        {"can_proceed": False, "wait_seconds": 600,
         "resets_in_text": "10 мин", "usage_pct": 95, "reason": "лимит"},
    ))
    monkeypatch.setattr(mgr_mod, "RATE_LIMIT_STAGGER_SEC", 30)

    class _Done(Exception):
        pass

    async def _fake_sleep(_sec):
        # Обрываем ожидание сразу — реально спать в тесте незачем.
        raise _Done()

    # Подменяется ССЫЛКА manager.asyncio, а не общий модуль процесса.
    monkeypatch.setattr(mgr_mod, "asyncio", _AsyncioShim(_fake_sleep))

    logged: list[str] = []

    async def _capture_log(_job, msg, level="info"):
        logged.append(str(msg))

    mgr._log = _capture_log

    # Сосед уже ждёт и знает сброс через час; наш CLI сообщает всего 10 минут.
    import time as _time

    far_deadline = _time.monotonic() + 3600
    mgr._rate_limit_deadline = far_deadline
    mgr._rate_limit_waiters = 1

    with pytest.raises(_Done):
        await mgr._wait_for_rate_limit(
            _job("B", AuditStage.NORM_VERIFY), reason="лимит", cli_output="reset"
        )

    # Дедлайн НЕ опущен до своих 10 минут: просыпаться раньше соседа
    # бессмысленно — сброса ещё не будет.
    assert mgr._rate_limit_deadline >= far_deadline, "общий дедлайн опущен под свой"
    # Второй ждущий получает разбежку, чтобы не стартовать одновременно с первым.
    assert any("разбежка" in m for m in logged), f"нет разбежки в логах: {logged}"
    # Сосед всё ещё ждёт → дедлайн не снимается.
    assert mgr._rate_limit_waiters == 1
    assert mgr._rate_limit_deadline != 0.0


@pytest.mark.asyncio
async def test_rate_limit_waiter_released_when_cancelled_before_wait(monkeypatch):
    """Отмена сразу после регистрации waiter не оставляет лишнего ждущего.

    I5. Между `_rate_limit_waiters += 1` и защищённой областью есть await —
    лог разбежки. Отмена именно там навсегда завышала счётчик: лишний ждущий
    никогда не уходит, поэтому последний реальный waiter не может снять общий
    дедлайн, и следующий эпизод наследует протухшее время сброса. Регистрация
    и `finally` обязаны быть неразделимы.
    """
    import backend.app.pipeline.manager as mgr_mod
    from backend.app.pipeline.manager import PipelineManager

    mgr = PipelineManager()
    _isolate_rate_limit(monkeypatch, mgr_mod, mgr, reset_sec=600, stagger_sec=30)

    async def _log_cancel(_job, msg, level="info"):
        # Отменяем ровно на сообщении о разбежке: это единственный await
        # между регистрацией waiter и входом в защищённую область.
        if "разбежка" in str(msg):
            raise asyncio.CancelledError()
        return None

    mgr._log = _log_cancel

    # Сосед уже ждёт и знает своё время сброса; наш waiter — второй.
    far_deadline = time.monotonic() + 600
    mgr._rate_limit_deadline = far_deadline
    mgr._rate_limit_waiters = 1
    waiters_before = mgr._rate_limit_waiters

    with pytest.raises(asyncio.CancelledError):
        await mgr._wait_for_rate_limit(
            _job("B", AuditStage.NORM_VERIFY), reason="лимит", cli_output="reset"
        )

    assert mgr._rate_limit_waiters == waiters_before, (
        "отменённый waiter не разрегистрирован: счётчик "
        f"{mgr._rate_limit_waiters} вместо {waiters_before}"
    )
    # Сосед всё ещё ждёт, поэтому общий дедлайн снимать нельзя.
    assert mgr._rate_limit_deadline >= far_deadline, "дедлайн живого соседа снят"


@pytest.mark.asyncio
async def test_shared_deadline_contract_across_waiters_and_episodes(monkeypatch):
    """Исполняемый контракт общего дедлайна: I2, I3, I4.

    Прежний тест на этом месте утверждал только «вернулось True» и потому был
    зелёным на двух разных ветках сразу — по известному времени сброса и через
    scanner fallback. Отличить их он не мог, а подмены ставил на процессные
    singleton'ы, поэтому переставал доказывать заявленное, стоило любой из них
    не подействовать. Здесь наблюдаемое — число пробуждений и опубликованный
    дедлайн: ветка проверяется явно, ожидание по стенным часам не нужно.
    """
    import backend.app.pipeline.manager as mgr_mod
    from backend.app.pipeline.manager import PipelineManager

    # ── I2: пока есть другие ждущие, общий дедлайн не снимается ──
    mgr = PipelineManager()
    mgr._log = _anoop_log
    far_deadline = time.monotonic() + 600
    mgr._rate_limit_deadline = far_deadline
    mgr._rate_limit_waiters = 1

    seen = _isolate_rate_limit(monkeypatch, mgr_mod, mgr, reset_sec=600, stagger_sec=30)
    ok = await mgr._wait_for_rate_limit(
        _job("B", AuditStage.NORM_VERIFY), reason="лимит", cli_output="reset"
    )
    assert ok is True
    assert seen, "ожидание не выполнялось ни одной итерации"
    assert mgr._rate_limit_waiters == 1, "счётчик не вернулся к живому соседу"
    assert mgr._rate_limit_deadline >= far_deadline, (
        "общий дедлайн снят, пока сосед ещё ждёт"
    )

    # ── I3: последний вышедший снимает и счётчик, и дедлайн ──
    mgr = PipelineManager()
    mgr._log = _anoop_log
    seen = _isolate_rate_limit(monkeypatch, mgr_mod, mgr, reset_sec=1, stagger_sec=30)
    ok = await mgr._wait_for_rate_limit(
        _job("A", AuditStage.NORM_VERIFY), reason="лимит", cli_output="reset"
    )
    assert ok is True
    # Ровно одно пробуждение = возврат по известному времени сброса, а не через
    # scanner fallback. Ветка зафиксирована, а не угадана.
    assert len(seen) == 1, f"ожидалось одно пробуждение, было {len(seen)}"
    assert mgr._rate_limit_waiters == 0
    assert mgr._rate_limit_deadline == 0.0, "последний ждавший не снял дедлайн"

    # ── I4: следующий непересекающийся эпизод не наследует протухший дедлайн ──
    seen_far = _isolate_rate_limit(monkeypatch, mgr_mod, mgr, reset_sec=600, stagger_sec=30)
    ok = await mgr._wait_for_rate_limit(
        _job("A", AuditStage.NORM_VERIFY), reason="лимит", cli_output="reset"
    )
    assert ok is True
    far_published = seen_far[0]
    assert mgr._rate_limit_waiters == 0
    assert mgr._rate_limit_deadline == 0.0

    seen_next = _isolate_rate_limit(monkeypatch, mgr_mod, mgr, reset_sec=1, stagger_sec=30)
    ok = await mgr._wait_for_rate_limit(
        _job("A", AuditStage.NORM_VERIFY), reason="лимит", cli_output="reset"
    )
    assert ok is True
    # Унаследуй эпизод чужой дальний дедлайн — пробуждений было бы много.
    assert len(seen_next) == 1, "эпизод унаследовал протухший дальний дедлайн"
    assert seen_next[0] < far_published, (
        "опубликован прежний дальний дедлайн вместо собственного короткого"
    )


# ─── 3. Пул потоков ──────────────────────────────────────────────────────────


def test_thread_pool_is_larger_than_python_default(monkeypatch):
    """Дефолт Python (~min(32, ядра+4)) выедается пятью проектами."""
    import os as _os

    from backend.app.main import default_thread_pool_size

    monkeypatch.delenv("THREAD_POOL_WORKERS", raising=False)
    size = default_thread_pool_size()
    python_default = min(32, (_os.cpu_count() or 4) + 4)
    assert size >= 32
    assert size >= python_default, "пул не больше дефолтного — смысла в правке нет"

    monkeypatch.setenv("THREAD_POOL_WORKERS", "48")
    assert default_thread_pool_size() == 48

    # Мусор не должен ронять старт бэкенда.
    monkeypatch.setenv("THREAD_POOL_WORKERS", "не-число")
    assert default_thread_pool_size() >= 32
