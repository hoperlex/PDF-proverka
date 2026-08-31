"""Общий пул процессов для CPU-тяжёлой работы конвейера.

Зачем отдельный модуль
──────────────────────
Когда очередь гоняет несколько проектов ОДНОВРЕМЕННО, вся CPU-работа
(разбор вектор-слоя, рендер PDF, геометрия профилей) конкурирует за одни и те
же ядра. Два антипаттерна, которых этот модуль избегает:

1. `asyncio.to_thread` для чистого CPU — упирается в GIL: N проектов
   «выполняются», а реально считает одно ядро (бенч на 16 ядрах: 85% CPU у
   бэкенда и 5–22 с на блок при чистых 1–1.5 с; см. block_context/builder.py).
2. Свой пул на каждый проект — N проектов × M воркеров выносят машину.

Отсюда правило: **пул ровно один на процесс бэкенда и общий для всех
проектов очереди**. Он и есть тот бюджет ядер, который делится между
параллельными проектами; планировщик ОС раскидывает воркеры сам.

Распределение по ядрам
──────────────────────
`CPU_POOL_PIN_CORES=true` включает жёсткую привязку: воркер i садится на ядро
`cores[i % len(cores)]` через `os.sched_setaffinity`. Это даёт локальность кэша
и убирает миграцию задач между ядрами под нагрузкой. По умолчанию ВЫКЛЮЧЕНО:
для смешанной нагрузки (CPU + сеть) свободный планировщик обычно не хуже, а
пиннинг мешает ему балансировать. Включать осмысленно, когда на машине
одновременно живут несколько проектов и профиль нагрузки ровный.

Метод старта — spawn: fork из многопоточного uvicorn-процесса рискует
дедлоком в дочернем.

Всё fail-soft: если пул недоступен (нет прав на форк, сломанный executor) —
`run()` считает в текущем потоке, стадия не падает. Единственное исключение —
завершение работы бэкенда: после `shutdown_pool()` считать заново нельзя,
см. «Жизненный цикл» ниже.

Жизненный цикл (W0-ENG-02)
──────────────────────────
`ProcessPoolExecutor.shutdown(wait=False)` возвращает управление мгновенно, но
НЕ завершает воркеры: интерпретатор всё равно join'ит их в своём `atexit`
(`concurrent.futures.process._python_exit`). Если воркер завис на CPU-задаче,
процесс бэкенда не выходит вовсе — измерено: `shutdown_pool()` возвращался за
0.00 с, а интерпретатор не завершился и за 45 с при воркере в `sleep(600)`,
плюс пять протёкших семафоров.

Поэтому `shutdown_pool()` здесь ограничен временем и доводит дело до конца:
снимает очередь → ждёт воркеры в пределах бюджета → `terminate()` тем, кто не
вышел → `kill()` тем, кто пережил terminate. Бюджет — `CPU_POOL_SHUTDOWN_SEC`.

Второе свойство того же дефекта: shutdown НЕ запирал модуль, и первый же
поздний `run()` молча поднимал НОВЫЙ пул процессов — уже после того, как
бэкенд отчитался о завершении. После `shutdown_pool()` пул не воскресает:
работа считается в потоке, а для повторного старта в том же процессе есть
явный `reset_pool_state()`.

Переменные окружения:
  CPU_POOL_WORKERS       — размер пула (0/пусто → авто: min(8, ядра − 2))
  CPU_POOL_PIN_CORES     — true/1/yes → привязать воркеры к ядрам
  CPU_POOL_SHUTDOWN_SEC  — бюджет мягкого завершения воркеров (по умолчанию 5 с)
"""
from __future__ import annotations

import asyncio
import multiprocessing
import os
import threading
import time
from concurrent.futures import BrokenExecutor, ProcessPoolExecutor
from typing import Any, Callable, Optional, TypeVar

T = TypeVar("T")

# Столько ядер оставляем бэкенду: HTTP/WS и сам event loop не должны голодать
# на фоне CPU-пула.
RESERVED_CORES = 2
DEFAULT_MAX_WORKERS = 8

# Бюджет мягкого завершения: сколько ждём, что воркер выйдет сам, прежде чем
# слать SIGTERM. Отдельно — сколько ждём после SIGTERM, прежде чем SIGKILL.
# Оба ограничены намеренно: shutdown обязан завершаться, а не «обычно
# завершаться».
DEFAULT_SHUTDOWN_SEC = 5.0
KILL_GRACE_SEC = 2.0

_POOL_LOCK = threading.Lock()
_POOL: Optional[ProcessPoolExecutor] = None
_POOL_DISABLED = False
_POOL_SHUTDOWN = False
_POOL_WORKERS = 0

# Счётчики жизненного цикла. Намеренно без labels: ни project_id, ни block_id,
# ни имени функции — иначе метрика становится high-cardinality (см. §8
# quality/runtime contract v1, node ID остаётся в логе, а не в метрике).
_STATS_LOCK = threading.Lock()
_STATS: dict[str, float] = {
    "submitted": 0,          # задач отправлено в пул
    "completed": 0,          # вернулись результатом
    "failed": 0,             # вернулись исключением самой задачи
    "cancelled": 0,          # await прерван снаружи
    "inline_fallbacks": 0,   # посчитано в потоке вместо пула
    "shutdowns": 0,          # вызовов shutdown_pool с живым пулом
    "workers_terminated": 0,  # не вышли сами → SIGTERM
    "workers_killed": 0,     # пережили SIGTERM → SIGKILL
    "last_shutdown_sec": 0.0,  # длительность последнего завершения
}


def _bump(key: str, delta: float = 1) -> None:
    with _STATS_LOCK:
        _STATS[key] += delta


def shutdown_budget_sec() -> float:
    """Бюджет мягкого завершения воркеров. Не может быть нулевым или nan."""
    raw = (os.environ.get("CPU_POOL_SHUTDOWN_SEC") or "").strip()
    if not raw:
        return DEFAULT_SHUTDOWN_SEC
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_SHUTDOWN_SEC
    # Бесконечность и отрицательное значение убивают саму цель ограничения.
    if not (value > 0) or value == float("inf"):
        return DEFAULT_SHUTDOWN_SEC
    return value


def _env_flag(name: str, default: bool = False) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def available_cores() -> list[int]:
    """Ядра, доступные ЭТОМУ процессу (учитывает cgroup/taskset контейнера)."""
    try:
        return sorted(os.sched_getaffinity(0))
    except AttributeError:  # не Linux
        return list(range(os.cpu_count() or 1))


def pool_workers() -> int:
    """Размер пула. CPU_POOL_WORKERS=1 → работа в текущем потоке (пул не нужен)."""
    # BLOCK_CONTEXT_WORKERS — legacy-имя: до появления общего пула им задавался
    # размер пула в block_context/builder.py. Держим как запасной ключ, чтобы у
    # тех, кто его уже настроил, размер пула не поехал молча.
    for key in ("CPU_POOL_WORKERS", "BLOCK_CONTEXT_WORKERS"):
        raw = (os.environ.get(key) or "").strip()
        if not raw:
            continue
        try:
            requested = int(raw)
        except ValueError:
            continue
        if requested > 0:
            return requested
    cores = len(available_cores())
    return max(1, min(DEFAULT_MAX_WORKERS, cores - RESERVED_CORES))


_PIN_COUNTER: Any = None  # multiprocessing.Value, создаётся вместе с пулом


def _pin_initializer(counter, cores: list[int]) -> None:
    """Инициализатор воркера: посадить процесс на своё ядро.

    Порядковый номер воркера берём из общего счётчика — ProcessPoolExecutor не
    сообщает индекс воркера, а имя процесса (`SpawnProcess-N`) не гарантирует
    плотную нумерацию при перезапуске упавшего воркера.
    """
    try:
        with counter.get_lock():
            idx = counter.value
            counter.value += 1
        core = cores[idx % len(cores)]
        os.sched_setaffinity(0, {core})
    except Exception:
        # Пиннинг — оптимизация, а не требование: не смогли — считаем как есть.
        pass


def _get_pool() -> Optional[ProcessPoolExecutor]:
    """Ленивый общий пул. None → считать в текущем потоке."""
    global _POOL, _POOL_DISABLED, _POOL_WORKERS, _PIN_COUNTER
    # Порядок проверок значим: после shutdown пул не воскресает. Раньше поздняя
    # задача поднимала НОВЫЙ пул процессов уже после завершения бэкенда, и
    # гасить его было некому.
    if _POOL_DISABLED or _POOL_SHUTDOWN:
        return None
    workers = pool_workers()
    if workers <= 1:
        return None
    with _POOL_LOCK:
        # Повторная проверка под замком: между первой и взятием замка другой
        # поток мог погасить пул.
        if _POOL_DISABLED or _POOL_SHUTDOWN:
            return None
        if _POOL is None:
            ctx = multiprocessing.get_context("spawn")
            kwargs: dict[str, Any] = {"max_workers": workers, "mp_context": ctx}
            if _env_flag("CPU_POOL_PIN_CORES"):
                cores = available_cores()
                if cores:
                    _PIN_COUNTER = ctx.Value("i", 0)
                    kwargs["initializer"] = _pin_initializer
                    kwargs["initargs"] = (_PIN_COUNTER, cores)
            try:
                _POOL = ProcessPoolExecutor(**kwargs)
                _POOL_WORKERS = workers
            except Exception as exc:  # окружение без права форка и т.п.
                _POOL_DISABLED = True
                print(f"[cpu_pool] пул процессов недоступен ({exc}); считаем в потоке")
                return None
        return _POOL


def get_executor() -> Optional[ProcessPoolExecutor]:
    """Сырой executor для вызывающих со своей логикой подачи задач.

    Нужен там, где мало `run()`: например block_context подаёт блоки окном и
    сам обрабатывает падение отдельного блока. Владелец пула всё равно один —
    этот модуль, поэтому N проектов делят общий бюджет ядер.
    """
    return _get_pool()


def _terminate_workers(procs: list, budget_sec: float) -> tuple[int, int]:
    """Довести воркеров до завершения за ограниченное время.

    Возвращает (сколько получили SIGTERM, сколько получили SIGKILL).

    Почему это вообще нужно. `ProcessPoolExecutor.shutdown(wait=False)` только
    просит менеджер-поток закончить; сами процессы он не трогает. Дальше
    интерпретатор в своём `atexit` join'ит менеджер-поток, тот join'ит
    воркеров — и если воркер занят CPU-задачей, выход процесса ждёт её конца.
    Бюджета там нет никакого, поэтому «завис воркер» превращается в «бэкенд не
    выключается».

    Лестница строго ступенчатая: сначала даём выйти самим, потом SIGTERM,
    потом SIGKILL. Пропускать ступени нельзя — SIGTERM даёт воркеру закрыть
    свои файлы и очереди, а SIGKILL не даёт.
    """
    terminated = 0
    killed = 0
    deadline = time.monotonic() + budget_sec

    # Ступень 1: дать выйти самим в пределах общего бюджета.
    for proc in procs:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            proc.join(remaining)
        except Exception:
            pass

    # Ступень 2: кто не вышел — SIGTERM.
    still_alive = []
    for proc in procs:
        try:
            if proc.is_alive():
                proc.terminate()
                terminated += 1
                still_alive.append(proc)
        except Exception:
            pass

    if still_alive:
        kill_deadline = time.monotonic() + KILL_GRACE_SEC
        for proc in still_alive:
            remaining = kill_deadline - time.monotonic()
            if remaining > 0:
                try:
                    proc.join(remaining)
                except Exception:
                    pass
        # Ступень 3: пережившие SIGTERM — SIGKILL. Без него бюджет остаётся
        # обещанием, а не гарантией.
        for proc in still_alive:
            try:
                if proc.is_alive():
                    proc.kill()
                    killed += 1
                    proc.join(KILL_GRACE_SEC)
            except Exception:
                pass

    return terminated, killed


def _close_pool(pool: Optional[ProcessPoolExecutor], reason: str) -> None:
    """Снять очередь и довести воркеров до конца за ограниченное время."""
    if pool is None:
        return
    started = time.monotonic()
    # Список процессов снимается ДО shutdown: `ProcessPoolExecutor.shutdown`
    # обнуляет `_processes` (CPython 3.12), и после вызова гасить уже некого.
    procs = list((getattr(pool, "_processes", None) or {}).values())
    try:
        pool.shutdown(wait=False, cancel_futures=True)
    except Exception:
        pass
    terminated, killed = _terminate_workers(procs, shutdown_budget_sec())
    elapsed = time.monotonic() - started
    _bump("workers_terminated", terminated)
    _bump("workers_killed", killed)
    with _STATS_LOCK:
        _STATS["last_shutdown_sec"] = round(elapsed, 3)
    print(
        f"[cpu_pool] пул остановлен ({reason}): воркеров {len(procs)}, "
        f"terminate {terminated}, kill {killed}, {elapsed:.2f} с"
    )


def disable_pool(reason: str) -> None:
    """Пул сломался — дальше считаем в потоке, стадия не падает."""
    global _POOL, _POOL_DISABLED
    with _POOL_LOCK:
        _POOL_DISABLED = True
        pool, _POOL = _POOL, None
    print(f"[cpu_pool] пул процессов отключён: {reason}")
    _close_pool(pool, f"отключён: {reason}")


def shutdown_pool() -> None:
    """Погасить пул на завершении бэкенда.

    Идемпотентна: повторный вызов ничего не ломает и не ждёт. После неё пул не
    поднимается заново — поздняя задача считается в потоке. Чтобы поднять пул
    в том же процессе снова, нужен явный `reset_pool_state()`.
    """
    global _POOL, _POOL_SHUTDOWN
    with _POOL_LOCK:
        _POOL_SHUTDOWN = True
        pool, _POOL = _POOL, None
    if pool is None:
        return
    _bump("shutdowns")
    _close_pool(pool, "shutdown")


def reset_pool_state() -> None:
    """Снять запреты и вернуть модуль в исходное состояние.

    Нужна там, где один процесс живёт дольше одного жизненного цикла пула:
    тесты и повторный старт. Production-путь её не вызывает — у бэкенда
    shutdown ровно один и он окончательный.
    """
    global _POOL_DISABLED, _POOL_SHUTDOWN, _POOL_WORKERS
    shutdown_pool()
    with _POOL_LOCK:
        _POOL_DISABLED = False
        _POOL_SHUTDOWN = False
        _POOL_WORKERS = 0


def pool_stats() -> dict:
    """Счётчики жизненного цикла. Без labels — метрика low-cardinality."""
    with _STATS_LOCK:
        return dict(_STATS)


def reset_pool_stats() -> None:
    """Обнулить счётчики.

    Отдельно от `reset_pool_state()`: перезапуск пула в одном процессе не
    должен стирать накопленную эксплуатационную статистику. Обнуление нужно
    только тому, кто измеряет ОДИН жизненный цикл — то есть тесту.
    """
    with _STATS_LOCK:
        for key in _STATS:
            _STATS[key] = 0


def pool_info() -> dict:
    """Диагностика для /api — что реально поднято."""
    return {
        "workers": _POOL_WORKERS if _POOL is not None else 0,
        "configured": pool_workers(),
        "cores": len(available_cores()),
        "pinned": _env_flag("CPU_POOL_PIN_CORES"),
        "disabled": _POOL_DISABLED,
        "shutdown": _POOL_SHUTDOWN,
        "alive": _POOL is not None,
        "shutdown_budget_sec": shutdown_budget_sec(),
        "stats": pool_stats(),
    }


async def run(fn: Callable[..., T], *args: Any) -> T:
    """Выполнить CPU-функцию в общем пуле (fallback — поток).

    `fn` и аргументы должны быть picklable: пул стартует через spawn.

    Отмена. Прервать уже начатую задачу `ProcessPoolExecutor` нечем: снять
    конкретный воркер с конкретной задачи API не позволяет. Поэтому отменённый
    `run()` возвращает управление сразу, но воркер остаётся занят до конца
    вычисления. Это ограничение фиксируется счётчиком `cancelled`, а не
    маскируется: гарантию «после отмены ядро свободно» модуль дать не может, и
    делать вид, что может, хуже, чем сказать прямо. Освобождение занятых
    воркеров даёт только `shutdown_pool()` со своей лестницей terminate/kill.
    """
    pool = _get_pool()
    if pool is None:
        _bump("inline_fallbacks")
        return await asyncio.to_thread(fn, *args)
    loop = asyncio.get_running_loop()
    _bump("submitted")
    try:
        result = await loop.run_in_executor(pool, fn, *args)
    except asyncio.CancelledError:
        _bump("cancelled")
        raise
    except (BrokenExecutor, OSError) as exc:
        # Пул сломался ПОТОМУ ЧТО его гасят — пересчитывать нельзя: бэкенд
        # уходит, а повторный запуск CPU-задачи в потоке продлил бы выключение
        # ровно на её длительность. Ошибка честно уходит вызывающему.
        if _POOL_SHUTDOWN:
            _bump("failed")
            raise RuntimeError(
                "cpu_pool: задача прервана остановкой пула процессов"
            ) from exc
        disable_pool(f"{type(exc).__name__}: {exc}")
        _bump("inline_fallbacks")
        return await asyncio.to_thread(fn, *args)
    except BaseException:
        # Исключение самой задачи. Пул при этом исправен и остаётся жить:
        # падение одного блока не должно гасить общий бюджет ядер.
        _bump("failed")
        raise
    _bump("completed")
    return result
