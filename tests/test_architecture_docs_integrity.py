"""Целостность архитектурного комплекта: JSON и локальные Markdown-ссылки."""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest


# Primary lane §5: unit — только чтение файлов репозитория, без процессов и сети.
pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parent.parent
ARCHITECTURE_DIR = ROOT / "docs" / "architecture"

_INLINE_LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
_EXTERNAL_SCHEMES = {"data", "http", "https", "mailto"}


def _lines_outside_fenced_blocks(text: str):
    """Кодовые примеры не являются ссылками архитектурного комплекта."""

    fence: str | None = None
    for line_number, line in enumerate(text.splitlines(), 1):
        stripped = line.lstrip()
        marker = stripped[:3]
        if marker in {"```", "~~~"}:
            fence = None if fence == marker else marker if fence is None else fence
            continue
        if fence is None:
            yield line_number, line


def _link_target(raw: str) -> str:
    """Отделить destination от необязательного Markdown title."""

    value = raw.strip()
    if value.startswith("<") and ">" in value:
        return value[1 : value.index(">")]
    return value.split(maxsplit=1)[0] if value else ""


def test_architecture_json_is_valid() -> None:
    errors: list[str] = []
    files = sorted(ARCHITECTURE_DIR.rglob("*.json"))
    assert files, "в архитектурном комплекте не найдено ни одного JSON"

    for path in files:
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            errors.append(f"{path.relative_to(ROOT)}: {exc}")

    assert not errors, "Невалидные архитектурные JSON:\n" + "\n".join(errors)


def test_architecture_local_markdown_links_resolve() -> None:
    errors: list[str] = []
    checked = 0

    for document in sorted(ARCHITECTURE_DIR.rglob("*.md")):
        text = document.read_text(encoding="utf-8")
        for line_number, line in _lines_outside_fenced_blocks(text):
            for match in _INLINE_LINK.finditer(line):
                raw = _link_target(match.group(1))
                if not raw or raw.startswith("#"):
                    continue

                parsed = urlsplit(raw)
                if parsed.scheme.lower() in _EXTERNAL_SCHEMES:
                    continue

                relative = unquote(parsed.path)
                if not relative:
                    continue

                checked += 1
                resolved = (document.parent / relative).resolve()
                try:
                    resolved.relative_to(ROOT.resolve())
                except ValueError:
                    errors.append(
                        f"{document.relative_to(ROOT)}:{line_number}: "
                        f"ссылка выходит за корень репозитория: {raw}"
                    )
                    continue

                if not resolved.exists():
                    errors.append(
                        f"{document.relative_to(ROOT)}:{line_number}: "
                        f"нет цели {raw}"
                    )

    assert checked, "в архитектурном комплекте не найдено локальных ссылок"
    assert not errors, "Битые локальные ссылки:\n" + "\n".join(errors)
