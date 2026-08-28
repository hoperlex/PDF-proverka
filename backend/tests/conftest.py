"""Backend test harness isolation from production storage cutover flags."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

# Журнал действий — в песочницу процесса (см. tests/conftest.py): базовое
# значение config.ACTION_LOG_DIR не должно указывать на прод logs/actions.
_ACTION_LOG_SANDBOX = tempfile.TemporaryDirectory(prefix="pdf-proverka-pytest-actionlog-")
os.environ.setdefault(
    "AUDIT_ACTION_LOG_DIR", str(Path(_ACTION_LOG_SANDBOX.name) / "actions_log")
)

# `backend/app/data/` — тоже живой машинный стейт (stage_models.json,
# prepare_queue.json, usage_data.json, hidden_projects.json ...). Полное
# обоснование и список исключений — в `tests/conftest.py`; здесь то же самое,
# потому что `pytest backend/tests` запускается и отдельно, а тогда
# `tests/conftest.py` вообще не загружается.
_APP_DATA_SOURCE = Path(__file__).resolve().parents[1] / "app" / "data"

#: Живой runtime-стейт в `backend/app/data` — в песочницу НЕ копируется.
_APP_DATA_RUNTIME_STATE = frozenset({
    "batch_queue.json",
    "external_registers",
    "hidden_projects.json",
    "missing_norms_vault.json",
    "objects.json",
    "paid_api_blocked_events.jsonl",
    "paid_cost.json",
    "paid_cost_events.jsonl",
    "prepare_queue.json",
    "project_groups.json",
    "project_rename.reverse.json",
    "section_optimization",
    "stage_batch_modes.json",
    "stage_comparison_saved_config.json",
    "stage_models.json",
    "usage_data.json",
    "usage_offsets.json",
    "users.json",
})

if not os.environ.get("AUDIT_APP_DATA_DIR"):
    # Имя каталога — ровно `data`: на это опирается
    # tests/text_analysis/test_checklist_loader.py.
    _APP_DATA_SANDBOX_ROOT = tempfile.TemporaryDirectory(
        prefix="pdf-proverka-pytest-appdata-"
    )
    _APP_DATA_SANDBOX = Path(_APP_DATA_SANDBOX_ROOT.name) / "data"
    _APP_DATA_SANDBOX.mkdir(parents=True, exist_ok=True)
    if _APP_DATA_SOURCE.is_dir():
        for _entry in sorted(_APP_DATA_SOURCE.iterdir()):
            if _entry.name in _APP_DATA_RUNTIME_STATE:
                continue
            if _entry.name.startswith("missing_norms_online_"):
                continue
            _target = _APP_DATA_SANDBOX / _entry.name
            if _entry.is_dir():
                shutil.copytree(_entry, _target, dirs_exist_ok=True)
            else:
                shutil.copy2(_entry, _target)
    os.environ["AUDIT_APP_DATA_DIR"] = str(_APP_DATA_SANDBOX)

_DEFAULT_STORAGE_ENV = {
    "AUDIT_STORAGE_BACKEND": "legacy",
    "AUDIT_PROJECTS_V2_WRITE_MODE": "dual_write_shadow",
    "AUDIT_PROJECTS_V2_READ_DEFAULT_ENABLED": "false",
}
for _name, _value in _DEFAULT_STORAGE_ENV.items():
    os.environ[_name] = _value


@pytest.fixture(autouse=True)
def _restore_process_environ():
    """Снимок `os.environ` до теста и точное восстановление после него.

    Тот же изолятор, что в `tests/conftest.py` (там же — полное обоснование:
    production-код вроде `remote_audit_runner.apply_routing_flags` штатно пишет
    флаги прямо в окружение процесса и за собой не убирает). Восстанавливаются
    ДОБАВЛЕННЫЕ (удаляются), ИЗМЕНЁННЫЕ (возвращается прежнее значение) и
    УДАЛЁННЫЕ (возвращаются) переменные.

    Объявлена ПЕРВОЙ в файле: autouse-фикстуры одного скоупа поднимаются в
    порядке объявления и сворачиваются в обратном, поэтому восстановление идёт
    ПОСЛЕ отката `monkeypatch` и остальных изоляторов.
    """
    snapshot = dict(os.environ)
    try:
        yield
    finally:
        current = dict(os.environ)
        if current == snapshot:
            return
        for name in current:
            if name not in snapshot:
                os.environ.pop(name, None)
        for name, value in snapshot.items():
            if current.get(name) != value:
                os.environ[name] = value


#: Модули, чьи ЗАГЛАВНЫЕ bool-глобали правит production-код
#: (`remote_audit_runner.apply_routing_flags`). Обоснование — в
#: `tests/conftest.py`: отката `os.environ` мало, флаг остаётся ещё и в
#: глобали уже импортированного модуля.
_FLAG_CARRIER_MODULES = (
    "backend.app.core.config",
    "backend.app.pipeline.stages.block_analysis.gemma_findings_only",
)


@pytest.fixture(autouse=True)
def _restore_routing_flag_attributes():
    """Снимок и восстановление ЗАГЛАВНЫХ bool-глобалей флаговых модулей."""
    snapshot = []
    for name in _FLAG_CARRIER_MODULES:
        module = sys.modules.get(name)
        if module is None:
            continue
        snapshot.append((module, {
            attr: value for attr, value in vars(module).items()
            if attr.isupper() and isinstance(value, bool)
        }))
    try:
        yield
    finally:
        for module, values in snapshot:
            for attr, value in values.items():
                if getattr(module, attr, None) is not value:
                    setattr(module, attr, value)


@pytest.fixture(autouse=True)
def _isolate_storage_cutover_env(monkeypatch):
    """Every backend test starts from legacy storage unless it opts into v2."""
    for name, value in _DEFAULT_STORAGE_ENV.items():
        monkeypatch.setenv(name, value)


@pytest.fixture(autouse=True)
def _isolate_action_log(tmp_path, monkeypatch):
    """Никакой backend-тест не пишет в живой logs/actions/ (журнал действий)."""
    try:
        from backend.app.core import config as _cfg
    except Exception:
        return
    monkeypatch.setattr(
        _cfg, "ACTION_LOG_DIR", tmp_path / "actions_log", raising=False
    )


@pytest.fixture(autouse=True)
def _isolate_schedule_completion_file(tmp_path, monkeypatch):
    """Никакой backend-тест не пишет в живой knowledge_base/schedule_completion.json.

    save_expert_review штампует «день завершения» проекта через
    schedule_service.set_completion_once — изолируем стор графика в per-test tmp.
    """
    try:
        import backend.app.services.common.schedule_service as _sched
    except Exception:
        return
    monkeypatch.setattr(
        _sched, "SCHEDULE_COMPLETION_FILE",
        tmp_path / "schedule_completion.json", raising=False,
    )
