"""Общая тест-конфигурация.

Тесты не должны зависеть от production `.env`. В частности, портальная
аутентификация (`PORTAL_AUTH_ENABLED=true` в prod) ломает TestClient-тесты,
которые ходят в API без логина. Жёстко выключаем её ДО импорта приложения.

`backend/app/main.py` грузит `.env` через `os.environ.setdefault(...)`, поэтому
переменная, выставленная здесь раньше импорта, не перезаписывается значением из
`.env`.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

os.environ["PORTAL_AUTH_ENABLED"] = "false"

# Keep both storage generations and the object registry away from live data for
# the entire pytest process.  Per-test monkeypatches are insufficient here:
# TestClient can leave a pipeline task alive after a fixture is torn down, at
# which point that task would see the restored production paths and recreate
# ``projects/``.  A process-lifetime sandbox remains valid until Python exits.
_STORAGE_SANDBOX = tempfile.TemporaryDirectory(prefix="pdf-proverka-pytest-storage-")
_STORAGE_SANDBOX_ROOT = Path(_STORAGE_SANDBOX.name)
os.environ["AUDIT_PROJECTS_DIR"] = str(_STORAGE_SANDBOX_ROOT / "projects")
os.environ["AUDIT_OBJECTS_FILE"] = str(_STORAGE_SANDBOX_ROOT / "objects.json")
# Журнал действий — тоже в песочницу процесса: мост logging живёт на root до
# конца pytest, а per-test monkeypatch откатывается на БАЗОВОЕ значение
# config.ACTION_LOG_DIR — оно не должно быть прод-директорией logs/actions.
os.environ["AUDIT_ACTION_LOG_DIR"] = str(_STORAGE_SANDBOX_ROOT / "actions_log")

# `backend/app/data/` — такой же живой машинный стейт, как `projects/` и
# `logs/actions/`: там лежат stage_models.json, prepare_queue.json,
# usage_data.json, hidden_projects.json, реестры и журналы платных вызовов.
# Без изоляции тест читает МАШИННУЮ маршрутизацию моделей вместо кодовых
# умолчаний — ровно этим падал
# `test_distributed_workers_network_e2e_11g.py::
# test_d_backend_passes_the_requirement_into_create_audit_job`: локальный
# stage_models.json уводил ВСЕ стадии на `openai/gpt-5.4`.
#
# Каталог нельзя подменить пустым: рядом с машинным стейтом в той же папке
# лежат файлы РЕПОЗИТОРИЯ (чек-листы дисциплин и их метаданные,
# model_prices.json, примеры телеметрии stage01, снимки
# section_optimization_pipeline), на которых стоят отдельные тесты. Поэтому в
# песочницу кладётся КОПИЯ каталога БЕЗ машинных файлов состояния. Имя папки
# — ровно `data`: на это опирается tests/text_analysis/test_checklist_loader.py
# (`CHECKLIST_DIR.parent.name == "data"`).
_APP_DATA_SOURCE = Path(__file__).resolve().parents[1] / "backend" / "app" / "data"
_APP_DATA_SANDBOX = _STORAGE_SANDBOX_ROOT / "data"

#: Живой runtime-стейт в `backend/app/data` — в песочницу НЕ копируется.
#: Список = пофайловые правила `.gitignore` для этой папки + runtime-константы
#: `backend/app/core/config.py` (BATCH_QUEUE_FILE, STAGE_MODELS_FILE и др.).
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
    "section_optimization",   # снимки прогонов конкретной машины (**/*.json)
    "stage_batch_modes.json",
    "stage_comparison_saved_config.json",
    "stage_models.json",
    "usage_data.json",
    "usage_offsets.json",
    "users.json",
})


def _seed_app_data_sandbox() -> None:
    """Положить в песочницу РЕПОЗИТОРНУЮ часть `backend/app/data`."""
    _APP_DATA_SANDBOX.mkdir(parents=True, exist_ok=True)
    if not _APP_DATA_SOURCE.is_dir():
        return
    for entry in sorted(_APP_DATA_SOURCE.iterdir()):
        if entry.name in _APP_DATA_RUNTIME_STATE:
            continue
        if entry.name.startswith("missing_norms_online_"):
            continue
        target = _APP_DATA_SANDBOX / entry.name
        if entry.is_dir():
            shutil.copytree(entry, target, dirs_exist_ok=True)
        else:
            shutil.copy2(entry, target)


_seed_app_data_sandbox()
os.environ["AUDIT_APP_DATA_DIR"] = str(_APP_DATA_SANDBOX)

# Storage cutover flags are production-controlled and may be v2-primary in the
# developer shell. Tests must start from a deterministic legacy baseline and
# opt into projects_v2 explicitly via monkeypatch inside the test.
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

    Тест, оставивший переменную в окружении процесса, портит СОСЕДЕЙ — и это
    не гипотеза: `test_openrouter_worker_provider_11j.py::
    test_rev6_feature_flags_cannot_inject_provider_env` дёргает боевую
    `remote_audit_runner.apply_routing_flags`, которая ШТАТНО пишет
    `STAGE01_THIRD_LEG_ENABLED=true` прямо в `os.environ` и за собой не
    убирает. После этого `test_stage01_dual_review.py`, зелёный в одиночку, в
    полном наборе падал. Чинится не один случай, а класс: любой вызов
    production-кода, правящего окружение, теперь откатывается на границе теста.

    Восстанавливаются все три вида расхождений:
      * ДОБАВЛЕННЫЕ переменные — удаляются;
      * ИЗМЕНЁННЫЕ — возвращаются к прежнему значению;
      * УДАЛЁННЫЕ — возвращаются обратно.

    Фикстура объявлена ПЕРВОЙ в файле намеренно: autouse-фикстуры одного скоупа
    поднимаются в порядке объявления и сворачиваются в обратном, поэтому её
    восстановление идёт ПОСЛЕ отката `monkeypatch` и остальных изоляторов —
    и снимок берётся до того, как они успели что-то выставить. Фикстуры более
    широких скоупов (module/session) поднимаются РАНЬШЕ функциональных, так что
    выставленное ими окружение попадает в снимок и не сносится.
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


#: Модули, чьи ЗАГЛАВНЫЕ bool-глобали правит production-код: тот же
#: `remote_audit_runner.apply_routing_flags` после записи в `os.environ`
#: делает `setattr` на уже импортированных модулях (списки `_CONFIG_BOOL_FLAGS`
#: и `_STAGE01_MODULE_FLAGS`) — «для тех, кто прочитал переменную однажды».
_FLAG_CARRIER_MODULES = (
    "backend.app.core.config",
    "backend.app.pipeline.stages.block_analysis.gemma_findings_only",
)


@pytest.fixture(autouse=True)
def _restore_routing_flag_attributes():
    """Вторая половина того же протекания: флаги в ГЛОБАЛЯХ модулей.

    Восстановления `os.environ` мало, и это проверено на живом наборе.
    `test_rev6_feature_flags_cannot_inject_provider_env` вызывает
    `apply_routing_flags`, а та не только пишет `STAGE01_THIRD_LEG_ENABLED` в
    окружение, но и ставит `gemma_findings_only.STAGE01_THIRD_LEG_ENABLED = True`
    напрямую — если модуль уже импортирован. В паре из двух модулей он ещё не
    импортирован и всё зелено; в полном наборе импортирован, и
    `test_stage01_dual_review` получает лишнюю «третью ногу» (`new: 2` вместо 1).
    Откат окружения такой `setattr` не отменяет — нужен снимок самих глобалей.

    Снимаются только ЗАГЛАВНЫЕ атрибуты типа bool и только у УЖЕ импортированных
    модулей: не импортированный на момент старта теста прочитает уже
    восстановленное окружение при своём импорте сам.
    """
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
def _isolate_batch_queue_file(tmp_path, monkeypatch):
    """НИ ОДИН тест не должен писать в реальный backend/app/data/batch_queue.json.

    Тесты, дёргающие реальный PipelineManager (start_batch / add_to_batch /
    resume_interrupted_batch / _persist_queue), без изоляции перезаписывают
    прод-файл очереди в общей data-папке — инцидент: фантомная M31A-очередь
    попала в production batch_queue.json. Перенаправляем module-global
    BATCH_QUEUE_FILE в per-test tmp для КАЖДОГО теста (autouse, future-proof).

    Тест, которому нужен собственный путь (напр. restart-recovery), может
    переопределить значение повторным monkeypatch.setattr — его значение
    победит, оба корректно откатятся (LIFO).

    Только тестовая изоляция: runtime-логика и API не меняются.
    """
    try:
        import backend.app.pipeline.manager as _mgr
    except Exception:
        # Тесты, не импортирующие backend (если такие есть) — изоляция не нужна.
        return
    monkeypatch.setattr(
        _mgr, "BATCH_QUEUE_FILE", tmp_path / "batch_queue.json", raising=False
    )


@pytest.fixture(autouse=True)
def _isolate_storage_cutover_env(tmp_path, monkeypatch):
    """Keep every test away from the live ``projects_v2`` store.

    The suite intentionally starts in ``dual_write_shadow`` so a number of
    integration tests exercise the mirror hooks.  Without an explicit v2 root
    those hooks resolve ``config.DATA_DIR / projects_v2`` and write synthetic
    pytest objects plus ledger entries into production.  Each test therefore
    gets a private v2 root by default; tests that need another root can still
    override or delete the environment variable with ``monkeypatch``.
    """
    for name, value in _DEFAULT_STORAGE_ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("AUDIT_PROJECTS_V2_DIR", str(tmp_path / "projects_v2"))


@pytest.fixture(autouse=True)
def _isolate_action_log(tmp_path, monkeypatch):
    """НИ ОДИН тест не должен писать в реальный logs/actions/.

    ActionLogMiddleware активен в полном app: любой TestClient-запрос без
    изоляции дописывал бы события в живой журнал действий. Перенаправляем
    config.ACTION_LOG_DIR в per-test tmp; тест журнала может переопределить
    повторным monkeypatch.setattr (LIFO)."""
    try:
        from backend.app.core import config as _cfg
    except Exception:
        return
    monkeypatch.setattr(
        _cfg, "ACTION_LOG_DIR", tmp_path / "actions_log", raising=False
    )


@pytest.fixture(autouse=True)
def _isolate_schedule_completion_file(tmp_path, monkeypatch):
    """НИ ОДИН тест не должен писать в реальный knowledge_base/schedule_completion.json.

    save_expert_review теперь штампует «день завершения» проекта через
    schedule_service.set_completion_once. Тесты, дёргающие save_expert_review
    (expert-review, external_register), без изоляции пишут в живой стор графика
    (инцидент: фейковые проекты DOC-REVIEW/1232-ЧМ-КМ-1 в проде). Перенаправляем
    module-global SCHEDULE_COMPLETION_FILE в per-test tmp для КАЖДОГО теста.

    Тест, которому нужен собственный путь, переопределяет повторным
    monkeypatch.setattr (его значение победит, оба откатятся LIFO).
    """
    try:
        import backend.app.services.common.schedule_service as _sched
    except Exception:
        return
    monkeypatch.setattr(
        _sched, "SCHEDULE_COMPLETION_FILE",
        tmp_path / "schedule_completion.json", raising=False,
    )
