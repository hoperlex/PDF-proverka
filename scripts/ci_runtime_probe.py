#!/usr/bin/env python3
"""Capability preflight по контракту `quality-runtime/v1` (§6).

Зачем:
    Контракт `docs/architecture/QUALITY_RUNTIME_CONTRACT_V1.md` (заморожен
    задачей W0-ARC-03) требует ОДИН versioned probe, который выполняется ДО
    pytest и доказывает, что окружение способно вынести выбранный lane. Если
    обязательная для lane capability отсутствует — это **setup failure до
    тестов**, а не skip (§6, правило 1). Молчаливый skip прячет сломанный
    runner и превращает красный lane в зелёный отчёт.

Интерфейс задан контрактом дословно (§6):

    python scripts/ci_runtime_probe.py --profile <lane>

    lane ∈ {unit, contract, integration, network, chaos}

Дополнительно (не меняет target interface):

    --json      машиночитаемый отчёт на stdout (для receipt из §8)
    --enforce   clean-room enforce profile (§3): все профильные проверки
                становятся обязательными для любого lane
    --timeout   жёсткий бюджет одной проверки в секундах (по умолчанию 10)

Три правила результата (§6) реализованы буквально:

    1. Отсутствие обязательной для lane capability → exit != 0 ДО тестов.
       Skip запрещён: статуса "SKIP" в отчёте нет вообще.
    2. Не выбранные lanes → `NOT_RUN` (не `passed`, не `skipped`); это видно
       и в человеческом выводе, и в JSON (`lanes`).
    3. Таблица «lane → обязательные capabilities» взята из §5 дословно
       (см. LANE_CAPABILITIES), а не придумана здесь.

Анти-hang:
    Probe защищает прогон от зависаний, поэтому сам зависать не имеет права.
    AnyIO worker-thread roundtrip и loopback-проверка выполняются в ОТДЕЛЬНОМ
    процессе под `subprocess` timeout: внутренний `anyio.fail_after`/
    `socket.settimeout` спасает только от отменяемых зависаний, а
    неотменяемый hang (§6: restricted sandbox 2026-08-28 зависал именно на
    AnyIO wake-up) снимается снаружи SIGKILL по группе процессов. Проверки с
    дочерними процессами тоже ждут только с bounded timeout и добивают
    группу в finally.

Сеть:
    наружу probe не ходит: только bind/connect на 127.0.0.1 и порт 0.

Секреты:
    проверка «нет provider secrets» печатает ТОЛЬКО имена переменных,
    никогда значения.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Контрактные константы (§1 шапка, §2, §3, §4)
# ---------------------------------------------------------------------------

CONTRACT_ID = "quality-runtime/v1"
CONTRACT_VERSION = "1.1.0"
CONTRACT_DOC = "docs/architecture/QUALITY_RUNTIME_CONTRACT_V1.md"
CONTRACT_BASE_COMMIT = "de2ccea1fc1fa4fd81f6dbace61593735cf46379"
#: Версия самого probe. Меняется вместе с набором проверок/кодов причин.
PROBE_VERSION = "1"

LANES: tuple[str, ...] = ("unit", "contract", "integration", "network", "chaos")

#: §3.1 Platform.
REQUIRED_OS = "Linux"
REQUIRED_ARCH = "x86_64"
REQUIRED_PYTHON = (3, 12, 3)
REQUIRED_NODE = "22.23.1"
REQUIRED_NPM = "10.9.8"
#: §3.1 Temporary storage: «свободно не менее 2 GiB».
MIN_TEMP_FREE_BYTES = 2 * 1024**3
#: §3.1 Locale/time.
REQUIRED_LOCALE_ENV = {"TZ": "UTC", "LC_ALL": "C.UTF-8", "PYTHONHASHSEED": "0"}

#: §3.2 Isolated runtime state — обязательные значения для каждого job.
REQUIRED_ISOLATION_FLAGS = {
    "AUDIT_DISABLE_DOTENV": "1",
    "PAID_API_ENABLED": "false",
    "PORTAL_AUTH_ENABLED": "false",
}
#: §3.2 — эти пути обязаны указывать в run-root, а не в рабочее дерево.
REQUIRED_ISOLATION_PATHS = (
    "AUDIT_APP_DATA_DIR",
    "AUDIT_PROJECTS_DIR",
    "AUDIT_OBJECTS_FILE",
    "AUDIT_ACTION_LOG_DIR",
    # CR-3: добавлена в §3.2 вместе с остальными, но в этот кортеж не попала —
    # переменную можно было удалить целиком, и проверка возвращала OK. Пока
    # запись о закрытии CR-3 существовала, а enforcement — нет.
    "AUDITMANAGER_DEPLOY_LOCK_DIR",
)

#: §2 Frozen input receipt — dependency-часть.
DEPENDENCY_RECEIPT = {
    "requirements.txt": (
        "e517f305175010e974f5dcdb288135dd3ad59f5a8fd7b16f069f898ee9262df4"
    ),
    "requirements-proto.txt": (
        "037a6d4a3402c1ae756a1cd8143be63e2d3a5fb2daf32d01040a79145794f92a"
    ),
    "requirements-dev.txt": (
        "935ce563a390983e2ce1d140010ea6446606098faf4c7adc0ca05f59a7614d5f"
    ),
    "constraints-qr-v1.txt": (
        "e701df30ffc0a942e08c77fc4458442d7f4fb3b4379560e47c437d4d4ab2dcbe"
    ),
}
#: §2 Frozen input receipt — frontend-часть (+ §4.3 `npm ci` только по lock).
FRONTEND_RECEIPT = {
    "frontend/package-lock.json": (
        "c679604b25329bdbcf89f80017011a0c51c07e770e326865b093f63633097040"
    ),
    "frontend/package.json": (
        "65749f5180ea6fd1e2d99f35c103365f9188f7e2cabaef3db53e8f051eef2075"
    ),
    "frontend/tsconfig.distributed.json": (
        "a3d3fb949642421af5563073f04658160534b04e78c3ebad895d4454eb487863"
    ),
}
#: §4.1 SHA-256 полного `python -m pip freeze` с завершающим переводом строки.
REFERENCE_PIP_FREEZE_SHA256 = (
    "557e95885700a44013febcc6559fa8ee278923507b71df8adba761e1e247f99c"
)
#: §4.1: materialized lock/constraints создаёт W0-INT-01. Probe только ищет его.
PYTHON_LOCK_CANDIDATES = (
    "constraints-qr-v1.txt",
    "requirements-lock.txt",
    "requirements-ci.lock",
    ".ci/lock/python-qr-v1.txt",
)

#: §3.3 Norm corpus.
NORM_VAULT_DIR = "norms/vault"
NORM_STATUS_INDEX = "norms/tools/status_index.json"
#: Источники ожидаемого checksum для norm artifact (первый существующий).
NORM_CHECKSUM_FILES = ("norms/vault.sha256", "norms/norm_artifact.sha256")
NORM_CHECKSUM_ENV = "QR_NORM_ARTIFACT_SHA256"

#: Provider/API-ключи проекта (§3.1 «provider/API keys отсутствуют»).
#: Список собран по фактическим читателям env в backend/, scripts/, audit_worker/.
PROVIDER_SECRET_ENV: tuple[str, ...] = (
    "OPENROUTER_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GEMINI_DIRECT_API_KEY",
    "GOOGLE_API_KEY",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "DEEPSEEK_API_KEY",
    "MISTRAL_API_KEY",
    "LMSTUDIO_API_KEY",
    "CHANDRA_BEARER_TOKEN",
    "EVIDENCE_LOCAL_VISION_BEARER_TOKEN",
    "AGENT_GATEWAY_SERVER_KEY",
    "AUDIT_WORKER_TOKEN",
    "PORTAL_SESSION_SECRET",
)
#: Плюс родовой шаблон: провайдерский префикс + ключевой суффикс.
PROVIDER_SECRET_PATTERN = re.compile(
    r"^(OPENAI|OPENROUTER|ANTHROPIC|CLAUDE|GOOGLE|GEMINI|VERTEX|DEEPSEEK|MISTRAL|XAI|GROQ"
    r"|COHERE|AZURE_OPENAI|HUGGINGFACE|HF|LMSTUDIO|CHANDRA|QWEN|YANDEX)"
    r"[A-Z0-9_]*_(API_KEY|APIKEY|KEY|TOKEN|SECRET|CREDENTIALS)$"
)
#: Переменные харнесса Claude Code/VSCode провайдерскими ключами проекта не являются.
SECRET_SCAN_EXEMPT = re.compile(r"^(CLAUDE_CODE|CLAUDECODE|VSCODE|GH|GITHUB_ACTION)")

# ---------------------------------------------------------------------------
# §5 Test lanes — таблица «lane → обязательные capabilities»
# ---------------------------------------------------------------------------
#
# Взято ДОСЛОВНО из колонки «Обязательные capabilities» таблицы §5:
#
#   unit         → «base Python»
#   contract     → «base Python, process spawn если test явно компилирует contract»
#   integration  → «thread wake-up; loopback для service-backed tests»
#   network      → «thread wake-up, loopback, process spawn/cleanup»
#   chaos        → «все capabilities, ≥2 GiB temp, отдельный runner/job»
#
# Условные формулировки («если test явно компилирует contract», «для
# service-backed tests») трактуются как ОБЯЗАТЕЛЬНЫЕ для lane job: probe
# выполняется до pytest и не знает состава выборки, а §6.1 запрещает
# превращать отсутствие capability в skip. Ослабить это нельзя — только
# новый receipt/версия контракта (§12).
#
# `base Python` включает работающий интерпретатор нужной платформы; ≥2 GiB
# temp для chaos вынесен отдельной capability, потому что §5 называет его явно.
CAP_BASE_PYTHON = "base_python"
CAP_THREAD_WAKEUP = "thread_wakeup"
CAP_LOOPBACK = "loopback"
CAP_PROCESS_SPAWN = "process_spawn"
CAP_PROCESS_SIGNALS = "process_signals"
CAP_TEMP_2GIB = "temp_space_2gib"

LANE_CAPABILITIES: dict[str, tuple[str, ...]] = {
    "unit": (CAP_BASE_PYTHON,),
    "contract": (CAP_BASE_PYTHON, CAP_PROCESS_SPAWN),
    "integration": (CAP_BASE_PYTHON, CAP_THREAD_WAKEUP, CAP_LOOPBACK),
    "network": (CAP_BASE_PYTHON, CAP_THREAD_WAKEUP, CAP_LOOPBACK, CAP_PROCESS_SPAWN),
    "chaos": (
        CAP_BASE_PYTHON,
        CAP_THREAD_WAKEUP,
        CAP_LOOPBACK,
        CAP_PROCESS_SPAWN,
        CAP_PROCESS_SIGNALS,
        CAP_TEMP_2GIB,
    ),
}
#: Все lane-capabilities из §5 (нужно, чтобы «не для этого lane» стало NOT_RUN).
LANE_CAPABILITY_IDS: tuple[str, ...] = (
    CAP_BASE_PYTHON,
    CAP_THREAD_WAKEUP,
    CAP_LOOPBACK,
    CAP_PROCESS_SPAWN,
    CAP_PROCESS_SIGNALS,
    CAP_TEMP_2GIB,
)

#: §6, правило 2: «Локальный unit/contract разрешён на restricted машине, если
#: их собственный preflight зелёный». Послабление дано ИМЕННО этим двум lanes и
#: только вне enforce. Для integration/network/chaos послабления нет, поэтому им
#: профиль §3.1 (в т.ч. `uid != 0`) обязателен всегда.
LOCAL_RELAXED_LANES = frozenset({"unit", "contract"})

# ---------------------------------------------------------------------------
# Коды причин
# ---------------------------------------------------------------------------

#: Машиночитаемый код → человекочитаемое описание. Любой код, попавший в отчёт,
#: обязан быть здесь (это проверяется тестом).
REASON_CODES: dict[str, str] = {
    # platform / profile
    "PLATFORM_OS_MISMATCH": "OS не соответствует clean-room profile (§3.1)",
    "PLATFORM_PYTHON_MISMATCH": "Python major.minor не соответствует §3.1",
    "PLATFORM_ARCH_MISMATCH": "архитектура не соответствует §3.1",
    "PLATFORM_PYTHON_PATCH_MISMATCH": "patch-версия Python отличается от пина §3.1",
    "PLATFORM_NODE_VERSION_MISMATCH": "версия Node отличается от пина §3.1",
    "PLATFORM_NPM_VERSION_MISMATCH": "версия npm отличается от пина §3.1",
    "PLATFORM_NODE_UNAVAILABLE": "Node/npm недоступны для проверки пина §3.1",
    "SOURCE_COMMIT_UNKNOWN": "провенанс прогона не определён — §8 требует source_commit",
    "LOCALE_PROFILE_MISMATCH": "TZ/LC_ALL/PYTHONHASHSEED не по §3.1",
    "USER_IS_ROOT": "прогон под root (uid=0), а §3.1 требует uid != 0",
    # temp
    "TEMP_DIR_UNUSABLE": "временный каталог недоступен",
    "TEMP_WRITE_FAILED": "запись во временный каталог не удалась",
    "TEMP_FSYNC_FAILED": "fsync во временном каталоге не удался",
    "TEMP_RENAME_FAILED": "rename во временном каталоге не удался",
    "TEMP_DELETE_FAILED": "удаление во временном каталоге не удалось",
    "TEMP_SPACE_UNKNOWN": "не удалось узнать свободное место во временном каталоге",
    "TEMP_SPACE_INSUFFICIENT": "свободного места меньше 2 GiB (§3.1/§5)",
    # anyio
    "ANYIO_IMPORT_FAILED": "не удалось импортировать anyio",
    "ANYIO_ROUNDTRIP_TIMEOUT": "AnyIO worker-thread roundtrip не уложился в бюджет",
    "ANYIO_ROUNDTRIP_HANG": "AnyIO worker-thread wake-up завис, процесс снят SIGKILL",
    "ANYIO_ROUNDTRIP_FAILED": "AnyIO worker-thread roundtrip упал с ошибкой",
    "ANYIO_ROUNDTRIP_MISMATCH": "AnyIO worker вернул неожиданное значение",
    # loopback
    "SOCKET_CREATE_DENIED": "создание socket запрещено окружением",
    "LOOPBACK_BIND_DENIED": "bind на 127.0.0.1 запрещён окружением",
    "LOOPBACK_LISTEN_DENIED": "listen на loopback запрещён окружением",
    "LOOPBACK_ACCEPT_TIMEOUT": "accept на loopback не дождался соединения",
    "LOOPBACK_ACCEPT_DENIED": "accept на loopback запрещён окружением",
    "LOOPBACK_CLIENT_FAILED": "клиентская сторона loopback не смогла connect/send",
    "LOOPBACK_IO_FAILED": "обмен данными по loopback не удался",
    "LOOPBACK_ROUNDTRIP_MISMATCH": "loopback вернул не те данные",
    "LOOPBACK_PROBE_HANG": "loopback-проверка зависла, процесс снят SIGKILL",
    "LOOPBACK_NOT_LOCAL": "peer оказался не loopback-адресом",
    # process
    "PROCESS_SPAWN_DENIED": "запуск дочернего процесса запрещён окружением",
    "PROCESS_WAIT_TIMEOUT": "дочерний процесс не завершился в бюджет",
    "PROCESS_EXIT_UNEXPECTED": "дочерний процесс завершился неожиданным кодом",
    "PROCESS_OUTPUT_UNEXPECTED": "дочерний процесс вернул неожиданный вывод",
    "PROCESS_TERMINATE_FAILED": "terminate дочернего процесса не сработал",
    "SIGTERM_DELIVERY_FAILED": "SIGTERM не доставлен/не завершил дочерний процесс",
    "SIGKILL_DELIVERY_FAILED": "SIGKILL не доставлен/не завершил дочерний процесс",
    "SIGNAL_CHILD_NOT_READY": "дочерний процесс не успел установить обработчик сигнала",
    # секреты и изоляция
    "SECRET_PRESENT_IN_ENV": "в окружении присутствует provider secret (§3.1)",
    "PAID_API_ENABLED_TRUE": "PAID_API_ENABLED включён — платные вызовы разрешены",
    "PAID_API_FLAG_UNSET": "PAID_API_ENABLED не выставлен явно в false (§3.2)",
    "SECRET_DOTENV_ACTIVE": ".env активен: AUDIT_DISABLE_DOTENV != 1 (§3.2)",
    "ISOLATION_FLAG_MISMATCH": "обязательный флаг §3.2 не выставлен или неверен",
    "ISOLATION_PATH_UNSET": "путь изоляции §3.2 не выставлен",
    "ISOLATION_PATH_INSIDE_WORKTREE": "путь изоляции §3.2 указывает в рабочее дерево",
    # norm corpus
    "OPTIONAL_NORM_CORPUS_ABSENT": "norm corpus не выбран локально (§3.3, optional)",
    "NORM_ARTIFACT_MISSING": "norm artifact отсутствует, а в enforce он обязателен (§3.3)",
    "NORM_STATUS_INDEX_MISSING": "norms/tools/status_index.json отсутствует (§3.3)",
    "NORM_CHECKSUM_MANIFEST_MISSING": "нет ожидаемого SHA-256 для norm artifact (§3.3)",
    "NORM_ARTIFACT_CHECKSUM_MISMATCH": "SHA-256 norm artifact не совпал (§3.3)",
    # receipts
    "DEPENDENCY_INPUT_MISSING": "вход dependency receipt отсутствует (§2)",
    "DEPENDENCY_INPUT_DRIFT": "SHA-256 dependency input не совпал с receipt (§2)",
    "PYTHON_LOCK_NOT_MATERIALIZED": "lock/constraints ещё не материализован (§4.1, W0-INT-01)",
    "PIP_FREEZE_DRIFT": "pip freeze не совпал с reference receipt §4.1",
    "PIP_FREEZE_UNAVAILABLE": "не удалось получить pip freeze",
    "FRONTEND_INPUT_MISSING": "вход frontend receipt отсутствует (§2/§4.3)",
    "FRONTEND_LOCK_DRIFT": "SHA-256 frontend input не совпал с receipt (§2/§4.3)",
    # инфраструктура самого probe
    "CHILD_PROTOCOL_ERROR": "дочерняя проверка вернула неразбираемый ответ",
    "PROBE_CHECK_CRASHED": "проверка упала с необработанной ошибкой (дефект probe)",
    "NOT_REQUIRED_FOR_LANE": "capability не входит в обязательные для этого lane (§5)",
}

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_WARN = "WARN"
STATUS_NOT_RUN = "NOT_RUN"

SEVERITY_REQUIRED = "required"
SEVERITY_ADVISORY = "advisory"
SEVERITY_NOT_APPLICABLE = "not_applicable"

EXIT_OK = 0
EXIT_SETUP_FAILURE = 1
EXIT_USAGE = 2


# ---------------------------------------------------------------------------
# Примитивы
# ---------------------------------------------------------------------------


@dataclass
class Outcome:
    """Результат одной проверки до применения severity."""

    ok: bool
    reason_code: str | None = None
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class CheckResult:
    check_id: str
    title: str
    contract_ref: str
    severity: str
    status: str
    reason_code: str | None
    message: str
    duration_seconds: float
    details: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "check": self.check_id,
            "title": self.title,
            "contract_ref": self.contract_ref,
            "severity": self.severity,
            "status": self.status,
            "reason_code": self.reason_code,
            "reason_text": REASON_CODES.get(self.reason_code or "", ""),
            "message": self.message,
            "duration_seconds": round(self.duration_seconds, 4),
            "details": self.details,
        }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _kill_group(proc: subprocess.Popen) -> None:
    """Bounded cleanup: снять всю группу процессов, не оставив сирот (§7.3)."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except OSError:
            pass


def run_child(code: str, budget: float, args: tuple[Any, ...] = ()) -> dict[str, Any]:
    """Выполнить проверку в отдельном процессе с ЖЁСТКИМ внешним timeout.

    Внутренний timeout (anyio.fail_after / socket.settimeout) спасает только от
    отменяемых зависаний. Неотменяемый hang снимается здесь: SIGKILL по группе.
    Возвращает {"ok", "code", "detail", "timed_out"}.
    """
    cmd = [sys.executable, "-c", code, *[str(a) for a in args]]
    try:
        proc = subprocess.Popen(  # noqa: S603 — фиксированный argv, без shell
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(ROOT),
            start_new_session=True,
        )
    except OSError as exc:
        return {
            "ok": False,
            "code": "PROCESS_SPAWN_DENIED",
            "detail": f"{type(exc).__name__}: {exc}",
            "timed_out": False,
        }
    try:
        out, err = proc.communicate(timeout=budget)
    except subprocess.TimeoutExpired:
        _kill_group(proc)
        try:
            out, err = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:  # pragma: no cover — после SIGKILL не бывает
            out, err = "", ""
        return {
            "ok": False,
            "code": None,
            "detail": f"нет ответа за {budget:g} s, процесс снят SIGKILL",
            "timed_out": True,
        }
    for line in reversed((out or "").strip().splitlines()):
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        payload["timed_out"] = False
        return payload
    tail = ((err or "").strip().splitlines() or [""])[-1][:200]
    return {
        "ok": False,
        "code": "CHILD_PROTOCOL_ERROR",
        "detail": f"rc={proc.returncode}; stderr: {tail}",
        "timed_out": False,
    }


def _tool_version(executable: str, budget: float = 5.0) -> str | None:
    """Версия внешнего инструмента; любая ошибка → None (не валит probe)."""
    binary = shutil.which(executable)
    if not binary:
        return None
    try:
        done = subprocess.run(  # noqa: S603
            [binary, "--version"],
            capture_output=True,
            text=True,
            timeout=budget,
            cwd=str(ROOT),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    return (done.stdout or done.stderr).strip().lstrip("v") or None


# ---------------------------------------------------------------------------
# Дочерние сценарии (исполняются в отдельном процессе)
# ---------------------------------------------------------------------------

ANYIO_CHILD = r'''
import json, sys
budget = float(sys.argv[1])


def emit(ok, code, detail):
    print(json.dumps({"ok": ok, "code": code, "detail": detail}))
    raise SystemExit(0)


try:
    import anyio
    from anyio import to_thread
except BaseException as exc:
    emit(False, "ANYIO_IMPORT_FAILED", type(exc).__name__ + ": " + str(exc))


async def _main():
    with anyio.fail_after(budget):
        return await to_thread.run_sync(lambda: 40 + 2)


try:
    value = anyio.run(_main)
except TimeoutError as exc:
    emit(False, "ANYIO_ROUNDTRIP_TIMEOUT", "anyio.fail_after(" + str(budget) + "s) сработал")
except BaseException as exc:
    emit(False, "ANYIO_ROUNDTRIP_FAILED", type(exc).__name__ + ": " + str(exc))
if value != 42:
    emit(False, "ANYIO_ROUNDTRIP_MISMATCH", "worker вернул " + repr(value))
emit(True, None, "anyio to_thread.run_sync roundtrip вернул 42")
'''

LOOPBACK_CHILD = r'''
import json, socket, sys, threading
budget = float(sys.argv[1])


def emit(ok, code, detail):
    print(json.dumps({"ok": ok, "code": code, "detail": detail}))
    raise SystemExit(0)


try:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
except OSError as exc:
    emit(False, "SOCKET_CREATE_DENIED", type(exc).__name__ + ": " + str(exc))
server.settimeout(budget)
try:
    server.bind(("127.0.0.1", 0))
except OSError as exc:
    emit(False, "LOOPBACK_BIND_DENIED", type(exc).__name__ + ": " + str(exc))
try:
    server.listen(1)
except OSError as exc:
    emit(False, "LOOPBACK_LISTEN_DENIED", type(exc).__name__ + ": " + str(exc))
address = server.getsockname()
box = {}


def _client():
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(budget)
        sock.connect(address)
        sock.sendall(b"qr-v1-ping")
        box["echo"] = sock.recv(64)
        sock.close()
    except BaseException as exc:
        box["error"] = type(exc).__name__ + ": " + str(exc)


thread = threading.Thread(target=_client, daemon=True)
thread.start()
try:
    conn, peer = server.accept()
except socket.timeout:
    emit(False, "LOOPBACK_ACCEPT_TIMEOUT", "accept не дождался соединения за " + str(budget) + "s")
except OSError as exc:
    emit(False, "LOOPBACK_ACCEPT_DENIED", type(exc).__name__ + ": " + str(exc))
conn.settimeout(budget)
try:
    received = conn.recv(64)
    conn.sendall(b"qr-v1-pong")
except OSError as exc:
    emit(False, "LOOPBACK_IO_FAILED", type(exc).__name__ + ": " + str(exc))
thread.join(budget)
if "error" in box:
    emit(False, "LOOPBACK_CLIENT_FAILED", box["error"])
if not str(peer[0]).startswith("127."):
    emit(False, "LOOPBACK_NOT_LOCAL", "peer=" + str(peer[0]))
if received != b"qr-v1-ping" or box.get("echo") != b"qr-v1-pong":
    emit(False, "LOOPBACK_ROUNDTRIP_MISMATCH", "server=" + repr(received) + " client=" + repr(box.get("echo")))
conn.close()
server.close()
emit(True, None, "bind/listen/connect/accept/echo на " + str(address[0]) + ":" + str(address[1]))
'''

ECHO_CHILD = 'import sys; sys.stdout.write("qr-v1-child-ok")'

SLEEP_CHILD = "import sys, time; time.sleep(float(sys.argv[1]))"

SIGTERM_IGNORING_CHILD = (
    "import pathlib, signal, sys, time\n"
    "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
    "pathlib.Path(sys.argv[1]).write_text('ready')\n"
    "time.sleep(float(sys.argv[2]))\n"
)


# ---------------------------------------------------------------------------
# Проверки
# ---------------------------------------------------------------------------


def check_platform(ctx: "ProbeContext") -> Outcome:
    """base Python: та ли OS и та ли major.minor (§3.1, §5)."""
    details = {
        "os": platform.system(),
        "architecture": platform.machine(),
        "python_version": platform.python_version(),
        "python_executable": sys.executable,
    }
    if platform.system() != REQUIRED_OS:
        return Outcome(
            False,
            "PLATFORM_OS_MISMATCH",
            f"OS={platform.system()!r}, контракт требует {REQUIRED_OS!r}",
            details,
        )
    if sys.version_info[:2] != REQUIRED_PYTHON[:2]:
        got = ".".join(str(p) for p in sys.version_info[:2])
        want = ".".join(str(p) for p in REQUIRED_PYTHON[:2])
        return Outcome(
            False, "PLATFORM_PYTHON_MISMATCH", f"Python {got}, контракт требует {want}.x", details
        )
    return Outcome(
        True,
        None,
        f"{platform.system()} / CPython {platform.python_version()}",
        details,
    )


def check_user_non_root(ctx: "ProbeContext") -> Outcome:
    """§3.1: пользователь непривилегированный, `uid != 0`; §6 проверяет явно."""
    uid = os.getuid()
    details = {"uid": uid, "euid": os.geteuid(), "gid": os.getgid()}
    if uid == 0:
        return Outcome(
            False,
            "USER_IS_ROOT",
            "прогон под root (uid=0), а clean-room profile qr-v1 требует "
            "непривилегированного пользователя; послабление §6.2 распространяется "
            "только на локальные unit/contract, для integration/network/chaos это "
            "setup failure",
            details,
        )
    return Outcome(True, None, f"uid={uid} (не root)", details)


def check_profile_pins(ctx: "ProbeContext") -> Outcome:
    """Точные пины §3.1: arch, patch Python, Node/npm, locale/time."""
    node_version = ctx.environment.get("node_version")
    npm_version = ctx.environment.get("npm_version")
    details = {
        "architecture": platform.machine(),
        "python_version": platform.python_version(),
        "node_version": node_version,
        "npm_version": npm_version,
        "locale_env": {name: os.environ.get(name) for name in REQUIRED_LOCALE_ENV},
    }
    if platform.machine() != REQUIRED_ARCH:
        return Outcome(
            False,
            "PLATFORM_ARCH_MISMATCH",
            f"architecture={platform.machine()!r}, контракт требует {REQUIRED_ARCH!r}",
            details,
        )
    if sys.version_info[:3] != REQUIRED_PYTHON:
        want = ".".join(str(p) for p in REQUIRED_PYTHON)
        return Outcome(
            False,
            "PLATFORM_PYTHON_PATCH_MISMATCH",
            f"Python {platform.python_version()}, пин контракта {want}",
            details,
        )
    if node_version is None or npm_version is None:
        return Outcome(
            False,
            "PLATFORM_NODE_UNAVAILABLE",
            "не удалось определить версии Node/npm для сверки с §3.1",
            details,
        )
    if node_version != REQUIRED_NODE:
        return Outcome(
            False,
            "PLATFORM_NODE_VERSION_MISMATCH",
            f"Node {node_version}, пин контракта {REQUIRED_NODE}",
            details,
        )
    if npm_version != REQUIRED_NPM:
        return Outcome(
            False,
            "PLATFORM_NPM_VERSION_MISMATCH",
            f"npm {npm_version}, пин контракта {REQUIRED_NPM}",
            details,
        )
    wrong = {
        name: os.environ.get(name)
        for name, want in REQUIRED_LOCALE_ENV.items()
        if os.environ.get(name) != want
    }
    if wrong:
        return Outcome(
            False,
            "LOCALE_PROFILE_MISMATCH",
            "не соответствуют §3.1: "
            + ", ".join(f"{k}={v!r}" for k, v in sorted(wrong.items())),
            details,
        )
    return Outcome(True, None, "arch/python/node/npm/locale совпали с §3.1", details)


def check_temp_rw(ctx: "ProbeContext") -> Outcome:
    """§6: запись/rename/delete в ИЗОЛИРОВАННОМ temp."""
    details = {"temp_root": tempfile.gettempdir()}
    try:
        sandbox = Path(tempfile.mkdtemp(prefix="ci-runtime-probe-"))
    except OSError as exc:
        return Outcome(False, "TEMP_DIR_UNUSABLE", f"{type(exc).__name__}: {exc}", details)
    details["sandbox"] = str(sandbox)
    payload = b"qr-v1-temp-probe\n"
    source = sandbox / "probe.tmp"
    target = sandbox / "probe.renamed"
    try:
        try:
            with source.open("wb") as fh:
                fh.write(payload)
                fh.flush()
                try:
                    os.fsync(fh.fileno())
                except OSError as exc:
                    return Outcome(
                        False,
                        "TEMP_FSYNC_FAILED",
                        f"{type(exc).__name__}: {exc}",
                        details,
                    )
        except OSError as exc:
            return Outcome(False, "TEMP_WRITE_FAILED", f"{type(exc).__name__}: {exc}", details)
        try:
            written = source.read_bytes()
        except OSError as exc:
            return Outcome(False, "TEMP_WRITE_FAILED", f"{type(exc).__name__}: {exc}", details)
        if written != payload:
            return Outcome(False, "TEMP_WRITE_FAILED", "прочитано не то, что записано", details)
        try:
            source.rename(target)
        except OSError as exc:
            return Outcome(False, "TEMP_RENAME_FAILED", f"{type(exc).__name__}: {exc}", details)
        try:
            target.unlink()
        except OSError as exc:
            return Outcome(False, "TEMP_DELETE_FAILED", f"{type(exc).__name__}: {exc}", details)
        if target.exists():
            return Outcome(False, "TEMP_DELETE_FAILED", "файл остался после unlink", details)
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)
    if sandbox.exists():
        return Outcome(False, "TEMP_DELETE_FAILED", "каталог остался после rmtree", details)
    return Outcome(True, None, f"write/fsync/rename/delete в {sandbox.parent}", details)


def check_temp_space(ctx: "ProbeContext") -> Outcome:
    """§3.1/§5: во временном хранилище свободно не менее 2 GiB."""
    temp_root = tempfile.gettempdir()
    try:
        usage = shutil.disk_usage(temp_root)
    except OSError as exc:
        return Outcome(
            False, "TEMP_SPACE_UNKNOWN", f"{type(exc).__name__}: {exc}", {"temp_root": temp_root}
        )
    details = {
        "temp_root": temp_root,
        "free_bytes": usage.free,
        "free_gib": round(usage.free / 1024**3, 2),
        "required_gib": MIN_TEMP_FREE_BYTES / 1024**3,
    }
    if usage.free < MIN_TEMP_FREE_BYTES:
        return Outcome(
            False,
            "TEMP_SPACE_INSUFFICIENT",
            f"свободно {details['free_gib']} GiB, требуется не менее 2 GiB",
            details,
        )
    return Outcome(True, None, f"свободно {details['free_gib']} GiB (>= 2 GiB)", details)


def check_thread_wakeup(ctx: "ProbeContext") -> Outcome:
    """§6: AnyIO worker-thread roundtrip с timeout (двойная защита от hang)."""
    result = run_child(ANYIO_CHILD, ctx.timeout, (ctx.inner_timeout,))
    details = {
        "outer_timeout_seconds": ctx.timeout,
        "inner_timeout_seconds": ctx.inner_timeout,
        "child_detail": result.get("detail"),
    }
    if result.get("timed_out"):
        return Outcome(
            False,
            "ANYIO_ROUNDTRIP_HANG",
            f"AnyIO worker-thread wake-up завис (> {ctx.timeout:g} s) и не отменился "
            "внутренним fail_after; процесс снят SIGKILL",
            details,
        )
    if not result.get("ok"):
        return Outcome(
            False,
            result.get("code") or "ANYIO_ROUNDTRIP_FAILED",
            str(result.get("detail") or ""),
            details,
        )
    return Outcome(True, None, str(result.get("detail") or "anyio roundtrip ok"), details)


def check_loopback(ctx: "ProbeContext") -> Outcome:
    """§6: bind/connect/accept на loopback, без единого обращения наружу."""
    result = run_child(LOOPBACK_CHILD, ctx.timeout, (ctx.inner_timeout,))
    details = {
        "outer_timeout_seconds": ctx.timeout,
        "inner_timeout_seconds": ctx.inner_timeout,
        "scope": "127.0.0.1 only, порт 0 (outbound не используется)",
        "child_detail": result.get("detail"),
    }
    if result.get("timed_out"):
        return Outcome(
            False,
            "LOOPBACK_PROBE_HANG",
            f"loopback-проверка не ответила за {ctx.timeout:g} s, процесс снят SIGKILL",
            details,
        )
    if not result.get("ok"):
        return Outcome(
            False,
            result.get("code") or "SOCKET_CREATE_DENIED",
            str(result.get("detail") or ""),
            details,
        )
    return Outcome(True, None, str(result.get("detail") or "loopback ok"), details)


def _spawn(args: list[str]) -> subprocess.Popen:
    return subprocess.Popen(  # noqa: S603
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(ROOT),
        start_new_session=True,
    )


def check_process_spawn(ctx: "ProbeContext") -> Outcome:
    """§6: spawn/wait/terminate дочернего процесса, cleanup без сирот."""
    details: dict[str, Any] = {"timeout_seconds": ctx.timeout}
    # 1) spawn + wait
    try:
        echo = _spawn([sys.executable, "-c", ECHO_CHILD])
    except OSError as exc:
        return Outcome(False, "PROCESS_SPAWN_DENIED", f"{type(exc).__name__}: {exc}", details)
    try:
        out, _err = echo.communicate(timeout=ctx.timeout)
    except subprocess.TimeoutExpired:
        _kill_group(echo)
        echo.wait(timeout=5)
        return Outcome(
            False, "PROCESS_WAIT_TIMEOUT", f"echo-child не завершился за {ctx.timeout:g} s", details
        )
    details["echo_returncode"] = echo.returncode
    if echo.returncode != 0:
        return Outcome(
            False, "PROCESS_EXIT_UNEXPECTED", f"echo-child rc={echo.returncode}", details
        )
    if (out or "").strip() != "qr-v1-child-ok":
        return Outcome(
            False, "PROCESS_OUTPUT_UNEXPECTED", f"echo-child stdout={out!r}", details
        )
    # 2) terminate + cleanup
    try:
        sleeper = _spawn([sys.executable, "-c", SLEEP_CHILD, "60"])
    except OSError as exc:
        return Outcome(False, "PROCESS_SPAWN_DENIED", f"{type(exc).__name__}: {exc}", details)
    try:
        sleeper.terminate()
        try:
            sleeper.wait(timeout=ctx.timeout)
        except subprocess.TimeoutExpired:
            _kill_group(sleeper)
            sleeper.wait(timeout=5)
            return Outcome(
                False,
                "PROCESS_TERMINATE_FAILED",
                f"дочерний процесс пережил terminate() и {ctx.timeout:g} s ожидания",
                details,
            )
    finally:
        if sleeper.poll() is None:  # pragma: no cover — страховка от сирот
            _kill_group(sleeper)
        sleeper.stdout and sleeper.stdout.close()
        sleeper.stderr and sleeper.stderr.close()
    details["terminate_returncode"] = sleeper.returncode
    return Outcome(
        True,
        None,
        f"spawn/wait ok (rc=0), terminate снял процесс (rc={sleeper.returncode})",
        details,
    )


def check_process_signals(ctx: "ProbeContext") -> Outcome:
    """§5/§6: для chaos обязаны работать SIGTERM и SIGKILL."""
    details: dict[str, Any] = {"timeout_seconds": ctx.timeout}
    # SIGTERM обычному процессу.
    try:
        victim = _spawn([sys.executable, "-c", SLEEP_CHILD, "60"])
    except OSError as exc:
        return Outcome(False, "PROCESS_SPAWN_DENIED", f"{type(exc).__name__}: {exc}", details)
    try:
        victim.send_signal(signal.SIGTERM)
        try:
            victim.wait(timeout=ctx.timeout)
        except subprocess.TimeoutExpired:
            _kill_group(victim)
            victim.wait(timeout=5)
            return Outcome(
                False,
                "SIGTERM_DELIVERY_FAILED",
                f"процесс не умер по SIGTERM за {ctx.timeout:g} s",
                details,
            )
    except OSError as exc:
        _kill_group(victim)
        return Outcome(False, "SIGTERM_DELIVERY_FAILED", f"{type(exc).__name__}: {exc}", details)
    finally:
        victim.stdout and victim.stdout.close()
        victim.stderr and victim.stderr.close()
    details["sigterm_returncode"] = victim.returncode
    if victim.returncode != -signal.SIGTERM:
        return Outcome(
            False,
            "SIGTERM_DELIVERY_FAILED",
            f"ожидался rc=-{int(signal.SIGTERM)}, получен {victim.returncode}",
            details,
        )
    # SIGKILL процессу, который SIGTERM игнорирует.
    sandbox = Path(tempfile.mkdtemp(prefix="ci-runtime-probe-signals-"))
    ready = sandbox / "ready"
    try:
        try:
            stubborn = _spawn(
                [sys.executable, "-c", SIGTERM_IGNORING_CHILD, str(ready), "60"]
            )
        except OSError as exc:
            return Outcome(False, "PROCESS_SPAWN_DENIED", f"{type(exc).__name__}: {exc}", details)
        try:
            deadline = time.monotonic() + min(ctx.timeout, 5.0)
            while not ready.exists() and time.monotonic() < deadline:
                if stubborn.poll() is not None:
                    break
                time.sleep(0.02)
            if not ready.exists():
                return Outcome(
                    False,
                    "SIGNAL_CHILD_NOT_READY",
                    "дочерний процесс не установил SIG_IGN за отведённое время",
                    details,
                )
            stubborn.send_signal(signal.SIGTERM)
            try:
                stubborn.wait(timeout=0.3)
                details["stubborn_died_on_sigterm"] = True
            except subprocess.TimeoutExpired:
                details["stubborn_died_on_sigterm"] = False
            stubborn.kill()
            try:
                stubborn.wait(timeout=ctx.timeout)
            except subprocess.TimeoutExpired:
                _kill_group(stubborn)
                return Outcome(
                    False,
                    "SIGKILL_DELIVERY_FAILED",
                    f"процесс пережил SIGKILL и {ctx.timeout:g} s ожидания",
                    details,
                )
        finally:
            if stubborn.poll() is None:  # pragma: no cover — страховка от сирот
                _kill_group(stubborn)
            stubborn.stdout and stubborn.stdout.close()
            stubborn.stderr and stubborn.stderr.close()
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)
    details["sigkill_returncode"] = stubborn.returncode
    if stubborn.returncode != -signal.SIGKILL:
        return Outcome(
            False,
            "SIGKILL_DELIVERY_FAILED",
            f"ожидался rc=-{int(signal.SIGKILL)}, получен {stubborn.returncode}",
            details,
        )
    return Outcome(
        True,
        None,
        f"SIGTERM снял процесс (rc={victim.returncode}), "
        f"SIGKILL снял игнорирующий SIGTERM процесс (rc={stubborn.returncode})",
        details,
    )


def _scan_provider_secrets() -> list[str]:
    """Имена переменных с provider secret. ЗНАЧЕНИЯ не читаются и не печатаются."""
    found: set[str] = set()
    for name, value in os.environ.items():
        if not (value or "").strip():
            continue
        if SECRET_SCAN_EXEMPT.match(name):
            continue
        if name in PROVIDER_SECRET_ENV or PROVIDER_SECRET_PATTERN.match(name):
            found.add(name)
    return sorted(found)


def _dotenv_secret_names(path: Path) -> list[str]:
    """Имена непустых provider-ключей внутри .env; значения не сохраняются."""
    names: set[str] = set()
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        raw_name, raw_value = line.split("=", 1)
        name = raw_name.strip().removeprefix("export ").strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            continue
        value = raw_value.strip()
        if not value or value in {"''", '""'} or value.startswith("#"):
            # Пустой placeholder не является присутствующим credential. Это
            # совпадает с проверкой os.environ выше, где пустое значение тоже
            # пропускается.
            continue
        upper = name.upper()
        if upper in PROVIDER_SECRET_ENV or PROVIDER_SECRET_PATTERN.match(upper):
            names.add(upper)
    return sorted(names)


def check_secrets_absent(ctx: "ProbeContext") -> Outcome:
    """§3.1/§6: provider secrets отсутствуют, платные вызовы запрещены.

    Считается не только собственное окружение probe: если рядом лежит `.env`, а
    `AUDIT_DISABLE_DOTENV` не выставлен (§3.2), провайдерские ключи из файла
    реально попадут в процесс pytest через `backend/app/core/config.py`. Это
    отказ по факту наличия ключей в файле, а не по факту существования `.env`:
    файл без provider-ключей ничего не нарушает.
    """
    leaked = _scan_provider_secrets()
    paid_raw = os.environ.get("PAID_API_ENABLED")
    paid_on = (paid_raw or "").strip().lower() in {"1", "true", "yes", "on"}
    dotenv_disabled = (os.environ.get("AUDIT_DISABLE_DOTENV") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    dotenv_file = ROOT / ".env"
    details = {
        # Только ИМЕНА: значения секретов не попадают ни в лог, ни в JSON.
        "scanned_names_present": leaked,
        "paid_api_enabled_raw": paid_raw,
        "dotenv_file_present": dotenv_file.exists(),
        "dotenv_disabled": dotenv_disabled,
    }
    if leaked:
        return Outcome(
            False,
            "SECRET_PRESENT_IN_ENV",
            "в окружении есть provider secrets (значения не печатаются): "
            + ", ".join(leaked),
            details,
        )
    if paid_on:
        return Outcome(
            False,
            "PAID_API_ENABLED_TRUE",
            "PAID_API_ENABLED включён: платные вызовы разрешены, clean-room это запрещает",
            details,
        )
    dotenv_names = (
        _dotenv_secret_names(dotenv_file)
        if dotenv_file.exists() and not dotenv_disabled
        else []
    )
    details["dotenv_secret_names"] = dotenv_names
    if dotenv_names:
        return Outcome(
            False,
            "SECRET_DOTENV_ACTIVE",
            f"{dotenv_file.name} будет загружен (AUDIT_DISABLE_DOTENV != 1) и внесёт "
            "provider secrets в процесс тестов (значения не печатаются): "
            + ", ".join(dotenv_names)
            + " — лечится AUDIT_DISABLE_DOTENV=1 из §3.2",
            details,
        )
    return Outcome(
        True, None, "provider secrets не найдены, платные вызовы выключены", details
    )


def check_runtime_isolation(ctx: "ProbeContext") -> Outcome:
    """§3.2: обязательные значения изолированного runtime state."""
    problems: list[str] = []
    details: dict[str, Any] = {"flags": {}, "paths": {}}
    for name, want in REQUIRED_ISOLATION_FLAGS.items():
        got = os.environ.get(name)
        details["flags"][name] = got
        if (got or "").strip().lower() != want:
            problems.append(f"{name}={got!r} (ожидалось {want!r})")
    if problems:
        return Outcome(
            False, "ISOLATION_FLAG_MISMATCH", "; ".join(problems), details
        )
    unset = []
    inside = []
    for name in REQUIRED_ISOLATION_PATHS:
        got = os.environ.get(name)
        details["paths"][name] = got
        if not got:
            unset.append(name)
            continue
        try:
            Path(got).resolve().relative_to(ROOT)
        except ValueError:
            continue
        inside.append(name)
    if unset:
        return Outcome(
            False, "ISOLATION_PATH_UNSET", "не выставлены: " + ", ".join(unset), details
        )
    if inside:
        return Outcome(
            False,
            "ISOLATION_PATH_INSIDE_WORKTREE",
            "указывают внутрь рабочего дерева: " + ", ".join(inside),
            details,
        )
    return Outcome(True, None, "isolated runtime state соответствует §3.2", details)


def _norm_artifact_digest(vault: Path) -> str:
    """Детерминированный digest дерева: относительный путь + содержимое."""
    digest = hashlib.sha256()
    for path in sorted(p for p in vault.rglob("*") if p.is_file()):
        digest.update(str(path.relative_to(vault)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_file(path).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def check_norm_artifact(ctx: "ProbeContext") -> Outcome:
    """§3.3: в enforce norm artifact обязателен и сверяется по SHA-256."""
    vault = ROOT / NORM_VAULT_DIR
    index = ROOT / NORM_STATUS_INDEX
    details: dict[str, Any] = {
        "vault": NORM_VAULT_DIR,
        "vault_present": vault.is_dir(),
        "status_index_present": index.is_file(),
        "enforce": ctx.enforce,
    }
    if not vault.is_dir():
        code = "NORM_ARTIFACT_MISSING" if ctx.enforce else "OPTIONAL_NORM_CORPUS_ABSENT"
        text = (
            f"{NORM_VAULT_DIR} отсутствует; в enforce CI это setup failure, не skip"
            if ctx.enforce
            else f"{NORM_VAULT_DIR} отсутствует — локально corpus не выбран (§3.3), "
            "тесты внешнего корпуса обязаны сделать явный skip с этим кодом"
        )
        return Outcome(False, code, text, details)
    expected = os.environ.get(NORM_CHECKSUM_ENV)
    source = NORM_CHECKSUM_ENV if expected else None
    if not expected:
        for candidate in NORM_CHECKSUM_FILES:
            path = ROOT / candidate
            if path.is_file():
                expected = path.read_text(encoding="utf-8").split()[0]
                source = candidate
                break
    actual = _norm_artifact_digest(vault)
    details["norm_artifact_sha256"] = actual
    details["checksum_source"] = source
    ctx.environment["norm_artifact_sha256"] = actual
    if not index.is_file():
        return Outcome(
            False, "NORM_STATUS_INDEX_MISSING", f"{NORM_STATUS_INDEX} отсутствует", details
        )
    if not expected:
        return Outcome(
            False,
            "NORM_CHECKSUM_MANIFEST_MISSING",
            f"нет ожидаемого SHA-256 (ни {NORM_CHECKSUM_ENV}, ни "
            + "/".join(NORM_CHECKSUM_FILES),
            details,
        )
    if expected.strip().lower() != actual:
        return Outcome(
            False,
            "NORM_ARTIFACT_CHECKSUM_MISMATCH",
            f"ожидался {expected.strip()[:16]}…, получен {actual[:16]}…",
            details,
        )
    return Outcome(True, None, f"norm artifact сверен по {source}", details)


def _receipt_outcome(
    receipt: dict[str, str], missing_code: str, drift_code: str, label: str
) -> tuple[Outcome, dict[str, str]]:
    actual: dict[str, str] = {}
    missing: list[str] = []
    drifted: list[str] = []
    for rel, expected in sorted(receipt.items()):
        path = ROOT / rel
        if not path.is_file():
            missing.append(rel)
            continue
        digest = sha256_file(path)
        actual[rel] = digest
        if digest != expected:
            drifted.append(f"{rel}: {digest[:12]}… != receipt {expected[:12]}…")
    details = {"sha256": actual, "missing": missing, "drifted": drifted}
    if missing:
        return (
            Outcome(False, missing_code, "нет файлов: " + ", ".join(missing), details),
            actual,
        )
    if drifted:
        return (
            Outcome(False, drift_code, "; ".join(drifted), details),
            actual,
        )
    return (
        Outcome(True, None, f"{label}: {len(actual)} вход(ов) совпали с receipt §2", details),
        actual,
    )


def check_dependency_receipt(ctx: "ProbeContext") -> Outcome:
    """§2/§6: dependency-входы совпадают с frozen receipt."""
    outcome, actual = _receipt_outcome(
        DEPENDENCY_RECEIPT, "DEPENDENCY_INPUT_MISSING", "DEPENDENCY_INPUT_DRIFT", "dependency"
    )
    ctx.environment["dependency_input_sha256"] = actual
    return outcome


def check_python_lock(ctx: "ProbeContext") -> Outcome:
    """§4.1/§6: lock материализован и установленный набор совпадает с receipt."""
    lock = next((c for c in PYTHON_LOCK_CANDIDATES if (ROOT / c).is_file()), None)
    details: dict[str, Any] = {
        "lock_file": lock,
        "lock_candidates": list(PYTHON_LOCK_CANDIDATES),
    }
    if lock:
        details["python_lock_sha256"] = sha256_file(ROOT / lock)
        ctx.environment["python_lock_sha256"] = details["python_lock_sha256"]
    try:
        done = subprocess.run(  # noqa: S603
            [sys.executable, "-m", "pip", "freeze"],
            capture_output=True,
            text=True,
            timeout=max(ctx.timeout, 30.0),
            cwd=str(ROOT),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return Outcome(
            False, "PIP_FREEZE_UNAVAILABLE", f"{type(exc).__name__}: {exc}", details
        )
    if done.returncode != 0:
        return Outcome(
            False,
            "PIP_FREEZE_UNAVAILABLE",
            f"pip freeze rc={done.returncode}",
            details,
        )
    freeze = done.stdout
    if freeze and not freeze.endswith("\n"):
        freeze += "\n"
    actual = hashlib.sha256(freeze.encode("utf-8")).hexdigest()
    details["pip_freeze_sha256"] = actual
    details["reference_pip_freeze_sha256"] = REFERENCE_PIP_FREEZE_SHA256
    ctx.environment["pip_freeze_sha256"] = actual
    if actual != REFERENCE_PIP_FREEZE_SHA256:
        return Outcome(
            False,
            "PIP_FREEZE_DRIFT",
            f"pip freeze {actual[:12]}… != reference §4.1 {REFERENCE_PIP_FREEZE_SHA256[:12]}…",
            details,
        )
    if lock is None:
        return Outcome(
            False,
            "PYTHON_LOCK_NOT_MATERIALIZED",
            "pip freeze совпал с §4.1, но materialized lock/constraints ещё нет "
            "(его создаёт W0-INT-01)",
            details,
        )
    return Outcome(True, None, f"lock {lock} и pip freeze совпали с §4.1", details)


def check_frontend_receipt(ctx: "ProbeContext") -> Outcome:
    """§2/§4.3/§6: frontend lock receipt совпадает."""
    outcome, actual = _receipt_outcome(
        FRONTEND_RECEIPT, "FRONTEND_INPUT_MISSING", "FRONTEND_LOCK_DRIFT", "frontend"
    )
    ctx.environment["frontend_lock_sha256"] = actual.get("frontend/package-lock.json")
    return outcome


# ---------------------------------------------------------------------------
# Реестр проверок и severity
# ---------------------------------------------------------------------------


@dataclass
class CheckSpec:
    check_id: str
    title: str
    contract_ref: str
    runner: Callable[["ProbeContext"], Outcome]
    #: True — проверка профиля (§3), а не lane capability (§5).
    profile_check: bool = False
    #: Профильная проверка, обязательная в ЛЮБОМ режиме.
    always_required: bool = False


#: Явный источник provenance для деревьев без `.git`. Clean-room создаётся через
#: `git archive`, и `git rev-parse` там не работает по построению.
SOURCE_COMMIT_ENV = "QR_SOURCE_COMMIT"
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _git_commit() -> str | None:
    try:
        done = subprocess.run(  # noqa: S603
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(ROOT),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() or None if done.returncode == 0 else None


def source_commit() -> tuple[str | None, str]:
    """§8 требует `source_commit` как обязательное поле receipt.

    Clean-room разворачивается из `git archive`, где `.git` нет по построению,
    поэтому `git rev-parse` возвращал None и ВСЕ сохранённые receipt выходили с
    `source_commit: null`. Приёмочная расписка без provenance не отвечает на
    вопрос «что именно проверено», то есть §8 не выполнен.

    Источник возвращается вместе со значением: env-переменная — более слабое
    доказательство, чем сам git, и подменять одно другим молча нельзя.
    """
    from_git = _git_commit()
    if from_git:
        return from_git, "git"
    for name in (SOURCE_COMMIT_ENV, "GITHUB_SHA"):
        value = (os.environ.get(name) or "").strip().lower()
        if _SHA_RE.match(value):
            return value, name
    return None, "unknown"


def check_source_provenance(ctx: "ProbeContext") -> Outcome:
    """§8: receipt без `source_commit` не является приёмочным свидетельством."""
    value, origin = source_commit()
    details = {"source_commit": value, "source_commit_origin": origin}
    ctx.environment["source_commit"] = value
    ctx.environment["source_commit_origin"] = origin
    if value is None:
        return Outcome(
            False,
            "SOURCE_COMMIT_UNKNOWN",
            "provenance не определена: нет `.git` и не выставлен "
            f"{SOURCE_COMMIT_ENV} или GITHUB_SHA (§8)",
            details,
        )
    return Outcome(True, None, f"source_commit {value[:12]}… из {origin}", details)


CHECKS: tuple[CheckSpec, ...] = (
    CheckSpec(CAP_BASE_PYTHON, "base Python / платформа", "§3.1, §5", check_platform),
    CheckSpec(
        "user_non_root",
        "непривилегированный пользователь",
        "§3.1, §6",
        check_user_non_root,
        profile_check=True,
    ),
    CheckSpec(
        "profile_pins",
        "пины arch/python/node/npm/locale",
        "§3.1",
        check_profile_pins,
        profile_check=True,
    ),
    CheckSpec(
        "temp_rw",
        "запись/rename/delete в изолированном temp",
        "§6",
        check_temp_rw,
        profile_check=True,
        always_required=True,
    ),
    CheckSpec(CAP_TEMP_2GIB, "свободный temp >= 2 GiB", "§3.1, §5", check_temp_space),
    CheckSpec(
        CAP_THREAD_WAKEUP, "AnyIO worker-thread roundtrip", "§5, §6", check_thread_wakeup
    ),
    CheckSpec(CAP_LOOPBACK, "bind/connect/accept на loopback", "§5, §6", check_loopback),
    CheckSpec(
        CAP_PROCESS_SPAWN, "spawn/wait/terminate child process", "§5, §6", check_process_spawn
    ),
    CheckSpec(CAP_PROCESS_SIGNALS, "SIGTERM и SIGKILL", "§5, §6", check_process_signals),
    CheckSpec(
        "secrets_absent",
        "нет provider secrets, платные вызовы запрещены",
        "§3.1, §6",
        check_secrets_absent,
        profile_check=True,
        always_required=True,
    ),
    CheckSpec(
        "runtime_isolation",
        "isolated runtime state",
        "§3.2",
        check_runtime_isolation,
        profile_check=True,
    ),
    CheckSpec(
        "norm_artifact",
        "norm artifact и его checksum",
        "§3.3, §6",
        check_norm_artifact,
        profile_check=True,
    ),
    CheckSpec(
        "dependency_receipt",
        "dependency receipt",
        "§2, §6",
        check_dependency_receipt,
        profile_check=True,
    ),
    CheckSpec(
        "python_lock", "python lock / pip freeze receipt", "§4.1, §6", check_python_lock,
        profile_check=True,
    ),
    CheckSpec(
        "frontend_receipt",
        "frontend lock receipt",
        "§2, §4.3, §6",
        check_frontend_receipt,
        profile_check=True,
    ),
    CheckSpec(
        "source_provenance",
        "provenance прогона (§8 source_commit)",
        "§8",
        check_source_provenance,
        profile_check=True,
    ),
)


def severity_for(spec: CheckSpec, lane: str, enforce: bool, ci: bool = False) -> str:
    """Насколько обязательна проверка для данного lane и режима.

    Контракт различает ДВЕ вещи, которые легко спутать в один флаг.

    Первая — «это CI-полоса, а не машина разработчика». §6 правило 1: в явном
    lane job отсутствие обязательной capability есть setup failure, и никаких
    послаблений там нет. Послабление §6.2 адресовано именно ЛОКАЛЬНОМУ прогону
    `unit`/`contract` на restricted машине.

    Вторая — «это enforce profile». К нему §3.3 и §6 правило 4 привязывают ровно
    один дополнительный вход: norm corpus. «Нет artifact — setup failure».

    Раньше обе оси кодировались одним `enforce`, и CI без него получал профильные
    проверки advisory: точные пины, изоляцию §3.2 и dependency receipt можно было
    нарушить, не покраснев. Основанием тому был комментарий «их materialization
    принадлежит W0-INT-01» — задача выполнена, основание отпало.

    Поэтому `ci=True` означает: послаблений §6.2 нет, профильные проверки §3
    обязательны, но corpus остаётся optional до перехода в enforce.
    """
    if not spec.profile_check:
        if spec.check_id in LANE_CAPABILITIES[lane]:
            return SEVERITY_REQUIRED
        return SEVERITY_NOT_APPLICABLE
    if spec.always_required or enforce:
        return SEVERITY_REQUIRED
    if ci:
        # Единственное исключение: §3.3 привязывает corpus именно к enforce CI.
        return SEVERITY_ADVISORY if spec.check_id == "norm_artifact" else SEVERITY_REQUIRED
    if spec.check_id == "user_non_root":
        # §6.2: локально restricted машина разрешена только unit/contract.
        return SEVERITY_ADVISORY if lane in LOCAL_RELAXED_LANES else SEVERITY_REQUIRED
    # Локальный прогон: §3.3 прямо называет corpus optional, остальное
    # информативно.
    return SEVERITY_ADVISORY


# ---------------------------------------------------------------------------
# Запуск
# ---------------------------------------------------------------------------


@dataclass
class ProbeContext:
    lane: str
    enforce: bool
    timeout: float
    environment: dict[str, Any]
    #: §6 правило 1 — прогон в CI-полосе; послаблений §6.2 нет. Отдельно от
    #: `enforce`, к которому §3.3 привязывает norm corpus.
    ci: bool = False

    @property
    def inner_timeout(self) -> float:
        """Внутренний бюджет всегда меньше внешнего, чтобы отличать hang от отказа."""
        return self.timeout / 2.0




def collect_environment() -> dict[str, Any]:
    try:
        free = shutil.disk_usage(tempfile.gettempdir()).free
    except OSError:
        free = None
    return {
        "os_image": platform.platform(),
        "architecture": platform.machine(),
        "uid": os.getuid(),
        "python_version": platform.python_version(),
        "python_executable": sys.executable,
        "node_version": _tool_version("node"),
        "npm_version": _tool_version("npm"),
        "temp_dir": tempfile.gettempdir(),
        "temp_free_bytes": free,
    }


def run_probe(lane: str, *, enforce: bool = False, ci: bool = False, timeout: float = 10.0) -> dict[str, Any]:
    """Выполнить preflight для одного lane и вернуть машиночитаемый отчёт."""
    if lane not in LANES:  # pragma: no cover — argparse ловит раньше
        raise ValueError(f"неизвестный lane: {lane!r}")
    started = time.time()
    started_mono = time.monotonic()
    ctx = ProbeContext(lane=lane, enforce=enforce, ci=ci, timeout=timeout, environment=collect_environment())

    results: list[CheckResult] = []
    for spec in CHECKS:
        severity = severity_for(spec, lane, enforce, ci)
        if severity == SEVERITY_NOT_APPLICABLE:
            results.append(
                CheckResult(
                    check_id=spec.check_id,
                    title=spec.title,
                    contract_ref=spec.contract_ref,
                    severity=severity,
                    status=STATUS_NOT_RUN,
                    reason_code="NOT_REQUIRED_FOR_LANE",
                    message=f"§5 не требует «{spec.check_id}» для lane {lane} — проверка не выполнялась",
                    duration_seconds=0.0,
                    details={},
                )
            )
            continue
        check_started = time.monotonic()
        try:
            outcome = spec.runner(ctx)
        except Exception as exc:  # pragma: no cover — сам probe не должен падать молча
            outcome = Outcome(
                False,
                "PROBE_CHECK_CRASHED",
                f"проверка упала: {type(exc).__name__}: {exc}",
                {},
            )
        elapsed = time.monotonic() - check_started
        if outcome.ok:
            status = STATUS_PASS
        else:
            status = STATUS_FAIL if severity == SEVERITY_REQUIRED else STATUS_WARN
        results.append(
            CheckResult(
                check_id=spec.check_id,
                title=spec.title,
                contract_ref=spec.contract_ref,
                severity=severity,
                status=status,
                reason_code=outcome.reason_code,
                message=outcome.message,
                duration_seconds=elapsed,
                details=outcome.details,
            )
        )

    failed = [r for r in results if r.status == STATUS_FAIL]
    warned = [r for r in results if r.status == STATUS_WARN]
    exit_code = EXIT_SETUP_FAILURE if failed else EXIT_OK
    completed = time.time()
    # Значение уже вычислено проверкой provenance; повторный вызов git не нужен.
    _report_commit = ctx.environment.get("source_commit")
    _report_origin = ctx.environment.get("source_commit_origin", "unknown")

    report = {
        "contract_id": CONTRACT_ID,
        "contract_version": CONTRACT_VERSION,
        "contract_doc": CONTRACT_DOC,
        "contract_base_commit": CONTRACT_BASE_COMMIT,
        "probe_version": PROBE_VERSION,
        "source_commit": _report_commit,
        "source_commit_origin": _report_origin,
        "lane": lane,
        "mode": "enforce" if enforce else ("ci" if ci else "local"),
        "command": f"python scripts/ci_runtime_probe.py --profile {lane}"
        + (" --enforce" if enforce else (" --ci" if ci else "")),
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started)),
        "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(completed)),
        "duration_seconds": round(time.monotonic() - started_mono, 3),
        "result": "setup_failure" if failed else "ok",
        "exit_code": exit_code,
        # §6, правило 2: lanes, которые НЕ выбраны, не passed и не skipped.
        "lanes": {name: ("PROBED" if name == lane else STATUS_NOT_RUN) for name in LANES},
        "required_capabilities": list(LANE_CAPABILITIES[lane]),
        "capabilities": {r.check_id: r.status for r in results},
        "checks": [r.as_dict() for r in results],
        "required_failed": [
            {"check": r.check_id, "reason_code": r.reason_code, "message": r.message}
            for r in failed
        ],
        "advisory_failed": [
            {"check": r.check_id, "reason_code": r.reason_code, "message": r.message}
            for r in warned
        ],
        "environment": ctx.environment,
        "norm_artifact_sha256": ctx.environment.get("norm_artifact_sha256"),
        "python_lock_sha256": ctx.environment.get("python_lock_sha256"),
        "pip_freeze_sha256": ctx.environment.get("pip_freeze_sha256"),
        "frontend_lock_sha256": ctx.environment.get("frontend_lock_sha256"),
        "skip_policy": "capability skip запрещён (§6.1): отсутствие обязательной "
        "capability — setup failure до pytest",
    }
    return report


# ---------------------------------------------------------------------------
# Человекочитаемый вывод
# ---------------------------------------------------------------------------


def render_text(report: dict[str, Any]) -> str:
    lane = report["lane"]
    env = report["environment"]
    lines: list[str] = []
    add = lines.append
    add(
        f"[probe] {report['contract_id']} v{report['contract_version']} "
        f"(probe {report['probe_version']}) | lane={lane} | mode={report['mode']}"
    )
    add(
        f"[probe] окружение: uid={env['uid']} python={env['python_version']} "
        f"{env['architecture']} node={env['node_version']} npm={env['npm_version']} "
        f"temp={env['temp_dir']}"
    )
    add(
        "[probe] lanes: "
        + " ".join(f"{name}={status}" for name, status in report["lanes"].items())
        + "   (§6.2: NOT_RUN — это НЕ passed и НЕ skipped)"
    )
    add(
        f"[probe] обязательные для lane {lane} capabilities (§5): "
        + ", ".join(report["required_capabilities"])
    )
    add("")
    width = max(len(r["check"]) for r in report["checks"]) + 2
    sev_width = max(len(r["severity"]) for r in report["checks"]) + 2
    add(f"  {'STATUS':<9}{'SEVERITY':<{sev_width}}{'CHECK':<{width}}REASON")
    for row in report["checks"]:
        code = row["reason_code"] or "-"
        add(f"  {row['status']:<9}{row['severity']:<{sev_width}}{row['check']:<{width}}{code}")
        if row["message"]:
            add(f"          └─ {row['contract_ref']}: {row['message']}")
    add("")
    if report["advisory_failed"]:
        add("[probe] ПРЕДУПРЕЖДЕНИЯ (не обязательны для этого lane/режима):")
        for row in report["advisory_failed"]:
            add(f"  - {row['check']} [{row['reason_code']}]: {row['message']}")
    if report["required_failed"]:
        add(f"[probe] РЕЗУЛЬТАТ: SETUP FAILURE — lane {lane} запускать НЕЛЬЗЯ.")
        add("[probe] отсутствуют обязательные capabilities:")
        for row in report["required_failed"]:
            add(f"  - {row['check']} [{row['reason_code']}]: {row['message']}")
        add(
            "[probe] §6.1: это setup failure ДО pytest, а не skip; "
            f"exit={report['exit_code']}"
        )
    else:
        add(f"[probe] РЕЗУЛЬТАТ: OK — lane {lane} может запускаться. exit=0")
    add(f"[probe] длительность: {report['duration_seconds']} s")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ci_runtime_probe.py",
        description=(
            "Capability preflight по контракту quality-runtime/v1 (§6). "
            "Запускается ДО pytest; отсутствие обязательной для lane capability — "
            "setup failure, а не skip."
        ),
    )
    parser.add_argument(
        "--profile",
        required=True,
        choices=list(LANES),
        help="lane, для которого проверяется окружение",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="машиночитаемый отчёт на stdout (поля пригодны для receipt §8)",
    )
    parser.add_argument(
        "--enforce",
        action="store_true",
        help="enforce clean-room profile (§3 + §3.3 norm corpus): обязательно всё",
    )
    parser.add_argument(
        "--ci",
        action="store_true",
        help=(
            "прогон в CI-полосе (§6 правило 1): послаблений §6.2 нет, профильные "
            "проверки §3 обязательны; corpus остаётся optional до --enforce"
        ),
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="жёсткий бюджет одной проверки в секундах (по умолчанию 10)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        print("[probe] --timeout должен быть конечным положительным числом", file=sys.stderr)
        return EXIT_USAGE
    report = run_probe(args.profile, enforce=args.enforce, ci=args.ci, timeout=args.timeout)
    if args.as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=False))
    else:
        print(render_text(report))
    return int(report["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
