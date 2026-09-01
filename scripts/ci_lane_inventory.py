#!/usr/bin/env python3
"""Инвентаризация test lanes по контракту `quality-runtime/v1` (§5).

Зачем:
    §5 контракта `docs/architecture/QUALITY_RUNTIME_CONTRACT_V1.md` требует,
    чтобы каждый Python test node нёс РОВНО ОДИН primary lane marker, и прямо
    называет непомеченный либо дважды помеченный node inventory failure. На
    момент W0-OPS-03 части 1 размечено 11 нод из ~7082 (квитанция
    `docs/architecture/receipts/W0-OPS-03-part1.json`), а находка OPS03-F2
    зафиксировала главное: объём разметки определяется ФАКТИЧЕСКИМ поведением
    тестов, а не существующими маркерами. Правило «slow ⇒ network» верно, но
    покрывает лишь два модуля из репозитория.

    Этот инструмент — доказательство объёма, а не разметка. Он статически (без
    единого запуска pytest) выводит lane каждого тестового модуля из
    наблюдаемых в исходнике признаков и сравнивает вывод с проставленными
    маркерами. Он НИЧЕГО не правит: ни тестов, ни `pytest.ini`, ни workflow.
    Разметка ~7000 нод — отдельное решение с отдельной приёмкой; без числа,
    полученного здесь, это решение принимать не на чем.

Интерфейс:

    python scripts/ci_lane_inventory.py [PATH ...]

        --json               машиночитаемый отчёт на stdout
        --evidence-sha256    SHA-256 канонического отчёта без root/времени
        --fail-on-unmarked   ненулевой код возврата при inventory failure
        --samples N          сколько примеров показывать в человеческом выводе

    По умолчанию exit 0 ВСЕГДА: W0-OPS-03 не включает enforce, а инструмент,
    который валит CI до того, как разметка сделана, просто выключат. Флаг
    `--fail-on-unmarked` — это будущий enforce, готовый к включению тем, кто
    закончит materialization.

Правило вывода lane (откуда взят каждый признак)
------------------------------------------------
Каскад проверяется СВЕРХУ ВНИЗ, первое совпадение выигрывает; порядок повторяет
порядок «тяжести» side effects в таблице §5 (chaos ⊃ network ⊃ integration ⊃
contract ⊃ unit), поэтому модуль всегда попадает в самый требовательный lane из
тех, чьи признаки в нём найдены.

1. `chaos` — §5: «recovery после SIGTERM/SIGKILL и restart». Требуются ОБА
   признака: (а) сигнал живому процессу — `os.kill`/`os.killpg`/`.send_signal`/
   `.sigkill()`/`.sigterm()`/`.kill()` либо любой вызов, среди аргументов
   которого стоит `signal.SIGKILL`/`signal.SIGTERM` (так написан
   `_stop(first, sig=signal.SIGKILL)` в `tests/test_distributed_workers_executor.py`);
   и (б) повторный запуск ПОСЛЕ убийства в той же функции — `subprocess.Popen`
   (`tests/test_distributed_workers_prepipeline_gate.py:1608`), фабрика класса
   `GatewayProcess.start(...)` (`tests/test_process_chaos_12e.py:82`) или вызов
   с корнем `spawn/restart/relaunch/revive/launch` (`_spawn_executor(...)`).
   Убийство БЕЗ повторного запуска — это cleanup дочернего процесса, который §5
   разрешает lane `network` («process spawn/cleanup»), поэтому такой модуль
   уходит в `network` и помечается «нужна ручная классификация».
2. `network` — §5: «реальный HTTP/gRPC/socket/process lifecycle». Признаки:
   `subprocess.Popen/run/check_output/check_call/call`, `socket.socket`/
   `socket.create_connection` (и методы `bind/connect/listen/accept`, если
   модуль импортирует `socket`), grpc-каналы и порты (`grpc.insecure_channel`,
   `grpc.aio.insecure_channel`, `add_insecure_port`, `grpc.server` — так устроен
   `tests/test_agent_gateway_12b.py`), любое обращение к `uvicorn`
   (`tests/test_distributed_workers_prepipeline_gate.py` поднимает его аргументом
   `--port`), `os.killpg`, а также импорт первопартийного класса-сервера
   (`from backend.app.agent_gateway.server import GatewayServer`): сокет
   открывает production-код, поэтому такой модуль отдельно помечается
   «нужна ручная классификация».
3. `integration` — §5: «изолированный FS, threads, provisioned local services».
   Признаки-решающие: `TestClient(...)` из fastapi/starlette (42 модуля),
   in-process ASGI-транспорт (`httpx.ASGITransport`, `SyncASGITransport` из
   `tests/distributed_workers_helpers.py`), рабочие потоки
   (`threading.Thread/Timer`, `ThreadPoolExecutor`, `ProcessPoolExecutor`,
   `asyncio.to_thread`, `run_in_executor`, `anyio.to_thread`), запись в ФС
   (`.write_text/.write_bytes/.mkdir/.touch/.unlink/.rename`, `open(..., "w")`,
   `os.makedirs`, `shutil.copy*/move/rmtree`, `tempfile.mkdtemp`,
   `tarfile.open`, `zipfile.ZipFile`, `sqlite3.connect`). ФС попала в
   `integration`, потому что §5 определяет `unit` как «только память»: тест,
   создающий файлы, под это определение не подходит.
4. `contract` — §5: «schema/version/provider-consumer compatibility», побочные
   эффекты «temp files и bounded local compiler process; без service/network».
   Признаки: импорт пакета `contracts` (28 модулей), строковые литералы с
   путями `contracts/`, `*.proto`, `*.schema.json`, `*_CONTRACT_V1.md`,
   `openapi` — так работает `tests/test_domain_contract_v1.py`, который сверяет
   `contracts/domain/v1/**` с markdown-источником. Этот шаг стоит ПОСЛЕ
   `integration` по сервисам/потокам, но ПЕРЕД шагом «только запись в ФС»:
   §5 разрешает contract-тесту временные файлы, поэтому запись сама по себе не
   выталкивает contract-тест в `integration`.
5. `unit` — §5: «только память; часы/random через fake». Ни одного решающего
   признака выше не найдено.

Чья это улика (приписывание признака ноде)
------------------------------------------
§5 требует маркер ПО НОДЕ, поэтому и сверять маркер надо с поведением НОДЫ, а не
файла. Признак достаётся ноде, только если она до него дотягивается:

* признак из тела теста — его собственный;
* признак из фикстуры — только тем нодам, которые эту фикстуру ЗАПРОСИЛИ:
  параметром функции, `@pytest.mark.usefixtures` (в т.ч. на классе и в
  `pytestmark`) или транзитивно, через фикстуру, запросившую другую фикстуру.
  Autouse-фикстура достаётся всем нодам своей области видимости — так работает
  pytest, и это правильно;
* признак helper-а (в этом же файле или в импортированном модуле тестов) —
  только тем, кто этот helper зовёт;
* признак уровня модуля (`import httpx` в шапке, константа `PROTO = "…proto"`)
  сам по себе НЕ решает ничего: импорт — это возможность, а не поведение.
  Он достаётся ноде, только если введённое им имя реально упомянуто в её теле,
  в её фикстуре или в вызванном ею helper-е.

До W0-OPS-03 части 3 приписывание было другим: любой признак фикстуры, helper-а
или шапки доставался ВСЕМ нодам файла. Проверяемый промах —
`tests/test_distributed_workers_central_handoff.py::
test_prompt_without_section_does_not_become_eom`: тест без единой фикстуры,
зовущий два чистых вычисления, получал `unit → integration` с уликами фикстуры
`center_env` (строка 68) и `httpx.ASGITransport` (строка 194).

Сводка `lanes` по-прежнему считается ПО МОДУЛЮ (максимум по файлу) и отвечает на
другой вопрос — «что в этом файле вообще есть».

Слабые признаки (`supporting`) в решение НЕ входят никогда: литерал
`127.0.0.1`/`localhost` (в `tests/test_distributed_workers_hardening.py` это
разбираемая строка, а не адрес соединения), `pytest.mark.asyncio` и голый
`asyncio.run` без воркеров, `protocol_version`-подобные идентификаторы. Они
попадают в отчёт как контекст для человека.

Что инструмент НЕ решает и честно помечает «нужна ручная классификация»
----------------------------------------------------------------------
* убийство процесса без доказательства перезапуска (chaos или network cleanup);
* модуль подменяет ту же API, следы которой найдены (`monkeypatch.setattr`,
  `mock.patch`): статически не видно, остаётся ли настоящий вызов на каком-то
  пути;
* решение опирается ТОЛЬКО на признаки, унаследованные из общего helper-модуля
  (`tests/distributed_workers_helpers.py`, `tests/chaos_harness_12e.py`):
  импорт помощника не доказывает, что каждый тест модуля им пользуется;
* динамический импорт/`getattr` рядом с признаками — цель вызова не видна;
* lane решён импортом первопартийного класса-сервера, чей сокет живёт в
  production-коде (`GatewayServer`), а не в теле теста;
* модуль не разобрался (`SyntaxError`) — lane неизвестен.

Границы метода (не лечатся никаким статическим анализом)
--------------------------------------------------------
* Приписывание признака ноде (раздел выше) — статическое, поэтому огрубляет в
  ОБЕ стороны, и обе стороны названы честно:
  — вверх: связь «нода → helper» ищется по УПОМИНАНИЮ имени, а не по факту
    вызова на исполняемом пути; класс тянет признаки всех своих методов;
  — вниз: фикстуры из `conftest.py` не разбираются вовсе (см. оговорку ниже),
    поэтому нода, чей lane создаёт conftest-фикстура, выглядит легче, чем есть.
    Верхняя оценка по корню: у 77 конфликтных нод из 1661 есть запрошенное имя,
    которого нет среди фикстур модуля и среди builtin-фикстур pytest. Настоящих
    среди них меньше — часть этих имён аргументы `parametrize`, а не фикстуры.
* Нода без единого решающего признака получает `unit`. Это самое слабое
  утверждение инструмента: production-код не разбирается (см. ниже), поэтому
  «признаков не нашлось» и «побочных эффектов нет» — не одно и то же.
* `tests/conftest.py` на импорте копирует `backend/app/data` в песочницу
  (`_seed_app_data_sandbox`), а autouse-фикстуры трогают ФС у КАЖДОГО теста.
  Эти эффекты не подмешиваются в per-module вывод — иначе весь корень стал бы
  `integration` и различия исчезли бы; они вынесены в отдельный раздел отчёта.
* Реальность сети за третьими библиотеками не видна: `httpx.AsyncClient` с
  ASGI-транспортом и он же с настоящим URL выглядят одинаково.
* Production-код (`backend/`, `audit_worker/`) НЕ разбирается: если тест зовёт
  функцию, которая внутри открывает сокет или порождает процесс, признака в
  тесте нет. Разбирать его нельзя — почти каждый тест импортирует `backend`, и
  тогда весь репозиторий стал бы `network`. Частичное лечение — узкое правило
  про класс-сервер выше; остальное остаётся принципиальной слепой зоной.
* `parametrize` разворачивает функцию в несколько нод; здесь считается ОЦЕНКА
  снизу по литеральным спискам аргументов, а не настоящий сбор pytest.
* `skipif`/`importorskip` могут снять модуль целиком — поведение lane при этом
  не меняется, но фактический прогон меняется.
* Признак из строкового литерала берётся только с токена без пробелов и НИКОГДА
  из докстроки: проза о поведении поведением не является. Обратная сторона —
  вызов, спрятанный в собранную по кускам команду, не будет виден.

Только стандартная библиотека: новых зависимостей не вводится (root
requirements принадлежат W0-INT-01), разбор — через `ast`.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator

ROOT = Path(__file__).resolve().parent.parent

CONTRACT_DOC = "docs/architecture/QUALITY_RUNTIME_CONTRACT_V1.md"
CONTRACT_SECTION = "§5"
#: Версия семантики отчёта. Поднята до "3" в W0-OPS-03 части 3: признак
#: приписывается КОНКРЕТНОЙ ноде (фикстура — только запросившим, импорт — только
#: упомянувшим, helper — только зовущим), поэтому `--evidence-sha256` того же
#: дерева отличается от отпечатка версии "2" законно, а не из-за дрейфа тестов.
TOOL_VERSION = "3"

#: §5: пять primary lanes. Порядок = порядок каскада вывода (тяжёлые первыми).
PRIMARY_LANES: tuple[str, ...] = ("chaos", "network", "integration", "contract", "unit")
#: §5 дословно: «`slow` — ортогональный атрибут, не lane». Сюда же провайдерские
#: и корпусные атрибуты — контракт называет их атрибутами, а не lanes.
ORTHOGONAL_MARKERS: frozenset[str] = frozenset(
    {"slow", "provider", "live", "corpus", "e2e"}
)
#: Маркеры pytest, к разметке lanes отношения не имеющие (шум при подсчёте).
NON_LANE_MARKERS: frozenset[str] = frozenset(
    {"parametrize", "skip", "skipif", "xfail", "usefixtures", "filterwarnings",
     "asyncio", "anyio", "timeout", "order", "dependency"}
)

LANE_UNKNOWN = "unknown"

# ---------------------------------------------------------------------------
# Таблицы признаков
# ---------------------------------------------------------------------------
# Каждая запись — то, что РЕАЛЬНО встречается в tests/ и backend/tests/; списки
# собраны обходом репозитория, а не по памяти. Ссылки на модули-примеры даны в
# докстроке выше, чтобы правило можно было перепроверить.

#: Точные dotted-имена вызовов, доказывающих запуск дочернего процесса.
SPAWN_CALLS: frozenset[str] = frozenset(
    {
        "subprocess.Popen",
        "subprocess.run",
        "subprocess.call",
        "subprocess.check_call",
        "subprocess.check_output",
        "subprocess.getoutput",
        "subprocess.getstatusoutput",
        "multiprocessing.Process",
        "os.system",
        "os.execv",
        "os.spawnv",
        "os.posix_spawn",
    }
)
#: §5 разрешает `contract`-тесту «bounded local compiler process» и прямо выдаёт
#: ему capability «process spawn если test явно компилирует contract». Признак
#: берётся ТОЛЬКО из аргументов самого вызова: так устроен
#: `tests/test_agent_stream_protocol_v1.py:132` — `[sys.executable, "-m",
#: "grpc_tools.protoc", …]`.
CONTRACT_COMPILER_RE = re.compile(
    r"\bprotoc\b|grpc_tools|\bmypy\b|openapi-generator|datamodel-code", re.IGNORECASE
)
#: Настоящие сокеты. Методы `bind/connect/...` учитываются отдельно и только
#: если модуль импортировал `socket`: голый `.connect(` — это ещё и `sqlite3`.
SOCKET_CALLS: frozenset[str] = frozenset(
    {"socket.socket", "socket.create_connection", "socket.socketpair", "socket.create_server"}
)
SOCKET_METHODS: frozenset[str] = frozenset(
    {"bind", "listen", "accept", "create_connection", "setsockopt", "getsockname"}
)
#: gRPC: канал/сервер/порт — это реальный сетевой lifecycle (§5 network).
GRPC_CALLS: frozenset[str] = frozenset(
    {
        "grpc.insecure_channel",
        "grpc.secure_channel",
        "grpc.server",
        "grpc.aio.insecure_channel",
        "grpc.aio.secure_channel",
        "grpc.aio.server",
    }
)
GRPC_METHODS: frozenset[str] = frozenset({"add_insecure_port", "add_secure_port"})
#: Сигналы живому процессу.
KILL_CALLS: frozenset[str] = frozenset({"os.kill", "os.killpg"})
KILL_METHODS: frozenset[str] = frozenset(
    {"send_signal", "sigkill", "sigterm", "killpg"}
)
#: `Popen.kill()` — это SIGKILL по семантике stdlib, поэтому метод в списке.
KILL_METHODS_HARD: frozenset[str] = frozenset({"kill"})
#: Имена сигналов, присутствие которых В АРГУМЕНТАХ вызова означает убийство.
KILL_SIGNAL_NAMES: frozenset[str] = frozenset({"SIGKILL", "SIGTERM", "SIGQUIT", "SIGABRT"})
#: Повторный запуск после убийства (доказательство «restart» из §5 chaos).
RESPAWN_NAME_RE = re.compile(r"spawn|restart|relaunch|revive|launch|reboot", re.IGNORECASE)

#: In-process HTTP-клиенты поверх ASGI: настоящего сокета нет, но есть портал с
#: рабочим потоком и живое приложение — это `integration`, не `network`.
ASGI_CALLS: frozenset[str] = frozenset(
    {"TestClient", "ASGITransport", "SyncASGITransport", "httpx.ASGITransport"}
)
#: Рабочие потоки/исполнители. §5 integration: «threads».
WORKER_CALLS: frozenset[str] = frozenset(
    {
        "threading.Thread",
        "threading.Timer",
        "ThreadPoolExecutor",
        "ProcessPoolExecutor",
        "concurrent.futures.ThreadPoolExecutor",
        "concurrent.futures.ProcessPoolExecutor",
        "asyncio.to_thread",
        "anyio.to_thread.run_sync",
    }
)
WORKER_METHODS: frozenset[str] = frozenset({"run_in_executor"})
#: Запись в файловую систему. §5: `unit` — «только память».
FS_WRITE_CALLS: frozenset[str] = frozenset(
    {
        "os.makedirs",
        "os.mkdir",
        "os.remove",
        "os.unlink",
        "os.rename",
        "os.replace",
        "os.symlink",
        "os.link",
        "os.chmod",
        "os.truncate",
        "shutil.copy",
        "shutil.copy2",
        "shutil.copyfile",
        "shutil.copytree",
        "shutil.move",
        "shutil.rmtree",
        "shutil.make_archive",
        "shutil.unpack_archive",
        "tempfile.mkdtemp",
        "tempfile.mkstemp",
        "tempfile.NamedTemporaryFile",
        "tempfile.TemporaryDirectory",
        "tarfile.open",
        "zipfile.ZipFile",
        "sqlite3.connect",
    }
)
FS_WRITE_METHODS: frozenset[str] = frozenset(
    {"write_text", "write_bytes", "mkdir", "touch", "unlink", "rmdir", "rename", "replace"}
)
#: Режимы `open()`, означающие запись.
WRITE_MODE_RE = re.compile(r"[wax+]")

#: Contract-признаки: путь к артефакту контракта в строковом литерале.
CONTRACT_PATH_RE = re.compile(
    r"(?:^|/)contracts/|\.proto\b|\.schema\.json\b|_CONTRACT(?:_V\d+)?\.md\b|openapi",
    re.IGNORECASE,
)
#: Импорт пакета контрактов — самый прямой признак provider-consumer теста.
CONTRACT_PACKAGES: frozenset[str] = frozenset({"contracts"})
#: Слабый признак «сверка версий»: сам по себе lane не определяет.
CONTRACT_VERSION_RE = re.compile(
    r"\b(?:protocol_version|schema_version|contract_version|CONTRACT_VERSION"
    r"|PROTOCOL_VERSION|SCHEMA_VERSION)\b"
)

#: Слабый признак: loopback-адрес в литерале. В hardening-тестах это разбираемая
#: строка, а не соединение, поэтому решающим он быть не может.
LOOPBACK_RE = re.compile(r"127\.0\.0\.1|localhost|\[::1\]|0\.0\.0\.0")
#: Настоящий HTTP-сервер: `uvicorn` в импорте, вызове или командной строке.
UVICORN_RE = re.compile(r"\buvicorn\b")
#: Строковый литерал считается поведением, только если похож на путь или аргумент
#: командной строки, то есть не содержит пробелов. Правило появилось после
#: реального промаха: докстрока `tests/distributed_workers_helpers.py:166` («для
#: ОТДЕЛЬНОГО процесса (uvicorn, smoke)») уводила два модуля в `network`.
#: Настоящий запуск выглядит иначе — `[PY, "-m", "uvicorn", ...]`, отдельный
#: токен без пробелов. Упоминание в прозе поведением не является.
TOKEN_LITERAL_RE = re.compile(r"^\S+$")

#: Первопартийные пакеты репозитория: их код инвентарь НЕ разбирает (иначе
#: `backend` со своими сокетами утянул бы в `network` вообще всё), но имя
#: импортированного из них класса-сервера — законный признак.
FIRST_PARTY_PACKAGES: frozenset[str] = frozenset(
    {"backend", "audit_worker", "contracts", "scripts", "norms", "tools", "deploy"}
)
#: Класс-сервер, поднимаемый тестом: сокет открывается в production-коде, в самом
#: тесте его не видно. Так устроен `tests/test_agent_grpc_client_12c.py` —
#: `GatewayServer.start()` внутри зовёт `grpc.aio.server` и `add_insecure_port`.
#: Признак узкий: по репозиторию срабатывает на трёх модулях.
FIRST_PARTY_SERVER_RE = re.compile(r"(?:Server|Gateway|Daemon|Listener)$")

#: API, подмена которых делает статический вывод недоказуемым.
PATCHABLE_APIS: frozenset[str] = frozenset(
    {"subprocess", "socket", "httpx", "grpc", "uvicorn", "os.kill", "threading", "shutil"}
)
PATCH_CALLS: frozenset[str] = frozenset(
    {"monkeypatch.setattr", "monkeypatch.setitem", "mock.patch", "patch", "patch.object",
     "unittest.mock.patch", "setattr"}
)
#: Динамика: цель вызова статически не видна.
DYNAMIC_CALLS: frozenset[str] = frozenset(
    {"importlib.import_module", "getattr", "__import__", "eval", "exec"}
)

#: Имена функций-уборщиков: сигнал внутри них — это cleanup из §5 network, а не
#: chaos. Тестовые функции (`test_*`) исключены: там убийство — часть сценария.
TEARDOWN_NAME_RE = re.compile(
    r"(?:^|_)(?:stop|teardown|cleanup|close|shutdown|terminate|finalize|dispose)"
    r"|^__exit__$",
    re.IGNORECASE,
)

#: Причины «нужна ручная классификация» → человекочитаемый текст.
MANUAL_REASONS: dict[str, str] = {
    "KILL_WITHOUT_RESTART": (
        "сигнал живому процессу есть, доказательства перезапуска нет: "
        "chaos (§5 «recovery … и restart») или cleanup внутри network"
    ),
    "PATCHED_API": "модуль подменяет ту же API, следы которой найдены — настоящий вызов не доказан",
    "INHERITED_ONLY": "решение держится только на признаках из общего helper-модуля",
    "DYNAMIC_DISPATCH": "рядом с признаками есть динамический импорт/getattr — цель вызова не видна",
    "NO_TEST_FUNCTIONS": "в модуле не найдено ни одной test-функции",
    "PARSE_ERROR": "модуль не разобрался, lane неизвестен",
    "PRODUCTION_SIDE_IO": (
        "lane решён импортом первопартийного класса-сервера: сокет открывает "
        "production-код, из теста он не виден — вывод стоит подтвердить глазами"
    ),
}

EXIT_OK = 0
EXIT_INVENTORY_FAILURE = 1
EXIT_USAGE = 2


# ---------------------------------------------------------------------------
# Структуры данных
# ---------------------------------------------------------------------------


@dataclass
class Evidence:
    """Один наблюдаемый признак.

    `deciding=False` означает «в решение не входит»: такие признаки печатаются
    как контекст, но никогда не двигают lane — иначе строка `"localhost"` в
    таблице параметров превратила бы unit-тест в network.
    """

    lane: str
    kind: str
    lineno: int
    detail: str
    deciding: bool = True
    inherited_from: str | None = None
    #: Имя объемлющей test-функции, если признак найден прямо в её теле. `None`
    #: означает «общий для модуля»: тело фикстуры, helper, импорт, тело класса.
    #: Разделение нужно, потому что §5 требует маркер ПО НОДЕ, а не по файлу.
    owner: str | None = None
    #: Ключ определения верхнего уровня, в теле которого признак найден:
    #: `"имя_функции"`, `"Класс"` или `"Класс::метод"`. `None` — уровень модуля
    #: (импорт, константа). Признак достаётся ноде, только если это определение
    #: достижимо из ноды: сама нода, запрошенная ею фикстура (в т.ч. транзитивно
    #: и autouse) или вызванный из них helper.
    scope: str | None = None
    #: Имена, которые вводит в модуль признак уровня модуля (`import httpx` →
    #: `("httpx",)`, `PROTO = "x.proto"` → `("PROTO",)`). Импорт — это
    #: ВОЗМОЖНОСТЬ, а не поведение: такой признак достаётся ноде, только если имя
    #: реально упомянуто в её теле, фикстуре или helper-е.
    binds: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "lane": self.lane,
            "kind": self.kind,
            "line": self.lineno,
            "detail": self.detail,
            "deciding": self.deciding,
        }
        if self.inherited_from:
            payload["inherited_from"] = self.inherited_from
        if self.owner:
            payload["owner"] = self.owner
        return payload


@dataclass
class TestNode:
    """Test-функция как единица разметки §5 (маркер требуется именно тут)."""

    name: str
    lineno: int
    markers: tuple[str, ...]
    primary: tuple[str, ...]
    orthogonal: tuple[str, ...]
    param_factor: int
    param_dynamic: bool
    #: Lane, выведенный ДЛЯ ЭТОЙ ноды: признаки её тела плюс признаки тех
    #: фикстур и helper-ов, до которых нода реально дотягивается. Заполняется
    #: после разбора, в `analyse_module`.
    inferred_lane: str = LANE_UNKNOWN
    #: Ключ определения ноды (`"test_x"` или `"TestGroup::test_x"`).
    scope_key: str = ""
    #: Признаки, решившие lane ИМЕННО ЭТОЙ ноды (не всего файла).
    decided_by: list[Evidence] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "line": self.lineno,
            "markers": list(self.markers),
            "primary_lane_markers": list(self.primary),
            "orthogonal_markers": list(self.orthogonal),
            "inferred_lane": self.inferred_lane,
            "estimated_nodes": self.param_factor,
            "parametrize_dynamic": self.param_dynamic,
        }


@dataclass
class Scope:
    """Определение верхнего уровня: тест, фикстура, helper или класс.

    Единица, к которой привязывается признак. `used` — все имена и атрибуты,
    упомянутые внутри (по ним видно, какой helper зовут и какой импорт реально
    используют); `requests` — запрошенные фикстуры (параметры функции и
    `usefixtures`).
    """

    key: str
    kind: str  # test | fixture | helper | class
    lineno: int
    used: set[str] = field(default_factory=set)
    requests: set[str] = field(default_factory=set)


@dataclass
class ScanResult:
    """Сырой результат разбора одного файла (до вывода lane)."""

    evidence: list[Evidence] = field(default_factory=list)
    nodes: list[TestNode] = field(default_factory=list)
    module_markers: list[str] = field(default_factory=list)
    imports: set[str] = field(default_factory=set)
    local_test_imports: set[str] = field(default_factory=set)
    patched_apis: set[str] = field(default_factory=set)
    dynamic_dispatch: bool = False
    parse_error: str | None = None
    #: Определения верхнего уровня по ключу (см. `Scope`).
    scopes: dict[str, Scope] = field(default_factory=dict)
    #: Имя фикстуры → ключ её определения (учитывает `@pytest.fixture(name=...)`).
    fixtures: dict[str, str] = field(default_factory=dict)
    #: Ключи autouse-фикстур: они достаются КАЖДОЙ ноде своей области видимости.
    autouse_fixtures: set[str] = field(default_factory=set)
    #: `usefixtures` уровня модуля — тоже достаётся каждой ноде.
    module_requests: set[str] = field(default_factory=set)
    #: `from tests.helpers import *`: имена helper-а становятся видны напрямую,
    #: адресно проследить их использование нельзя.
    star_imports: set[str] = field(default_factory=set)


def _compiler_argument(node: ast.Call) -> str | None:
    """Токен компилятора контракта среди литеральных аргументов вызова."""
    for argument in ast.walk(node):
        if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
            found = CONTRACT_COMPILER_RE.search(argument.value)
            if found:
                return argument.value[:40]
    return None


def _contract_side_effects_are_allowed(node: TestNode) -> bool:
    """§5 дословно разрешает `contract`-тесту «temp files и bounded local
    compiler process».

    Каскад ставит `contract` ВЫШЕ шага «только запись в ФС» именно поэтому.
    Пока признак contract-артефакта доставался всем нодам файла, вопрос не
    возникал; после перехода на приписывание по ноде тест, который пишет
    временные файлы (или зовёт `grpc_tools.protoc`) и сам ничего из
    `contracts/**` не трогает, стал выглядеть как `integration`/`network`.
    Маркер `contract` он этим НЕ нарушает — §5 оба side effect разрешил и для
    второго прямо выдал capability «process spawn если test явно компилирует
    contract», поэтому расхождением это не считается.
    """
    if node.primary[:1] != ("contract",) or not node.decided_by:
        return False
    if node.inferred_lane == "integration":
        return all(e.kind in FS_KINDS for e in node.decided_by)
    if node.inferred_lane == "network":
        return all(
            e.kind == "process_spawn" and CONTRACT_COMPILER_RE.search(e.detail)
            for e in node.decided_by
        )
    return False


@dataclass
class ModuleReport:
    """Итог по модулю: что выведено, что размечено и где расхождение."""

    path: str
    inferred_lane: str
    decided_by: list[Evidence]
    evidence: list[Evidence]
    nodes: list[TestNode]
    module_primary: tuple[str, ...]
    manual_review: list[str]
    parse_error: str | None

    # --- производные счётчики -------------------------------------------------
    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def estimated_node_count(self) -> int:
        return sum(node.param_factor for node in self.nodes)

    @property
    def unmarked_nodes(self) -> list[TestNode]:
        return [n for n in self.nodes if not n.primary]

    @property
    def double_marked_nodes(self) -> list[TestNode]:
        return [n for n in self.nodes if len(set(n.primary)) > 1]

    @property
    def conflicting_nodes(self) -> list[TestNode]:
        """Нода с ОДНИМ маркером, который не совпал с её собственным поведением.

        Сравнение идёт с lane САМОЙ НОДЫ, а не всего файла: один модуль
        законно смешивает lanes (в `tests/test_distributed_workers_executor.py`
        часть тестов убивает и поднимает исполнителя, часть — нет), и сверка с
        максимумом по файлу выдавала бы конфликт там, где его нет. Именно
        поэтому смешение полос в файле само по себе НЕ повод для ручного
        разбора: риск живёт на уровне ноды и ловится здесь.

        Направление расхождения (`direction` в отчёте) означает разное:
        маркер легче поведения — тест поедет в лёгкой полосе и сломает её
        бюджет §7; маркер тяжелее — тест едет дороже, чем нужно, чаще всего
        из-за `pytestmark`, накрывшего файл целиком.
        """
        return [
            n
            for n in self.nodes
            if len(set(n.primary)) == 1
            and n.inferred_lane != LANE_UNKNOWN
            and n.primary[0] != n.inferred_lane
            and not _contract_side_effects_are_allowed(n)
        ]

    @property
    def marked_nodes(self) -> list[TestNode]:
        return [n for n in self.nodes if n.primary]

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "inferred_lane": self.inferred_lane,
            "inferred_node_lanes": sorted({n.inferred_lane for n in self.nodes}),
            "decided_by": [e.as_dict() for e in self.decided_by],
            "evidence": [e.as_dict() for e in self.evidence],
            "marker_lanes_present": sorted({m for n in self.nodes for m in n.primary}
                                           | set(self.module_primary)),
            "test_functions": self.node_count,
            "estimated_nodes": self.estimated_node_count,
            "unmarked_functions": len(self.unmarked_nodes),
            "double_marked_functions": [n.name for n in self.double_marked_nodes],
            "conflicting_functions": [
                {"name": n.name, "marker": n.primary[0], "inferred": n.inferred_lane}
                for n in self.conflicting_nodes
            ],
            "manual_review": self.manual_review,
            "parse_error": self.parse_error,
            "nodes": [n.as_dict() for n in self.nodes],
        }


# ---------------------------------------------------------------------------
# Разбор
# ---------------------------------------------------------------------------


def _dotted(node: ast.AST) -> str | None:
    """Dotted-имя выражения. `a.b.c` → "a.b.c", `f().b` → "*.b"."""
    parts: list[str] = []
    current: ast.AST = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
        return ".".join(reversed(parts))
    if parts:
        return "*." + ".".join(reversed(parts))
    return None


def _marker_name(node: ast.AST) -> str | None:
    """Имя маркера из декоратора/значения `pytestmark`.

    Понимает `pytest.mark.x`, `pytest.mark.x(...)` и голый `mark.x`; всё
    остальное (вычисляемые маркеры) осознанно игнорируется — угадывать нельзя.
    """
    if isinstance(node, ast.Call):
        return _marker_name(node.func)
    dotted = _dotted(node)
    if not dotted:
        return None
    parts = dotted.split(".")
    if len(parts) >= 2 and parts[-2] == "mark":
        return parts[-1]
    return None


def _iter_marker_nodes(value: ast.AST) -> Iterator[ast.AST]:
    """`pytestmark` может быть одним маркером или списком/кортежем."""
    if isinstance(value, (ast.List, ast.Tuple)):
        yield from value.elts
    else:
        yield value


def _parametrize_factor(decorator: ast.AST) -> tuple[int, bool]:
    """Оценка снизу числа нод, порождаемых `parametrize`.

    Считается только литеральный список/кортеж значений: вычисляемый набор
    (генератор, переменная, `pytest.param` из функции) честно помечается
    `dynamic` и множителя не даёт. Настоящий сбор pytest здесь не эмулируется.
    """
    if not isinstance(decorator, ast.Call):
        return 1, False
    if _marker_name(decorator) != "parametrize":
        return 1, False
    positional = [a for a in decorator.args]
    if len(positional) < 2:
        return 1, True
    values = positional[1]
    if isinstance(values, (ast.List, ast.Tuple, ast.Set)):
        return max(1, len(values.elts)), False
    return 1, True


def _assign_targets(targets: Iterable[ast.AST]) -> set[str]:
    """Имена, которым присваивается значение (включая распаковку кортежа)."""
    names: set[str] = set()
    for target in targets:
        for sub in ast.walk(target):
            if isinstance(sub, ast.Name):
                names.add(sub.id)
    return names


def _usefixtures_names(decorators: Iterable[ast.AST]) -> set[str]:
    """Имена из `@pytest.mark.usefixtures("a", "b")`.

    §5 требует маркер по ноде, а `usefixtures` — второй (после параметра
    функции) законный способ ноды запросить фикстуру, поэтому его признаки
    достаются ей так же, как признаки параметра.
    """
    names: set[str] = set()
    for decorator in decorators:
        if not isinstance(decorator, ast.Call):
            continue
        if _marker_name(decorator) != "usefixtures":
            continue
        for argument in decorator.args:
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                names.add(argument.value)
    return names


def _parameter_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Параметры функции — то, что pytest подставит фикстурами."""
    args = node.args
    names = {
        a.arg
        for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)
        if a.arg not in {"self", "cls"}
    }
    return names


def _fixture_decorator(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> tuple[str | None, bool]:
    """`(имя фикстуры, autouse)` или `(None, False)`, если это не фикстура.

    Понимает `@pytest.fixture`, `@pytest.fixture(...)`, голый `@fixture` и
    `@pytest_asyncio.fixture`, а также переименование `name=`.
    """
    for decorator in node.decorator_list:
        call = decorator if isinstance(decorator, ast.Call) else None
        target = call.func if call is not None else decorator
        dotted = _dotted(target) or ""
        tail = dotted.rsplit(".", 1)[-1]
        if tail not in {"fixture", "yield_fixture"}:
            continue
        name = node.name
        autouse = False
        if call is not None:
            for keyword in call.keywords:
                if keyword.arg == "name" and isinstance(keyword.value, ast.Constant):
                    if isinstance(keyword.value.value, str):
                        name = keyword.value.value
                elif keyword.arg == "autouse":
                    autouse = bool(
                        isinstance(keyword.value, ast.Constant) and keyword.value.value
                    )
        return name, autouse
    return None, False


class _ModuleScanner(ast.NodeVisitor):
    """Сбор признаков и маркеров одного файла.

    Контекст, который приходится тащить руками:
      * стек функций — чтобы понять, где случился вызов (тест или уборщик);
      * флаг `finally` — сигнал в `finally` это cleanup, а не chaos-сценарий;
      * стек классов — тесты живут и в `class Test*`.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.result = ScanResult()
        self._func_stack: list[str] = []
        self._class_stack: list[str] = []
        self._in_finally = 0
        #: id докстрок: проза о поведении — не поведение (см. TOKEN_LITERAL_RE).
        self._docstring_ids: set[int] = set()
        #: (признак, ключ функции, строка) — чтобы доказывать restart ПОСАЙТНО.
        self.kill_sites: list[tuple[Evidence, str, int]] = []
        self.respawn_sites: list[tuple[str, int]] = []
        self._class_markers: list[list[str]] = []
        self._class_requests: list[set[str]] = []
        #: Путь определений (имя, "class"|"func") — из него строится ключ scope.
        self._path: list[tuple[str, str]] = []
        #: Имена, которым присваивается разбираемое сейчас выражение уровня
        #: модуля: `PROTO = "contracts/x.proto"` привязывает признак к `PROTO`.
        self._binds: tuple[str, ...] = ()

    # -- служебное ----------------------------------------------------------
    @property
    def _func_key(self) -> str:
        return "::".join(self._class_stack + self._func_stack) or "<module>"

    @property
    def _scope_key(self) -> str | None:
        """Ключ ближайшего определения верхнего уровня.

        Путь обрезается на ПЕРВОЙ функции: тело вложенной функции принадлежит
        тому же определению, что и её родитель (`helper` внутри фикстуры —
        часть фикстуры). `None` — уровень модуля.
        """
        parts: list[str] = []
        for name, kind in self._path:
            parts.append(name)
            if kind == "func":
                break
        return "::".join(parts) if parts else None

    def _ensure_scope(self, key: str, kind: str, lineno: int) -> Scope:
        scope = self.result.scopes.get(key)
        if scope is None:
            scope = Scope(key=key, kind=kind, lineno=lineno)
            self.result.scopes[key] = scope
        elif kind != "helper" and scope.kind == "helper":
            scope.kind = kind
        return scope

    def _note_symbol(self, name: str) -> None:
        """Запомнить упоминание имени в текущем определении.

        Так становится видно, какой helper нода зовёт и каким импортом она
        реально пользуется (правила 2 и 3 приписывания улик).
        """
        key = self._scope_key
        if key is None:
            return
        scope = self.result.scopes.get(key)
        if scope is not None:
            scope.used.add(name)

    def visit_Name(self, node: ast.Name) -> None:
        self._note_symbol(node.id)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        self._note_symbol(node.attr)
        self.generic_visit(node)

    @property
    def _in_teardown(self) -> bool:
        """Мы внутри `finally` или функции-уборщика (но не внутри теста)."""
        if self._in_finally:
            return True
        for name in self._func_stack:
            if name.startswith("test"):
                return False
            if TEARDOWN_NAME_RE.search(name):
                return True
        return False

    def _add(
        self,
        lane: str,
        kind: str,
        node: ast.AST,
        detail: str,
        *,
        deciding: bool = True,
        binds: tuple[str, ...] | None = None,
    ) -> Evidence:
        owner = self._func_stack[0] if self._func_stack else None
        if owner is not None and not owner.startswith("test"):
            # `owner` — только имя test-функции (совместимость поля в JSON);
            # адресация признака идёт по `scope`.
            owner = None
        scope = self._scope_key
        evidence = Evidence(
            lane,
            kind,
            getattr(node, "lineno", 0),
            detail,
            deciding,
            owner=owner,
            scope=scope,
            binds=(binds if binds is not None else (() if scope else self._binds)),
        )
        self.result.evidence.append(evidence)
        return evidence

    # -- импорты ------------------------------------------------------------
    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.result.imports.add(alias.name.split(".")[0])
            bound = alias.asname or alias.name.split(".")[0]
            self._note_symbol(bound)
            self._note_import(alias.name, node, (bound,))
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        head = module.split(".")[0]
        bound = tuple(
            alias.asname or alias.name for alias in node.names if alias.name != "*"
        )
        for name in bound:
            self._note_symbol(name)
        if head in FIRST_PARTY_PACKAGES:
            for alias in node.names:
                if FIRST_PARTY_SERVER_RE.search(alias.name):
                    self._add(
                        "network",
                        "first_party_server",
                        node,
                        f"{module}.{alias.name}",
                        binds=(alias.asname or alias.name,),
                    )
        if node.level:
            # Относительный импорт внутри тестового пакета; уровень учитывается
            # при резолве пути ниже.
            module = "." * node.level + module
        if module:
            self.result.imports.add(module.split(".")[0])
            if any(alias.name == "*" for alias in node.names):
                self.result.star_imports.add(module)
            self._note_import(module, node, bound)
        self.generic_visit(node)

    def _note_import(
        self, module: str, node: ast.AST, binds: tuple[str, ...] = ()
    ) -> None:
        head = module.split(".")[0]
        if head in CONTRACT_PACKAGES:
            self._add(
                "contract", "import_contracts", node, f"import {module}", binds=binds
            )
        if head == "uvicorn" or UVICORN_RE.search(module):
            self._add("network", "uvicorn", node, f"import {module}", binds=binds)
        if module.startswith("tests") or module.startswith("backend.tests") or module.startswith("."):
            self.result.local_test_imports.add(module)

    # -- определения --------------------------------------------------------
    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        markers = [m for m in (_marker_name(d) for d in node.decorator_list) if m]
        markers.extend(self._class_pytestmark(node))
        requests = _usefixtures_names(node.decorator_list)
        requests |= self._class_pytestmark_fixtures(node)
        self._class_stack.append(node.name)
        self._class_markers.append(markers)
        self._class_requests.append(requests)
        self._path.append((node.name, "class"))
        key = self._scope_key
        if key is not None and not self._func_stack:
            self._ensure_scope(key, "class", node.lineno).requests |= requests
        self.generic_visit(node)
        self._path.pop()
        self._class_requests.pop()
        self._class_markers.pop()
        self._class_stack.pop()

    @staticmethod
    def _class_pytestmark_fixtures(node: ast.ClassDef) -> set[str]:
        found: set[str] = set()
        for stmt in node.body:
            if isinstance(stmt, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "pytestmark" for t in stmt.targets
            ):
                found |= _usefixtures_names(list(_iter_marker_nodes(stmt.value)))
        return found

    @staticmethod
    def _class_pytestmark(node: ast.ClassDef) -> list[str]:
        found: list[str] = []
        for stmt in node.body:
            if isinstance(stmt, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "pytestmark" for t in stmt.targets
            ):
                for element in _iter_marker_nodes(stmt.value):
                    name = _marker_name(element)
                    if name:
                        found.append(name)
        return found

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._handle_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._handle_function(node)

    def _handle_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        nested = bool(self._func_stack)
        is_test = node.name.startswith("test") and (
            not nested  # вложенные функции нодами не являются
        )
        fixture_name, autouse = (None, False) if nested else _fixture_decorator(node)
        self._path.append((node.name, "func"))
        scope_key = self._scope_key or node.name
        if not nested:
            kind = "fixture" if fixture_name else ("test" if is_test else "helper")
            scope = self._ensure_scope(scope_key, kind, node.lineno)
            scope.requests |= _usefixtures_names(node.decorator_list)
            for level in self._class_requests:
                scope.requests |= level
            if kind in {"test", "fixture"}:
                # Параметры теста/фикстуры — это запрос фикстур. У helper-а
                # параметры фикстурами не являются, поэтому их не берём.
                scope.requests |= _parameter_names(node)
            if fixture_name:
                self.result.fixtures.setdefault(fixture_name, scope_key)
                if autouse:
                    self.result.autouse_fixtures.add(scope_key)
        if is_test:
            markers = [m for m in (_marker_name(d) for d in node.decorator_list) if m]
            for level in self._class_markers:
                markers.extend(level)
            factor = 1
            dynamic = False
            for decorator in node.decorator_list:
                mult, is_dynamic = _parametrize_factor(decorator)
                factor *= mult
                dynamic = dynamic or is_dynamic
            all_markers = tuple(sorted(set(markers) | set(self.result.module_markers)))
            primary = tuple(m for m in all_markers if m in PRIMARY_LANES)
            orthogonal = tuple(m for m in all_markers if m in ORTHOGONAL_MARKERS)
            self.result.nodes.append(
                TestNode(
                    name=node.name,
                    lineno=node.lineno,
                    markers=all_markers,
                    primary=primary,
                    orthogonal=orthogonal,
                    param_factor=factor,
                    param_dynamic=dynamic,
                    scope_key=scope_key,
                )
            )
        self._func_stack.append(node.name)
        self.generic_visit(node)
        self._func_stack.pop()
        self._path.pop()

    def visit_Assign(self, node: ast.Assign) -> None:
        module_level = not self._func_stack and not self._class_stack
        if module_level:
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "pytestmark":
                    for element in _iter_marker_nodes(node.value):
                        name = _marker_name(element)
                        if name:
                            self.result.module_markers.append(name)
                    self.result.module_requests |= _usefixtures_names(
                        list(_iter_marker_nodes(node.value))
                    )
        if not module_level:
            self.generic_visit(node)
            return
        # Константа уровня модуля привязывает свои признаки к своему имени:
        # `PROTO = "contracts/x.proto"` — возможность, а не поведение, пока
        # какая-нибудь нода не упомянет `PROTO`.
        previous = self._binds
        self._binds = tuple(_assign_targets(node.targets))
        self.generic_visit(node)
        self._binds = previous

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if self._func_stack or self._class_stack:
            self.generic_visit(node)
            return
        previous = self._binds
        self._binds = tuple(_assign_targets([node.target]))
        self.generic_visit(node)
        self._binds = previous

    # -- поток управления ---------------------------------------------------
    def visit_Try(self, node: ast.Try) -> None:
        for stmt in node.body:
            self.visit(stmt)
        for handler in node.handlers:
            self.visit(handler)
        for stmt in node.orelse:
            self.visit(stmt)
        self._in_finally += 1
        for stmt in node.finalbody:
            self.visit(stmt)
        self._in_finally -= 1

    # -- литералы -----------------------------------------------------------
    def visit_Constant(self, node: ast.Constant) -> None:
        if (
            isinstance(node.value, str)
            and len(node.value) <= 400
            and id(node) not in self._docstring_ids
        ):
            text = node.value
            token = TOKEN_LITERAL_RE.match(text) is not None
            if token and CONTRACT_PATH_RE.search(text):
                self._add("contract", "contract_path_literal", node, text[:80])
            if token and UVICORN_RE.search(text):
                self._add("network", "uvicorn", node, text[:80])
            if LOOPBACK_RE.search(text):
                # Слабый признак: строка может просто разбираться тестом.
                self._add("network", "loopback_literal", node, text[:80], deciding=False)
            if CONTRACT_VERSION_RE.search(text):
                self._add("contract", "version_token", node, text[:80], deciding=False)
        self.generic_visit(node)

    # -- вызовы -------------------------------------------------------------
    def visit_Call(self, node: ast.Call) -> None:
        full = _dotted(node.func) or ""
        tail = full.rsplit(".", 1)[-1] if full else ""
        base = full.split(".")[0] if full else ""

        self._check_patching(node, full)
        if full in DYNAMIC_CALLS or tail in {"import_module"}:
            self.result.dynamic_dispatch = True

        # --- процессы -------------------------------------------------------
        if full in SPAWN_CALLS:
            compiler = _compiler_argument(node)
            self._add(
                "network",
                "process_spawn",
                node,
                f"{full}({compiler})" if compiler else full,
            )
            self.respawn_sites.append((self._func_key, node.lineno))
        elif RESPAWN_NAME_RE.search(tail) or (
            tail == "start" and base[:1].isupper()
        ):
            # Фабрика процесса (`GatewayProcess.start`) или helper `_spawn_*`:
            # сам по себе lane не определяет, но доказывает «restart» для §5.
            self.respawn_sites.append((self._func_key, node.lineno))

        # --- сокеты ---------------------------------------------------------
        if full in SOCKET_CALLS:
            self._add("network", "socket", node, full)
        elif "socket" in self.result.imports and tail in SOCKET_METHODS:
            self._add("network", "socket_method", node, full or tail)
        elif "socket" in self.result.imports and tail == "connect":
            self._add("network", "socket_method", node, full or tail)

        # --- grpc -----------------------------------------------------------
        if full in GRPC_CALLS or tail in GRPC_METHODS:
            self._add("network", "grpc_channel", node, full or tail)

        # --- uvicorn --------------------------------------------------------
        if base == "uvicorn":
            self._add("network", "uvicorn", node, full)

        # --- сигналы --------------------------------------------------------
        self._check_kill(node, full, tail)

        # --- in-process сервисы и потоки ------------------------------------
        if tail in ASGI_CALLS or full in ASGI_CALLS:
            self._add("integration", "asgi_client", node, full or tail)
        if full in WORKER_CALLS or tail in WORKER_METHODS or tail in {
            "ThreadPoolExecutor", "ProcessPoolExecutor", "Thread", "Timer",
        }:
            self._add("integration", "worker_thread", node, full or tail)
        if full in {"asyncio.run", "anyio.run"} or tail in {"run_until_complete"}:
            # Голый event loop без воркеров — слабый признак (§5 не относит его
            # к integration сам по себе).
            self._add("integration", "event_loop", node, full or tail, deciding=False)

        # --- файловая система ------------------------------------------------
        if full in FS_WRITE_CALLS:
            self._add("integration", "fs_write", node, full)
        elif tail in FS_WRITE_METHODS:
            self._add("integration", "fs_write", node, full or tail)
        elif full == "open" or tail == "open":
            self._add_open(node, full or tail)

        self.generic_visit(node)

    def _add_open(self, node: ast.Call, label: str) -> None:
        """`open(path, "w")`/`Path.open("wb")` — запись; чтение игнорируем."""
        mode: str | None = None
        args = list(node.args)
        if label == "open" and len(args) >= 2 and isinstance(args[1], ast.Constant):
            mode = args[1].value if isinstance(args[1].value, str) else None
        elif label != "open" and args and isinstance(args[0], ast.Constant):
            mode = args[0].value if isinstance(args[0].value, str) else None
        for keyword in node.keywords:
            if keyword.arg == "mode" and isinstance(keyword.value, ast.Constant):
                mode = keyword.value.value if isinstance(keyword.value.value, str) else mode
        if mode and WRITE_MODE_RE.search(mode):
            self._add("integration", "fs_write", node, f"{label}(mode={mode!r})")

    def _check_patching(self, node: ast.Call, full: str) -> None:
        """Запомнить подмену рискованной API: она обесценивает найденные следы."""
        if full not in PATCH_CALLS and not full.endswith(".setattr"):
            return
        for argument in list(node.args) + [kw.value for kw in node.keywords]:
            target = None
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                target = argument.value
            else:
                target = _dotted(argument)
            if not target:
                continue
            head = target.split(".")[0]
            if head in PATCHABLE_APIS or target in PATCHABLE_APIS:
                self.result.patched_apis.add(head)

    def _check_kill(self, node: ast.Call, full: str, tail: str) -> None:
        """Отличить убийство живого процесса от liveness-пробы и от cleanup."""
        signal_names = self._signal_arguments(node)
        is_kill_call = full in KILL_CALLS
        is_kill_method = tail in KILL_METHODS or tail in KILL_METHODS_HARD
        if is_kill_call and self._is_liveness_probe(node):
            # `os.kill(pid, 0)` ничего не убивает: это проверка «жив ли».
            self._add("network", "liveness_probe", node, full, deciding=False)
            return
        if not (is_kill_call or is_kill_method or signal_names):
            return
        detail = full or tail
        if signal_names:
            detail = f"{detail}({'/'.join(sorted(signal_names))})"
        if self._in_teardown:
            # §5 разрешает lane `network` «process spawn/cleanup».
            self._add("network", "process_cleanup", node, detail)
            return
        evidence = self._add("chaos", "process_signal", node, detail)
        self.kill_sites.append((evidence, self._func_key, node.lineno))

    @staticmethod
    def _signal_arguments(node: ast.Call) -> set[str]:
        """Имена сигналов среди аргументов вызова (в т.ч. `sig=signal.SIGKILL`)."""
        found: set[str] = set()
        for argument in list(node.args) + [kw.value for kw in node.keywords]:
            dotted = _dotted(argument)
            if not dotted:
                continue
            if dotted.split(".")[-1] in KILL_SIGNAL_NAMES:
                found.add(dotted.split(".")[-1])
        return found

    @staticmethod
    def _is_liveness_probe(node: ast.Call) -> bool:
        return (
            len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value == 0
        )


def scan_source(source: str, path: Path) -> ScanResult:
    """Разобрать исходник модуля и вернуть признаки/маркеры/ноды."""
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        result = ScanResult()
        result.parse_error = f"{type(exc).__name__}: {exc}"
        return result
    scanner = _ModuleScanner(path)
    for holder in ast.walk(tree):
        if isinstance(
            holder, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            body = getattr(holder, "body", [])
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                scanner._docstring_ids.add(id(body[0].value))
    # Маркеры уровня модуля нужны нодам, а `pytestmark` может стоять и после
    # функций, поэтому собираем их отдельным быстрым проходом ДО основного.
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "pytestmark" for t in stmt.targets
        ):
            for element in _iter_marker_nodes(stmt.value):
                name = _marker_name(element)
                if name:
                    scanner.result.module_markers.append(name)
    scanner.visit(tree)
    scanner.result.module_markers = sorted(set(scanner.result.module_markers))
    # «Убили и подняли снова» — доказательство chaos из §5. Повторный запуск
    # ищем в ТОЙ ЖЕ функции строго после сигнала и гасим КАЖДОЕ место убийства
    # отдельно: в одном модуле бывает и chaos-сценарий, и обычная уборка.
    for evidence, func, kill_line in scanner.kill_sites:
        proven = any(f == func and line > kill_line for f, line in scanner.respawn_sites)
        if not proven:
            evidence.deciding = False
    return scanner.result


# ---------------------------------------------------------------------------
# Обход дерева
# ---------------------------------------------------------------------------


def read_pytest_paths(root: Path) -> tuple[list[str], set[str], set[str]]:
    """`testpaths`, `norecursedirs` и зарегистрированные маркеры из `pytest.ini`.

    Файл только ЧИТАЕТСЯ: `pytest.ini` прямо исключён из объёма W0-OPS-03
    (см. квитанцию части 1), поэтому инструмент под него подстраивается, а не
    наоборот. При отсутствии файла берутся значения по умолчанию из контракта
    §5.1 (`tests backend/tests`).
    """
    ini = root / "pytest.ini"
    testpaths = ["tests", "backend/tests"]
    norecurse: set[str] = {".git", "__pycache__", ".venv", "node_modules"}
    markers: set[str] = set()
    if not ini.is_file():
        return testpaths, norecurse, markers
    section: str | None = None
    for raw in ini.read_text(encoding="utf-8", errors="replace").splitlines():
        if not raw.strip():
            continue
        if not raw[:1].isspace() and "=" in raw:
            key, value = raw.split("=", 1)
            section = key.strip()
            value = value.strip()
            if section == "testpaths" and value:
                testpaths = value.split()
            elif section == "norecursedirs" and value:
                norecurse.update(value.split())
            elif section == "markers" and value:
                markers.add(value.split(":", 1)[0].strip())
            continue
        if section == "markers":
            markers.add(raw.strip().split(":", 1)[0].strip())
        elif section == "norecursedirs":
            norecurse.update(raw.split())
    return testpaths, norecurse, markers


def iter_test_modules(root: Path, testpaths: Iterable[str], norecurse: set[str]) -> list[Path]:
    """Все файлы `test_*.py`/`*_test.py` под `testpaths`, минус `norecursedirs`."""
    excluded_parts = {p.strip("/").split("/")[-1] for p in norecurse if "*" not in p}
    excluded_rel = {p.strip("/") for p in norecurse if "/" in p}
    found: list[Path] = []
    for entry in testpaths:
        base = (root / entry).resolve()
        if base.is_file():
            found.append(base)
            continue
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            name = path.name
            if not (name.startswith("test_") or name.endswith("_test.py")):
                continue
            relative = path.relative_to(root).as_posix() if _is_relative(path, root) else path.as_posix()
            if any(part in excluded_parts for part in path.parts):
                continue
            if any(relative.startswith(prefix + "/") for prefix in excluded_rel):
                continue
            found.append(path)
    return found


def _is_relative(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _resolve_local_import(module: str, path: Path, root: Path) -> Path | None:
    """Путь к первопартийному helper-модулю тестов (`tests.*`, относительный)."""
    if module.startswith("."):
        level = len(module) - len(module.lstrip("."))
        rest = module.lstrip(".")
        base = path.parent
        for _ in range(level - 1):
            base = base.parent
        candidate = base / Path(*rest.split(".")) if rest else base
    else:
        candidate = root / Path(*module.split("."))
    for option in (candidate.with_suffix(".py"), candidate / "__init__.py"):
        if option.is_file():
            return option
    return None


# ---------------------------------------------------------------------------
# Вывод lane
# ---------------------------------------------------------------------------


def _deciding(evidence: Iterable[Evidence], lane: str, kinds: set[str] | None = None) -> list[Evidence]:
    return [
        e
        for e in evidence
        if e.deciding and e.lane == lane and (kinds is None or e.kind in kinds)
    ]


#: Признаки integration, означающие живой сервис/поток, а не просто файлы. Они
#: сильнее contract: §5 разрешает contract-тесту temp files, но не сервисы.
SERVICE_KINDS = {"asgi_client", "worker_thread"}
FS_KINDS = {"fs_write"}


def infer_lane(evidence: list[Evidence]) -> tuple[str, list[Evidence]]:
    """Каскад §5: вернуть выведенный lane и признаки, которые его решили."""
    chaos = _deciding(evidence, "chaos")
    if chaos:
        return "chaos", chaos
    network = _deciding(evidence, "network")
    if network:
        return "network", network
    service = _deciding(evidence, "integration", SERVICE_KINDS)
    if service:
        return "integration", service
    contract = _deciding(evidence, "contract")
    if contract:
        return "contract", contract
    filesystem = _deciding(evidence, "integration", FS_KINDS)
    if filesystem:
        return "integration", filesystem
    return "unit", []


def _symbol_index(scopes: dict[str, Scope]) -> dict[str, set[str]]:
    """Имя верхнего уровня → все его scope-ключи (класс тянет свои методы)."""
    index: dict[str, set[str]] = {}
    for key in scopes:
        head = key.split("::")[0]
        index.setdefault(head, set()).add(key)
    return index


def _ancestor_keys(key: str) -> list[str]:
    """`"A::B::t"` → `["A", "A::B"]`: тело класса принадлежит его методам."""
    parts = key.split("::")
    return ["::".join(parts[:i]) for i in range(1, len(parts))]


def _reachable_scopes(
    start: Iterable[str],
    scopes: dict[str, Scope],
    fixtures: dict[str, str],
    symbol_index: dict[str, set[str]],
) -> set[str]:
    """Определения, до которых нода реально дотягивается.

    Ребро есть в трёх случаях, и только в них: нода/фикстура ЗАПРОСИЛА фикстуру
    (параметром или `usefixtures`, транзитивно), определение УПОМЯНУЛО имя
    другого определения (вызов helper-а), метод принадлежит классу. Признак,
    найденный вне этого множества, ноде не приписывается.
    """
    seen: set[str] = set()
    queue = [key for key in start if key]
    while queue:
        key = queue.pop()
        if key in seen or key not in scopes:
            continue
        seen.add(key)
        queue.extend(k for k in _ancestor_keys(key) if k not in seen)
        scope = scopes[key]
        for name in scope.requests:
            target = fixtures.get(name)
            if target is not None and target not in seen:
                queue.append(target)
        for symbol in scope.used:
            for target in symbol_index.get(symbol, ()):
                if target not in seen:
                    queue.append(target)
    return seen


def _evidence_applies(evidence: Evidence, closure: set[str], used: set[str]) -> bool:
    """Достаётся ли признак КОНКРЕТНОЙ ноде.

    Три правила, ради которых инвентарь и переписан:
      * признак из тела определения — если определение достижимо из ноды;
      * признак из чужого helper-модуля — если нода (или её фикстура) упоминает
        имя того определения, где он найден;
      * признак уровня модуля (импорт, константа) — только если введённое им
        имя реально упомянуто. Импорт — возможность, а не поведение.
    """
    if evidence.inherited_from:
        if evidence.scope is not None:
            return evidence.scope.split("::")[0] in used
        return any(name in used for name in evidence.binds)
    if evidence.scope is not None:
        return evidence.scope in closure
    return any(name in used for name in evidence.binds)


def analyse_module(
    path: Path,
    root: Path,
    cache: dict[Path, ScanResult],
    depth: int = 2,
) -> ModuleReport:
    """Разобрать модуль, подмешать признаки helper-модулей и вывести lane."""
    own = _scan_cached(path, cache)
    evidence = list(own.evidence)
    inherited: list[Evidence] = []
    #: Имена, попавшие в модуль через `from helper import *`: адресно проследить
    #: их использование нельзя, поэтому они считаются упомянутыми всегда.
    implicit_symbols: set[str] = set()
    if not own.parse_error and depth > 0:
        seen: set[Path] = {path}
        queue: list[tuple[str, Path, int]] = []
        for module in sorted(own.local_test_imports):
            helper = _resolve_local_import(module, path, root)
            if helper and helper not in seen:
                queue.append((module, helper, depth))
        while queue:
            module, helper, level = queue.pop(0)
            if helper in seen:
                continue
            seen.add(helper)
            helper_scan = _scan_cached(helper, cache)
            label = helper.relative_to(root).as_posix() if _is_relative(helper, root) else str(helper)
            if module in own.star_imports:
                implicit_symbols |= {k.split("::")[0] for k in helper_scan.scopes}
            for item in helper_scan.evidence:
                if not item.deciding:
                    continue
                inherited.append(
                    Evidence(
                        item.lane,
                        item.kind,
                        item.lineno,
                        item.detail,
                        True,
                        label,
                        scope=item.scope,
                        binds=item.binds,
                    )
                )
            if level > 1:
                for nested in sorted(helper_scan.local_test_imports):
                    nested_path = _resolve_local_import(nested, helper, root)
                    if nested_path and nested_path not in seen:
                        queue.append((nested, nested_path, level - 1))
    evidence.extend(inherited)

    lane, decided_by = infer_lane(evidence)
    # Lane ноды выводится ТОЛЬКО из того, до чего нода дотягивается: её тело,
    # запрошенные ею фикстуры (в т.ч. autouse и транзитивные), вызванные из них
    # helper-ы. Импорт уровня модуля решает лишь тогда, когда введённое им имя
    # действительно упомянуто. Сводка по модулю (`lane` выше) осталась
    # максимумом по файлу: она отвечает на другой вопрос — «что в этом файле
    # вообще есть».
    symbol_index = _symbol_index(own.scopes)
    always_on = set(own.autouse_fixtures)
    for name in own.module_requests:
        target = own.fixtures.get(name)
        if target is not None:
            always_on.add(target)
    for node in own.nodes:
        closure = _reachable_scopes(
            {node.scope_key} | always_on, own.scopes, own.fixtures, symbol_index
        )
        used = set(implicit_symbols)
        for key in closure:
            used |= own.scopes[key].used
        node_evidence = [e for e in evidence if _evidence_applies(e, closure, used)]
        node.inferred_lane, node.decided_by = infer_lane(node_evidence)

    manual: list[str] = []
    if own.parse_error:
        manual.append("PARSE_ERROR")
        lane = LANE_UNKNOWN
        decided_by = []
        for node in own.nodes:
            node.inferred_lane = LANE_UNKNOWN
            node.decided_by = []
    else:
        if any(e.kind == "process_signal" and not e.deciding for e in own.evidence):
            manual.append("KILL_WITHOUT_RESTART")
        if decided_by and all(e.inherited_from for e in decided_by):
            manual.append("INHERITED_ONLY")
        if any(e.kind == "first_party_server" for e in decided_by):
            manual.append("PRODUCTION_SIDE_IO")
        risky = {e.kind for e in decided_by}
        if own.patched_apis and risky & {
            "process_spawn", "socket", "socket_method", "grpc_channel", "uvicorn",
            "process_signal", "process_cleanup", "worker_thread",
        }:
            manual.append("PATCHED_API")
        if own.dynamic_dispatch and decided_by:
            manual.append("DYNAMIC_DISPATCH")
        if not own.nodes:
            manual.append("NO_TEST_FUNCTIONS")

    relative = path.relative_to(root).as_posix() if _is_relative(path, root) else str(path)
    return ModuleReport(
        path=relative,
        inferred_lane=lane,
        decided_by=decided_by,
        evidence=evidence,
        nodes=own.nodes,
        module_primary=tuple(m for m in own.module_markers if m in PRIMARY_LANES),
        manual_review=manual,
        parse_error=own.parse_error,
    )


def _scan_cached(path: Path, cache: dict[Path, ScanResult]) -> ScanResult:
    if path in cache:
        return cache[path]
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        result = ScanResult()
        result.parse_error = f"{type(exc).__name__}: {exc}"
    else:
        result = scan_source(source, path)
    cache[path] = result
    return result


# ---------------------------------------------------------------------------
# Отчёт
# ---------------------------------------------------------------------------


#: Направление расхождения «маркер ↔ поведение». Разница не косметическая:
#: `understated` — поведение ТЯЖЕЛЕЕ маркера, тест поедет в лёгкую полосу и
#: сломает её бюджет (§7); `overstated` — маркер тяжелее поведения, тест просто
#: едет дороже, чем нужно, и чаще всего это следствие модульного `pytestmark`,
#: покрывающего файл целиком.
CONFLICT_UNDERSTATED = "understated"
CONFLICT_OVERSTATED = "overstated"


def _conflict_direction(marker: str, inferred: str) -> str:
    order = {lane: index for index, lane in enumerate(PRIMARY_LANES)}
    return (
        CONFLICT_UNDERSTATED
        if order.get(inferred, len(order)) < order.get(marker, len(order))
        else CONFLICT_OVERSTATED
    )


def build_report(root: Path, paths: list[str] | None = None) -> dict[str, Any]:
    """Собрать полный инвентарь. Возвращает готовый к сериализации словарь."""
    started = time.monotonic()
    testpaths, norecurse, registered = read_pytest_paths(root)
    selected = paths or testpaths
    modules = iter_test_modules(root, selected, norecurse)
    cache: dict[Path, ScanResult] = {}
    reports = [analyse_module(path, root, cache) for path in modules]

    lanes: dict[str, dict[str, int]] = {
        lane: {"modules": 0, "functions": 0, "estimated_nodes": 0,
               "marked_functions": 0, "unmarked_functions": 0}
        for lane in (*PRIMARY_LANES, LANE_UNKNOWN)
    }
    unmarked_modules: list[str] = []
    conflicts: list[dict[str, Any]] = []
    double_marked: list[dict[str, Any]] = []
    manual: dict[str, list[str]] = {code: [] for code in MANUAL_REASONS}
    marker_lane_counts: dict[str, int] = {lane: 0 for lane in PRIMARY_LANES}
    orthogonal_counts: dict[str, int] = {}
    total_functions = 0
    total_estimated = 0
    unmarked_functions = 0

    for report in reports:
        bucket = lanes[report.inferred_lane]
        bucket["modules"] += 1
        bucket["functions"] += report.node_count
        bucket["estimated_nodes"] += report.estimated_node_count
        bucket["marked_functions"] += len(report.marked_nodes)
        bucket["unmarked_functions"] += len(report.unmarked_nodes)
        total_functions += report.node_count
        total_estimated += report.estimated_node_count
        unmarked_functions += len(report.unmarked_nodes)
        if report.nodes and not report.marked_nodes:
            unmarked_modules.append(report.path)
        for node in report.nodes:
            for marker in set(node.primary):
                marker_lane_counts[marker] = marker_lane_counts.get(marker, 0) + 1
            for marker in node.orthogonal:
                orthogonal_counts[marker] = orthogonal_counts.get(marker, 0) + 1
        for node in report.conflicting_nodes:
            conflicts.append(
                {
                    "path": report.path,
                    "function": node.name,
                    "marker": node.primary[0],
                    "inferred": node.inferred_lane,
                    "module_inferred": report.inferred_lane,
                    "direction": _conflict_direction(node.primary[0], node.inferred_lane),
                    "marker_from": (
                        "module" if node.primary[0] in report.module_primary else "node"
                    ),
                    # Улики САМОЙ НОДЫ: раньше здесь стояли модульные, и список
                    # конфликтов вводил в заблуждение даже там, где конфликт был
                    # настоящий (улика указывала на чужую строку).
                    "evidence": [e.as_dict() for e in node.decided_by[:3]],
                }
            )
        for node in report.double_marked_nodes:
            double_marked.append(
                {"path": report.path, "function": node.name, "markers": sorted(set(node.primary))}
            )
        for code in report.manual_review:
            manual[code].append(report.path)

    duration = time.monotonic() - started
    unregistered = sorted(
        {lane for lane, count in marker_lane_counts.items() if count and lane not in registered}
    )
    return {
        "tool": "ci_lane_inventory",
        "tool_version": TOOL_VERSION,
        "contract": {"document": CONTRACT_DOC, "section": CONTRACT_SECTION},
        "mode": "observe-only",
        "root": str(root),
        "testpaths": list(selected),
        "duration_seconds": round(duration, 3),
        "totals": {
            "modules": len(reports),
            "test_functions": total_functions,
            "estimated_nodes": total_estimated,
            "modules_without_any_primary_marker": len(unmarked_modules),
            "functions_without_primary_marker": unmarked_functions,
            "functions_with_primary_marker": total_functions - unmarked_functions,
            "double_marked_functions": len(double_marked),
            "marker_behaviour_conflicts": len(conflicts),
            "marker_behaviour_conflicts_understated": sum(
                1 for c in conflicts if c["direction"] == CONFLICT_UNDERSTATED
            ),
            "marker_behaviour_conflicts_overstated": sum(
                1 for c in conflicts if c["direction"] == CONFLICT_OVERSTATED
            ),
            "modules_needing_manual_review": sum(1 for r in reports if r.manual_review),
        },
        "lanes": lanes,
        "markers": {
            "primary_marker_functions": marker_lane_counts,
            "orthogonal_marker_functions": orthogonal_counts,
            "registered_in_pytest_ini": sorted(registered),
            "used_but_not_registered": unregistered,
        },
        "conflicts": conflicts,
        "double_marked": double_marked,
        "manual_review": {code: sorted(paths) for code, paths in manual.items() if paths},
        "unmarked_modules": unmarked_modules,
        "conftest_note": (
            "tests/conftest.py на импорте копирует backend/app/data в песочницу и "
            "держит autouse-фикстуры, трогающие ФС у каждого теста; эти эффекты "
            "НЕ подмешаны в per-module вывод, иначе весь корень стал бы integration"
        ),
        "modules": [report.as_dict() for report in reports],
    }


def evidence_sha256(report: dict[str, Any]) -> str:
    """Отпечаток воспроизводимой семантики инвентаря.

    Полный `--json` намеренно содержит абсолютный root и время
    прогона. Они полезны для диагностики, но делают SHA-256
    разным на каждом запуске и машине. Evidence исключает только
    эти два несемантических поля; все lanes, markers, счётчики и
    находки остаются под отпечатком.
    """
    semantic = {
        key: value
        for key, value in report.items()
        if key not in {"root", "duration_seconds"}
    }
    encoded = json.dumps(
        semantic,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def render_human(report: dict[str, Any], samples: int) -> str:
    """Человекочитаемая сводка: числа, а не мнение."""
    totals = report["totals"]
    lines: list[str] = []
    lines.append(
        f"CI lane inventory — {CONTRACT_DOC} {CONTRACT_SECTION} (observe-only, ничего не правит)"
    )
    lines.append(
        f"корни: {', '.join(report['testpaths'])} | модулей: {totals['modules']} | "
        f"test-функций: {totals['test_functions']} | нод (оценка снизу): "
        f"{totals['estimated_nodes']} | {report['duration_seconds']:.2f} s"
    )
    lines.append("")
    lines.append("Выведенный lane по фактическому поведению:")
    header = f"  {'lane':<12}{'модулей':>9}{'функций':>10}{'нод~':>9}{'помечено':>11}{'без маркера':>14}"
    lines.append(header)
    lines.append("  " + "-" * (len(header) - 2))
    for lane in (*PRIMARY_LANES, LANE_UNKNOWN):
        row = report["lanes"][lane]
        if not row["modules"]:
            continue
        lines.append(
            f"  {lane:<12}{row['modules']:>9}{row['functions']:>10}"
            f"{row['estimated_nodes']:>9}{row['marked_functions']:>11}"
            f"{row['unmarked_functions']:>14}"
        )
    lines.append("")
    lines.append("Разметка §5:")
    lines.append(
        f"  функций с primary lane marker : {totals['functions_with_primary_marker']}"
    )
    lines.append(
        f"  функций БЕЗ маркера           : {totals['functions_without_primary_marker']}"
        "   ← inventory failure §5"
    )
    lines.append(
        f"  модулей без единого маркера   : {totals['modules_without_any_primary_marker']}"
    )
    lines.append(
        f"  функций с ДВУМЯ primary       : {totals['double_marked_functions']}"
        "   ← inventory failure §5"
    )
    lines.append(
        f"  конфликт маркер vs поведение  : {totals['marker_behaviour_conflicts']}"
        f" (поведение тяжелее маркера: {totals['marker_behaviour_conflicts_understated']}"
        f", маркер тяжелее поведения: {totals['marker_behaviour_conflicts_overstated']})"
    )
    lines.append(
        f"  нужна ручная классификация    : {totals['modules_needing_manual_review']} модулей"
    )
    marker_counts = {k: v for k, v in report["markers"]["primary_marker_functions"].items() if v}
    lines.append(
        "  маркеры по lanes              : "
        + (", ".join(f"{k}={v}" for k, v in sorted(marker_counts.items())) or "нет")
    )
    orthogonal = report["markers"]["orthogonal_marker_functions"]
    lines.append(
        "  ортогональные атрибуты        : "
        + (", ".join(f"{k}={v}" for k, v in sorted(orthogonal.items())) or "нет")
        + "  (§5: `slow` — не lane)"
    )
    if report["markers"]["used_but_not_registered"]:
        lines.append(
            "  НЕ зарегистрированы в pytest.ini: "
            + ", ".join(report["markers"]["used_but_not_registered"])
            + "  (файл вне объёма задачи, только замечено)"
        )

    if report["conflicts"]:
        # Сначала опасное направление: маркер легче поведения — такой тест
        # поедет в лёгкой полосе и сломает её бюджет. Обратное направление
        # (маркер тяжелее) стоит денег, но полосу не ломает.
        ordered = sorted(
            report["conflicts"], key=lambda c: c["direction"] != CONFLICT_UNDERSTATED
        )
        lines.append("")
        lines.append(f"Конфликты «маркер vs поведение» (первые {samples}):")
        for item in ordered[:samples]:
            evidence = ", ".join(
                f"{e['kind']}@{e['line']}" for e in item["evidence"]
            ) or "улик нет"
            arrow = "поведение ТЯЖЕЛЕЕ" if item["direction"] == CONFLICT_UNDERSTATED else "маркер тяжелее"
            lines.append(
                f"  {item['path']}::{item['function']}: маркер {item['marker']}"
                f" ({item['marker_from']}), поведение {item['inferred']}"
                f" — {arrow} ({evidence})"
            )
    if report["double_marked"]:
        lines.append("")
        lines.append(f"Две primary-метки на одной ноде (первые {samples}):")
        for item in report["double_marked"][:samples]:
            lines.append(f"  {item['path']}::{item['function']}: {', '.join(item['markers'])}")

    if report["manual_review"]:
        lines.append("")
        lines.append("Нужна ручная классификация (статически не решается):")
        for code, paths in sorted(report["manual_review"].items()):
            lines.append(f"  {code} ({len(paths)}): {MANUAL_REASONS[code]}")
            for path in paths[:samples]:
                lines.append(f"      {path}")
            if len(paths) > samples:
                lines.append(f"      … ещё {len(paths) - samples}")

    lines.append("")
    lines.append("Оговорка: " + report["conftest_note"] + ".")
    lines.append(
        "Инструмент только инвентаризует: маркеры не расставляет, тесты не правит, "
        "по умолчанию exit 0."
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ci_lane_inventory",
        description=(
            "Статическая инвентаризация test lanes по §5 quality-runtime/v1: "
            "выводит lane каждого тестового модуля из поведения и сравнивает с маркерами."
        ),
    )
    parser.add_argument(
        "paths", nargs="*", help="каталоги/файлы вместо testpaths из pytest.ini"
    )
    parser.add_argument("--root", default=str(ROOT), help="корень репозитория")
    output = parser.add_mutually_exclusive_group()
    output.add_argument("--json", action="store_true", help="машиночитаемый отчёт")
    output.add_argument(
        "--evidence-sha256",
        action="store_true",
        help="воспроизводимый SHA-256 отчёта без root и duration",
    )
    parser.add_argument(
        "--fail-on-unmarked",
        action="store_true",
        help=(
            "ненулевой код при inventory failure §5 (непомеченные или дважды "
            "помеченные ноды). ВЫКЛЮЧЕНО по умолчанию: W0-OPS-03 не включает enforce"
        ),
    )
    parser.add_argument(
        "--samples", type=int, default=5, help="сколько примеров печатать (по умолчанию 5)"
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"корень не найден: {root}", file=sys.stderr)
        return EXIT_USAGE
    report = build_report(root, args.paths or None)

    if args.evidence_sha256:
        print(evidence_sha256(report))
    elif args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_human(report, max(0, args.samples)))

    if args.fail_on_unmarked:
        totals = report["totals"]
        if totals["functions_without_primary_marker"] or totals["double_marked_functions"]:
            return EXIT_INVENTORY_FAILURE
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover — точка входа CLI
    raise SystemExit(main())
