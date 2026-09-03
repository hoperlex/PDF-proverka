"""Static grep-smoke для UI переименования папки проекта.

Task — кнопка «N версий» убрана, рядом с версией показано имя проекта +
карандаш, по клику открывается rename-редактор, после успеха фронт обновляет
состояние (project_id) и навигирует на новый проект.

Source of truth — `frontend/` (webapp/static покрыт parity-тестом отдельно).
"""
from __future__ import annotations

from pathlib import Path

import pytest

# Primary lane §5: unit — только память: ни ФС, ни потоков, ни процессов, ни сокетов.
pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parent.parent
HTML = (_ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
JS = (_ROOT / "frontend" / "static" / "js" / "app.js").read_text(encoding="utf-8")


# ─── Test 1: кнопка «N версий» убрана ───────────────────────────────────────
def test_no_versions_count_button_near_selector():
    # старая кнопка-тоггл рядом с селектором версии удалена
    assert "versionsPanelOpen = !versionsPanelOpen" not in HTML
    assert "}} версии" not in HTML
    assert "project-version-switch__btn" not in HTML


# ─── Test 2: имя проекта + карандаш рядом с версией ─────────────────────────
def test_project_name_and_pencil_shown():
    assert "project-version-switch__name" in HTML
    assert "currentProject.name" in HTML
    assert "project-version-switch__pencil" in HTML
    assert "@click=\"startRename()\"" in HTML


def test_rename_editor_present():
    assert "v-model=\"renameValue\"" in HTML
    assert "@click=\"submitRename()\"" in HTML
    assert "@click=\"cancelRename()\"" in HTML
    assert "Сохранить" in HTML and "Отмена" in HTML


# ─── Test 9: фронт обновляет состояние после успешного rename ───────────────
def test_js_rename_functions_and_state_update():
    assert "async function apiPatch(" in JS
    assert "function startRename(" in JS
    assert "async function submitRename(" in JS
    # вызывает PATCH .../rename
    assert "/rename`" in JS
    # после смены project_id — controlled-навигация на новый проект
    assert "navigate('/project/' + newId)" in JS
    # refs/функции проброшены в setup return
    for token in ("renameEditing", "renameValue", "renameError",
                  "startRename", "submitRename", "cancelRename"):
        assert token in JS, token


# ─── версионная панель и модалка создания версии удалены (91f48104) ──────────
# Проверка переписана под действующее поведение. Коммит 91f48104 (2026-07-02)
# «feat(frontend): удалить кнопку «Версии» и её панель/модалку» намеренно снял
# кнопку «⚙ Версии» вместе с раскрываемой панелью «Версии проекта» и модалкой
# «Создать новую версию»; из app.js удалены versionsPanelOpen,
# showCreateVersionModal, newVersionComment и createNewVersion. Прежняя
# формулировка требовала обратного («панель НЕ удалена») и не могла стать
# зелёной, не отменив это решение. Проверка разведена на две стороны решения:
# удалённое обязано отсутствовать, уцелевшее — присутствовать.
def test_versions_panel_and_create_modal_removed():
    for token in ("versions-panel", "showCreateVersionModal",
                  "newVersionComment", "createNewVersion", "versionsPanelOpen"):
        assert token not in HTML, token
        assert token not in JS, token


def test_version_switching_survived_panel_removal():
    # то, ради чего панель существовала — доступ к версиям — осталось в
    # выпадающем списке «Версия:» в шапке проекта: 91f48104 прямо оставил
    # «переключение и переименование версий через выпадающий список»
    assert "project-version-switch__select" in HTML
    assert "Версия:" in HTML
    assert "selectVersion(" in HTML
    assert "in projectVersions" in HTML
    assert "function selectVersion(" in JS
    assert "projectVersions" in JS
