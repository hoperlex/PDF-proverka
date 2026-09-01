"""
test_stage02_smoke_controls.py
------------------------------
Регресс-тесты для post-cutover stabilization Stage 02 (2026-05-14):

Найденные проблемы (из post-cutover smoke):
1. Stage 02 при `cancel` после ~30s обработал 19/26 блоков (внутренняя
   параллельность DEFAULT_PARALLELISM=3 + быстрый GPT-5.4). Для smoke это
   слишком много блоков. Нужны env-лимиты:
   - AUDIT_STAGE02_MAX_BLOCKS: ограничивает количество блоков (blocks_filter).
   - AUDIT_STAGE02_MAX_PARALLEL_BATCHES: ограничивает параллельность.

2. При cancel Stage 02 не вызывал `record_block_analysis_usage`, поэтому
   job.cost_usd оставался $0.0, а у пользователя реально ушли деньги
   за GPT-5.4 (OpenRouter). Теперь partial cost учитывается даже при cancel.

Контракт обоих env:
- если env не задан/пустой/невалидный — production behavior без изменений.
- если задан — Stage 02 использует blocks_filter / parallelism override.

Тесты НЕ запускают реальный LLM. Используют monkeypatch
run_findings_only_for_project для проверки argv и pipeline.

Run:
    python -m pytest tests/test_stage02_smoke_controls.py -v
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

# Primary lane §5: integration — пишет во временную ФС, а `unit` по §5 — «только
# память».
pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ─── 1. _read_stage02_smoke_env контракт ───────────────────────────────


def test_smoke_env_empty_returns_empty_dict(monkeypatch):
    """Без env-переменных → пустой dict (production default behavior)."""
    monkeypatch.delenv("AUDIT_STAGE02_MAX_BLOCKS", raising=False)
    monkeypatch.delenv("AUDIT_STAGE02_MAX_PARALLEL_BATCHES", raising=False)
    from backend.app.pipeline.stages.block_analysis.runner import _read_stage02_smoke_env
    assert _read_stage02_smoke_env() == {}


def test_smoke_env_max_blocks_int(monkeypatch):
    monkeypatch.setenv("AUDIT_STAGE02_MAX_BLOCKS", "1")
    monkeypatch.delenv("AUDIT_STAGE02_MAX_PARALLEL_BATCHES", raising=False)
    from backend.app.pipeline.stages.block_analysis.runner import _read_stage02_smoke_env
    assert _read_stage02_smoke_env() == {"max_blocks": 1}


def test_smoke_env_max_parallel_int(monkeypatch):
    monkeypatch.delenv("AUDIT_STAGE02_MAX_BLOCKS", raising=False)
    monkeypatch.setenv("AUDIT_STAGE02_MAX_PARALLEL_BATCHES", "1")
    from backend.app.pipeline.stages.block_analysis.runner import _read_stage02_smoke_env
    assert _read_stage02_smoke_env() == {"max_parallel": 1}


def test_smoke_env_both_set(monkeypatch):
    monkeypatch.setenv("AUDIT_STAGE02_MAX_BLOCKS", "2")
    monkeypatch.setenv("AUDIT_STAGE02_MAX_PARALLEL_BATCHES", "1")
    from backend.app.pipeline.stages.block_analysis.runner import _read_stage02_smoke_env
    assert _read_stage02_smoke_env() == {"max_blocks": 2, "max_parallel": 1}


def test_smoke_env_invalid_ignored(monkeypatch):
    """Невалидные значения (не-int, ≤0) игнорируются — production не ломается."""
    monkeypatch.setenv("AUDIT_STAGE02_MAX_BLOCKS", "abc")
    monkeypatch.setenv("AUDIT_STAGE02_MAX_PARALLEL_BATCHES", "0")
    from backend.app.pipeline.stages.block_analysis.runner import _read_stage02_smoke_env
    assert _read_stage02_smoke_env() == {}


def test_smoke_env_negative_ignored(monkeypatch):
    monkeypatch.setenv("AUDIT_STAGE02_MAX_BLOCKS", "-5")
    monkeypatch.setenv("AUDIT_STAGE02_MAX_PARALLEL_BATCHES", "-1")
    from backend.app.pipeline.stages.block_analysis.runner import _read_stage02_smoke_env
    assert _read_stage02_smoke_env() == {}


def test_smoke_env_empty_string_ignored(monkeypatch):
    monkeypatch.setenv("AUDIT_STAGE02_MAX_BLOCKS", "")
    monkeypatch.setenv("AUDIT_STAGE02_MAX_PARALLEL_BATCHES", "")
    from backend.app.pipeline.stages.block_analysis.runner import _read_stage02_smoke_env
    assert _read_stage02_smoke_env() == {}


# ─── 2. Stage 02 runner интеграция: env → run_findings_only_for_project ──


def _make_stage02_project(tmp_path: Path) -> Path:
    """Минимальный project_dir с stage02_blocks_index, document_graph,
    gemma_enrichment_summary — чтобы prerequisites прошли до вызова LLM."""
    project_dir = tmp_path / "M31A"
    output_dir = project_dir / "_output"
    (output_dir / "blocks_stage02_100").mkdir(parents=True)
    (output_dir / "blocks_gemma_100").mkdir(parents=True)
    # project_info
    (project_dir / "project_info.json").write_text(
        json.dumps({"project_id": "M31A", "section": "EOM", "md_file": "doc.md"}),
        encoding="utf-8",
    )
    (project_dir / "doc.md").write_text("# fake md\n\n[TEXT b1]\n", encoding="utf-8")
    # 5 blocks в stage02 index
    blocks = [{"block_id": f"BLK-{i:03d}", "page": i, "file": f"BLK-{i:03d}.png"} for i in range(1, 6)]
    (output_dir / "blocks_stage02_100" / "index.json").write_text(
        json.dumps({"blocks": blocks, "policy": {"profile": "stage02_100", "dpi": 100, "min_long_side": 800, "compact": False}}),
        encoding="utf-8",
    )
    (output_dir / "blocks_gemma_100" / "index.json").write_text(
        json.dumps({"blocks": blocks, "policy": {"profile": "gemma_100_base", "dpi": 100, "min_long_side": 800, "compact": False, "skip_small": False}}),
        encoding="utf-8",
    )
    (output_dir / "document_graph.json").write_text(
        json.dumps({"pages": [{"page": i, "sheet_no": str(i)} for i in range(1, 6)]}),
        encoding="utf-8",
    )
    (output_dir / "gemma_enrichment_summary.json").write_text(
        json.dumps({"schema_version": 2, "blocks_total": 5, "base_blocks_ok": 5}),
        encoding="utf-8",
    )
    return project_dir


def _make_ctx(project_dir: Path):
    """Минимальный PipelineStageContext с no-op callbacks + capture для usage record."""
    from backend.app.pipeline.context import PipelineStageContext

    captured = {"logs": [], "usage_summary": None, "pipeline_log": []}

    async def _log(msg, level="info"):
        captured["logs"].append((level, msg))

    async def _check_before_launch():
        return True

    async def _check_pause():
        return True

    async def _wait_for_rate_limit(reason, cli_output):
        return True

    def _record_cli_usage(*a, **k):
        pass

    def _update_pipeline_log(stage_key, status, **kwargs):
        captured["pipeline_log"].append((stage_key, status, kwargs))

    async def _run_subprocess(*a, **k):
        return (0, "", "")

    def _record_block_analysis_usage(summary):
        captured["usage_summary"] = summary

    ctx = PipelineStageContext(
        project_dir=project_dir,
        project_id="M31A",
        output_dir=project_dir / "_output",
        log=_log,
        check_before_launch=_check_before_launch,
        check_pause=_check_pause,
        wait_for_rate_limit=_wait_for_rate_limit,
        record_cli_usage=_record_cli_usage,
        update_pipeline_log=_update_pipeline_log,
        run_subprocess=_run_subprocess,
        record_block_analysis_usage=_record_block_analysis_usage,
    )
    return ctx, captured


def _patch_run_findings_only(monkeypatch, capture_dict, *, summary_overrides=None):
    """Подменяет gemma_findings_only.run_findings_only_for_project и
    check_prerequisites на mock'и, чтобы Stage 02 тесты не упирались в
    validate_gemma_summary / crop_index_matches_policy."""
    summary_overrides = summary_overrides or {}
    base_summary = {
        "model": "openai/gpt-5.4",
        "blocks_total": 5,
        "blocks_ok": 5,
        "blocks_failed": 0,
        "blocks_skipped_no_context": 0,
        "wall_clock_s": 10.0,
        "cancelled": False,
        "uncovered_blocks": [],
        "totals": {
            "input_tokens": 1000,
            "output_tokens": 500,
            "reasoning_tokens": 200,
            "findings": 3,
            "estimated_cost_usd_total": 0.05,
        },
    }
    base_summary.update(summary_overrides)

    async def _fake_run(project_dir, **kwargs):
        capture_dict["call_kwargs"] = kwargs
        return {
            "output_doc": {},
            "summary": base_summary,
            "plan": [],
            "run_dir": None,
        }

    def _fake_prereq(project_dir, **kwargs):
        return {"ok": True, "reasons": [], "blocks_total": 5, "with_context": 5, "uncovered_blocks": []}

    from backend.app.pipeline.stages.block_analysis import gemma_findings_only as gfo
    monkeypatch.setattr(gfo, "run_findings_only_for_project", _fake_run)
    monkeypatch.setattr(gfo, "check_prerequisites", _fake_prereq)


# ─── Маршрутизация моделей: условия задаёт тест, а не машина ────────────────
#
# Потолок параллельности Stage 02 выбирает МОДЕЛЬ этапа: ансамбль/codex идут по
# STAGE01_CODEX_PARALLELISM (один блок ансамбля = несколько одновременных
# запусков CLI), остальные модели — по общему DEFAULT_PARALLELISM. Модель runner
# берёт из `get_stage_model("block_batch")`, то есть из
# `backend/app/data/stage_models.json` — МАШИННОГО файла: он в .gitignore, в
# чистом клоне его нет, а на конкретной машине там может стоять что угодно. Сам
# потолок ансамбля тоже приходит из окружения (`AUDIT_STAGE02_CODEX_PARALLELISM`
# разбирается один раз на импорте config), а мост провайдеров вообще способен
# перебить модель целиком по env-переменной привязки.
#
# Пока тесты ниже ничего из этого не задавали, они проверяли не код, а состояние
# машины: локальный stage_models.json уводил block_batch на `openai/gpt-5.4`, и
# «умолчания» означали чужую локальную маршрутизацию вместо кодовых
# `_STAGE_MODEL_DEFAULTS`. Поэтому маршрутизация фиксируется здесь явно.

#: Потолок ансамблевой ветки в этих тестах. Значение НАРОЧНО не совпадает ни с
#: production-дефолтом ансамбля (1), ни с DEFAULT_PARALLELISM (3): так видно, что
#: runner читает именно STAGE01_CODEX_PARALLELISM, а не совпал с соседней
#: константой.
_ENSEMBLE_PARALLELISM = 2


def _pin_stage02_routing(
    monkeypatch, model: str, *, ensemble_parallelism: int = _ENSEMBLE_PARALLELISM,
):
    """Зафиксировать модель этапа и потолок ансамбля; вернуть модуль runner."""
    import backend.app.pipeline.stages.block_analysis.runner as runner_mod
    from backend.app.pipeline.stages.block_analysis import gemma_findings_only as gfo

    def _fake_get_stage_model(key):
        assert key == "block_batch", f"Stage 02 спросил чужую стадию: {key}"
        return model

    # Мост провайдеров активируется env-переменной привязки; при активном мосте
    # модель задаёт локальная политика воркера, и заданная тестом строка не
    # применяется вовсе. Для этих тестов мост выключен явно.
    monkeypatch.setattr(gfo, "provider_bridge_active", lambda: False)
    monkeypatch.setattr(runner_mod, "get_stage_model", _fake_get_stage_model)
    monkeypatch.setattr(runner_mod, "STAGE01_CODEX_PARALLELISM", ensemble_parallelism)
    return runner_mod


def _branch_routing(branch: str) -> tuple[str, int]:
    """(модель, ожидаемая параллельность без smoke-env) для обеих веток выбора."""
    from backend.app.core.config import STAGE02_DUAL_MODEL_ID
    from backend.app.pipeline.stages.block_analysis.gemma_findings_only import (
        DEFAULT_MODEL,
        DEFAULT_PARALLELISM,
    )

    if branch == "ensemble":
        return STAGE02_DUAL_MODEL_ID, _ENSEMBLE_PARALLELISM
    return DEFAULT_MODEL, DEFAULT_PARALLELISM


def _smoke_limit_logs(captured, marker: str = "") -> list:
    """SMOKE-LIMIT записи audit log (опционально — только про конкретный лимит)."""
    return [
        (lvl, msg) for lvl, msg in captured["logs"]
        if "SMOKE-LIMIT" in msg and marker in msg
    ]


@pytest.mark.asyncio
async def test_stage02_no_env_uses_defaults(tmp_path, monkeypatch):
    """Без smoke-env Stage 02 работает на КОДОВЫХ умолчаниях.

    Правильное поведение: `_STAGE_MODEL_DEFAULTS["block_batch"]` — ансамбль,
    а у ансамблевой ветки СВОЙ потолок (STAGE01_CODEX_PARALLELISM), потому что
    один блок ансамбля разворачивается в несколько одновременных запусков CLI;
    брать здесь общий DEFAULT_PARALLELISM=3 было бы девять параллельных CLI.
    blocks_filter при этом None и SMOKE-LIMIT предупреждений нет — лимиты не
    заданы, обрабатывается весь документ.

    Прежняя версия теста ждала DEFAULT_PARALLELISM и зеленела только потому,
    что машинный stage_models.json уводил block_batch на `openai/gpt-5.4`.
    """
    from backend.app.core.config import _STAGE_MODEL_DEFAULTS, STAGE02_DUAL_MODEL_ID

    default_model = _STAGE_MODEL_DEFAULTS["block_batch"]
    assert default_model == STAGE02_DUAL_MODEL_ID, (
        f"кодовое умолчание block_batch больше не ансамблевое ({default_model}) — "
        "ожидаемую параллельность нужно пересмотреть по смыслу, а не подогнать"
    )

    monkeypatch.delenv("AUDIT_STAGE02_MAX_BLOCKS", raising=False)
    monkeypatch.delenv("AUDIT_STAGE02_MAX_PARALLEL_BATCHES", raising=False)

    project_dir = _make_stage02_project(tmp_path)
    capture = {}
    _patch_run_findings_only(monkeypatch, capture)
    runner_mod = _pin_stage02_routing(monkeypatch, default_model)

    ctx, captured = _make_ctx(project_dir)
    result = await runner_mod.run_block_analysis_findings_only(ctx)
    assert result.success

    kw = capture["call_kwargs"]
    assert kw.get("parallelism") == _ENSEMBLE_PARALLELISM
    assert kw.get("blocks_filter") is None
    assert not _smoke_limit_logs(captured), "без env не должно быть SMOKE-LIMIT записей"


@pytest.mark.asyncio
@pytest.mark.parametrize("branch", ["ensemble", "single"])
async def test_stage02_no_env_parallelism_matches_model_branch(
    tmp_path, monkeypatch, branch,
):
    """Без env потолок определяет ВЕТКА модели, и обе ветки проверяются явно.

    ансамбль → STAGE01_CODEX_PARALLELISM, одиночная модель → DEFAULT_PARALLELISM.
    Ветку `single` раньше покрывал машинный stage_models.json (block_batch там
    стоял на `openai/gpt-5.4`); теперь модель задаёт сам тест.
    """
    model, expected_parallelism = _branch_routing(branch)

    monkeypatch.delenv("AUDIT_STAGE02_MAX_BLOCKS", raising=False)
    monkeypatch.delenv("AUDIT_STAGE02_MAX_PARALLEL_BATCHES", raising=False)

    project_dir = _make_stage02_project(tmp_path)
    capture = {}
    _patch_run_findings_only(monkeypatch, capture)
    runner_mod = _pin_stage02_routing(monkeypatch, model)

    ctx, captured = _make_ctx(project_dir)
    result = await runner_mod.run_block_analysis_findings_only(ctx)
    assert result.success

    kw = capture["call_kwargs"]
    assert kw.get("parallelism") == expected_parallelism, (
        f"model={model}: ожидалась параллельность {expected_parallelism}, "
        f"получено {kw.get('parallelism')}"
    )
    assert kw.get("blocks_filter") is None
    assert not _smoke_limit_logs(captured)


@pytest.mark.asyncio
async def test_stage02_max_blocks_limits_to_first_n(tmp_path, monkeypatch):
    """AUDIT_STAGE02_MAX_BLOCKS=1 → blocks_filter = первый block_id."""
    monkeypatch.setenv("AUDIT_STAGE02_MAX_BLOCKS", "1")
    monkeypatch.delenv("AUDIT_STAGE02_MAX_PARALLEL_BATCHES", raising=False)

    project_dir = _make_stage02_project(tmp_path)
    capture = {}
    _patch_run_findings_only(monkeypatch, capture)

    from backend.app.pipeline.stages.block_analysis.runner import (
        run_block_analysis_findings_only,
    )
    ctx, captured = _make_ctx(project_dir)
    await run_block_analysis_findings_only(ctx)

    kw = capture["call_kwargs"]
    assert kw.get("blocks_filter") == ["BLK-001"], (
        f"AUDIT_STAGE02_MAX_BLOCKS=1 не ограничил blocks_filter: {kw.get('blocks_filter')}"
    )

    # Проверим, что в audit log есть SMOKE-LIMIT warn
    smoke_logs = [
        (lvl, msg) for lvl, msg in captured["logs"]
        if "SMOKE-LIMIT" in msg and "MAX_BLOCKS" in msg
    ]
    assert smoke_logs, "Нет SMOKE-LIMIT warn записи в audit log"
    assert smoke_logs[0][0] == "warn"


@pytest.mark.asyncio
async def test_stage02_max_blocks_3_limits_to_first_3(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_STAGE02_MAX_BLOCKS", "3")
    project_dir = _make_stage02_project(tmp_path)
    capture = {}
    _patch_run_findings_only(monkeypatch, capture)

    from backend.app.pipeline.stages.block_analysis.runner import (
        run_block_analysis_findings_only,
    )
    ctx, _captured = _make_ctx(project_dir)
    await run_block_analysis_findings_only(ctx)

    assert capture["call_kwargs"].get("blocks_filter") == ["BLK-001", "BLK-002", "BLK-003"]


@pytest.mark.asyncio
@pytest.mark.parametrize("branch", ["ensemble", "single"])
async def test_stage02_max_parallel_overrides_default(tmp_path, monkeypatch, branch):
    """AUDIT_STAGE02_MAX_PARALLEL_BATCHES бьёт дефолт ЛЮБОЙ ветки модели.

    Предмет теста — сам override, поэтому модель задаётся явно и прогоняются обе
    ветки. Значение 1 меньше обоих дефолтов (ансамбль и одиночная модель), значит
    SMOKE-LIMIT warn обязан появиться в обоих случаях и назвать дефолт ИМЕННО
    этой ветки — иначе оператор smoke-прогона не поймёт, от чего он отступил.
    """
    model, default_parallelism = _branch_routing(branch)
    assert default_parallelism != 1, (
        "override совпал с дефолтом ветки — тест перестал что-либо проверять"
    )

    monkeypatch.delenv("AUDIT_STAGE02_MAX_BLOCKS", raising=False)
    monkeypatch.setenv("AUDIT_STAGE02_MAX_PARALLEL_BATCHES", "1")

    project_dir = _make_stage02_project(tmp_path)
    capture = {}
    _patch_run_findings_only(monkeypatch, capture)
    runner_mod = _pin_stage02_routing(monkeypatch, model)

    ctx, captured = _make_ctx(project_dir)
    await runner_mod.run_block_analysis_findings_only(ctx)

    assert capture["call_kwargs"].get("parallelism") == 1
    smoke_logs = _smoke_limit_logs(captured, "MAX_PARALLEL_BATCHES")
    assert smoke_logs
    assert smoke_logs[0][0] == "warn"
    assert f"default={default_parallelism}" in smoke_logs[0][1], (
        f"SMOKE-LIMIT не назвал дефолт ветки {model}: {smoke_logs[0][1]}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("branch", ["ensemble", "single"])
async def test_stage02_invalid_env_uses_defaults(tmp_path, monkeypatch, branch):
    """Невалидный env не ломает production: остаётся дефолт ВЕТКИ модели.

    Правильное поведение — полное отсутствие эффекта: та же параллельность, что
    и без env, blocks_filter=None и ни одной SMOKE-LIMIT записи (иначе оператор
    решит, что лимит применился). Модель задаётся явно, обе ветки прогоняются.
    """
    model, expected_parallelism = _branch_routing(branch)

    monkeypatch.setenv("AUDIT_STAGE02_MAX_BLOCKS", "garbage")
    monkeypatch.setenv("AUDIT_STAGE02_MAX_PARALLEL_BATCHES", "0")

    project_dir = _make_stage02_project(tmp_path)
    capture = {}
    _patch_run_findings_only(monkeypatch, capture)
    runner_mod = _pin_stage02_routing(monkeypatch, model)

    ctx, captured = _make_ctx(project_dir)
    await runner_mod.run_block_analysis_findings_only(ctx)

    assert capture["call_kwargs"].get("parallelism") == expected_parallelism
    assert capture["call_kwargs"].get("blocks_filter") is None
    assert not _smoke_limit_logs(captured), (
        "невалидный env не должен выглядеть как применённый лимит"
    )


# ─── 3. Cost-on-cancel: Stage 02 cancelled → record_block_analysis_usage ──


@pytest.mark.asyncio
async def test_stage02_cancel_records_partial_cost(tmp_path, monkeypatch):
    """При cancel Stage 02 partial cost должен попадать в usage tracker
    (раньше job.cost_usd оставался $0.0 — пользователь не видел расход)."""
    project_dir = _make_stage02_project(tmp_path)
    capture = {}
    _patch_run_findings_only(
        monkeypatch, capture,
        summary_overrides={
            "cancelled": True,
            "blocks_ok": 19,  # как в реальном smoke
            "blocks_failed": 0,
            "totals": {
                "input_tokens": 40517,
                "output_tokens": 17118,
                "reasoning_tokens": 10092,
                "findings": 30,
                "estimated_cost_usd_total": 0.32,
            },
        },
    )

    from backend.app.pipeline.stages.block_analysis.runner import (
        run_block_analysis_findings_only,
    )
    ctx, captured = _make_ctx(project_dir)
    result = await run_block_analysis_findings_only(ctx)

    assert result.cancelled
    # КЛЮЧЕВОЕ: usage_summary должен быть записан
    assert captured["usage_summary"] is not None, (
        "Cancel НЕ записал partial usage — bug повторился"
    )
    totals = captured["usage_summary"].get("totals", {})
    assert totals.get("estimated_cost_usd_total") == 0.32
    # Должна быть warn запись со списанной суммой
    cancel_logs = [
        msg for lvl, msg in captured["logs"]
        if "Stage 02 cancelled" in msg or "cancelled: обработано" in msg
    ]
    assert cancel_logs, "Нет warn-лога о partial cost при cancel"


@pytest.mark.asyncio
async def test_stage02_cancel_with_zero_blocks_skips_recording(tmp_path, monkeypatch):
    """Cancel ДО первого OK блока — usage не записывается (нет смысла)."""
    project_dir = _make_stage02_project(tmp_path)
    capture = {}
    _patch_run_findings_only(
        monkeypatch, capture,
        summary_overrides={
            "cancelled": True,
            "blocks_ok": 0,
            "totals": {
                "input_tokens": 0,
                "output_tokens": 0,
                "reasoning_tokens": 0,
                "findings": 0,
                "estimated_cost_usd_total": 0.0,
            },
        },
    )

    from backend.app.pipeline.stages.block_analysis.runner import (
        run_block_analysis_findings_only,
    )
    ctx, captured = _make_ctx(project_dir)
    result = await run_block_analysis_findings_only(ctx)

    assert result.cancelled
    # Без partial cost — recorder не вызывался
    assert captured["usage_summary"] is None


@pytest.mark.asyncio
async def test_stage02_normal_completion_records_usage_as_before(tmp_path, monkeypatch):
    """Регрессия: при нормальном завершении (не cancel) usage всё ещё записывается."""
    project_dir = _make_stage02_project(tmp_path)
    capture = {}
    _patch_run_findings_only(monkeypatch, capture)  # default cancelled=False

    from backend.app.pipeline.stages.block_analysis.runner import (
        run_block_analysis_findings_only,
    )
    ctx, captured = _make_ctx(project_dir)
    result = await run_block_analysis_findings_only(ctx)

    assert result.success
    assert captured["usage_summary"] is not None
    # totals от mocked summary
    assert captured["usage_summary"].get("totals", {}).get("estimated_cost_usd_total") == 0.05


# ─── 4. _record_findings_only_usage: cost aggregation для OpenRouter ───


def test_record_findings_only_usage_openrouter_writes_real_cost(tmp_path, monkeypatch):
    """OpenRouter (model='openai/gpt-5.4') → cost_usd реальный, не notional."""
    from backend.app.pipeline.manager import PipelineManager
    from backend.app.models.audit import AuditJob, AuditStage, JobStatus
    from backend.app.services.common import usage_service

    captured_records = []
    monkeypatch.setattr(
        usage_service.usage_tracker, "record_usage",
        lambda r: captured_records.append(r),
    )

    pm = PipelineManager()
    job = AuditJob(
        job_id="j1", project_id="M31A", version_id="v2",
        stage=AuditStage.BLOCK_ANALYSIS, status=JobStatus.RUNNING,
    )
    summary = {
        "model": "openai/gpt-5.4",
        "blocks_ok": 19,
        "wall_clock_s": 30.0,
        "totals": {
            "input_tokens": 40517,
            "output_tokens": 17118,
            "estimated_cost_usd_total": 0.3227,
        },
    }
    pm._record_findings_only_usage(job, summary)

    assert len(captured_records) == 1
    rec = captured_records[0]
    # OpenRouter — реальный платёж: cost_usd > 0, notional == 0
    assert rec.cost_usd == 0.3227
    assert rec.cost_usd_notional == 0.0
    assert rec.input_tokens == 40517
    assert rec.output_tokens == 17118
    # job aggregator тоже обновился
    assert job.cost_usd == 0.3227
    assert job.cli_calls == 19


def test_record_findings_only_usage_claude_cli_uses_notional(tmp_path, monkeypatch):
    """Claude CLI (model='claude-opus-4-7') → cost_usd=0 (subscription),
    notional=cost (для аналитики)."""
    from backend.app.pipeline.manager import PipelineManager
    from backend.app.models.audit import AuditJob, AuditStage, JobStatus
    from backend.app.services.common import usage_service

    captured_records = []
    monkeypatch.setattr(
        usage_service.usage_tracker, "record_usage",
        lambda r: captured_records.append(r),
    )

    pm = PipelineManager()
    job = AuditJob(
        job_id="j2", project_id="M31A", version_id="v1",
        stage=AuditStage.BLOCK_ANALYSIS, status=JobStatus.RUNNING,
    )
    summary = {
        "model": "claude-opus-4-7",
        "blocks_ok": 5,
        "wall_clock_s": 15.0,
        "totals": {
            "input_tokens": 5000,
            "output_tokens": 1000,
            "estimated_cost_usd_total": 0.075,
        },
    }
    pm._record_findings_only_usage(job, summary)

    rec = captured_records[0]
    assert rec.cost_usd == 0.0  # subscription
    assert rec.cost_usd_notional == 0.075
    assert job.cost_usd == 0.0  # подписка не списывается с job


def test_record_findings_only_usage_empty_summary_noop(monkeypatch):
    """Пустой summary (cancelled до первого блока) → no record."""
    from backend.app.pipeline.manager import PipelineManager
    from backend.app.models.audit import AuditJob, AuditStage, JobStatus
    from backend.app.services.common import usage_service

    captured_records = []
    monkeypatch.setattr(
        usage_service.usage_tracker, "record_usage",
        lambda r: captured_records.append(r),
    )

    pm = PipelineManager()
    job = AuditJob(
        job_id="j3", project_id="M31A", version_id="v2",
        stage=AuditStage.BLOCK_ANALYSIS, status=JobStatus.RUNNING,
    )
    pm._record_findings_only_usage(job, {"model": "openai/gpt-5.4", "totals": {}})
    assert captured_records == []


# ─── 4. Параллельность блоков в codex/ensemble режимах ────────────────────


async def _parallelism_for_ensemble(tmp_path, monkeypatch) -> int:
    """Прогнать Stage 02 на ensemble-модели и вернуть переданный parallelism."""
    import importlib

    # Гасим load_dotenv: config вызывает его при импорте, и на боевой машине из
    # .env приезжает реальное значение AUDIT_STAGE02_CODEX_PARALLELISM. Без
    # заглушки тест проверял бы .env сервера, а не поведение кода.
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **kw: None)

    import backend.app.core.config as cfg
    importlib.reload(cfg)
    import backend.app.pipeline.stages.block_analysis.runner as runner_mod
    importlib.reload(runner_mod)

    monkeypatch.setattr(runner_mod, "get_stage_model", lambda key: "ensemble/gpt-codex")
    monkeypatch.delenv("AUDIT_STAGE02_MAX_PARALLEL_BATCHES", raising=False)
    monkeypatch.delenv("AUDIT_STAGE02_MAX_BLOCKS", raising=False)

    project_dir = _make_stage02_project(tmp_path)
    capture = {}
    _patch_run_findings_only(monkeypatch, capture)
    ctx, _captured = _make_ctx(project_dir)
    result = await runner_mod.run_block_analysis_findings_only(ctx)
    assert result.success
    return capture["call_kwargs"].get("parallelism")


@pytest.mark.asyncio
async def test_ensemble_parallelism_defaults_to_one(tmp_path, monkeypatch):
    """Без env ensemble идёт по одному блоку — прежнее поведение не меняется."""
    monkeypatch.delenv("AUDIT_STAGE02_CODEX_PARALLELISM", raising=False)
    assert await _parallelism_for_ensemble(tmp_path, monkeypatch) == 1


@pytest.mark.asyncio
async def test_ensemble_parallelism_env_override(tmp_path, monkeypatch):
    """AUDIT_STAGE02_CODEX_PARALLELISM=3 → три блока одновременно."""
    monkeypatch.setenv("AUDIT_STAGE02_CODEX_PARALLELISM", "3")
    assert await _parallelism_for_ensemble(tmp_path, monkeypatch) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", ["garbage", "0", "-2", ""])
async def test_ensemble_parallelism_invalid_env_falls_back_to_one(
    tmp_path, monkeypatch, raw,
):
    """Невалидное значение не должно ломать production — откат на 1."""
    monkeypatch.setenv("AUDIT_STAGE02_CODEX_PARALLELISM", raw)
    assert await _parallelism_for_ensemble(tmp_path, monkeypatch) == 1
