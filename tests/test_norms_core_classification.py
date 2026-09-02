"""
test_norms_core_classification.py
---------------------------------
Классификация статусов норм на уровне `norms/_core.py`.

Разделение уровней. Адаптер (`norms/external_provider.py`) отвечает за резолв
по `status_index.json` — это tests/test_norms_status_index_fallback.py. Здесь
проверяется вторая половина: как `_core` переводит ответ адаптера в запись
`check` конвейера — verified_via, сводный статус, edition_status,
needs_revision, вёдра missing/unsupported и отбор цитат в paragraphs_to_verify.
Раньше эта проверка жила внутри тестов адаптера; уровню адаптера она не
принадлежит.

Классов ровно ТРИ (контракт status_index-only):
    authoritative — норма есть в индексе (vault или override_only);
    missing       — семейство поддержано, записи в индексе нет → ручная очередь;
    unsupported   — семейство не распознано → ревизия поддержки семейств.

Четвёртого класса `known_unverified` («знаем из norms_db.json, но vault'ом не
подтверждено») в этом контракте нет: `norms_db.json` перестал быть источником
истины, а seed индекса из него запрещён `norms/tools/README.md`. Его отсутствие
здесь проверяется явно — возвращение такого ведра означало бы возврат legacy
fallback.

Запуск:
    python -m pytest tests/test_norms_core_classification.py -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Primary lane §5: integration — пишет синтетический индекс и paragraph cache во
# временную ФС.
pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ---------------------------------------------------------------------------
# Синтетическое окружение
# ---------------------------------------------------------------------------
# Корпус норм (§3.3 quality/runtime contract v1) здесь не нужен: индекс той же
# схемы строится во временном каталоге.

_INDEX_ENTRIES = [
    {
        "code": "СП 256.1325800.2016",
        "aliases": ["СП 256.1325800.2016"],
        "type": "СП",
        "year": 2016,
        "title": "Электроустановки жилых и общественных зданий",
        "file": "СП 256_1325800_2016_document.md",
        "doc_status": "active",
        "edition_status": None,
        "source": "vault",
        "authoritative": True,
        "has_text": True,
    },
    {
        # override_only: authoritative, но текста документа нет → цитаты не
        # заказываем.
        "code": "СНиП 2.04.01-85",
        "aliases": ["СНиП 2.04.01-85"],
        "type": "СНиП",
        "doc_status": "replaced",
        "replacement_doc": "СП 30.13330.2020",
        "source": "override_only",
        "authoritative": True,
        "has_text": False,
    },
]


def _norm(code: str, finding_id: str, clause: str | None = None) -> dict:
    cited = f"{code}, п. {clause}" if clause else code
    return {
        "cited_as": [cited],
        "affected_findings": [finding_id],
        "finding_norms": {finding_id: cited},
    }


#: Четыре нормы: authoritative с текстом, authoritative без текста,
#: поддержанное семейство вне индекса, нераспознанное семейство.
def _norms_data() -> dict:
    return {
        "norms": {
            "СП 256.1325800.2016": _norm("СП 256.1325800.2016", "F-1", "7.4.2"),
            "СНиП 2.04.01-85": _norm("СНиП 2.04.01-85", "F-2"),
            "СП 50.13330.2024": _norm("СП 50.13330.2024", "F-3"),
            "ничего нет": _norm("ничего нет", "F-4"),
        }
    }


@pytest.fixture
def core(monkeypatch, tmp_path):
    """`norms._core` с изолированными индексом, paragraph cache и norms_db."""
    from norms import _core
    from norms import external_provider as ep

    index_path = tmp_path / "status_index.json"
    index_path.write_text(
        json.dumps({"meta": {"source": "vault"}, "norms": _INDEX_ENTRIES},
                   ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(ep, "NORMS_STATUS_INDEX_PATH", index_path)
    ep._reset_cache()

    # Paragraph cache — пустой временный: иначе состав paragraphs_to_verify
    # зависел бы от машинного norms/norms_paragraphs.json.
    monkeypatch.setattr(_core, "NORMS_PARAGRAPHS_PATH", tmp_path / "paragraphs.json")

    # norms_db.json ДОЛЖЕН быть безразличен классификации. Кладём в него норму,
    # которой нет в индексе: если она когда-нибудь станет authoritative или
    # заведёт себе отдельное ведро — это возврат legacy fallback.
    db_path = tmp_path / "norms_db.json"
    db_path.write_text(
        json.dumps({"meta": {}, "norms": {"СП 50.13330.2024": {
            "doc_number": "СП 50.13330.2024",
            "title": "Тепловая защита зданий",
            "status": "active",
        }}}, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(_core, "NORMS_DB_PATH", db_path)

    yield _core
    ep._reset_cache()


def _by_norm(result: dict) -> dict[str, dict]:
    return {c["norm_as_cited"].split(",")[0]: c for c in result["checks"]}


# ---------------------------------------------------------------------------
# 1. Три ведра классификации
# ---------------------------------------------------------------------------

def test_counters_split_authoritative_missing_unsupported(core):
    result = core.generate_deterministic_checks(_norms_data(), project_id="ЭОМ/тест")
    meta = result["meta"]
    assert meta["total_checked"] == 4
    assert meta["authoritative"] == 2
    assert meta["missing"] == 1
    assert meta["unsupported"] == 1
    assert meta["project_id"] == "ЭОМ/тест"
    assert meta["source"] == "norms_main_status_index"


def test_verified_via_per_norm(core):
    checks = _by_norm(core.generate_deterministic_checks(_norms_data()))
    assert checks["СП 256.1325800.2016"]["verified_via"] == "norms_authoritative"
    assert checks["СНиП 2.04.01-85"]["verified_via"] == "norms_authoritative"
    assert checks["СП 50.13330.2024"]["verified_via"] == "norms_missing"
    assert checks["ничего нет"]["verified_via"] == "norms_unsupported"


def test_status_and_revision_flags(core):
    checks = _by_norm(core.generate_deterministic_checks(_norms_data()))
    active = checks["СП 256.1325800.2016"]
    assert (active["status"], active["needs_revision"]) == ("active", False)
    assert active["authoritative"] is True
    assert active["has_text"] is True
    assert active["norms_title"] == "Электроустановки жилых и общественных зданий"

    replaced = checks["СНиП 2.04.01-85"]
    assert (replaced["status"], replaced["needs_revision"]) == ("replaced", True)
    assert replaced["replacement_doc"] == "СП 30.13330.2020"
    assert replaced["has_text"] is False

    missing = checks["СП 50.13330.2024"]
    assert (missing["status"], missing["needs_revision"]) == ("not_found", False)
    assert missing["authoritative"] is False
    assert missing["edition_status"] == "unknown"

    unsupported = checks["ничего нет"]
    assert unsupported["status"] == "unknown"
    assert unsupported["authoritative"] is False


def test_missing_bucket_carries_family_and_action(core):
    result = core.generate_deterministic_checks(_norms_data())
    assert [m["norm"] for m in result["missing_norms"]] == ["СП 50.13330.2024"]
    item = result["missing_norms"][0]
    assert item["detected_family"] == "СП"
    assert item["supported_family"] is True
    assert item["resolution_reason"] == "not_in_index"
    assert item["action"] == "add_document_to_vault"
    assert item["affected_findings"] == ["F-3"]


def test_unsupported_bucket_carries_action(core):
    result = core.generate_deterministic_checks(_norms_data())
    assert [m["norm"] for m in result["unsupported_norms"]] == ["ничего нет"]
    item = result["unsupported_norms"][0]
    assert item["detected_family"] is None
    assert item["supported_family"] is False
    assert item["resolution_reason"] == "unsupported_family"
    assert item["action"] == "review_family_support"


def test_norms_db_does_not_create_a_fourth_bucket(core):
    """Норма из norms_db.json, которой нет в индексе, остаётся missing.

    Ведра `known_unverified` в контракте status_index-only не существует:
    `norms_db.json` не источник истины, и его содержимое не влияет ни на
    классификацию, ни на authoritative.
    """
    result = core.generate_deterministic_checks(_norms_data())
    assert "known_unverified_norms" not in result
    assert "known_unverified" not in result["meta"]
    assert not any(c["verified_via"] == "norms_known_unverified"
                   for c in result["checks"])
    db_norm = _by_norm(result)["СП 50.13330.2024"]
    assert db_norm["verified_via"] == "norms_missing"
    assert db_norm["authoritative"] is False


# ---------------------------------------------------------------------------
# 2. Отбор цитат в paragraphs_to_verify
# ---------------------------------------------------------------------------

def test_paragraphs_requested_only_for_authoritative_with_text(core):
    """Цитату заказываем, только если норма authoritative И текст есть."""
    result = core.generate_deterministic_checks(_norms_data())
    assert [p["finding_id"] for p in result["paragraphs_to_verify"]] == ["F-1"]
    item = result["paragraphs_to_verify"][0]
    assert item["matched_code"] == "СП 256.1325800.2016"
    assert item["has_text"] is True
    assert item["paragraph_key"] == "СП 256.1325800.2016, п. 7.4.2"
    assert result["meta"]["paragraphs_trusted_skipped"] == 0
    assert result["meta"]["paragraphs_legacy_ignored"] == 0


def _write_paragraph_cache(core_mod, entry: dict) -> None:
    core_mod.NORMS_PARAGRAPHS_PATH.write_text(
        json.dumps({"meta": {}, "paragraphs": {
            "СП 256.1325800.2016, п. 7.4.2": entry}}, ensure_ascii=False),
        encoding="utf-8",
    )


def test_trusted_paragraph_cache_skips_llm(core):
    _write_paragraph_cache(core, {"verified_via": "native_python", "quote": "…"})
    result = core.generate_deterministic_checks(_norms_data())
    assert result["paragraphs_to_verify"] == []
    assert result["meta"]["paragraphs_trusted_skipped"] == 1
    assert result["meta"]["paragraphs_legacy_ignored"] == 0


def test_legacy_paragraph_cache_is_reverified(core):
    """Легаси-кеш из websearch не доверенный — цитата перепроверяется."""
    _write_paragraph_cache(
        core, {"verified_via": "websearch", "source": "websearch+webfetch"})
    result = core.generate_deterministic_checks(_norms_data())
    assert [p["finding_id"] for p in result["paragraphs_to_verify"]] == ["F-1"]
    assert result["meta"]["paragraphs_trusted_skipped"] == 0
    assert result["meta"]["paragraphs_legacy_ignored"] == 1


# ---------------------------------------------------------------------------
# 3. Таблицы перевода ответа адаптера в поля check
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("resolved,expected", [
    ({"found": True, "status": "active"}, "active"),
    ({"found": True, "status": "outdated_edition"}, "outdated_edition"),
    ({"found": True, "status": "replaced"}, "replaced"),
    ({"found": True, "status": "cancelled"}, "cancelled"),
    ({"found": True, "status": "unknown"}, "unknown"),
    ({"found": False, "resolution_reason": "not_in_index"}, "not_found"),
    ({"found": False, "resolution_reason": "unsupported_family"}, "unknown"),
    ({"found": False, "resolution_reason": "not_found"}, "unknown"),
])
def test_status_from_resolved(core, resolved, expected):
    assert core._status_from_resolved(resolved) == expected


@pytest.mark.parametrize("resolved,expected", [
    ({"found": True}, "norms_authoritative"),
    ({"found": False, "resolution_reason": "not_in_index"}, "norms_missing"),
    ({"found": False, "resolution_reason": "unsupported_family"}, "norms_unsupported"),
    ({"found": False, "resolution_reason": "not_found"}, "norms_missing"),
])
def test_verified_via_from_resolved(core, resolved, expected):
    assert core._verified_via_from_resolved(resolved) == expected


@pytest.mark.parametrize("status,edition_status,needs_revision", [
    ("active", "active", False),
    ("outdated_edition", "outdated_edition", True),
    ("replaced", "replaced", True),
    ("cancelled", "cancelled", True),
    ("unknown", "unknown", False),
])
def test_edition_status_and_needs_revision(core, status, edition_status,
                                           needs_revision):
    """edition_status описывает редакцию; для not_found она «unknown»,
    а не «not_found» — иначе путается валидатор norm_checks."""
    check = core._build_check_from_resolved(
        norm_key="СП 256.1325800.2016",
        cited_as="СП 256.1325800.2016",
        affected=["F-1"],
        resolved={"found": True, "status": status},
    )
    assert check["edition_status"] == edition_status
    assert check["needs_revision"] is needs_revision


def test_missing_check_explains_manual_queue(core):
    check = core._build_check_from_resolved(
        norm_key="СП 50.13330.2024",
        cited_as="СП 50.13330.2024",
        affected=["F-3"],
        resolved={"found": False, "resolution_reason": "not_in_index",
                  "detected_family": "СП", "supported_family": True},
    )
    assert check["verified_via"] == "norms_missing"
    assert "missing_norms_queue" in check["details"]
    assert check["doc_number"] == "СП 50.13330.2024"


def test_optimization_ids_stay_in_their_own_field(core):
    """OPT-ID не подмешиваются в affected_findings — их читают как F-ID."""
    check = core._build_check_from_resolved(
        norm_key="СП 256.1325800.2016",
        cited_as="СП 256.1325800.2016",
        affected=["F-1"],
        resolved={"found": True, "status": "active"},
        affected_optimizations=["OPT-1"],
    )
    assert check["affected_findings"] == ["F-1"]
    assert check["affected_optimizations"] == ["OPT-1"]
