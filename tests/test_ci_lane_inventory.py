"""Тесты инвентаря test lanes (`scripts/ci_lane_inventory.py`), W0-OPS-03 часть 2.

Проверяется не «инструмент что-то посчитал», а три вещи, ради которых он
существует:

* правило вывода lane соответствует таблице §5 контракта
  `docs/architecture/QUALITY_RUNTIME_CONTRACT_V1.md` — на СИНТЕТИЧЕСКИХ
  исходниках, где ожидаемый lane известен заранее, а не на живом репозитории,
  чей ответ пришлось бы подгонять;
* инструмент честен там, где статика бессильна: убийство процесса без
  перезапуска, подменённая API и признаки из чужого helper-модуля попадают в
  «нужна ручная классификация», а не в уверенный lane;
* инструмент безопасен: по умолчанию exit 0 (W0-OPS-03 не включает enforce),
  ни один файл не изменяется, новых зависимостей нет.

Синтетические модули пишутся в `tmp_path` и НИКОГДА не запускаются: инвентарь
разбирает их через `ast`, поэтому «тест», который в реальном прогоне убил бы
процесс, здесь безопасен.
"""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# Primary lane §5: network — `run_cli` запускает инвентарь настоящим дочерним
# процессом (§5: «реальный … process lifecycle», разрешено process spawn/cleanup).
# Слово `uvicorn` ниже встречается только как синтетический вход для инструмента.
pytestmark = pytest.mark.network

ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = ROOT / "scripts" / "ci_lane_inventory.py"

_spec = importlib.util.spec_from_file_location("ci_lane_inventory", SCRIPT_PATH)
inventory = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
# Регистрация до exec_module: dataclass'ы с строковыми аннотациями резолвят их
# через sys.modules[cls.__module__].
sys.modules["ci_lane_inventory"] = inventory
_spec.loader.exec_module(inventory)


# ---------------------------------------------------------------------------
# Помощники
# ---------------------------------------------------------------------------


def write_module(tmp_path: Path, source: str, name: str = "test_sample.py") -> Path:
    """Положить синтетический тестовый модуль в `<tmp>/tests/`."""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    path = tests_dir / name
    path.write_text(source, encoding="utf-8")
    return path


def analyse(tmp_path: Path, source: str, name: str = "test_sample.py"):
    path = write_module(tmp_path, source, name)
    return inventory.analyse_module(path, tmp_path, {})


def run_cli(tmp_path: Path, *args: str) -> subprocess.CompletedProcess:
    """Запустить инструмент отдельным процессом — так проверяется код возврата."""
    env = dict(os.environ)
    env["AUDIT_DISABLE_DOTENV"] = "1"
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--root", str(tmp_path), *args],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )


def tree_digest(root: Path) -> dict[str, str]:
    """SHA-256 каждого файла дерева — чтобы доказать, что инструмент не пишет."""
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


# ---------------------------------------------------------------------------
# Правило вывода: §5, шаг за шагом
# ---------------------------------------------------------------------------


def test_pure_memory_module_is_unit(tmp_path):
    """§5 `unit`: «только память» — ни одного побочного эффекта в исходнике."""
    report = analyse(
        tmp_path,
        "def test_sum():\n"
        "    assert sum([1, 2, 3]) == 6\n",
    )
    assert report.inferred_lane == "unit"
    assert report.decided_by == []


def test_filesystem_write_is_not_unit(tmp_path):
    """§5 определяет `unit` как «только память»: запись файла из него выводит."""
    report = analyse(
        tmp_path,
        "def test_writes(tmp_path):\n"
        "    (tmp_path / 'a.txt').write_text('x')\n"
        "    assert (tmp_path / 'a.txt').exists()\n",
    )
    assert report.inferred_lane == "integration"
    assert {e.kind for e in report.decided_by} == {"fs_write"}


def test_testclient_is_integration(tmp_path):
    """§5 `integration`: «provisioned local services» — живое ASGI-приложение."""
    report = analyse(
        tmp_path,
        "from fastapi.testclient import TestClient\n"
        "from backend.app.main import app\n"
        "def test_health():\n"
        "    client = TestClient(app)\n"
        "    assert client.get('/health').status_code == 200\n",
    )
    assert report.inferred_lane == "integration"
    assert "asgi_client" in {e.kind for e in report.decided_by}


def test_worker_thread_is_integration(tmp_path):
    """§5 `integration`: «threads»."""
    report = analyse(
        tmp_path,
        "import threading\n"
        "def test_thread():\n"
        "    worker = threading.Thread(target=lambda: None)\n"
        "    worker.start()\n"
        "    worker.join()\n",
    )
    assert report.inferred_lane == "integration"
    assert "worker_thread" in {e.kind for e in report.decided_by}


def test_subprocess_is_network(tmp_path):
    """§5 `network`: «реальный … process lifecycle» и «child processes»."""
    report = analyse(
        tmp_path,
        "import subprocess, sys\n"
        "def test_child():\n"
        "    done = subprocess.run([sys.executable, '-c', 'pass'])\n"
        "    assert done.returncode == 0\n",
    )
    assert report.inferred_lane == "network"
    assert "process_spawn" in {e.kind for e in report.decided_by}


def test_socket_is_network(tmp_path):
    """§5 `network`: «реальный … socket … lifecycle»."""
    report = analyse(
        tmp_path,
        "import socket\n"
        "def test_bind():\n"
        "    sock = socket.socket()\n"
        "    sock.bind(('127.0.0.1', 0))\n"
        "    sock.close()\n",
    )
    assert report.inferred_lane == "network"
    assert "socket" in {e.kind for e in report.decided_by}


def test_grpc_channel_is_network(tmp_path):
    """§5 `network`: «реальный … gRPC … lifecycle»."""
    report = analyse(
        tmp_path,
        "import grpc\n"
        "def test_channel():\n"
        "    channel = grpc.insecure_channel('127.0.0.1:50051')\n"
        "    assert channel is not None\n",
    )
    assert report.inferred_lane == "network"
    assert "grpc_channel" in {e.kind for e in report.decided_by}


def test_uvicorn_import_is_network(tmp_path):
    """`uvicorn` — настоящий HTTP-сервер, это lane `network`, а не integration."""
    report = analyse(
        tmp_path,
        "import uvicorn\n"
        "def test_server():\n"
        "    uvicorn.run('app:app', port=8081)\n",
    )
    assert report.inferred_lane == "network"
    assert {e.kind for e in report.decided_by} == {"uvicorn"}


def test_uvicorn_in_child_command_line_is_network(tmp_path):
    """Так поднимает сервер `tests/test_distributed_workers_prepipeline_gate.py`."""
    report = analyse(
        tmp_path,
        "import subprocess, sys\n"
        "def test_server():\n"
        "    proc = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app:app'])\n"
        "    proc.terminate()\n",
    )
    assert report.inferred_lane == "network"
    assert {"process_spawn", "uvicorn"} <= {e.kind for e in report.decided_by}


def test_prose_about_behaviour_is_not_behaviour(tmp_path):
    """Регресс: докстрока про uvicorn уводила два модуля в `network`.

    Промах был настоящий — `tests/distributed_workers_helpers.py:166` («…для
    ОТДЕЛЬНОГО процесса (uvicorn, smoke)») делал сетевыми два импортирующих её
    модуля. Признак берётся только с токена без пробелов и никогда из докстроки.
    """
    report = analyse(
        tmp_path,
        '''"""Окружение для ОТДЕЛЬНОГО процесса (uvicorn, smoke) и contracts/domain."""\n'''
        "def test_pure():\n"
        "    \"\"\"Проверяет разбор, а не запуск uvicorn на contracts/domain/v1.\"\"\"\n"
        "    assert True\n",
    )
    assert report.inferred_lane == "unit"
    assert report.evidence == []


def test_first_party_server_import_is_network_but_flagged(tmp_path):
    """Сокет `GatewayServer` открывает production-код — вывод помечается как требующий глаз."""
    report = analyse(
        tmp_path,
        "from backend.app.agent_gateway.server import GatewayServer\n"
        "def test_gateway(tmp_path):\n"
        "    server = GatewayServer(config=None)\n"
        "    assert server is not None\n",
    )
    assert report.inferred_lane == "network"
    assert "first_party_server" in {e.kind for e in report.decided_by}
    assert "PRODUCTION_SIDE_IO" in report.manual_review


def test_ordinary_first_party_import_is_not_network(tmp_path):
    """Правило узкое: обычный импорт из `backend` сетевым модуль не делает."""
    report = analyse(
        tmp_path,
        "from backend.app.services.findings import merge_findings\n"
        "def test_merge():\n"
        "    assert merge_findings([]) == []\n",
    )
    assert report.inferred_lane == "unit"


def test_contract_artifact_is_contract(tmp_path):
    """§5 `contract`: «schema/version/provider-consumer compatibility»."""
    report = analyse(
        tmp_path,
        "import json\n"
        "from pathlib import Path\n"
        "def test_states_match_markdown():\n"
        "    data = json.loads(Path('contracts/domain/v1/states.json').read_text())\n"
        "    assert data['state_machines']\n",
    )
    assert report.inferred_lane == "contract"
    assert "contract_path_literal" in {e.kind for e in report.decided_by}


def test_contract_may_use_temp_files_and_stays_contract(tmp_path):
    """§5 разрешает contract-тесту «temp files»: запись его в integration не гонит."""
    report = analyse(
        tmp_path,
        "from pathlib import Path\n"
        "def test_proto_roundtrip(tmp_path):\n"
        "    (tmp_path / 'copy.proto').write_text(\n"
        "        Path('contracts/agent_stream/v1/common.proto').read_text()\n"
        "    )\n"
        "    assert (tmp_path / 'copy.proto').exists()\n",
    )
    assert report.inferred_lane == "contract"


def test_service_beats_contract(tmp_path):
    """Сервис/поток сильнее contract: §5 запрещает contract-тесту service/network."""
    report = analyse(
        tmp_path,
        "import threading\n"
        "from pathlib import Path\n"
        "def test_proto_and_thread():\n"
        "    Path('contracts/agent_stream/v1/common.proto').read_text()\n"
        "    threading.Thread(target=lambda: None).start()\n",
    )
    assert report.inferred_lane == "integration"


def test_kill_with_restart_is_chaos(tmp_path):
    """§5 `chaos` = «recovery после SIGTERM/SIGKILL и restart» — нужны ОБА факта."""
    report = analyse(
        tmp_path,
        "import signal, subprocess, sys\n"
        "def test_gateway_restart():\n"
        "    first = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(9)'])\n"
        "    first.send_signal(signal.SIGKILL)\n"
        "    second = subprocess.Popen([sys.executable, '-c', 'pass'])\n"
        "    assert second.wait() == 0\n",
    )
    assert report.inferred_lane == "chaos"
    assert "process_signal" in {e.kind for e in report.decided_by}


def test_kill_in_finally_is_network_cleanup_not_chaos(tmp_path):
    """§5 отдаёт «process spawn/cleanup» lane `network`: уборка — не chaos."""
    report = analyse(
        tmp_path,
        "import signal, subprocess, sys\n"
        "def test_child_runs():\n"
        "    proc = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(9)'])\n"
        "    try:\n"
        "        assert proc.pid > 0\n"
        "    finally:\n"
        "        proc.send_signal(signal.SIGTERM)\n",
    )
    assert report.inferred_lane == "network"
    assert "process_cleanup" in {e.kind for e in report.evidence}
    assert "KILL_WITHOUT_RESTART" not in report.manual_review


def test_kill_without_restart_needs_manual_classification(tmp_path):
    """Честность вместо угадывания: убили и не подняли — решает человек."""
    report = analyse(
        tmp_path,
        "import signal, subprocess, sys\n"
        "def test_dies():\n"
        "    proc = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(9)'])\n"
        "    proc.send_signal(signal.SIGTERM)\n"
        "    assert proc.wait() != 0\n",
    )
    assert report.inferred_lane == "network"
    assert "KILL_WITHOUT_RESTART" in report.manual_review


def test_liveness_probe_is_not_a_kill(tmp_path):
    """`os.kill(pid, 0)` ничего не убивает — в `tests/test_cpu_pool.py` это проба."""
    report = analyse(
        tmp_path,
        "import os\n"
        "def test_alive():\n"
        "    os.kill(1234, 0)\n",
    )
    assert report.inferred_lane == "unit"
    assert "liveness_probe" in {e.kind for e in report.evidence}
    assert all(e.kind != "process_signal" for e in report.decided_by)


def test_loopback_literal_alone_is_not_network(tmp_path):
    """Слабый признак не решает: строка с адресом может просто разбираться."""
    report = analyse(
        tmp_path,
        "def test_url_parsing():\n"
        "    assert 'http://127.0.0.1:8081'.startswith('http://')\n",
    )
    assert report.inferred_lane == "unit"
    weak = [e for e in report.evidence if e.kind == "loopback_literal"]
    assert weak and all(not e.deciding for e in weak)


def test_patched_subprocess_without_real_call_is_not_network(tmp_path):
    """Подмена API — это не её вызов: `monkeypatch.setattr` сети не создаёт."""
    report = analyse(
        tmp_path,
        "import subprocess\n"
        "def test_patched(monkeypatch):\n"
        "    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: None)\n"
        "    assert True\n",
    )
    assert report.inferred_lane == "unit"


def test_real_call_next_to_patch_is_flagged_for_manual_review(tmp_path):
    """Если та же API и вызывается, и подменяется — статика не решает, кто победил."""
    report = analyse(
        tmp_path,
        "import subprocess\n"
        "def test_mixed(monkeypatch):\n"
        "    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: None)\n"
        "    subprocess.run(['true'])\n",
    )
    assert report.inferred_lane == "network"
    assert "PATCHED_API" in report.manual_review


def test_helper_evidence_is_inherited_and_flagged(tmp_path):
    """Признак из общего helper-модуля учитывается, но помечается как слабый."""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    (tests_dir / "__init__.py").write_text("", encoding="utf-8")
    (tests_dir / "spawn_helper.py").write_text(
        "import subprocess, sys\n"
        "def launch_child():\n"
        "    return subprocess.Popen([sys.executable, '-c', 'pass'])\n",
        encoding="utf-8",
    )
    report = analyse(
        tmp_path,
        "from tests.spawn_helper import launch_child\n"
        "def test_uses_helper():\n"
        "    assert launch_child() is not None\n",
    )
    assert report.inferred_lane == "network"
    assert any(e.inherited_from for e in report.decided_by)
    assert "INHERITED_ONLY" in report.manual_review


def test_syntax_error_gives_unknown_lane_not_a_guess(tmp_path):
    """Неразобранный модуль — `unknown`, а не «наверное unit»."""
    report = analyse(tmp_path, "def test_broken(:\n    pass\n")
    assert report.inferred_lane == inventory.LANE_UNKNOWN
    assert "PARSE_ERROR" in report.manual_review
    assert report.parse_error


# ---------------------------------------------------------------------------
# Разметка: непомеченные, двойные, конфликтующие ноды
# ---------------------------------------------------------------------------


def test_unmarked_node_is_inventory_failure(tmp_path):
    """§5: «Непомеченный … тест после W0-OPS-03 является inventory failure»."""
    report = analyse(
        tmp_path,
        "def test_one():\n    assert True\n"
        "def test_two():\n    assert True\n",
    )
    assert len(report.unmarked_nodes) == 2
    assert report.marked_nodes == []


def test_slow_is_orthogonal_attribute_not_a_lane(tmp_path):
    """§5 дословно: «`slow` — ортогональный атрибут, не lane»."""
    report = analyse(
        tmp_path,
        "import pytest\n"
        "@pytest.mark.slow\n"
        "def test_slow_but_unmarked():\n"
        "    assert True\n",
    )
    node = report.nodes[0]
    assert node.orthogonal == ("slow",)
    assert node.primary == ()
    assert len(report.unmarked_nodes) == 1


def test_two_primary_markers_are_inventory_failure(tmp_path):
    """§5: «одновременно отнесённый к двум primary lanes тест» — тоже failure."""
    report = analyse(
        tmp_path,
        "import pytest\n"
        "@pytest.mark.unit\n"
        "@pytest.mark.network\n"
        "def test_two_lanes():\n"
        "    assert True\n",
    )
    assert [n.name for n in report.double_marked_nodes] == ["test_two_lanes"]


def test_marker_conflicting_with_behaviour_is_reported(tmp_path):
    """Маркер `network` на тесте без единого сетевого признака — расхождение."""
    report = analyse(
        tmp_path,
        "import pytest\n"
        "@pytest.mark.network\n"
        "def test_pure():\n"
        "    assert 2 + 2 == 4\n",
    )
    conflicts = report.conflicting_nodes
    assert [n.name for n in conflicts] == ["test_pure"]
    assert conflicts[0].primary == ("network",)
    assert conflicts[0].inferred_lane == "unit"


def test_matching_marker_is_not_a_conflict(tmp_path):
    """Совпадение маркера с поведением конфликтом не считается."""
    report = analyse(
        tmp_path,
        "import pytest, subprocess, sys\n"
        "@pytest.mark.network\n"
        "def test_child():\n"
        "    assert subprocess.run([sys.executable, '-c', 'pass']).returncode == 0\n",
    )
    assert report.conflicting_nodes == []


def test_node_lane_is_per_node_not_per_module(tmp_path):
    """Модуль вправе смешивать lanes: маркер сверяется с поведением САМОЙ ноды."""
    report = analyse(
        tmp_path,
        "import pytest, signal, subprocess, sys\n"
        "@pytest.mark.chaos\n"
        "def test_restarts():\n"
        "    first = subprocess.Popen([sys.executable, '-c', 'pass'])\n"
        "    first.send_signal(signal.SIGKILL)\n"
        "    second = subprocess.Popen([sys.executable, '-c', 'pass'])\n"
        "    assert second.wait() == 0\n"
        "@pytest.mark.network\n"
        "def test_only_spawns():\n"
        "    assert subprocess.run([sys.executable, '-c', 'pass']).returncode == 0\n",
    )
    lanes = {node.name: node.inferred_lane for node in report.nodes}
    assert lanes == {"test_restarts": "chaos", "test_only_spawns": "network"}
    assert report.inferred_lane == "chaos"  # сводка по файлу — максимум
    assert report.conflicting_nodes == []


def test_module_level_pytestmark_applies_to_every_node(tmp_path):
    """`pytestmark = pytest.mark.chaos` — так помечен `tests/test_process_chaos_12e.py`."""
    report = analyse(
        tmp_path,
        "import pytest\n"
        "pytestmark = pytest.mark.chaos\n"
        "def test_a():\n    assert True\n"
        "def test_b():\n    assert True\n",
    )
    assert all(node.primary == ("chaos",) for node in report.nodes)
    assert report.unmarked_nodes == []


def test_class_based_tests_are_counted(tmp_path):
    """Ноды живут и в `class Test*` — иначе объём был бы занижен."""
    report = analyse(
        tmp_path,
        "import pytest\n"
        "@pytest.mark.integration\n"
        "class TestGroup:\n"
        "    def test_inner(self):\n"
        "        assert True\n",
    )
    assert [n.name for n in report.nodes] == ["test_inner"]
    assert report.nodes[0].primary == ("integration",)


def test_parametrize_expands_estimated_node_count(tmp_path):
    """`parametrize` порождает несколько нод; считается оценка СНИЗУ по литералу."""
    report = analyse(
        tmp_path,
        "import pytest\n"
        "@pytest.mark.parametrize('value', [1, 2, 3])\n"
        "def test_values(value):\n"
        "    assert value\n",
    )
    assert report.node_count == 1
    assert report.estimated_node_count == 3
    assert report.nodes[0].param_dynamic is False


def test_dynamic_parametrize_is_marked_dynamic(tmp_path):
    """Вычисляемый набор параметров множителя не даёт и помечается честно."""
    report = analyse(
        tmp_path,
        "import pytest\n"
        "CASES = [1, 2]\n"
        "@pytest.mark.parametrize('value', CASES)\n"
        "def test_values(value):\n"
        "    assert value\n",
    )
    assert report.estimated_node_count == 1
    assert report.nodes[0].param_dynamic is True


# ---------------------------------------------------------------------------
# CLI: коды возврата, JSON, безопасность
# ---------------------------------------------------------------------------


def test_cli_default_exit_code_is_zero(tmp_path):
    """Инструмент observe-only: без флага он не валит прогон даже при failure."""
    write_module(tmp_path, "def test_unmarked():\n    assert True\n")
    done = run_cli(tmp_path)
    assert done.returncode == inventory.EXIT_OK, done.stderr
    assert "inventory failure" in done.stdout


def test_cli_fail_on_unmarked_exits_nonzero(tmp_path):
    """`--fail-on-unmarked` — будущий enforce §5, включается явно."""
    write_module(tmp_path, "def test_unmarked():\n    assert True\n")
    done = run_cli(tmp_path, "--fail-on-unmarked")
    assert done.returncode == inventory.EXIT_INVENTORY_FAILURE, done.stdout


def test_cli_fail_on_unmarked_is_green_when_everything_is_marked(tmp_path):
    """Флаг ловит именно inventory failure, а не «всегда красный»."""
    write_module(
        tmp_path,
        "import pytest\n"
        "@pytest.mark.unit\n"
        "def test_marked():\n"
        "    assert True\n",
    )
    done = run_cli(tmp_path, "--fail-on-unmarked")
    assert done.returncode == inventory.EXIT_OK, done.stdout


def test_cli_fail_on_unmarked_catches_double_marked_node(tmp_path):
    """Вторая половина правила §5: двойная разметка тоже inventory failure."""
    write_module(
        tmp_path,
        "import pytest\n"
        "@pytest.mark.unit\n"
        "@pytest.mark.contract\n"
        "def test_two_lanes():\n"
        "    assert True\n",
    )
    done = run_cli(tmp_path, "--fail-on-unmarked")
    assert done.returncode == inventory.EXIT_INVENTORY_FAILURE, done.stdout


def test_cli_json_is_machine_readable(tmp_path):
    """`--json` даёт разбираемый отчёт со всеми ключевыми счётчиками."""
    write_module(
        tmp_path,
        "import pytest, subprocess, sys\n"
        "@pytest.mark.network\n"
        "def test_child():\n"
        "    assert subprocess.run([sys.executable, '-c', 'pass']).returncode == 0\n",
    )
    done = run_cli(tmp_path, "--json")
    assert done.returncode == inventory.EXIT_OK, done.stderr
    payload = json.loads(done.stdout)
    assert payload["mode"] == "observe-only"
    assert payload["totals"]["modules"] == 1
    assert payload["totals"]["functions_with_primary_marker"] == 1
    assert payload["lanes"]["network"]["modules"] == 1
    assert payload["modules"][0]["inferred_lane"] == "network"

    # Полный JSON не годится для evidence: duration меняется,
    # а root зависит от машины. Специальный режим должен дать
    # один и тот же отпечаток на повторных запусках.
    digest_a = run_cli(tmp_path, "--evidence-sha256")
    digest_b = run_cli(tmp_path, "--evidence-sha256")
    assert digest_a.returncode == inventory.EXIT_OK, digest_a.stderr
    assert digest_b.returncode == inventory.EXIT_OK, digest_b.stderr
    assert digest_a.stdout == digest_b.stdout
    assert len(digest_a.stdout.strip()) == 64


def test_cli_unknown_root_is_usage_error(tmp_path):
    done = run_cli(tmp_path / "нет-такого", "--json")
    assert done.returncode == inventory.EXIT_USAGE


def test_tool_does_not_modify_anything(tmp_path):
    """Ключевое ограничение задачи: инвентарь не правит тесты и не ставит маркеры."""
    write_module(tmp_path, "def test_unmarked():\n    assert True\n")
    (tmp_path / "pytest.ini").write_text(
        "[pytest]\ntestpaths = tests\nmarkers =\n    slow: сюда никто не пишет\n",
        encoding="utf-8",
    )
    before = tree_digest(tmp_path)
    assert run_cli(tmp_path, "--json").returncode == inventory.EXIT_OK
    assert run_cli(tmp_path, "--fail-on-unmarked").returncode != inventory.EXIT_OK
    assert tree_digest(tmp_path) == before


def test_pytest_ini_is_only_read_for_paths_and_markers(tmp_path):
    """`pytest.ini` вне объёма W0-OPS-03: инструмент под него подстраивается."""
    (tmp_path / "pytest.ini").write_text(
        "[pytest]\n"
        "testpaths = suite\n"
        "norecursedirs = suite/legacy\n"
        "markers =\n"
        "    slow: поднимает НАСТОЯЩИЕ процессы\n"
        "    chaos: убивает процессы\n",
        encoding="utf-8",
    )
    suite = tmp_path / "suite"
    (suite / "legacy").mkdir(parents=True)
    (suite / "test_live.py").write_text("def test_a():\n    assert True\n", encoding="utf-8")
    (suite / "legacy" / "test_old.py").write_text(
        "def test_b():\n    assert True\n", encoding="utf-8"
    )
    report = inventory.build_report(tmp_path)
    assert report["testpaths"] == ["suite"]
    assert [m["path"] for m in report["modules"]] == ["suite/test_live.py"]
    assert set(report["markers"]["registered_in_pytest_ini"]) == {"slow", "chaos"}


def test_marker_used_but_not_registered_is_reported(tmp_path):
    """Маркер без регистрации даёт PytestUnknownMarkWarning — это стоит видеть."""
    (tmp_path / "pytest.ini").write_text(
        "[pytest]\ntestpaths = tests\nmarkers =\n    slow: атрибут\n", encoding="utf-8"
    )
    write_module(
        tmp_path,
        "import pytest\n@pytest.mark.network\ndef test_x():\n    assert True\n",
    )
    report = inventory.build_report(tmp_path)
    assert report["markers"]["used_but_not_registered"] == ["network"]


# ---------------------------------------------------------------------------
# Ограничения задачи: без зависимостей, по всему репозиторию, быстро
# ---------------------------------------------------------------------------


def test_script_imports_only_stdlib():
    """Новых зависимостей быть не должно: root requirements принадлежат W0-INT-01."""
    tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"), filename=str(SCRIPT_PATH))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            imported.add(node.module.split(".")[0])
    assert imported <= set(sys.stdlib_module_names), sorted(
        imported - set(sys.stdlib_module_names)
    )


def test_real_repository_scan_is_fast_and_non_trivial():
    """Требование задачи: весь репозиторий — быстрее 60 секунд.

    Заодно это единственный тест, который смотрит на живое дерево: он проверяет
    не конкретные числа (они меняются с каждым новым тестом), а что инвентарь
    вообще доходит до конца и видит оба корня из §5.1.
    """
    report = inventory.build_report(ROOT)
    assert report["duration_seconds"] < 60
    assert report["totals"]["modules"] > 300
    assert report["totals"]["test_functions"] > 3000
    scanned = {module["path"].split("/")[0] for module in report["modules"]}
    # §5.1 называет оба корня: `pytest tests backend/tests`.
    assert scanned == {"tests", "backend"}
    assert set(report["lanes"]) == set(inventory.PRIMARY_LANES) | {inventory.LANE_UNKNOWN}
    # До W0-INT-01 здесь доказывалось обратное («разметки ещё нет, > 1000 нод без
    # маркера»). Разметка сделана, и утверждать про её отсутствие больше нечего;
    # ценность у живого дерева осталась ровно одна — §5 называет непомеченную и
    # дважды помеченную ноду inventory failure, значит обеих быть не должно.
    assert report["totals"]["functions_without_primary_marker"] == 0
    assert report["totals"]["double_marked_functions"] == 0
    # Сумма по lanes обязана сойтись с общим числом функций: нода не может ни
    # потеряться между полосами, ни попасть сразу в две.
    marked = report["markers"]["primary_marker_functions"]
    assert sum(marked.values()) == report["totals"]["test_functions"]


def test_module_without_test_functions_is_flagged(tmp_path):
    """Файл `test_*.py` без единой ноды — аномалия сбора, а не «пустой unit»."""
    report = analyse(
        tmp_path,
        "SHARED_FIXTURE_DATA = {'a': 1}\n"
        "def helper():\n"
        "    return SHARED_FIXTURE_DATA\n",
    )
    assert report.nodes == []
    assert "NO_TEST_FUNCTIONS" in report.manual_review


def test_mixed_primary_markers_in_one_module_are_flagged(tmp_path):
    """Разные primary lanes в одном файле — повод посмотреть глазами."""
    report = analyse(
        tmp_path,
        "import pytest\n"
        "@pytest.mark.unit\n"
        "def test_a():\n    assert True\n"
        "@pytest.mark.integration\n"
        "def test_b():\n    assert True\n",
    )
    assert "MIXED_MARKERS" in report.manual_review


def test_every_manual_review_code_has_human_text():
    """Код причины без текста — это отчёт, который никто не сможет прочитать."""
    used = {
        "KILL_WITHOUT_RESTART",
        "PATCHED_API",
        "INHERITED_ONLY",
        "DYNAMIC_DISPATCH",
        "NO_TEST_FUNCTIONS",
        "PARSE_ERROR",
        "MIXED_MARKERS",
        "PRODUCTION_SIDE_IO",
    }
    assert used == set(inventory.MANUAL_REASONS)
    assert all(text.strip() for text in inventory.MANUAL_REASONS.values())


def test_primary_lanes_match_contract_table():
    """Пять lanes §5 — не выдумка инструмента, а таблица контракта."""
    contract = (ROOT / inventory.CONTRACT_DOC).read_text(encoding="utf-8")
    section = contract.split("## 5. Test lanes", 1)[1].split("## 6.", 1)[0]
    for lane in inventory.PRIMARY_LANES:
        assert f"`{lane}`" in section, lane
    assert "`slow` —" in section and "не lane" in section
