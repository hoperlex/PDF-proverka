"""Реестр ADR и заголовки самих ADR — один факт в двух местах.

REV-27: реестр объявлял ADR-0006 и ADR-0018 `accepted`, а документы продолжали
говорить `proposed` и «не утверждено». Расхождение прожило целый коммит, потому
что его ничто не проверяло: приёмку правили в одном файле, а читают её из
другого.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Primary lane §5: unit — читает файлы репозитория, без процессов и сети.
pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "docs/architecture/ADR_INDEX.md"

_ROW = re.compile(r"^\| \[(ADR-\d{4})\]\(([^)]+)\) \| (\w+) \|", re.M)
_STATUS = re.compile(r"^\*\*Статус:\*\*\s*(\w+)", re.M)


def _index_rows() -> list[tuple[str, str, str]]:
    return _ROW.findall(INDEX.read_text(encoding="utf-8"))


def test_index_and_adr_directory_cover_each_other() -> None:
    """Ни одного ADR мимо реестра и ни одной строки реестра без документа.

    Магическое «не меньше N» здесь бесполезно: оно не заметит ни забытый в
    реестре новый ADR, ни строку, ссылающуюся в пустоту.
    """
    rows = _index_rows()
    assert rows, "таблица статусов не разобралась — изменился формат"
    listed = {rel.split("/")[-1] for _, rel, _ in rows}
    on_disk = {f.name for f in (ROOT / "docs/architecture/adr").glob("ADR-*.md")}
    assert not on_disk - listed, f"ADR есть на диске, но нет в реестре: {sorted(on_disk - listed)}"
    assert not listed - on_disk, f"реестр ссылается на отсутствующие файлы: {sorted(listed - on_disk)}"


@pytest.mark.parametrize("adr_id, rel, index_status", _index_rows())
def test_document_status_matches_index(adr_id: str, rel: str, index_status: str) -> None:
    """Статус в документе обязан совпадать со статусом в реестре."""
    doc = (INDEX.parent / rel).resolve()
    assert doc.is_file(), f"{adr_id}: реестр ссылается на несуществующий {rel}"
    found = _STATUS.search(doc.read_text(encoding="utf-8"))
    assert found, f"{adr_id}: в документе нет строки «**Статус:**»"
    assert found.group(1) == index_status, (
        f"{adr_id}: реестр говорит {index_status!r}, документ — {found.group(1)!r}"
    )


@pytest.mark.parametrize("adr_id, rel, index_status", _index_rows())
def test_accepted_adr_names_who_approved_it(adr_id: str, rel: str, index_status: str) -> None:
    """`accepted` без записи «кто утвердил» — это не приёмка, а правка поля."""
    if index_status != "accepted":
        return
    text = (INDEX.parent / rel).resolve().read_text(encoding="utf-8")
    approved = re.search(r"^\*\*Утверждено:\*\*\s*(.+?)<br>", text, re.M)
    assert approved, f"{adr_id}: нет строки «**Утверждено:**»"
    assert "не утверждено" not in approved.group(1), (
        f"{adr_id}: статус accepted, но утверждение отсутствует — {approved.group(1)!r}"
    )
