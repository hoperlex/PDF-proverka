"""reserc.md #34 — единый источник индекса норм.

Было: external_provider (статусы) дефолтил на НЕсуществующий backend/.../tools/
status_index.json → пустой индекс; _native_verify (цитаты пунктов) хардкодил
внешний /home/coder/projects/Norms/tools. Стало: оба берут in-repo norms/tools
(authoritative), env-override сохранён, при расхождении путей — warning.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import pytest

from backend.app.pipeline.stages.norms import _native_verify as nv
from backend.app.pipeline.stages.norms import external_provider as ep

# Primary lane §5: unit — только память: ни ФС, ни потоков, ни процессов, ни сокетов.
pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parent.parent
_NORMS_VAULT = _REPO_ROOT / "norms" / "vault"

# --- Признак «корпус обязан быть на месте» --------------------------------
#
# Решение владельца по C-2 (docs/architecture/ci_environment_matrix.md):
# нормативный корпус ПОДВОЗИТСЯ артефактом, а не объявляется optional. Отсюда
# несимметричная семантика: где корпус подвозят, его отсутствие — сломанный
# provision и падение; где не подвозят — skip с причиной. Иначе provision
# однажды сломается, тесты тихо пропустятся, и «зелёный» CI будет означать
# «нормативный контур не проверялся».
#
# ПОЧЕМУ ПРИЗНАК СМЕНЁН 2026-09-03. Прежняя редакция опознавала строгость по
# стандартной переменной `CI` (и `GITHUB_ACTIONS`), потому что «собственного
# флага в репозитории нет, а ci.yml вне ведения этой задачи». Оба основания
# перестали быть верными, и признак стал ЛОЖНЫМ: GitHub выставляет `CI=true`
# сам, а `.github/workflows/ci.yml` объявляет отсутствие ненастроенного
# источника допустимым для профиля `--ci` (`OPTIONAL_NORM_CORPUS_ABSENT`,
# exit 0). Два утверждения об одном факте расходились, и публикация ветки дала
# бы два падения полосы `unit` на пустом baseline — то есть новую блокирующую
# регрессию из ниоткуда. Измерено: профиль GitHub без корпуса — 2 failed,
# 5 passed.
#
# Теперь строгость следует ФАКТУ, а не окружению: корпус обязан быть там, где
# ИСТОЧНИК АРТЕФАКТА СКОНФИГУРИРОВАН. Это ровно то, что имелось в виду под
# «подвозится артефактом», и это знание уже есть в проекте — правило одно, и
# оно переиспользуется из `scripts/ci_provision_norms.source_config()`, а не
# пишется здесь второй раз. Как только владелец назовёт источник, тест
# становится строгим сам, без правки workflow и без ручных переменных.
#
# `AUDIT_CI_STRICT` сохранён как ЯВНЫЙ override в обе стороны: им включают
# строгость локально для проверки и им же сознательно ослабляют job, которому
# корпус не подвозят. Разбор булева значения — как в `_env_bool`
# (backend/app/core/config.py): {1,true,yes,on}.
_TRUTHY_ENV = {"1", "true", "yes", "on"}

_SCRIPTS_DIR = _REPO_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))


def _corpus_source_configured() -> bool:
    """Задан ли внешний источник корпуса. Правило одно на проект."""
    import ci_provision_norms as provision

    return bool(provision.source_config()["configured"])


def _strictness_reason() -> str | None:
    """Почему корпус обязателен в этом прогоне (иначе None)."""
    override = (os.environ.get("AUDIT_CI_STRICT") or "").strip()
    if override:
        if override.lower() in _TRUTHY_ENV:
            return f"AUDIT_CI_STRICT={override!r} (явный override)"
        return None
    if _corpus_source_configured():
        return "источник корпуса сконфигурирован (QR_NORM_ARTIFACT_*)"
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
    reason = _strictness_reason()
    if reason is not None:
        pytest.fail(
            f"{detail}. Основание строгости: {reason}. "
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


# --- Сторож против возврата ложного признака -------------------------------


def test_github_profile_without_configured_source_skips_not_fails(monkeypatch):
    """Профиль GitHub без сконфигурированного источника не делает прогон красным.

    Ради этого сторожа он и написан. Прежняя редакция опознавала строгость по
    переменной `CI`, которую GitHub Actions выставляет сам, — и публикация ветки
    без корпуса дала бы два падения полосы `unit` на пустом baseline. Это
    выглядело бы как регрессия, которой нет: `.github/workflows/ci.yml`
    объявляет ненастроенный источник допустимым для профиля `--ci`.

    Тест закрывает КЛАСС дефекта: любой возврат к признаку «мы в CI» вместо
    признака «источник задан» роняет его.
    """
    for name in ("CI", "GITHUB_ACTIONS", "GITLAB_CI", "TRAVIS", "CIRCLECI"):
        monkeypatch.setenv(name, "true")
    monkeypatch.delenv("AUDIT_CI_STRICT", raising=False)
    for name in ("QR_NORM_ARTIFACT_SOURCE_ID", "QR_NORM_ARTIFACT_URL",
                 "QR_NORM_ARTIFACT_VERSION", "QR_NORM_ARTIFACT_TOKEN",
                 "QR_NORM_ARTIFACT_AUTH_SCHEME"):
        monkeypatch.delenv(name, raising=False)

    assert _strictness_reason() is None, (
        "строгость снова выводится из окружения CI, а не из факта настройки "
        "источника — публикация ветки без корпуса даст ложную регрессию"
    )


def test_configured_source_makes_corpus_mandatory(monkeypatch):
    """Как только источник назван, отсутствие корпуса становится падением.

    Обратная половина: ослабление признака не должно превратиться в «корпус
    больше никогда не обязателен». Достаточно ОДНОЙ заданной переменной —
    неполная конфигурация опаснее её отсутствия и трактуется как «источник
    объявлен».
    """
    monkeypatch.delenv("AUDIT_CI_STRICT", raising=False)
    for name in ("CI", "GITHUB_ACTIONS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("QR_NORM_ARTIFACT_SOURCE_ID", "owner/norms-vault")

    reason = _strictness_reason()
    assert reason is not None and "источник корпуса сконфигурирован" in reason


def test_explicit_override_wins_in_both_directions(monkeypatch):
    """`AUDIT_CI_STRICT` перебивает факт в обе стороны — это его назначение."""
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("QR_NORM_ARTIFACT_SOURCE_ID", raising=False)

    monkeypatch.setenv("AUDIT_CI_STRICT", "1")
    assert "явный override" in (_strictness_reason() or "")

    monkeypatch.setenv("QR_NORM_ARTIFACT_SOURCE_ID", "owner/norms-vault")
    monkeypatch.setenv("AUDIT_CI_STRICT", "0")
    assert _strictness_reason() is None, (
        "явное ослабление обязано работать и при заданном источнике: иначе job, "
        "которому корпус не подвозят, нельзя настроить вовсе"
    )
