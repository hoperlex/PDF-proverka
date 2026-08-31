#!/usr/bin/env python3
"""Per-test timeout по контракту `quality-runtime/v1` §7 — pytest-плагин.

Зачем отдельный плагин, а не `pytest-timeout`
─────────────────────────────────────────────
Контракт требует, чтобы hang превращался в диагностируемый failure с node ID,
thread dump, инвентарём дочерних процессов и СВЕЖИМ JUnit. Готовый
`pytest-timeout` в окружении не установлен, а добавление root-зависимости
принадлежит `W0-INT-01` (§11) — `W0-OPS-03` не имеет права править
`requirements*.txt`. Поэтому harness обходится стандартной библиотекой.

Плагин НЕ регистрируется в `pytest.ini`: файл конфигурации тоже принадлежит
интегратору. Подключение — только явным `-p ci_timeout_plugin` с
`PYTHONPATH=scripts`, как это делает `scripts/ci_test_lane.py`. Без этого
флага поведение pytest не меняется вообще.

Что делает при срабатывании бюджета (§7, пять требований дословно)
──────────────────────────────────────────────────────────────────
1. печатает полный pytest node ID и lane;
2. снимает dump всех Python-потоков (`faulthandler`) и инвентарь дочерних
   процессов;
3. добивает дочерние процессы лестницей SIGTERM → SIGKILL;
4. отдаёт наружу файл события, из которого `ci_test_lane.py` строит свежий
   JUnit с `<failure type="timeout">`;
5. завершает процесс ненулевым кодом `EXIT_TIMEOUT`.

Почему `os._exit`, а не исключение
───────────────────────────────────
Зависание по определению не отменяемо изнутри: тест не отдаёт GIL или ждёт
неотменяемую операцию (§6 контракта прямо описывает такой AnyIO wake-up).
Исключение, брошенное в watchdog-потоке, до зависшего теста не дойдёт, а
`pytest` не получит управление, чтобы дописать отчёт. Поэтому единственный
надёжный выход — принудительный, а целостность отчёта обеспечивается тем, что
результаты пишутся в журнал событий ПО ХОДУ прогона, а не в конце.

Переменные окружения (их выставляет `ci_test_lane.py`):
    CI_LANE_NAME              — имя lane для диагностики
    CI_LANE_PER_TEST_TIMEOUT  — бюджет одного теста в секундах
    CI_LANE_EVENTS            — путь к JSONL-журналу событий
    CI_LANE_DIAG              — путь к JSON-диагностике таймаута
"""
from __future__ import annotations

import faulthandler
import json
import os
import signal
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ci_redaction import (  # noqa: E402
    publishable_comm,
    render_argv_summary,
    safe_cmdline,
    sanitize_traceback,
    summarize_argv,
)

#: Код возврата, по которому раннер отличает таймаут от обычного падения.
#: 1–5 заняты самим pytest, поэтому берём заведомо свободный.
EXIT_TIMEOUT = 87

#: Сколько ждать дочерний процесс после SIGTERM, прежде чем слать SIGKILL.
CHILD_KILL_GRACE_SEC = 2.0


def _env_float(name: str, default: float) -> float:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    # Бесконечность и ноль обесценивают сам смысл бюджета.
    if not (value > 0) or value == float("inf"):
        return default
    return value


def _scan_proc() -> tuple[dict[int, list[int]], dict[int, dict[str, object]]]:
    """Один проход по /proc: карта ppid → дети и сведения о каждом процессе."""
    proc = Path("/proc")
    tree: dict[int, list[int]] = {}
    info: dict[int, dict[str, object]] = {}
    if not proc.is_dir():
        return tree, info
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # comm может содержать пробелы и скобки — режем по ПОСЛЕДНЕЙ ')'.
        close = stat.rfind(")")
        if close < 0:
            continue
        fields = stat[close + 2 :].split()
        if len(fields) < 2:
            continue
        state, ppid_raw = fields[0], fields[1]
        try:
            pid, ppid = int(entry.name), int(ppid_raw)
        except ValueError:
            continue
        # `comm` задаётся самим процессом через prctl(PR_SET_NAME) — это не
        # имя программы, а пятнадцать подконтрольных источнику символов.
        comm = publishable_comm(stat[stat.find("(") + 1 : close])
        try:
            raw = (entry / "cmdline").read_bytes()
            # argv разделён нулями. Разбираем ПО НИМ, а не склеиваем в строку:
            # без границ аргументов нельзя отличить флаг от значения, а значит
            # и решить, что разрешено публиковать.
            argv = [
                part.decode("utf-8", errors="replace")
                for part in raw.split(b"\0")
                if part
            ]
            # Публикуется не «очищенная» строка, а ТОЛЬКО безопасная по
            # построению структура (P-13: разрешено то, что явно разрешено, а
            # не то, что не запрещено). Позиционные аргументы не публикуются
            # вовсе: именно они чаще всего и оказываются секретом.
            #
            # Сборка стоит В ИСТОЧНИКЕ, а не перед каждой публикацией: cmdline
            # уходит в JUnit, журнал событий И диагностику таймаута, и три
            # точки — это три возможности забыть одну.
            summary = summarize_argv(argv)
            cmdline = render_argv_summary(summary)
        except OSError:
            cmdline = ""
            summary = {
                "argc": 0,
                "positional_count": 0,
                "hidden_flag_count": 0,
                "argv_fingerprint": "",
            }
        tree.setdefault(ppid, []).append(pid)
        info[pid] = {
            "pid": pid,
            "comm": comm,
            "state": state,
            "cmdline": cmdline[:400],
            # Отпечаток и счётчики — чтобы по сокращённой строке всё же можно
            # было сличить два процесса и понять, сколько сведений скрыто.
            # Отпечаток — HMAC со случайным ключом прогона: обычный SHA-256
            # от argv восстанавливается перебором словаря.
            "argc": summary["argc"],
            "positional_count": summary["positional_count"],
            "hidden_flag_count": summary["hidden_flag_count"],
            "argv_fingerprint": summary["argv_fingerprint"],
        }
    return tree, info


def child_processes(pid: int | None = None) -> list[dict[str, object]]:
    """Инвентарь ВСЕХ потомков через /proc (§7, требование 2).

    Обходится всё дерево, а не только прямые дети. Раньше перечислялся один
    уровень, и внуки зависшего теста переживали cleanup: типичная связка
    «тест → uvicorn → воркер» оставляла воркера с ppid=1. Осиротевший процесс
    держит порт, файл или лок и валит СЛЕДУЮЩИЙ job причиной, никак не
    связанной с его кодом, — а в JUnit при этом честно написано «дочерних
    процессов: 1».

    Каждая запись несёт `depth`: 1 — прямой ребёнок, 2 — внук и так далее.
    Порядок — от самых глубоких к верхним, чтобы cleanup сначала снимал
    листья и родитель не успевал породить замену.

    Без внешних зависимостей: `psutil` в окружении нет, а ставить его — та же
    root-зависимость, что и `pytest-timeout`. На не-Linux вернёт пустой
    список, и это честно отражается полем `proc_available`.
    """
    root_pid = os.getpid() if pid is None else pid
    tree, info = _scan_proc()
    found: list[dict[str, object]] = []
    seen: set[int] = {root_pid}
    frontier = [(child, 1) for child in tree.get(root_pid, [])]
    while frontier:
        current, depth = frontier.pop(0)
        if current in seen:
            continue
        seen.add(current)
        record = info.get(current)
        if record is not None:
            found.append({**record, "depth": depth})
        frontier.extend((grand, depth + 1) for grand in tree.get(current, []))
    return sorted(found, key=lambda item: (-int(item["depth"]), int(item["pid"])))


def terminate_children(children: list[dict[str, object]]) -> dict[str, int]:
    """Bounded cleanup дочерних процессов (§7, требование 3)."""
    terminated = 0
    killed = 0
    pids = [int(item["pid"]) for item in children]
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
            terminated += 1
        except OSError:
            pass
    deadline = time.monotonic() + CHILD_KILL_GRACE_SEC
    while time.monotonic() < deadline:
        alive = [pid for pid in pids if _alive(pid)]
        if not alive:
            break
        time.sleep(0.05)
    for pid in pids:
        if _alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
                killed += 1
            except OSError:
                pass
    return {"terminated": terminated, "killed": killed}


def _alive(pid: int) -> bool:
    """Жив ли процесс. Зомби считается мёртвым.

    `os.kill(pid, 0)` для зомби возвращает успех: запись в таблице процессов
    ещё есть, пока родитель его не забрал. Без проверки состояния harness
    сообщал бы «пришлось слать SIGKILL» там, где процесс давно завершился, —
    и телеметрия cleanup врала бы в сторону паники.
    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return True
    close = stat.rfind(")")
    if close < 0:
        return True
    fields = stat[close + 2 :].split()
    return bool(fields) and fields[0] != "Z"


def thread_dump() -> str:
    """Полный dump всех потоков (§7, требование 2).

    `faulthandler` пишет через файловый дескриптор и `io.StringIO` не
    принимает (`UnsupportedOperation: fileno`) — поэтому дамп идёт в реальный
    временный файл. Это ещё и надёжнее при настоящем зависании: faulthandler
    ничего не аллоцирует.

    Запасной путь — `sys._current_frames()`: он тоже показывает все потоки и
    работает, если временный файл создать не удалось. Оставлять диагностику
    без дампа нельзя: без него таймаут сообщает, ЧТО зависло, но не ГДЕ.
    """
    try:
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as handle:
            faulthandler.dump_traceback(file=handle, all_threads=True)
            handle.flush()
            handle.seek(0)
            text = handle.read()
        if text.strip():
            return text
    except Exception:  # pragma: no cover — зависит от состояния рантайма
        pass
    return _frames_dump()


def _frames_dump() -> str:
    """Запасной дамп: собирается из полей кадра, а не из готового текста.

    `traceback.format_stack()` и `thread.name` здесь не используются, и это не
    стилистика. Оба публиковали свободный ввод:

      * имя потока задаёт тот, кто его создал — `threading.Thread(name=…)`,
        то есть это произвольная строка, а не структура. Измерено: имя
        `q7z4m2n8p5r3t` уходило в дамп целиком;
      * `format_stack` печатает ТЕКСТ исполняемой строки исходника. Строка
        вида `conn = connect("postgres://u:p@host")` попадала в артефакт
        дословно.

    Поэтому кадры обходятся вручную и печатаются ровно три поля: имя файла без
    каталогов, номер строки и имя функции. Это то же, что печатает
    `faulthandler` (он тоже показывает числовой идентификатор потока, а не
    имя), и того же достаточно, чтобы ответить, где зависло.
    """
    try:
        chunks: list[str] = []
        for ident, frame in sys._current_frames().items():
            chunks.append(f"Thread {ident} (most recent call first):")
            current = frame
            depth = 0
            while current is not None and depth < 200:
                code = current.f_code
                chunks.append(
                    f'  File "{os.path.basename(code.co_filename)}", '
                    f"line {current.f_lineno} in {code.co_name}"
                )
                current = current.f_back
                depth += 1
            chunks.append("")
        return "\n".join(chunks)
    except Exception as exc:  # pragma: no cover
        return f"thread dump недоступен: {type(exc).__name__}: {exc}"


class LaneTimeoutPlugin:
    """Watchdog вокруг каждого теста плюс потоковый журнал результатов."""

    def __init__(self) -> None:
        self.lane = os.environ.get("CI_LANE_NAME", "unknown")
        self.budget = _env_float("CI_LANE_PER_TEST_TIMEOUT", 0.0)
        events = os.environ.get("CI_LANE_EVENTS")
        diag = os.environ.get("CI_LANE_DIAG")
        self.events_path = Path(events) if events else None
        self.diag_path = Path(diag) if diag else None
        self._timer: threading.Timer | None = None
        self._events_handle = None
        self._current: str | None = None
        self._started_at = 0.0
        self._lock = threading.Lock()

    # ── журнал событий ────────────────────────────────────────────────
    def _append(self, payload: dict[str, object], lock_timeout: float | None = None) -> None:
        """Дописать событие и сразу вытолкнуть буфер.

        Журнал — единственный источник результатов, если процесс будет снят
        принудительно. Поэтому запись НЕ буферизуется до конца сессии: хвост,
        ради которого журнал и заведён, потерялся бы первым.

        `flush()` без `fsync()` — сознательно. От чего защищаемся: от смерти
        процесса (`os._exit` из watchdog, SIGKILL по группе от раннера).
        Вытолкнутые данные в этих случаях уже в странице кэша ядра и
        переживают гибель процесса; `fsync` спасал бы только от отказа машины,
        а его цена линейна по числу тестов. Замерено на 86 тестах: с fsync
        накладные +0.25 с (≈2.9 мс на тест), то есть на полном наборе ~7000
        тестов это две-три десятка секунд, потраченных на гарантию, которая
        здесь не нужна.

        Дескриптор открывается ОДИН раз на сессию: переоткрытие файла на
        каждое из ~21000 событий полного набора — это ещё три системных
        вызова на запись без всякой пользы.
        """
        if self.events_path is None:
            return
        line = json.dumps(payload, ensure_ascii=False) + "\n"
        # Замок берётся с бюджетом, а не намертво. Watchdog обязан дописать
        # свою запись даже если основной поток застрял внутри `_append`:
        # иначе сторож, поставленный ловить зависания, сам зависает на замке —
        # и таймаут не срабатывает вообще. Возможная перемешанная строка
        # безопасна: `read_events` пропускает неразбираемые строки, а потерять
        # запись о таймауте нельзя.
        acquired = self._lock.acquire(timeout=lock_timeout) if lock_timeout else self._lock.acquire()
        try:
            if self._events_handle is None:
                self._events_handle = open(self.events_path, "a", encoding="utf-8")
            self._events_handle.write(line)
            self._events_handle.flush()
        finally:
            if acquired:
                self._lock.release()

    # ── hooks ─────────────────────────────────────────────────────────
    def pytest_runtest_logstart(self, nodeid: str, location) -> None:  # noqa: ARG002
        self._current = nodeid
        self._started_at = time.monotonic()
        # Старт ноды публикуется в журнал: при исчерпании WALL-бюджета процесс
        # снимает раннер снаружи, watchdog не срабатывает, и без этой записи
        # активная нода осталась бы неизвестной. §7 требует node ID и в этом
        # случае тоже.
        self._append({"event": "test_start", "nodeid": nodeid})
        self._arm(nodeid)

    def pytest_runtest_logfinish(self, nodeid: str, location) -> None:  # noqa: ARG002
        self._disarm()
        self._append({"event": "test_finish", "nodeid": nodeid})
        self._current = None

    def pytest_runtest_logreport(self, report) -> None:
        self._append(
            {
                "event": "report",
                "nodeid": report.nodeid,
                "when": report.when,
                "outcome": report.outcome,
                "duration": round(getattr(report, "duration", 0.0) or 0.0, 4),
                # `longrepr` не публикуется. Bible объявляет traceback
                # непроверенным вводом, а журнал ни одним потребителем его не
                # читал: сборщик JUnit строит отчёт из исходов, не из текста
                # падения. Поле было чистой обузой — измерено, туда уезжал
                # `customer_password=…` из assert-сообщения. Не чистим, а не
                # публикуем: непубликуемое поле не может протечь.
            }
        )

    def pytest_sessionstart(self, session) -> None:  # noqa: ARG002
        self._append({"event": "session_start", "lane": self.lane, "budget": self.budget})

    def pytest_sessionfinish(self, session, exitstatus) -> None:  # noqa: ARG002
        self._disarm()
        self._append({"event": "session_finish", "exitstatus": int(exitstatus)})
        with self._lock:
            handle, self._events_handle = self._events_handle, None
        if handle is not None:
            try:
                handle.close()
            except OSError:
                pass

    def pytest_collection_modifyitems(self, session, config, items) -> None:  # noqa: ARG002
        self._append({"event": "collected", "count": len(items)})

    def pytest_deselected(self, items) -> None:
        """§8 требует поле `deselected` в receipt.

        В JUnit этого числа нет вообще, а разбирать stdout pytest — значит
        зависеть от формата сообщения. Хук отдаёт его напрямую; он может
        вызываться несколько раз, поэтому раннер суммирует записи.
        """
        self._append({"event": "deselected", "count": len(items)})

    # ── watchdog ──────────────────────────────────────────────────────
    def _arm(self, nodeid: str) -> None:
        self._disarm()
        if self.budget <= 0:
            return
        timer = threading.Timer(self.budget, self._on_timeout, args=(nodeid,))
        timer.daemon = True
        timer.start()
        self._timer = timer

    def _disarm(self) -> None:
        timer, self._timer = self._timer, None
        if timer is not None:
            timer.cancel()

    def _on_timeout(self, nodeid: str) -> None:
        elapsed = time.monotonic() - self._started_at
        children = child_processes()
        dump = sanitize_traceback(thread_dump())
        cleanup = terminate_children(children)
        payload = {
            "event": "timeout",
            "lane": self.lane,
            "nodeid": nodeid,
            "budget_seconds": self.budget,
            "elapsed_seconds": round(elapsed, 3),
            "proc_available": Path("/proc").is_dir(),
            "children": children,
            "child_cleanup": cleanup,
            "thread_dump": dump,
        }
        # Диагностика пишется ДВАЖДЫ: в журнал событий (там её увидит сборщик
        # JUnit) и в отдельный файл (его читает человек и CI-артефакт).
        self._append(payload, lock_timeout=2.0)
        if self.diag_path is not None:
            try:
                self.diag_path.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            except OSError:
                pass
        # На stderr — коротко и по делу: node ID и lane обязаны быть видны в
        # логе job'а без раскапывания артефактов.
        print(
            f"\n[ci-timeout] lane={self.lane} node={nodeid} "
            f"бюджет {self.budget:g} s исчерпан (прошло {elapsed:.1f} s); "
            f"дочерних процессов {len(children)}, "
            f"terminate {cleanup['terminated']}, kill {cleanup['killed']}",
            file=sys.stderr,
            flush=True,
        )
        print(dump, file=sys.stderr, flush=True)
        os._exit(EXIT_TIMEOUT)


def pytest_configure(config) -> None:
    """Точка входа плагина. Регистрируется только при явном `-p`."""
    config.pluginmanager.register(LaneTimeoutPlugin(), "ci-lane-timeout")
