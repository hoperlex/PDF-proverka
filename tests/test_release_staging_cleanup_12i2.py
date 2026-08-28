"""12I.2 — уборка временного дерева сборки релиза не зависит от исхода сборки.

Дефект, который эти тесты закрывают, не гипотетический: неудачные сборки
оставляли в `/tmp` (tmpfs 32 ГБ) запечатанные деревья по ~1 ГБ, `rm -rf` их не
брал, и переполненная tmpfs останавливала на машине всё, чему нужен временный
файл. Поэтому проверяется не «функция вызывается», а пять исходов подряд и
отсутствие накопления.
"""
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.release_staging import (  # noqa: E402
    STAGING_PREFIX,
    cleanup_staging,
    make_writable,
    seal_tree,
    staging_workspace,
)

# --- Признак «прогон идёт в CI» -------------------------------------------
#
# Решение владельца по C-4 (docs/architecture/ci_environment_matrix.md): набор
# гоняется НЕПРИВИЛЕГИРОВАННЫМ пользователем на раннере. Под root режимы 0o555
# не действуют, `rm -rf` сносит запечатанное дерево, и доказательство теста
# исчезает вместе с окружением. Тест, не способный доказать своё утверждение,
# обязан сказать об этом, а не быть зелёным или красным по случайности:
# локально под root — skip с причиной, в CI под root — ошибка, потому что
# контракт раннера нарушен.
#
# Признак тот же, что в tests/test_norms_index_unification.py (там же полное
# обоснование выбора): `AUDIT_CI_STRICT` — явный override в соглашении
# репозитория (префикс AUDIT_*, булев разбор как у `_env_bool` в
# backend/app/core/config.py), при его отсутствии — стандартный `CI` /
# `GITHUB_ACTIONS`, который CI-системы выставляют сами (workflow править не
# требуется).
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


def _require_unprivileged_user() -> None:
    """Доказательство держится на правах доступа — под root его нет."""
    euid = getattr(os, "geteuid", lambda: -1)()
    if euid != 0:
        return
    detail = (
        "прогон идёт под root (euid=0): режимы 0o555 на суперпользователя не "
        "действуют, наивный `rm -rf` сносит запечатанное дерево, и тест "
        "ничего не доказывает"
    )
    marker = _ci_marker()
    if marker is not None:
        pytest.fail(
            f"{detail}. Признак CI: {marker}={os.environ.get(marker)!r}. "
            f"По решению владельца (C-4) набор обязан выполняться "
            f"непривилегированным пользователем — запуск раннера под root "
            f"нарушает контракт окружения, а не проверяемое поведение"
        )
    pytest.skip(
        f"{detail}. Локально это допустимо; в CI (AUDIT_CI_STRICT=1 либо "
        f"CI=true) тот же случай ЛОМАЕТ прогон — раннер обязан быть "
        f"непривилегированным"
    )


def _build_tree(root: Path) -> Path:
    """Дерево, похожее на релиз: вложенность, исполняемый файл, симлинк."""
    app = root / "app" / "backend" / "services"
    app.mkdir(parents=True)
    (app / "module.py").write_text("x = 1\n", encoding="utf-8")
    binaries = root / "venv" / "bin"
    binaries.mkdir(parents=True)
    launcher = binaries / "python"
    launcher.write_text("#!/bin/sh\n", encoding="utf-8")
    launcher.chmod(0o755)
    (binaries / "python3").symlink_to(launcher)
    (root / "release-manifest.json").write_text("{}", encoding="utf-8")
    return root


def _tree_bytes(root: Path) -> int:
    return sum(p.stat().st_size for p in root.rglob("*") if p.is_file() and not p.is_symlink())


def test_successful_build_removes_staging(tmp_path):
    with staging_workspace(parent=tmp_path) as staging:
        _build_tree(staging)
        assert staging.exists()
        captured = staging
    assert not captured.exists()


def test_failure_before_sealing_removes_staging(tmp_path):
    captured = None
    with pytest.raises(RuntimeError):
        with staging_workspace(parent=tmp_path) as staging:
            captured = staging
            _build_tree(staging)
            raise RuntimeError("сборка отказала до запечатывания")
    assert captured is not None and not captured.exists()


def test_failure_after_sealing_relaxes_modes_and_removes_staging(tmp_path):
    """Главный сценарий: именно он и оставлял неудаляемый гигабайт."""
    captured = None
    with pytest.raises(RuntimeError):
        with staging_workspace(parent=tmp_path) as staging:
            captured = staging
            _build_tree(staging)
            seal_tree(staging)
            # Предусловие теста: дерево действительно запечатано, а не «как бы».
            assert stat.S_IMODE((staging / "app").stat().st_mode) == 0o555
            raise RuntimeError("проверка релиза не прошла ПОСЛЕ запечатывания")
    assert captured is not None and not captured.exists()


def test_sealed_tree_is_not_removable_without_relaxing_modes(tmp_path):
    """Доказательство причины: без снятия режимов снос действительно не идёт."""
    _require_unprivileged_user()
    import shutil

    staging = tmp_path / f"{STAGING_PREFIX}manual"
    staging.mkdir()
    _build_tree(staging)
    seal_tree(staging)
    shutil.rmtree(staging, ignore_errors=True)
    assert staging.exists(), "запечатанное дерево обязано пережить наивный rm -rf"
    cleanup_staging(staging)
    assert not staging.exists()


def test_exception_inside_cleanup_path_still_leaves_nothing(tmp_path):
    """Исключение произвольного типа не должно отменять уборку."""
    captured = None
    with pytest.raises(KeyboardInterrupt):
        with staging_workspace(parent=tmp_path) as staging:
            captured = staging
            _build_tree(staging)
            seal_tree(staging)
            raise KeyboardInterrupt
    assert captured is not None and not captured.exists()


def test_repeated_failed_builds_do_not_accumulate_bytes(tmp_path):
    """Пять отказов подряд не оставляют ни байта: это и была утечка в tmpfs."""
    for attempt in range(5):
        with pytest.raises(RuntimeError):
            with staging_workspace(parent=tmp_path) as staging:
                _build_tree(staging)
                seal_tree(staging)
                raise RuntimeError(f"отказ {attempt}")
    leftovers = [p for p in tmp_path.iterdir() if p.name.startswith(STAGING_PREFIX)]
    assert leftovers == []
    assert _tree_bytes(tmp_path) == 0


def test_cleanup_refuses_foreign_directory(tmp_path):
    """Уборка не трогает чужие каталоги — даже если её позвали ошибочно."""
    foreign = tmp_path / "production-release"
    foreign.mkdir()
    (foreign / "release-manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        cleanup_staging(foreign)
    assert (foreign / "release-manifest.json").is_file()


def test_make_writable_keeps_symlinks_and_exec_bit(tmp_path):
    staging = tmp_path / f"{STAGING_PREFIX}modes"
    staging.mkdir()
    _build_tree(staging)
    seal_tree(staging)
    make_writable(staging)
    launcher = staging / "venv" / "bin" / "python"
    alias = staging / "venv" / "bin" / "python3"
    assert alias.is_symlink(), "симлинк обязан остаться симлинком"
    assert stat.S_IMODE(launcher.stat().st_mode) & 0o100, "бит исполнения не снимаем"
    assert stat.S_IMODE(launcher.stat().st_mode) & 0o200, "запись обязана появиться"
    assert stat.S_IMODE((staging / "app").stat().st_mode) & 0o300 == 0o300


def test_cleanup_of_missing_directory_is_noop(tmp_path):
    cleanup_staging(tmp_path / f"{STAGING_PREFIX}never-created")
