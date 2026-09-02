"""
test_norms_status_index_fallback.py
-----------------------------------
Regression-тесты адаптера `norms/external_provider.py`.

КОНТРАКТ — `status_index-only`. Единственный источник истины по статусам норм
это `norms/tools/status_index.json`, который `norms/tools/build_status_index.py`
детерминированно собирает ровно из двух входов: `vault/*.md` и
`tools/status_overrides.yaml`. Провайдер его только ЧИТАЕТ. `norms_db.json`,
`missing_norms_vault.json` и сам vault источниками статуса НЕ являются
(`norms/tools/README.md` прямо запрещает seed из `norms_db.json`), WebSearch и
WebFetch запрещены концептуально: нормы нет в индексе → `found=False`,
`resolution_reason=not_in_index` и очередь на ручное добавление.

Почему файл переписан. Прежняя редакция проверяла другой контракт, которого у
провайдера не было никогда: четыре класса `authoritative / known_unverified /
missing / unsupported` в поле `classification`, сборку индекса из
`norms_db.json` и `missing_norms_vault.json`, функцию `diagnostics()` и атрибуты
`NORMS_DB_PATH`, `NORMS_VAULT_PATH`, `MISSING_NORMS_VAULT_PATHS`. Ни одного из
них в модуле нет, поэтому все 33 узла падали на setup фикстуры с AttributeError
за доли секунды и не проверяли ничего. Тот контракт восстановлению не подлежит:
он и есть запрещённый legacy fallback на `norms_db.json`.

Классификационные проверки `norms/_core.py` (verified_via, счётчики, ведро
missing/unsupported) вынесены на свой уровень — tests/test_norms_core_classification.py.

Покрытие:
  0. три состояния индекса — absent / broken / ok — и отказ с названным
     дефектом вместо KeyError (D4, D5, раздел 8);
  1. индекса нет → безопасный пустой каркас, not_in_index / unsupported_family;
  2. authoritative-индекс: vault-запись, override_only, устаревшая редакция,
     умолчания для минимальной записи;
  3. норма вне индекса не подменяется соседней (регресс на substring-матч);
  4. aliases, приоритет собственного кода записи над чужим alias;
  5. нормализация форм записи;
  6. определение семейства для всех поддерживаемых префиксов;
  7. детерминизм: независимость от порядка записей, стабильная схема payload,
     семантика кеша и force_reload.

Запуск:
    python -m pytest tests/test_norms_status_index_fallback.py -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Primary lane §5: integration — пишет синтетический индекс во временную ФС, а
# `unit` по §5 — «только память».
pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ---------------------------------------------------------------------------
# Синтетический индекс
# ---------------------------------------------------------------------------
# Корпус норм (`norms/vault/**` и производный status_index.json) в репозитории
# не лежит и подвозится артефактом только в enforce CI (§3.3 quality/runtime
# contract v1). Эти тесты его НЕ требуют: они строят индекс той же схемы во
# временном каталоге, поэтому исход не зависит от наличия корпуса.

def _entry(code: str, **override) -> dict:
    """Запись индекса в схеме norms/tools/README.md с разумными умолчаниями."""
    base = {
        "code": code,
        "aliases": [code],
        "type": code.split()[0],
        "year": None,
        "title": f"Синтетическая запись {code}",
        "file": None,
        "doc_status": "active",
        "edition_status": None,
        "replacement_doc": None,
        "current_version": None,
        "details": None,
        "source_url": None,
        "last_verified": None,
        "parse_confidence": "high",
        "source": "vault",
        "authoritative": True,
        "has_text": True,
    }
    base.update(override)
    return base


#: Полный синтетический корпус: vault, override_only, устаревшая редакция,
#: запись с явным authoritative=false и «голая» запись из одного поля code.
def _authoritative_entries() -> list[dict]:
    return [
        _entry(
            "СП 256.1325800.2016",
            aliases=["СП 256.1325800.2016", "СП 256_1325800_2016", "СП 31-110-2003"],
            year=2016,
            title="Электроустановки жилых и общественных зданий",
            file="СП 256_1325800_2016_document.md",
        ),
        _entry(
            "СП 30.13330.2016",
            year=2016,
            edition_status="outdated",
            current_version="СП 30.13330.2020",
            details="В базе хранится актуальная редакция 2020",
        ),
        _entry(
            "СНиП 2.04.01-85",
            doc_status="replaced",
            replacement_doc="СП 30.13330.2020",
            source="override_only",
            has_text=False,
            aliases=["СНиП 2.04.01-85", "СНиП 2.04.01-85*"],
        ),
        _entry(
            "ГОСТ 9388-60",
            doc_status="cancelled",
            source="override_only",
            has_text=False,
        ),
        _entry(
            "ГОСТ 21.205-93",
            doc_status="unknown",
            source="override_only",
            has_text=False,
        ),
        # Запись, которую сборщик пометил НЕ authoritative. Провайдер обязан
        # передать флаг как есть, а не повысить его по своему усмотрению.
        _entry("ВСН 59-88", authoritative=False, has_text=False),
        # Минимальная запись: всё, кроме code, отсутствует — проверяем умолчания.
        {"code": "МДС 12-29.2006"},
    ]


def _write_index(provider, path: Path, entries: list[dict]) -> Path:
    path.write_text(
        json.dumps({"meta": {"source": "vault", "total": len(entries)},
                    "norms": entries}, ensure_ascii=False),
        encoding="utf-8",
    )
    provider.NORMS_STATUS_INDEX_PATH = path
    provider._reset_cache()
    return path


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------

@pytest.fixture
def provider(monkeypatch, tmp_path):
    """Провайдер, отвязанный от машинного индекса.

    По умолчанию путь указывает на НЕсуществующий файл — это «индекса нет».
    Кеш модуля глобальный, поэтому сбрасывается и до, и после теста.
    """
    from norms import external_provider as ep

    monkeypatch.setattr(
        ep, "NORMS_STATUS_INDEX_PATH", tmp_path / "absent_status_index.json")
    ep._reset_cache()
    yield ep
    ep._reset_cache()


@pytest.fixture
def indexed(provider, tmp_path):
    """Провайдер с непустым authoritative-индексом."""
    _write_index(provider, tmp_path / "status_index.json", _authoritative_entries())
    return provider


# ---------------------------------------------------------------------------
# 1. Индекса нет — деградация без падений
# ---------------------------------------------------------------------------

def test_missing_index_returns_empty_skeleton(provider):
    """Файла индекса нет → пустой валидный каркас, а не исключение."""
    data = provider.load_status_index()
    assert data == {"meta": {}, "norms": []}


def test_missing_index_supported_family_goes_to_manual_queue(provider):
    """Поддерживаемое семейство без индекса → not_in_index + ручная очередь."""
    r = provider.resolve_norm_status("СП 256.1325800.2016")
    assert r["found"] is False
    assert r["matched_code"] is None
    assert r["resolution_reason"] == "not_in_index"
    assert r["detected_family"] == "СП"
    assert r["supported_family"] is True
    assert r["needs_manual_addition"] is True
    assert r["authoritative"] is False
    assert r["status"] == "unknown"
    assert r["source"] == "not_found"


def test_missing_index_unsupported_family(provider):
    """Семейство не распознано → unsupported_family, в очередь НЕ ставим."""
    r = provider.resolve_norm_status("какой-то произвольный текст")
    assert r["resolution_reason"] == "unsupported_family"
    assert r["detected_family"] is None
    assert r["supported_family"] is False
    assert r["needs_manual_addition"] is False
    assert r["found"] is False


@pytest.mark.parametrize("blank", ["", "   ", "\n\t ", "**  **", None])
def test_blank_query_is_not_found(provider, blank):
    """Пустой запрос — это not_found, а не «неподдерживаемое семейство»."""
    r = provider.resolve_norm_status(blank)
    assert r["found"] is False
    assert r["resolution_reason"] == "not_found"
    assert r["detected_family"] is None
    assert r["supported_family"] is False
    assert r["normalized_query"] == ""


# ---------------------------------------------------------------------------
# 2. Authoritative-индекс
# ---------------------------------------------------------------------------

def test_vault_entry_is_authoritative(indexed):
    r = indexed.resolve_norm_status("СП 256.1325800.2016")
    assert r["found"] is True
    assert r["matched_code"] == "СП 256.1325800.2016"
    assert r["resolution_reason"] == "exact"
    assert r["authoritative"] is True
    assert r["status"] == "active"
    assert r["doc_status"] == "active"
    assert r["source"] == "vault"
    assert r["has_text"] is True
    assert r["needs_manual_addition"] is False
    assert r["title"] == "Электроустановки жилых и общественных зданий"
    assert r["file"] == "СП 256_1325800_2016_document.md"
    assert r["year"] == 2016


def test_override_only_entry_is_manual_override(indexed):
    """Запись из status_overrides.yaml: authoritative, но без текста."""
    r = indexed.resolve_norm_status("СНиП 2.04.01-85")
    assert r["found"] is True
    assert r["resolution_reason"] == "manual_override"
    assert r["source"] == "override_only"
    assert r["authoritative"] is True
    assert r["status"] == "replaced"
    assert r["replacement_doc"] == "СП 30.13330.2020"
    assert r["has_text"] is False


def test_cancelled_entry_reports_cancelled(indexed):
    r = indexed.resolve_norm_status("ГОСТ 9388-60")
    assert r["found"] is True
    assert r["status"] == "cancelled"
    assert r["doc_status"] == "cancelled"
    assert r["resolution_reason"] == "manual_override"


def test_unknown_doc_status_is_found_but_unknown(indexed):
    """`unknown` в индексе — это ЗНАНИЕ о незнании, а не отсутствие записи."""
    r = indexed.resolve_norm_status("ГОСТ 21.205-93")
    assert r["found"] is True
    assert r["doc_status"] == "unknown"
    assert r["status"] == "unknown"
    assert r["needs_manual_addition"] is False


def test_outdated_edition_maps_to_outdated_edition(indexed):
    """active + edition_status=outdated → сводный статус outdated_edition."""
    r = indexed.resolve_norm_status("СП 30.13330.2016")
    assert r["status"] == "outdated_edition"
    assert r["doc_status"] == "active"
    assert r["edition_status"] == "outdated"
    assert r["current_version"] == "СП 30.13330.2020"


def test_minimal_entry_uses_documented_defaults(indexed):
    """Запись из одного `code`: doc_status unknown, source vault, has_text False."""
    r = indexed.resolve_norm_status("МДС 12-29.2006")
    assert r["found"] is True
    assert r["doc_status"] == "unknown"
    assert r["status"] == "unknown"
    assert r["source"] == "vault"
    assert r["has_text"] is False
    assert r["authoritative"] is True
    assert r["detected_family"] == "МДС"


def test_provider_does_not_promote_entry_to_authoritative(indexed):
    """authoritative приходит ИЗ индекса; провайдер его не назначает сам."""
    r = indexed.resolve_norm_status("ВСН 59-88")
    assert r["found"] is True
    assert r["authoritative"] is False


# ---------------------------------------------------------------------------
# 3. Нормы нет в индексе — и её нельзя подменить соседней
# ---------------------------------------------------------------------------

def test_norm_absent_from_populated_index_is_not_in_index(indexed):
    """Индекс непустой, но нормы в нём нет → not_in_index, не «похожая»."""
    r = indexed.resolve_norm_status("СП 50.13330.2024")
    assert r["found"] is False
    assert r["matched_code"] is None
    assert r["resolution_reason"] == "not_in_index"
    assert r["supported_family"] is True
    assert r["needs_manual_addition"] is True


@pytest.mark.parametrize("query", ["СП 25", "СП 2", "СП 25.13330.2020"])
def test_prefix_of_another_code_is_not_a_match(indexed, query):
    """Регресс. «СП 25» — это СП 25.13330 (основания на вечномёрзлых грунтах),
    а не «СП 256.1325800.2016»: обрыв внутри числового токена матчем не считаем.
    """
    r = indexed.resolve_norm_status(query)
    assert r["found"] is False
    assert r["matched_code"] is None
    assert r["resolution_reason"] == "not_in_index"


@pytest.mark.parametrize("reverse", [False, True])
def test_ambiguous_prefix_is_refused(provider, tmp_path, reverse):
    """«СП 30» при двух редакциях в индексе неразрешим → not_in_index.

    Выбор «первой по файлу» записи означал бы, что редакция нормы зависит от
    порядка строк в индексе.
    """
    entries = [_entry("СП 30.13330.2016"), _entry("СП 30.13330.2020")]
    if reverse:
        entries.reverse()
    _write_index(provider, tmp_path / "ambiguous.json", entries)
    r = provider.resolve_norm_status("СП 30")
    assert r["found"] is False
    assert r["resolution_reason"] == "not_in_index"


def test_code_with_trailing_clause_still_resolves(indexed):
    """Код + хвост («, п. 7.4.2») резолвится: код целиком присутствует в запросе."""
    r = indexed.resolve_norm_status("СП 256.1325800.2016, п. 7.4.2")
    assert r["found"] is True
    assert r["matched_code"] == "СП 256.1325800.2016"
    assert r["resolution_reason"] == "alias"


def test_unsupported_family_with_populated_index(indexed):
    """Непустой индекс не превращает мусорный запрос в норму."""
    r = indexed.resolve_norm_status("см. проектную документацию раздела ЭОМ")
    assert r["found"] is False
    assert r["resolution_reason"] == "unsupported_family"
    assert r["supported_family"] is False


# ---------------------------------------------------------------------------
# 4. Aliases
# ---------------------------------------------------------------------------

def test_alias_resolves_to_canonical_code(indexed):
    r = indexed.resolve_norm_status("СП 31-110-2003")
    assert r["found"] is True
    assert r["matched_code"] == "СП 256.1325800.2016"
    assert r["resolution_reason"] == "alias"
    assert r["authoritative"] is True


def test_alias_written_with_underscores_matches_canonical(indexed):
    """`_` и `.` в коде эквивалентны — это тот же canonical, а не alias-ветка."""
    r = indexed.resolve_norm_status("СП 256_1325800_2016")
    assert r["matched_code"] == "СП 256.1325800.2016"
    assert r["resolution_reason"] == "exact"


@pytest.mark.parametrize("reverse", [False, True])
def test_own_code_wins_over_foreign_alias(provider, tmp_path, reverse):
    """Регресс. Alias одной записи не должен перекрывать СОБСТВЕННЫЙ код другой.

    «СНиП 2.04.01-85» — и alias актуального СП 30.13330.2020, и отдельная
    запись со статусом replaced. Ответом обязана быть собственная запись:
    иначе заменённый документ отвечает active, и это зависит от порядка строк
    в индексе.
    """
    entries = [
        _entry("СП 30.13330.2020", aliases=["СП 30.13330.2020", "СНиП 2.04.01-85"]),
        _entry(
            "СНиП 2.04.01-85",
            doc_status="replaced",
            replacement_doc="СП 30.13330.2020",
            source="override_only",
            has_text=False,
        ),
    ]
    if reverse:
        entries.reverse()
    _write_index(provider, tmp_path / "alias_clash.json", entries)
    r = provider.resolve_norm_status("СНиП 2.04.01-85")
    assert r["matched_code"] == "СНиП 2.04.01-85"
    assert r["status"] == "replaced"
    assert r["resolution_reason"] == "manual_override"


# ---------------------------------------------------------------------------
# 5. Нормализация форм записи
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("variant", [
    "СП 256.1325800.2016",
    " СП 256.1325800.2016 ",
    "сп 256.1325800.2016",
    "СП  256.1325800.2016",                 # двойные пробелы
    "СП\t256.1325800.2016",                 # табуляция
    "**СП 256.1325800.2016**",              # markdown
    "*СП 256.1325800.2016*",
    "СП 256.1325800.2016.",                 # хвостовая пунктуация
    "СП 256.1325800.2016 (ред. 29.01.2024)",
    "СП 256.1325800.2016 ред. 29.01.2024",
    "СП 256.1325800.2016 (изм. 1-6)",
    "СП 256.1325800.2016 (действует)",
    "СП 256.1325800.2016 (утв. приказом)",
    "СП 256.1325800.2016 с изменениями",
    "СП 256.1325800.2016 с изменением № 1",
])
def test_normalization_variants_resolve_to_same_norm(indexed, variant):
    r = indexed.resolve_norm_status(variant)
    assert r["found"] is True, f"не разобрана форма записи: {variant!r}"
    assert r["matched_code"] == "СП 256.1325800.2016"
    assert r["query"] == variant
    assert r["status"] == "active"


def test_query_is_returned_verbatim(indexed):
    """`query` — вход как есть, `normalized_query` — результат разбора."""
    r = indexed.resolve_norm_status("  **СП 256.1325800.2016** (ред. 29.01.2024) ")
    assert r["query"] == "  **СП 256.1325800.2016** (ред. 29.01.2024) "
    assert r["normalized_query"] == "СП 256.1325800.2016"


# ---------------------------------------------------------------------------
# 6. Определение семейства
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected_family", [
    ("СП 1.13130.2020", "СП"),
    ("СанПиН 2.1.3684-21", "СанПиН"),
    ("ГОСТ 12.1.004-91", "ГОСТ"),
    ("ГОСТ Р 50571.5.54-2013", "ГОСТ Р"),
    ("СНиП 2.04.01-85", "СНиП"),
    ("ВСН 59-88", "ВСН"),
    ("МДС 12-29.2006", "МДС"),
    ("РД 34.21.122-87", "РД"),
    ("ПУЭ-7", "ПУЭ"),
    ("СО 153.34.21.122-2003", "СО"),
    ("Постановление Правительства РФ от 28.05.2007 N 87", "ПП РФ"),
    ("Федеральный закон 123-ФЗ", "ФЗ"),
    ("123-ФЗ", "ФЗ"),
])
def test_family_detection(provider, raw, expected_family):
    """Семейство определяется по строке запроса даже при пустом индексе."""
    r = provider.resolve_norm_status(raw)
    assert r["detected_family"] == expected_family
    assert r["supported_family"] is True
    assert r["resolution_reason"] == "not_in_index"


def test_family_table_matches_norms_toolchain(provider):
    """Список семейств — одна политика на две реализации.

    Провайдер объявляет «те же семейства, что Norms-main маркирует supported»,
    а фактическая таблица разъехалась с `norms/tools/norms_api.py`: там был
    СанПиН, здесь его не было, и любой СанПиН вне индекса уезжал в
    unsupported_norms вместо очереди на добавление документа.
    """
    tools = _ROOT / "norms" / "tools"
    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))
    import norms_api  # noqa: PLC0415 — тулчейн лежит вне пакета norms

    assert ([name for name, _ in provider._FAMILY_PATTERNS]
            == [name for name, _ in norms_api._FAMILY_PATTERNS])


@pytest.mark.parametrize("raw", [
    "просто текст",
    "Требования пожарной безопасности",
    "п. 7.4.2",
    "12.1.004-91",
])
def test_family_not_detected(provider, raw):
    r = provider.resolve_norm_status(raw)
    assert r["detected_family"] is None
    assert r["resolution_reason"] == "unsupported_family"


# ---------------------------------------------------------------------------
# 7. Детерминизм, схема payload и кеш
# ---------------------------------------------------------------------------

#: Схема ответа — общая для found и not-found: потребитель (`norms/_core.py`)
#: читает одни и те же ключи, не проверяя ветку.
_PAYLOAD_KEYS = {
    "query", "normalized_query", "found", "matched_code", "status",
    "doc_status", "edition_status", "authoritative", "resolution_reason",
    "detected_family", "supported_family", "needs_manual_addition", "has_text",
    "replacement_doc", "current_version", "title", "file", "type", "year",
    "details", "source_url", "last_verified", "parse_confidence", "source",
    # Диагностика состояния индекса (D4): «нормы нет в индексе» обязано
    # отличаться от «индекс нечитаем» на стороне потребителя.
    "index_state", "index_defect",
}


@pytest.mark.parametrize("query", [
    "СП 256.1325800.2016",      # найдена
    "СП 50.13330.2024",         # not_in_index
    "просто текст",             # unsupported_family
    "",                         # not_found
])
def test_payload_schema_is_stable(indexed, query):
    assert set(indexed.resolve_norm_status(query)) == _PAYLOAD_KEYS


@pytest.mark.parametrize("query", [
    "СП 256.1325800.2016", "СП 31-110-2003", "СП 50.13330.2024", "просто текст",
])
def test_repeated_calls_are_identical(indexed, query):
    assert indexed.resolve_norm_status(query) == indexed.resolve_norm_status(query)


def test_result_does_not_depend_on_entry_order(provider, tmp_path):
    """Тот же корпус в обратном порядке даёт тот же ответ."""
    forward = _authoritative_entries()
    _write_index(provider, tmp_path / "forward.json", forward)
    queries = ["СП 256.1325800.2016", "СНиП 2.04.01-85", "СП 31-110-2003",
               "ГОСТ 9388-60", "СП 50.13330.2024"]
    first = {q: provider.resolve_norm_status(q) for q in queries}

    _write_index(provider, tmp_path / "reverse.json", list(reversed(forward)))
    second = {q: provider.resolve_norm_status(q) for q in queries}
    assert first == second


def test_index_is_cached_until_force_reload(provider, tmp_path):
    """Индекс читается один раз; перечитать — только явным force_reload."""
    path = _write_index(
        provider, tmp_path / "cached.json", [_entry("СП 256.1325800.2016")])
    assert provider.resolve_norm_status("СП 256.1325800.2016")["found"] is True

    path.write_text(
        json.dumps({"meta": {}, "norms": [_entry("ГОСТ 12.1.004-91")]},
                   ensure_ascii=False),
        encoding="utf-8",
    )
    # Без force_reload виден прежний снимок.
    assert provider.resolve_norm_status("СП 256.1325800.2016")["found"] is True
    assert provider.resolve_norm_status("ГОСТ 12.1.004-91")["found"] is False

    provider.load_status_index(force_reload=True)
    assert provider.resolve_norm_status("СП 256.1325800.2016")["found"] is False
    assert provider.resolve_norm_status("ГОСТ 12.1.004-91")["found"] is True


def test_provider_never_writes_to_index(provider, tmp_path):
    """Адаптер только читает: содержимое и mtime индекса не меняются."""
    path = _write_index(
        provider, tmp_path / "readonly.json", _authoritative_entries())
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    for q in ["СП 256.1325800.2016", "СП 50.13330.2024", "мусор", ""]:
        provider.resolve_norm_status(q)
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


def test_public_api_is_status_index_only(provider):
    """Контракт модуля: никаких norms_db / vault / missing-vault входов.

    Прежняя редакция тестов патчила у провайдера NORMS_DB_PATH,
    NORMS_VAULT_PATH и MISSING_NORMS_VAULT_PATHS. Их появление означало бы
    возврат legacy fallback на norms_db.json, запрещённого norms/tools/README.md.
    """
    assert provider.__all__ == [
        "NORMS_STATUS_INDEX_PATH", "StatusIndexError", "load_status_index",
        "resolve_norm_status", "status_index_state"]
    for forbidden in ("NORMS_DB_PATH", "NORMS_VAULT_PATH",
                      "MISSING_NORMS_VAULT_PATHS"):
        assert not hasattr(provider, forbidden), (
            f"{forbidden} у провайдера — это legacy fallback на norms_db.json")


# ---------------------------------------------------------------------------
# 8. Три состояния индекса: absent / broken / ok  (D4, D5)
# ---------------------------------------------------------------------------
# D4. Битый индекс маскировался под обычное «не найдено»: и отсутствие файла,
# и битый JSON давали resolution_reason="not_found", supported_family=False,
# needs_manual_addition=False, а в norms/_core.py — verified_via="norms_missing"
# для ВСЕГО корпуса. Ни одно поле не сообщало, что индекс сломан, хотя лечится
# это иначе, чем отсутствие корпуса.
#
# D5. Запись без "code" роняла load_status_index() голым KeyError: 'code', а
# resolve_norm_status() ловил только OSError/JSONDecodeError — падал конвейер.
# Политика: отказать внятно (StatusIndexError с названным defect) на уровне
# читателя, не глотая кривую запись, и НЕ бросать на уровне resolve.


def _write_raw(provider, path: Path, text: str) -> Path:
    """Положить в индекс произвольный текст (в т.ч. заведомо непригодный)."""
    path.write_text(text, encoding="utf-8")
    provider.NORMS_STATUS_INDEX_PATH = path
    provider._reset_cache()
    return path


#: Непригодные индексы: (текст файла, ожидаемый код дефекта).
_BROKEN_INDEXES = [
    ("{не json", "invalid_json"),
    ("", "invalid_json"),
    ("[]", "not_an_object"),
    ('"строка"', "not_an_object"),
    ('{"meta": {}}', "norms_key_absent"),
    ('{"meta": {}, "norms": {}}', "norms_not_a_list"),
    ('{"meta": {}, "norms": ["СП 256.1325800.2016"]}', "entry_not_an_object"),
    ('{"meta": {}, "norms": [{"title": "x"}]}', "entry_missing_code"),
    ('{"meta": {}, "norms": [{"code": ""}]}', "entry_blank_code"),
    ('{"meta": {}, "norms": [{"code": null}]}', "entry_blank_code"),
    ('{"meta": {}, "norms": [{"code": 256}]}', "entry_blank_code"),
    ('{"meta": {}, "norms": [{"code": "СП 1", "aliases": "СП 1"}]}',
     "entry_aliases_not_a_list"),
]


@pytest.mark.parametrize("raw,defect", _BROKEN_INDEXES)
def test_broken_index_is_refused_with_named_defect(provider, tmp_path, raw, defect):
    """D5: непригодный индекс → StatusIndexError с НАЗВАННЫМ дефектом.

    Не KeyError, не JSONDecodeError, не тихий пропуск кривой записи.
    """
    _write_raw(provider, tmp_path / "broken.json", raw)
    with pytest.raises(provider.StatusIndexError) as exc:
        provider.load_status_index()
    assert exc.value.defect == defect
    assert str(tmp_path / "broken.json") == exc.value.path
    # Сообщение обязано называть дефект — иначе «внятный отказ» не внятный.
    assert defect in str(exc.value)


def test_entry_without_code_no_longer_raises_keyerror(provider, tmp_path):
    """D5-репро: {"meta":{},"norms":[{"title":"x"}]} давал KeyError: 'code'."""
    _write_raw(provider, tmp_path / "no_code.json",
               '{"meta":{},"norms":[{"title":"x"}]}')
    with pytest.raises(provider.StatusIndexError) as exc:
        provider.load_status_index()
    assert not isinstance(exc.value, KeyError)
    assert exc.value.defect == "entry_missing_code"
    assert exc.value.location == "norms[0]"


def test_broken_entry_is_not_silently_skipped(provider, tmp_path):
    """Политика D5: кривую запись НЕ глотаем.

    Иначе индекс выглядел бы здоровым и молча не содержал бы норму: её
    резолв дал бы not_in_index, и дефект сборщика замаскировался бы под
    «нормы нет в базе» — та же маскировка, что D4, только точечная.
    """
    _write_raw(
        provider, tmp_path / "half_broken.json",
        '{"meta":{},"norms":[{"code":"СП 256.1325800.2016","doc_status":"active"},'
        '{"title":"без кода"}]}',
    )
    r = provider.resolve_norm_status("СП 256.1325800.2016")
    # Здоровая соседняя запись НЕ выдаётся как ни в чём не бывало.
    assert r["found"] is False
    assert r["resolution_reason"] == "index_unreadable"
    assert r["index_defect"] == "entry_missing_code"


@pytest.mark.parametrize("raw,defect", _BROKEN_INDEXES)
def test_resolve_never_raises_on_broken_index(provider, tmp_path, raw, defect):
    """D5: контракт конвейера — resolve_norm_status не бросает НИКОГДА."""
    _write_raw(provider, tmp_path / "broken.json", raw)
    for query in ["СП 256.1325800.2016", "какой-то произвольный текст", "", None]:
        r = provider.resolve_norm_status(query)
        assert isinstance(r, dict)
        assert set(r) == _PAYLOAD_KEYS
        assert r["index_state"] == "broken"


@pytest.mark.parametrize("raw,defect", _BROKEN_INDEXES)
def test_broken_index_is_distinguishable_from_not_found(provider, tmp_path,
                                                        raw, defect):
    """D4-репро: битый индекс обязан отличаться от «нормы нет в индексе»."""
    _write_raw(provider, tmp_path / "broken.json", raw)
    r = provider.resolve_norm_status("СП 256.1325800.2016")
    assert r["found"] is False
    assert r["resolution_reason"] == "index_unreadable"
    assert r["index_state"] == "broken"
    assert r["index_defect"] == defect
    # Ручная очередь — неверное лечение: добавление документа в vault не
    # чинит битый артефакт.
    assert r["needs_manual_addition"] is False
    # Семейство определяется регуляркой и от индекса не зависит — сообщаем
    # его честно, чтобы было видно, что сам запрос корректен.
    assert r["detected_family"] == "СП"
    assert r["supported_family"] is True


def test_broken_index_does_not_claim_unsupported_family(provider, tmp_path):
    """При битом индексе вердикт unsupported_family недопустим.

    unsupported_family означает «в индексе НЕТ И семейство не распознано».
    Первую половину конъюнкции на битом индексе проверить нельзя.
    """
    _write_raw(provider, tmp_path / "broken.json", "{не json")
    r = provider.resolve_norm_status("какой-то произвольный текст")
    assert r["resolution_reason"] == "index_unreadable"
    assert r["index_state"] == "broken"
    assert r["detected_family"] is None
    assert r["supported_family"] is False
    assert r["needs_manual_addition"] is False


def test_blank_query_stays_not_found_even_on_broken_index(provider, tmp_path):
    """Вердикт о пустом запросе — про запрос, а не про индекс."""
    _write_raw(provider, tmp_path / "broken.json", "{не json")
    r = provider.resolve_norm_status("   ")
    assert r["resolution_reason"] == "not_found"
    # …но состояние индекса не скрывается и здесь.
    assert r["index_state"] == "broken"


# --- Три состояния через status_index_state() -------------------------------

def test_state_absent_when_file_missing(provider):
    """Файла нет — это «absent», а не поломка."""
    st = provider.status_index_state()
    assert st["state"] == "absent"
    assert st["defect"] is None
    assert st["norm_count"] == 0
    assert st["path"] == str(provider.NORMS_STATUS_INDEX_PATH)


def test_state_ok_for_populated_index(indexed):
    st = indexed.status_index_state()
    assert st["state"] == "ok"
    assert st["defect"] is None
    assert st["norm_count"] == len(_authoritative_entries())


def test_state_ok_for_valid_empty_index(provider, tmp_path):
    """ПУСТОЙ индекс валиден: это «ok» с нулём записей, а не «broken»."""
    _write_index(provider, tmp_path / "empty.json", [])
    st = provider.status_index_state()
    assert st["state"] == "ok"
    assert st["defect"] is None
    assert st["norm_count"] == 0
    # И резолв по нему — обычное «нормы нет в индексе».
    r = provider.resolve_norm_status("СП 256.1325800.2016")
    assert r["resolution_reason"] == "not_in_index"
    assert r["index_state"] == "ok"
    assert r["needs_manual_addition"] is True


@pytest.mark.parametrize("raw,defect", _BROKEN_INDEXES)
def test_state_broken_names_the_defect(provider, tmp_path, raw, defect):
    _write_raw(provider, tmp_path / "broken.json", raw)
    st = provider.status_index_state()
    assert st["state"] == "broken"
    assert st["defect"] == defect
    assert st["detail"]
    assert st["norm_count"] == 0


def test_three_states_are_pairwise_distinguishable(provider, tmp_path):
    """Итог D4: absent / broken / ok различимы машиной, а не по тексту.

    Раньше все три давали один и тот же ответ на одну и ту же норму.
    """
    seen = {}

    seen["absent"] = (provider.status_index_state()["state"],
                      provider.resolve_norm_status("СП 256.1325800.2016"))

    _write_raw(provider, tmp_path / "broken.json", "{не json")
    seen["broken"] = (provider.status_index_state()["state"],
                      provider.resolve_norm_status("СП 256.1325800.2016"))

    _write_index(provider, tmp_path / "ok.json", _authoritative_entries())
    seen["ok"] = (provider.status_index_state()["state"],
                  provider.resolve_norm_status("СП 256.1325800.2016"))

    assert [seen[k][0] for k in ("absent", "broken", "ok")] == [
        "absent", "broken", "ok"]
    marks = {k: (v[1]["index_state"], v[1]["resolution_reason"], v[1]["found"])
             for k, v in seen.items()}
    assert marks == {
        "absent": ("absent", "not_in_index", False),
        "broken": ("broken", "index_unreadable", False),
        "ok": ("ok", "exact", True),
    }
    assert len(set(marks.values())) == 3


# --- Кеш отказа и восстановление -------------------------------------------

def test_broken_index_failure_is_cached_and_stable(provider, tmp_path):
    """Отказ кешируется наравне с удачным чтением: ответ не «плавает».

    Иначе битый файл перечитывался бы на каждой норме корпуса.
    """
    path = _write_raw(provider, tmp_path / "broken.json", '{"meta":{},"norms":[{}]}')
    first = provider.resolve_norm_status("СП 256.1325800.2016")
    mtime = path.stat().st_mtime_ns
    second = provider.resolve_norm_status("СП 256.1325800.2016")
    assert first == second
    assert path.stat().st_mtime_ns == mtime
    with pytest.raises(provider.StatusIndexError):
        provider.load_status_index()


def test_force_reload_recovers_after_index_is_repaired(provider, tmp_path):
    """Починили артефакт → force_reload возвращает состояние в ok."""
    path = _write_raw(provider, tmp_path / "index.json", "{не json")
    assert provider.status_index_state()["state"] == "broken"

    path.write_text(
        json.dumps({"meta": {}, "norms": [_entry("СП 256.1325800.2016")]},
                   ensure_ascii=False),
        encoding="utf-8",
    )
    # Без force_reload виден прежний (сломанный) снимок — семантика кеша та же.
    assert provider.status_index_state()["state"] == "broken"

    assert provider.status_index_state(force_reload=True)["state"] == "ok"
    r = provider.resolve_norm_status("СП 256.1325800.2016")
    assert (r["found"], r["index_state"], r["index_defect"]) == (True, "ok", None)


def test_provider_never_writes_to_broken_index(provider, tmp_path):
    """Даже на непригодном индексе адаптер остаётся read-only."""
    path = _write_raw(provider, tmp_path / "broken.json", '{"meta":{},"norms":[{}]}')
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    for q in ["СП 256.1325800.2016", "мусор", ""]:
        provider.resolve_norm_status(q)
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


def test_healthy_index_reports_state_ok_in_every_payload(indexed):
    """index_state есть в ОБЕИХ ветках payload — found и not-found."""
    for query in ["СП 256.1325800.2016", "СП 50.13330.2024", "просто текст", ""]:
        r = indexed.resolve_norm_status(query)
        assert r["index_state"] == "ok"
        assert r["index_defect"] is None
