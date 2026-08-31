"""Тесты общего пула процессов для CPU-тяжёлых этапов.

Пул один на процесс бэкенда и общий для всех проектов очереди — это тот бюджет
ядер, который делится между параллельными проектами. Проверяем:

  1. Размер пула считается от доступных ядер с резервом под сам бэкенд.
  2. CPU_POOL_WORKERS переопределяет авто-расчёт.
  3. CPU_POOL_WORKERS=1 → пул не поднимается, работа идёт в потоке.
  4. Работа реально уходит в РАЗНЫЕ процессы (то, чего не даёт to_thread из-за GIL).
  5. CPU_POOL_PIN_CORES=true сажает каждый воркер на своё ядро.
  6. Сломанный пул не роняет стадию: disable_pool → fallback в поток.
  7. pool_info честно отражает состояние.

Ниже — характеризация жизненного цикла (W0-ENG-02): normal, error, cancel и
shutdown. Она фиксирует ровно те свойства, отсутствие которых делало выключение
бэкенда незавершающимся, и одно свойство, которого модуль дать НЕ может
(освобождение воркера при отмене) — оно записано как есть, а не замаскировано.

Run: python -m pytest tests/test_cpu_pool.py -v
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.app.services.common import cpu_pool  # noqa: E402


# Модульного уровня — чтобы функция была picklable для spawn-воркеров.
def _probe(marker: int):
    """Вернуть pid и привязку к ядрам — по ним видно, где реально считалось."""
    try:
        aff = tuple(sorted(os.sched_getaffinity(0)))
    except Exception:
        aff = None
    return os.getpid(), aff, marker


def _boom(marker: int):
    """Задача, падающая внутри воркера."""
    raise ValueError(f"подопытный сбой задачи {marker}")


def _sleep_forever(marker: int):
    """Заведомо зависший воркер: столько ни один тест не ждёт."""
    time.sleep(600)
    return marker


def _pid_is_gone(pid: int) -> bool:
    """Процесса с таким pid больше нет (сигнал 0 — только проверка)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return False


_ENV_KEYS = ("CPU_POOL_WORKERS", "CPU_POOL_PIN_CORES", "CPU_POOL_SHUTDOWN_SEC")


@pytest.fixture(autouse=True)
def _reset_pool():
    """Каждый тест стартует с чистым пулом и без унаследованных env.

    Сброс идёт через публичный `reset_pool_state()`, а не присваиванием
    приватных флагов: после `shutdown_pool()` модуль намеренно заперт, и тест,
    открывающий его в обход, проверял бы не тот модуль, что работает в проде.
    """
    saved = {k: os.environ.get(k) for k in _ENV_KEYS}
    cpu_pool.reset_pool_state()
    cpu_pool.reset_pool_stats()   # счётчики модульные: без обнуления тест мерил бы весь прогон
    yield
    cpu_pool.reset_pool_state()
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def test_pool_size_reserves_cores_for_backend(monkeypatch):
    """Авто-размер оставляет ядра под HTTP/WS и не превышает потолок."""
    monkeypatch.delenv("CPU_POOL_WORKERS", raising=False)
    monkeypatch.setattr(cpu_pool, "available_cores", lambda: list(range(16)))
    assert cpu_pool.pool_workers() == min(cpu_pool.DEFAULT_MAX_WORKERS, 16 - cpu_pool.RESERVED_CORES)

    # Маленькая машина: не уходим в ноль или отрицательное.
    monkeypatch.setattr(cpu_pool, "available_cores", lambda: [0])
    assert cpu_pool.pool_workers() == 1


def test_env_overrides_pool_size(monkeypatch):
    monkeypatch.setenv("CPU_POOL_WORKERS", "3")
    assert cpu_pool.pool_workers() == 3

    # Мусор в переменной не должен ронять расчёт — падаем на авто.
    monkeypatch.setenv("CPU_POOL_WORKERS", "не-число")
    monkeypatch.setattr(cpu_pool, "available_cores", lambda: list(range(8)))
    assert cpu_pool.pool_workers() == min(cpu_pool.DEFAULT_MAX_WORKERS, 8 - cpu_pool.RESERVED_CORES)


def test_single_worker_runs_inline_without_pool(monkeypatch):
    """CPU_POOL_WORKERS=1 → пул не поднимаем, считаем в потоке (как до параллели)."""
    monkeypatch.setenv("CPU_POOL_WORKERS", "1")
    assert cpu_pool._get_pool() is None

    pid, _, marker = asyncio.run(cpu_pool.run(_probe, 42))
    assert marker == 42
    assert pid == os.getpid()  # тот же процесс — работа не уехала в пул


def test_work_spreads_across_processes(monkeypatch):
    """Главное свойство: задачи считаются в РАЗНЫХ процессах, а не под одним GIL."""
    monkeypatch.setenv("CPU_POOL_WORKERS", "4")
    monkeypatch.delenv("CPU_POOL_PIN_CORES", raising=False)

    async def _run():
        return await asyncio.gather(*[cpu_pool.run(_probe, i) for i in range(12)])

    res = asyncio.run(_run())
    pids = {pid for pid, _, _ in res}
    assert len(pids) > 1, "работа не разошлась по процессам — пул не задействован"
    assert os.getpid() not in pids, "считали в родительском процессе вместо пула"
    assert sorted(m for _, _, m in res) == list(range(12))


@pytest.mark.skipif(
    not hasattr(os, "sched_setaffinity"), reason="привязка к ядрам только на Linux"
)
def test_pin_cores_gives_each_worker_own_core(monkeypatch):
    """CPU_POOL_PIN_CORES=true → каждый воркер садится на одно (своё) ядро."""
    if len(cpu_pool.available_cores()) < 2:
        pytest.skip("нужно минимум 2 ядра")

    monkeypatch.setenv("CPU_POOL_WORKERS", "2")
    monkeypatch.setenv("CPU_POOL_PIN_CORES", "true")

    async def _run():
        return await asyncio.gather(*[cpu_pool.run(_probe, i) for i in range(8)])

    res = asyncio.run(_run())
    affinities = {aff for _, aff, _ in res}
    assert affinities, "не получили привязок"
    for aff in affinities:
        assert aff is not None and len(aff) == 1, f"воркер не привязан к одному ядру: {aff}"
    # Два воркера — два РАЗНЫХ ядра, а не оба на нулевом.
    assert len(affinities) == 2, f"воркеры сели на одно ядро: {affinities}"


def test_broken_pool_falls_back_to_thread(monkeypatch):
    """Сломанный executor не роняет этап — досчитываем в потоке."""
    from concurrent.futures import BrokenExecutor

    monkeypatch.setenv("CPU_POOL_WORKERS", "2")

    class _BrokenPool:
        def submit(self, *a, **kw):
            raise BrokenExecutor("подопытный сбой")

    monkeypatch.setattr(cpu_pool, "_get_pool", lambda: _BrokenPool())

    # run_in_executor поднимет BrokenExecutor — ждём тихий fallback, не исключение.
    loop_run = asyncio.AbstractEventLoop.run_in_executor

    def _raising(self, executor, func, *args):
        fut = asyncio.get_event_loop().create_future()
        fut.set_exception(BrokenExecutor("подопытный сбой"))
        return fut

    monkeypatch.setattr(asyncio.AbstractEventLoop, "run_in_executor", _raising)
    try:
        pid, _, marker = asyncio.run(cpu_pool.run(_probe, 7))
    finally:
        monkeypatch.setattr(asyncio.AbstractEventLoop, "run_in_executor", loop_run)

    assert marker == 7
    assert pid == os.getpid()  # посчитали здесь же, в потоке
    assert cpu_pool._POOL_DISABLED is True


def test_pool_info_reports_state(monkeypatch):
    monkeypatch.setenv("CPU_POOL_WORKERS", "2")
    info = cpu_pool.pool_info()
    assert info["configured"] == 2
    assert info["alive"] is False  # ленивый: ещё не поднят

    asyncio.run(cpu_pool.run(_probe, 1))
    info = cpu_pool.pool_info()
    assert info["alive"] is True
    assert info["workers"] == 2
    assert info["cores"] >= 1


# ─────────────────────────────────────────────────────────────────────────────
# Характеризация жизненного цикла (W0-ENG-02)
#
# Что чинилось. `ProcessPoolExecutor.shutdown(wait=False)` возвращается
# мгновенно, но воркеров не завершает: их join'ит интерпретатор в своём
# `atexit`. Измерено ДО правки: `shutdown_pool()` возвращался за 0.00 с, а
# процесс не выходил и за 45 с при воркере в `sleep(600)`. Плюс первый же
# поздний `run()` поднимал НОВЫЙ пул уже после отчёта о завершении.
# ─────────────────────────────────────────────────────────────────────────────


def test_normal_completion_frees_the_worker(monkeypatch):
    """Штатный путь: задача досчитала — воркер снова принимает работу."""
    monkeypatch.setenv("CPU_POOL_WORKERS", "2")

    async def _run():
        first = await cpu_pool.run(_probe, 1)
        second = await cpu_pool.run(_probe, 2)
        return first, second

    (pid1, _, m1), (pid2, _, m2) = asyncio.run(_run())
    assert (m1, m2) == (1, 2)
    assert pid1 != os.getpid() and pid2 != os.getpid()

    stats = cpu_pool.pool_stats()
    assert stats["submitted"] == 2
    assert stats["completed"] == 2
    assert stats["failed"] == 0


def test_task_error_does_not_take_the_pool_down(monkeypatch):
    """Падение задачи — это падение задачи, а не общего бюджета ядер.

    Пул один на весь бэкенд: если бы исключение одного блока гасило его,
    один плохой PDF останавливал бы CPU-работу всех проектов очереди.
    """
    monkeypatch.setenv("CPU_POOL_WORKERS", "2")

    async def _run():
        with pytest.raises(ValueError, match="подопытный сбой задачи 5"):
            await cpu_pool.run(_boom, 5)
        # Пул обязан пережить падение и посчитать следующую задачу.
        return await cpu_pool.run(_probe, 6)

    pid, _, marker = asyncio.run(_run())
    assert marker == 6
    assert pid != os.getpid(), "после ошибки задачи работа ушла в поток — пул погас"

    stats = cpu_pool.pool_stats()
    assert stats["failed"] == 1
    assert stats["completed"] == 1
    assert cpu_pool.pool_info()["alive"] is True


def test_cancel_returns_immediately_and_is_counted(monkeypatch):
    """Отмена не подвешивает вызывающего — и честно считается.

    Гарантии «после отмены воркер свободен» модуль дать НЕ может: снять
    начатую задачу `ProcessPoolExecutor` нечем. Тест фиксирует то, что
    действительно есть — управление возвращается сразу, — и то, что занятость
    воркера учтена счётчиком, а не забыта.
    """
    monkeypatch.setenv("CPU_POOL_WORKERS", "2")

    async def _run():
        task = asyncio.ensure_future(cpu_pool.run(_sleep_forever, 1))
        await asyncio.sleep(0.5)          # дать воркеру стартовать
        started = time.monotonic()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return time.monotonic() - started

    elapsed = asyncio.run(_run())
    assert elapsed < 5.0, f"отмена ждала завершения задачи: {elapsed:.1f} с"
    assert cpu_pool.pool_stats()["cancelled"] == 1


def test_shutdown_is_bounded_and_kills_a_hung_worker(monkeypatch):
    """Завершение ограничено временем даже при заведомо зависшем воркере.

    Ровно этот путь и не завершался: `shutdown(wait=False)` только просил
    менеджер-поток закончить, а сами процессы оставались считать.
    """
    monkeypatch.setenv("CPU_POOL_WORKERS", "2")
    monkeypatch.setenv("CPU_POOL_SHUTDOWN_SEC", "2")

    async def _start():
        task = asyncio.ensure_future(cpu_pool.run(_sleep_forever, 1))
        await asyncio.sleep(0.5)
        return task

    loop = asyncio.new_event_loop()
    try:
        task = loop.run_until_complete(_start())
        started = time.monotonic()
        cpu_pool.shutdown_pool()
        elapsed = time.monotonic() - started
        task.cancel()
    finally:
        loop.close()

    # Бюджет 2 с + до 2 с на добивание после SIGTERM; с запасом на медленный
    # раннер — но НЕ бесконечность, ради которой всё и делалось.
    assert elapsed < 10.0, f"shutdown не уложился в бюджет: {elapsed:.1f} с"
    stats = cpu_pool.pool_stats()
    assert stats["shutdowns"] == 1
    assert stats["workers_terminated"] >= 1, "зависший воркер не получил SIGTERM"
    assert stats["last_shutdown_sec"] > 0


def test_shutdown_leaves_no_worker_processes(monkeypatch):
    """После завершения не остаётся ни одного процесса пула."""
    monkeypatch.setenv("CPU_POOL_WORKERS", "2")

    async def _run():
        return await asyncio.gather(*[cpu_pool.run(_probe, i) for i in range(6)])

    pids = {pid for pid, _, _ in asyncio.run(_run())}
    assert pids and os.getpid() not in pids

    cpu_pool.shutdown_pool()

    deadline = time.monotonic() + 10
    alive = {pid for pid in pids if not _pid_is_gone(pid)}
    while alive and time.monotonic() < deadline:
        time.sleep(0.1)
        alive = {pid for pid in alive if not _pid_is_gone(pid)}
    assert not alive, f"после shutdown остались процессы пула: {sorted(alive)}"


def test_shutdown_is_idempotent(monkeypatch):
    """Повтор безопасен: второй и третий вызов ничего не ждут и не падают."""
    monkeypatch.setenv("CPU_POOL_WORKERS", "2")
    asyncio.run(cpu_pool.run(_probe, 1))

    cpu_pool.shutdown_pool()
    started = time.monotonic()
    cpu_pool.shutdown_pool()
    cpu_pool.shutdown_pool()
    elapsed = time.monotonic() - started

    assert elapsed < 1.0, f"повторный shutdown чего-то ждал: {elapsed:.2f} с"
    # Счётчик растёт только на реальном гашении живого пула.
    assert cpu_pool.pool_stats()["shutdowns"] == 1


def test_pool_does_not_revive_after_shutdown(monkeypatch):
    """Поздняя задача не поднимает новый пул уже после завершения бэкенда."""
    monkeypatch.setenv("CPU_POOL_WORKERS", "2")
    asyncio.run(cpu_pool.run(_probe, 1))
    cpu_pool.shutdown_pool()

    pid, _, marker = asyncio.run(cpu_pool.run(_probe, 2))
    assert marker == 2
    assert pid == os.getpid(), "после shutdown пул воскрес и завёл новые процессы"

    info = cpu_pool.pool_info()
    assert info["shutdown"] is True
    assert info["alive"] is False


def test_reset_pool_state_allows_a_new_lifecycle(monkeypatch):
    """Явный сброс — единственный способ снова поднять пул в том же процессе."""
    monkeypatch.setenv("CPU_POOL_WORKERS", "2")
    asyncio.run(cpu_pool.run(_probe, 1))
    cpu_pool.shutdown_pool()
    cpu_pool.reset_pool_state()

    pid, _, marker = asyncio.run(cpu_pool.run(_probe, 3))
    assert marker == 3
    assert pid != os.getpid(), "после сброса пул не поднялся"
    assert cpu_pool.pool_info()["shutdown"] is False


def test_backend_process_exits_despite_a_hung_worker(tmp_path):
    """Сквозная проверка: интерпретатор ВЫХОДИТ, а не висит в atexit.

    Внутрипроцессные проверки выше не могут доказать это свойство: зависание
    случается уже после `main()`, в `atexit` самого интерпретатора. Поэтому
    сценарий гоняется отдельным процессом, а тест смотрит на код возврата.
    До правки этот же сценарий не завершался (замер: >45 с при бюджете теста).
    """
    script = tmp_path / "hung_worker_shutdown.py"
    script.write_text(
        textwrap.dedent(
            f"""
            import asyncio, os, sys, time
            sys.path.insert(0, {str(_ROOT)!r})
            from backend.app.services.common import cpu_pool

            def _hang(n):
                time.sleep(600)
                return n

            async def main():
                os.environ["CPU_POOL_WORKERS"] = "2"
                os.environ["CPU_POOL_SHUTDOWN_SEC"] = "2"
                task = asyncio.ensure_future(cpu_pool.run(_hang, 1))
                await asyncio.sleep(1.0)
                cpu_pool.shutdown_pool()
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            if __name__ == "__main__":
                asyncio.run(main())
                print("EXITED_CLEANLY")
            """
        ).strip(),
        encoding="utf-8",
    )

    env = dict(os.environ, AUDIT_DISABLE_DOTENV="1")
    started = time.monotonic()
    proc = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True, text=True, timeout=60, env=env,
    )
    elapsed = time.monotonic() - started

    assert "EXITED_CLEANLY" in proc.stdout, proc.stdout + proc.stderr
    assert proc.returncode == 0, f"код {proc.returncode}: {proc.stderr}"
    assert elapsed < 30, f"процесс выходил {elapsed:.1f} с — бюджет не соблюдён"


def test_shutdown_budget_rejects_nonsense(monkeypatch):
    """Бюджет, который нельзя выдержать, не принимается молча."""
    monkeypatch.delenv("CPU_POOL_SHUTDOWN_SEC", raising=False)
    assert cpu_pool.shutdown_budget_sec() == cpu_pool.DEFAULT_SHUTDOWN_SEC

    for bad in ("0", "-1", "nan", "inf", "не-число", ""):
        monkeypatch.setenv("CPU_POOL_SHUTDOWN_SEC", bad)
        assert cpu_pool.shutdown_budget_sec() == cpu_pool.DEFAULT_SHUTDOWN_SEC, bad

    monkeypatch.setenv("CPU_POOL_SHUTDOWN_SEC", "1.5")
    assert cpu_pool.shutdown_budget_sec() == 1.5


def test_lifecycle_telemetry_has_no_high_cardinality_labels():
    """Счётчики — скаляры с фиксированным набором имён.

    Контракт §8 запрещает node ID и прочие идентификаторы как labels метрик.
    Тест ловит попытку добавить в телеметрию project_id/block_id: набор ключей
    фиксирован, а значения обязаны быть числами.
    """
    stats = cpu_pool.pool_stats()
    assert set(stats) == {
        "submitted", "completed", "failed", "cancelled", "inline_fallbacks",
        "shutdowns", "workers_terminated", "workers_killed", "last_shutdown_sec",
    }
    for key, value in stats.items():
        assert isinstance(value, (int, float)), f"{key} — не число: {value!r}"
