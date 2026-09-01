"""reserc.md #34 — единый источник индекса норм.

Было: external_provider (статусы) дефолтил на НЕсуществующий backend/.../tools/
status_index.json → пустой индекс; _native_verify (цитаты пунктов) хардкодил
внешний /home/coder/projects/Norms/tools. Стало: оба берут in-repo norms/tools
(authoritative), env-override сохранён, при расхождении путей — warning.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest

from backend.app.pipeline.stages.norms import _native_verify as nv
from backend.app.pipeline.stages.norms import external_provider as ep

# Primary lane §5: unit — только память: ни ФС, ни потоков, ни процессов, ни сокетов.
pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parent.parent
_NORMS_VAULT = _REPO_ROOT / "norms" / "vault"

# --- Признак «прогон идёт в CI» -------------------------------------------
#
# Решение владельца по C-2 (docs/architecture/ci_environment_matrix.md):
# нормативный корпус ПОДВОЗИТСЯ артефактом в CI, а не объявляется optional.
# Отсюда несимметричная семантика: локально отсутствие корпуса — skip с
# причиной, в CI — падение. Иначе provision однажды сломается, тесты тихо
# пропустятся, и «зелёный» CI будет означать «нормативный контур не
# проверялся».
#
# Выбор признака. Собственного флага «мы в CI» в репозитории нет (grep по
# AUDIT_CI*/CI_* пуст), а `.github/workflows/ci.yml` вне ведения этой задачи —
# дописать туда свою переменную нельзя. Поэтому:
#   1) `AUDIT_CI_STRICT` — явный override в существующем соглашении репозитория
#      (префикс AUDIT_*, булев разбор один в один как `_env_bool` в
#      backend/app/core/config.py: {1,true,yes,on}). Им же CI-профиль
#      включается локально для проверки, и им же (значение "0"/"false")
#      сознательно ослабляется job, которому корпус не подвозят;
#   2) при отсутствии override — стандартный `CI` (и `GITHUB_ACTIONS`), который
#      GitHub Actions, GitLab CI, CircleCI и Travis выставляют сами. Это даёт
#      требуемое «ломать прогон в CI» без правки workflow.
_TRUTHY_ENV = {"1", "true", "yes", "on"}


def _ci_marker() -> str | None:
    """Имя переменной, по которой прогон опознан как CI (иначе None)."""
    override = (os.environ.get("AUDIT_CI_STRICT") or "").strip()
    if override:
        return "AUDIT_CI_STRICT" if override.lower() in _TRUTHY_ENV else None
    for name in ("CI", "GITHUB_ACTIONS"):
        if (os.environ.get(name) or "").strip().lower() in _TRUTHY_ENV:
            return name
    return None


def _require_norms_corpus() -> None:
    """Корпус норм обязателен в CI и необязателен локально.

    Не хватает `norms/vault/` (в .gitignore) и производного от него
    `norms/tools/status_index.json` — их подвозит артефакт CI.
    """
    missing = [
        str(path.relative_to(_REPO_ROOT))
        for path in (_NORMS_VAULT, ep._DEFAULT_STATUS_INDEX)
        if not path.exists()
    ]
    if not missing:
        return
    detail = (
        f"нормативный корпус не предоставлен: нет {', '.join(missing)} "
        f"(vault лежит вне git, status_index.json собирается из него "
        f"norms/tools/build_status_index.py)"
    )
    marker = _ci_marker()
    if marker is not None:
        pytest.fail(
            f"{detail}. Признак CI: {marker}={os.environ.get(marker)!r}. "
            f"По решению владельца (C-2) корпус подвозится в CI артефактом, "
            f"поэтому его отсутствие — сломанный provision, а не повод "
            f"пропустить нормативный контур"
        )
    pytest.skip(
        f"{detail}. Локально это допустимо; в CI "
        f"(AUDIT_CI_STRICT=1 либо CI=true) тот же случай ЛОМАЕТ прогон — "
        f"корпус обязан подвозиться артефактом"
    )


def test_status_and_paragraph_indexes_share_norms_tools_root():
    tools = nv._default_norms_tools_path()
    assert tools.name == "tools" and tools.parent.name == "norms"
    # дефолтный status_index лежит в том же norms/tools
    assert ep._DEFAULT_STATUS_INDEX == tools / "status_index.json"


def test_inrepo_index_exists_and_has_consistent_total():
    # Размер индекса растёт вместе с vault и status_overrides; проверяем схему,
    # а не историческое число записей.
    _require_norms_corpus()
    assert ep._DEFAULT_STATUS_INDEX.exists(), "in-repo status_index.json отсутствует"
    import json
    payload = json.loads(ep._DEFAULT_STATUS_INDEX.read_text(encoding="utf-8"))
    assert payload.get("meta", {}).get("total") == len(payload.get("norms", []))
    assert payload["meta"]["total"] >= 565


def test_native_default_no_longer_hardcodes_external():
    # Прежний хардкод /home/coder/projects/Norms/tools больше не дефолт.
    assert nv._default_norms_tools_path() != Path("/home/coder/projects/Norms/tools")


def test_divergence_warning_fires(monkeypatch, caplog):
    monkeypatch.setattr(nv, "NORMS_TOOLS_PATH", Path("/some/other/place/tools"))
    with caplog.at_level(logging.WARNING):
        nv._warn_if_index_paths_diverge()
    assert any("#34" in r.getMessage() for r in caplog.records)


def test_no_divergence_no_warning(monkeypatch, caplog):
    # Когда оба пути совпадают — предупреждения нет.
    same = Path(ep.NORMS_STATUS_INDEX_PATH).resolve().parent
    monkeypatch.setattr(nv, "NORMS_TOOLS_PATH", same)
    with caplog.at_level(logging.WARNING):
        nv._warn_if_index_paths_diverge()
    assert not any("#34" in r.getMessage() for r in caplog.records)

def test_sanpin_family_filename_and_core_extraction():
    import sys

    tools = Path(__file__).resolve().parent.parent / "norms" / "tools"
    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))
    from norms._core import extract_norms_from_text
    from norms_api import detect_family
    from parse_filename import parse_filename

    code = "СанПиН 2.1.3684-21"
    parsed = parse_filename(
        "СанПиН 2.1.3684-21_ Санитарные требования_document.md"
    )

    assert extract_norms_from_text(f"{code}, п. 4") == [code]
    assert detect_family(code) == "СанПиН"
    assert parsed["code"] == code
    assert parsed["year"] == 2021
    assert parsed["parse_confidence"] == "high"


def test_sanpin_official_copy_has_unambiguous_paragraphs():
    _require_norms_corpus()
    import sys

    tools = Path(__file__).resolve().parent.parent / "norms" / "tools"
    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))
    import norms_api

    norms_api.load_status_index(force_reload=True)
    status = norms_api.get_norm_status("СанПиН 2.1.3684-21")
    invalid_26 = norms_api.get_paragraph("СанПиН 2.1.3684-21", "2.6")
    invalid_27 = norms_api.get_paragraph("СанПиН 2.1.3684-21", "2.7")
    paragraph_4 = norms_api.get_paragraph("СанПиН 2.1.3684-21", "4")

    assert status["authoritative"] is True
    assert status["year"] == 2021
    assert invalid_26["resolution_reason"] == "paragraph_not_found"
    assert invalid_27["resolution_reason"] == "paragraph_not_found"
    assert paragraph_4["found"] is True
    assert "Расстояние от контейнерных" in paragraph_4["text"]

