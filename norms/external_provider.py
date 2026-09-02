"""Adapter к нормативной базе.

Единственный источник истины по статусам норм — status_index.json в
`norms/tools/status_index.json` внутри этого же проекта. Этот модуль
только ЧИТАЕТ его, ничего не пишет.

WebSearch / WebFetch / интернет здесь запрещены концептуально: если нормы
нет в индексе, мы возвращаем found=False и направляем её в очередь на
ручное добавление (missing_norms_queue.json), а не пытаемся «угадать».

Публичный API:
    load_status_index(force_reload: bool = False) -> dict
    status_index_state(force_reload: bool = False) -> dict
    resolve_norm_status(raw_norm: str) -> dict
    StatusIndexError

Схема возврата resolve_norm_status описана в его докстринге.

─── Три состояния индекса (D4) ──────────────────────────────────────────
Раньше состояний было фактически два: «индекс дал ответ» и «индекс не дал
ответа». Файла нет, файл — битый JSON, файл не той схемы — всё сводилось к
одному и тому же `resolution_reason="not_found"`, а в `norms/_core.py` — к
одному и тому же `verified_via="norms_missing"`. Битый индекс объявлял
пропущенным ВЕСЬ корпус и выглядел ровно как отсутствие корпуса, хотя
лечится совершенно иначе (починить артефакт против «добавить документ в
vault»).

Теперь состояний ТРИ, и они машиночитаемы:

    "absent"  — файла индекса нет. Штатная ситуация: корпус подвозится
                артефактом только в enforce CI. Резолв честно отвечает
                not_in_index → очередь на ручное добавление.
    "broken"  — файл есть, но непригоден: не парсится, не та схема, кривая
                запись. Резолв отвечает resolution_reason="index_unreadable",
                needs_manual_addition=False: чинить надо индекс, а не vault.
    "ok"      — файл прочитан и прошёл проверку схемы. ПУСТОЙ индекс
                («norms»: []) — это тоже "ok": пустота валидна и отличима
                от поломки.

Способ различения выбран двойной, потому что у состояния два разных
потребителя:
  1. диагностические поля `index_state` и `index_defect` В КАЖДОМ ответе
     resolve_norm_status() — их читает конвейер (`norms/_core.py`), который
     вызывает резолв по норме и никакого второго вызова делать не станет;
     поле в ответе гарантирует, что различение доедет до `verified_via`;
  2. отдельная функция status_index_state() — для тех, кто спрашивает про
     ИНДЕКС, а не про норму (preflight конвейера, meta отчёта, CI-проверка
     артефакта). Ей не нужно выдумывать фиктивный запрос нормы, и она
     отдаёт подробности (defect, location, detail, norm_count), которым не
     место в payload'е каждой нормы.

─── Политика по кривой записи (D5) ──────────────────────────────────────
Запись без обязательного `code` роняла load_status_index() голым
`KeyError: 'code'`, а resolve_norm_status() ловил только OSError и
JSONDecodeError — падал весь конвейер.

Выбрана политика «ОТКАЗАТЬ ВНЯТНО, НЕ ГЛОТАТЬ»:
  * load_status_index() — низкоуровневый читатель — при непригодном индексе
    бросает StatusIndexError с НАЗВАННЫМ дефектом (`defect`) и местом
    (`location`, например "norms[3]"). Голого KeyError наружу больше нет;
  * resolve_norm_status() — контракт конвейера — не бросает НИКОГДА: ловит
    StatusIndexError и возвращает штатный payload с
    resolution_reason="index_unreadable" и index_defect=<код дефекта>.

Почему отказ, а не пропуск кривой записи. status_index.json — машинный
артефакт детерминированного сборщика (norms/tools/build_status_index.py) из
vault и overrides. Запись без `code` в нём — это дефект сборщика или
повреждение артефакта, а не «грязные входные данные». Тихо выбросив такую
запись, мы получим индекс, который выглядит здоровым и молча не содержит
норму: её резолв даст not_in_index, норма уедет в очередь на ручное
добавление, и дефект сборщика будет замаскирован под «нормы нет в базе» —
то есть ровно та же маскировка, что и D4, только точечная и потому ещё
менее заметная. Отказ же локализован: он называет defect и location,
конвейер от него не падает, а масштаб потери виден сразу — не одна норма,
а весь индекс, что для машинного артефакта честнее.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

# ─── Путь к индексу статусов ──────────────────────────────────────────────
# #34: authoritative — in-repo norms/tools/status_index.json (565 норм), тот же
# корень, что и тулчейн цитат пунктов (_native_verify.NORMS_TOOLS_PATH).
# Переопределяется env NORMS_STATUS_INDEX_PATH.
_DEFAULT_STATUS_INDEX = Path(__file__).resolve().parent / "tools" / "status_index.json"
NORMS_STATUS_INDEX_PATH = Path(
    os.environ.get("NORMS_STATUS_INDEX_PATH", str(_DEFAULT_STATUS_INDEX))
)


# ─── Состояния индекса и отказ с названным дефектом ───────────────────────
#: Индекс прочитан и прошёл проверку схемы (в т.ч. валидный ПУСТОЙ индекс).
INDEX_STATE_OK = "ok"
#: Файла индекса нет — штатная деградация, не дефект.
INDEX_STATE_ABSENT = "absent"
#: Файл есть, но непригоден: не парсится / не та схема / кривая запись.
INDEX_STATE_BROKEN = "broken"


class StatusIndexError(RuntimeError):
    """Индекс статусов присутствует, но непригоден к использованию.

    Отказ с НАЗВАННЫМ дефектом вместо голого KeyError/JSONDecodeError
    наружу и вместо тихого пропуска кривой записи (см. политику D5 в
    докстринге модуля).

    Атрибуты:
        defect   — машинный код дефекта, одно из _INDEX_DEFECTS;
        location — место в документе ("norms[3]", "norms[3].aliases") или
                   None, если дефект относится к файлу целиком;
        path     — путь к индексу, на котором дефект найден.
    """

    def __init__(self, defect: str, message: str, path,
                 location: str | None = None) -> None:
        self.defect = defect
        self.location = location
        self.path = str(path)
        where = f", {location}" if location else ""
        super().__init__(f"status_index [{defect}{where}] {self.path}: {message}")


#: Полный перечень кодов дефекта — контракт для потребителя index_defect.
_INDEX_DEFECTS = frozenset({
    "unreadable_file",          # файл есть, но не читается (права, ФС)
    "invalid_encoding",         # не UTF-8
    "invalid_json",             # не парсится как JSON
    "not_an_object",            # корень не объект
    "norms_key_absent",         # в корне нет ключа "norms"
    "norms_not_a_list",         # "norms" не список
    "entry_not_an_object",      # элемент "norms" не объект
    "entry_missing_code",       # у записи нет обязательного "code" (D5)
    "entry_blank_code",         # "code" не строка либо пустой
    "entry_aliases_not_a_list",  # "aliases" не список
})


def _validate_index_payload(data: Any, path) -> list[dict]:
    """Проверить схему индекса и вернуть список записей.

    Проверяется ровно тот минимум, на который опирается загрузка: корень —
    объект, "norms" — список объектов, у каждого непустой строковый "code",
    "aliases" (если есть) — список. Остальные поля читаются через .get() с
    умолчаниями, их отсутствие дефектом не является.
    """
    if not isinstance(data, dict):
        raise StatusIndexError(
            "not_an_object",
            f"корень индекса — {type(data).__name__}, ожидался объект",
            path)
    if "norms" not in data:
        raise StatusIndexError(
            "norms_key_absent", "в корне индекса нет ключа 'norms'", path)
    norms = data["norms"]
    if not isinstance(norms, list):
        raise StatusIndexError(
            "norms_not_a_list",
            f"'norms' — {type(norms).__name__}, ожидался список", path,
            location="norms")
    for i, entry in enumerate(norms):
        loc = f"norms[{i}]"
        if not isinstance(entry, dict):
            raise StatusIndexError(
                "entry_not_an_object",
                f"запись индекса — {type(entry).__name__}, ожидался объект",
                path, location=loc)
        if "code" not in entry:
            # D5: раньше здесь наружу летел KeyError: 'code'.
            raise StatusIndexError(
                "entry_missing_code",
                "у записи нет обязательного поля 'code'", path, location=loc)
        code = entry["code"]
        if not isinstance(code, str) or not code.strip():
            raise StatusIndexError(
                "entry_blank_code",
                f"'code' — {type(code).__name__} {code!r}, "
                "ожидалась непустая строка", path, location=loc)
        aliases = entry.get("aliases")
        if aliases is not None and not isinstance(aliases, list):
            raise StatusIndexError(
                "entry_aliases_not_a_list",
                f"'aliases' — {type(aliases).__name__}, ожидался список",
                path, location=f"{loc}.aliases")
    return norms


# ─── Определение семейства ────────────────────────────────────────────────
# Порядок важен: узкие шаблоны до широких.
_FAMILY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # Таблица обязана совпадать с norms/tools/norms_api.py::_FAMILY_PATTERNS —
    # это одна и та же политика «какие семейства мы умеем принимать». СанПиН
    # там был, здесь его не было, и любой СанПиН вне индекса уезжал в
    # unsupported_norms («ревизия поддержки семейств») вместо очереди на
    # добавление документа.
    ("СанПиН", re.compile(r"^\s*СанПиН\s+\d", re.IGNORECASE)),
    ("ГОСТ Р", re.compile(r"^\s*ГОСТ\s+Р\b", re.IGNORECASE)),
    ("ГОСТ", re.compile(r"^\s*ГОСТ\b", re.IGNORECASE)),
    ("СНиП", re.compile(r"^\s*СНиП\b", re.IGNORECASE)),
    ("СП", re.compile(r"^\s*СП\s*\d", re.IGNORECASE)),
    ("ВСН", re.compile(r"^\s*ВСН\b", re.IGNORECASE)),
    ("МДС", re.compile(r"^\s*МДС\b", re.IGNORECASE)),
    ("РД", re.compile(r"^\s*РД\b", re.IGNORECASE)),
    ("ПУЭ", re.compile(r"^\s*(?:ПУЭ|ПЭУ)\b", re.IGNORECASE)),
    ("ПП РФ", re.compile(
        r"^\s*(?:Постановление\s+Правительства|ПП\s*РФ)\b", re.IGNORECASE)),
    ("ФЗ", re.compile(
        r"^\s*(?:Федеральный\s+закон|ФЗ\s+\d|\d+-ФЗ)\b", re.IGNORECASE)),
    ("СО", re.compile(r"^\s*СО\s+\d", re.IGNORECASE)),
]

# Те же семейства, что Norms-main маркирует supported. Важно: supported
# ≠ доступно в индексе. supported означает: мы умеем направить такую норму
# в intake queue и в дальнейшем либо добавить, либо пометить override.
_SUPPORTED_FAMILIES = {name for name, _ in _FAMILY_PATTERNS}


def _detect_family(code: str) -> str | None:
    if not code:
        return None
    s = str(code).strip()
    for name, rx in _FAMILY_PATTERNS:
        if rx.match(s):
            return name
    return None


# ─── Нормализация строки запроса ──────────────────────────────────────────
def _normalize_query(raw: str) -> str:
    if raw is None:
        return ""
    s = str(raw).strip()
    # Схлопываем пробелы, убираем markdown
    s = s.replace("**", "").replace("*", "")
    s = re.sub(r"\s+", " ", s)
    # Убираем хвосты в скобках: (действует...), (ред. ...), (изм. ...),
    # (с изменениями...), (введ...), (утв...), (актуал...), (в ред...)
    s = re.sub(
        r"\s*\((?:действу|ред\.|изм\.|с изм|введ|утв|актуал|в ред)[^)]*\)",
        "", s, flags=re.IGNORECASE,
    )
    s = re.sub(r"\s+с\s+(?:[Ии]зменениями?|[Ии]зменением)\s*(?:№\s*[\d,\s\-–]+)?", "", s)
    s = re.sub(r"\s*ред\.\s*\d{2}\.\d{2}\.\d{4}", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = s.rstrip(".,;: ")
    return s


def _match_key(s: str) -> str:
    """Ключ для нечеткого матча: без пробелов, _/. унифицированы, lower."""
    if not s:
        return ""
    return re.sub(r"\s+", "", s).replace("_", ".").lower()


# Разделители токенов внутри кода нормы ПОСЛЕ _match_key: пробелы вырезаны,
# «_» приведён к «.», остаются «.», «-», «/», «:».
_CODE_BOUNDARY_CHARS = frozenset(".-/:")


def _is_boundary_prefix(query_key: str, index_key: str) -> bool:
    """True, если query_key — префикс index_key, обрывающийся на границе токена.

    «сп256» → «сп256.1325800.2016»: обрыв на «.», префикс легитимен.
    «сп25»  → «сп256.1325800.2016»: обрыв внутри числа — это другая норма.
    """
    if not query_key or len(index_key) <= len(query_key):
        return False
    if not index_key.startswith(query_key):
        return False
    return index_key[len(query_key)] in _CODE_BOUNDARY_CHARS


# ─── Кеш ──────────────────────────────────────────────────────────────────
_index_cache: dict | None = None
_lookup_cache: dict[str, str] | None = None       # match-key → canonical code
_alias_kind_cache: dict[str, str] | None = None   # match-key → "canonical"|"alias"
_by_code_cache: dict[str, dict] | None = None     # canonical code → entry
_index_state_cache: str | None = None             # "ok" | "absent"
#: Дефект закешированного отказа. Кешируется наравне с удачным чтением:
#: иначе битый индекс перечитывался бы на каждой из сотен норм корпуса, а
#: ответ при этом всё равно один и тот же.
_index_error_cache: StatusIndexError | None = None


def _fail_index(exc: StatusIndexError) -> StatusIndexError:
    """Запомнить отказ в кеше и вернуть его для raise."""
    global _index_error_cache, _index_state_cache
    _index_error_cache = exc
    _index_state_cache = INDEX_STATE_BROKEN
    return exc


def load_status_index(force_reload: bool = False) -> dict:
    """Прочитать status_index.json из Norms-main и закешировать.

    Никогда не пишет обратно.

    Отсутствие файла — НЕ ошибка: возвращается пустой валидный каркас
    ({"meta": {}, "norms": []}), состояние индекса — "absent".

    Непригодный индекс — ошибка: StatusIndexError с названным дефектом.
    Раньше здесь наружу летели JSONDecodeError и голый KeyError: 'code'
    (D5). Вызывающему, который не хочет исключений, адресован
    resolve_norm_status() — он не бросает никогда, — либо
    status_index_state() для проверки состояния без резолва.

    Raises:
        StatusIndexError: файл есть, но не читается / не парсится / не той
            схемы / содержит запись без обязательного `code`.
    """
    global _index_cache, _lookup_cache, _alias_kind_cache, _by_code_cache
    global _index_state_cache, _index_error_cache
    if force_reload:
        _reset_cache()
    if _index_error_cache is not None:
        # Тот же объект исключения переиспользуется, поэтому чистим его
        # traceback: иначе он прирастал бы кадрами на каждой норме корпуса.
        raise _index_error_cache.with_traceback(None)
    if _index_cache is not None:
        return _index_cache

    path = NORMS_STATUS_INDEX_PATH
    try:
        exists = path.exists()
    except OSError as exc:  # длинный путь, битый симлинк и подобное
        raise _fail_index(StatusIndexError("unreadable_file", str(exc), path))
    if not exists:
        # Не роняем процесс — возвращаем пустой индекс. Все запросы вернут
        # not_found с resolution_reason=not_in_index.
        _index_cache = {"meta": {}, "norms": []}
        _lookup_cache = {}
        _alias_kind_cache = {}
        _by_code_cache = {}
        _index_state_cache = INDEX_STATE_ABSENT
        return _index_cache

    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
    except OSError as exc:
        raise _fail_index(StatusIndexError("unreadable_file", str(exc), path))
    except UnicodeDecodeError as exc:
        raise _fail_index(StatusIndexError("invalid_encoding", str(exc), path))

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise _fail_index(StatusIndexError("invalid_json", str(exc), path))

    try:
        entries = _validate_index_payload(data, path)
    except StatusIndexError as exc:
        raise _fail_index(exc)

    _index_cache = data
    _index_state_cache = INDEX_STATE_OK

    lookup: dict[str, str] = {}
    alias_kind: dict[str, str] = {}
    by_code: dict[str, dict] = {}

    # Два прохода, и порядок принципиален. Собственный код записи ВСЕГДА
    # сильнее чужого alias: иначе alias записи «СП 30.13330.2020»
    # («СНиП 2.04.01-85») перекрывал одноимённую запись самого СНиП, и
    # заменённый документ отвечал статусом active — зависимость результата от
    # порядка записей в файле индекса.
    for entry in entries:
        code = entry["code"]
        by_code[code] = entry
        canon_key = _match_key(code)
        if canon_key and canon_key not in lookup:
            lookup[canon_key] = code
            alias_kind[canon_key] = "canonical"

    for entry in entries:
        code = entry["code"]
        canon_key = _match_key(code)
        for alias in entry.get("aliases") or []:
            ak = _match_key(alias)
            if not ak or ak == canon_key:
                continue
            lookup.setdefault(ak, code)
            alias_kind.setdefault(ak, "alias")

    _lookup_cache = lookup
    _alias_kind_cache = alias_kind
    _by_code_cache = by_code
    return data


def _reset_cache() -> None:
    """Тестовый хелпер — сбрасывает кеш (включая закешированный отказ)."""
    global _index_cache, _lookup_cache, _alias_kind_cache, _by_code_cache
    global _index_state_cache, _index_error_cache
    _index_cache = None
    _lookup_cache = None
    _alias_kind_cache = None
    _by_code_cache = None
    _index_state_cache = None
    _index_error_cache = None


def status_index_state(force_reload: bool = False) -> dict:
    """Состояние индекса статусов — машиночитаемо и без исключений.

    Ответ на вопрос «что с ИНДЕКСОМ», в отличие от resolve_norm_status(),
    который отвечает на вопрос «что с НОРМОЙ». Нужна тем, у кого нет нормы
    для запроса: preflight конвейера, meta отчёта, CI-проверка артефакта.

    Returns:
        {
            "state": "ok" | "absent" | "broken",
            "path": str,                 # какой файл смотрели
            "defect": str | None,        # код дефекта для state="broken"
            "location": str | None,      # место дефекта ("norms[3]")
            "detail": str | None,        # человекочитаемое пояснение
            "norm_count": int,           # записей в индексе (0, если не ok)
        }
    """
    try:
        data = load_status_index(force_reload=force_reload)
    except StatusIndexError as exc:
        return {
            "state": INDEX_STATE_BROKEN,
            "path": exc.path,
            "defect": exc.defect,
            "location": exc.location,
            "detail": str(exc),
            "norm_count": 0,
        }
    return {
        "state": _index_state_cache or INDEX_STATE_OK,
        "path": str(NORMS_STATUS_INDEX_PATH),
        "defect": None,
        "location": None,
        "detail": None,
        "norm_count": len(data.get("norms", [])),
    }


# ─── Core resolve ─────────────────────────────────────────────────────────
def _peek_index_state() -> str:
    """Состояние индекса без исключений — для веток, где резолв не нужен."""
    try:
        load_status_index()
    except StatusIndexError:
        return INDEX_STATE_BROKEN
    return _index_state_cache or INDEX_STATE_OK



def _effective_status(doc_status: str | None, edition_status: str | None) -> str:
    """Свести (doc_status, edition_status) к единому статусу замечания.

    Mapping (см. норм-мэппинг из ТЗ):
        active + None/current  → active
        active + outdated      → outdated_edition
        replaced               → replaced
        cancelled              → cancelled
        иначе                  → unknown
    """
    if doc_status == "replaced":
        return "replaced"
    if doc_status == "cancelled":
        return "cancelled"
    if doc_status == "active":
        if edition_status == "outdated":
            return "outdated_edition"
        return "active"
    return "unknown"


def _resolve_in_index(normalized: str) -> tuple[str | None, str]:
    """Вернуть (canonical_code, kind) или (None, "none")."""
    load_status_index()
    assert _lookup_cache is not None
    assert _alias_kind_cache is not None

    key = _match_key(normalized)
    if not key:
        return None, "none"
    if key in _lookup_cache:
        return _lookup_cache[key], _alias_kind_cache.get(key, "canonical")

    # substring-fallback. Разрешены ровно два безопасных случая:
    #   1) ключ индекса целиком присутствует в запросе — «код + хвост»
    #      («СП 256.1325800.2016 п. 7.4.2»);
    #   2) запрос — префикс кода, обрывающийся на ГРАНИЦЕ токена
    #      («СП 256» → «СП 256.1325800.2016»).
    # Обрыв внутри числового токена запрещён: «СП 25» — это СП 25.13330
    # (основания на вечномёрзлых грунтах), и матч его в «СП 256.1325800.2016»
    # подменял одну норму другой, помечая результат found/authoritative.
    best_score: int | None = None
    best_codes: list[str] = []
    for k, code in _lookup_cache.items():
        if not (k in key or _is_boundary_prefix(key, k)):
            continue
        score = abs(len(k) - len(key))
        if best_score is None or score < best_score:
            best_score, best_codes = score, [code]
        elif score == best_score and code not in best_codes:
            best_codes.append(code)
    # Ничья между РАЗНЫМИ кодами («СП 30» при наличии редакций 2016 и 2020)
    # без домысла неразрешима: честнее вернуть not_in_index и отправить норму
    # в очередь на ручное добавление, чем выбрать по порядку записей в файле.
    if len(best_codes) == 1:
        return best_codes[0], "substring"
    return None, "none"


def _not_found(
    query: str,
    normalized: str,
    resolution_reason: str,
    family: str | None,
    supported_family: bool,
    index_state: str = INDEX_STATE_OK,
    index_defect: str | None = None,
) -> dict:
    """Сформировать payload «не найдено» в edge-формате контракта.

    index_state/index_defect — диагностика D4: они и отличают «нормы нет в
    индексе» от «индекс нечитаем» на стороне потребителя.
    """
    return {
        "query": query,
        "normalized_query": normalized,
        "found": False,
        "matched_code": None,
        "status": "unknown",
        "doc_status": None,
        "edition_status": None,
        "authoritative": False,
        "resolution_reason": resolution_reason,
        "detected_family": family,
        "supported_family": supported_family,
        "needs_manual_addition": supported_family and resolution_reason == "not_in_index",
        "has_text": False,
        "replacement_doc": None,
        "current_version": None,
        "title": None,
        "file": None,
        "type": None,
        "year": None,
        "details": None,
        "source_url": None,
        "last_verified": None,
        "parse_confidence": None,
        "source": "not_found",
        "index_state": index_state,
        "index_defect": index_defect,
    }


def resolve_norm_status(raw_norm: str) -> dict:
    """Authoritative статус нормы из Norms-main status_index.

    Нормализует вход, ищет по canonical code и aliases, определяет семейство
    и возвращает стабильный payload.

    Ключевые поля:
      query, normalized_query, found, matched_code,
      status ∈ {active, outdated_edition, replaced, cancelled, unknown},
      doc_status, edition_status, authoritative,
      resolution_reason ∈ {exact, alias, manual_override,
                           not_in_index, unsupported_family, not_found,
                           index_unreadable},
      detected_family, supported_family, needs_manual_addition, has_text,
      replacement_doc, current_version, title, file, type, year,
      details, source_url, last_verified, parse_confidence, source,
      index_state ∈ {ok, absent, broken}, index_defect.

    Не бросает исключений НИКОГДА — это контракт конвейера. Непригодный
    индекс возвращается как resolution_reason="index_unreadable" +
    index_state="broken" + index_defect=<код дефекта>, а не как not_found и
    не как падение (D4/D5).
    """
    original = "" if raw_norm is None else str(raw_norm)
    normalized = _normalize_query(original)

    # Пустой запрос → not_found без семейства. Этот вердикт об одном лишь
    # запросе, индекс для него не нужен — поэтому проверка идёт до загрузки.
    if not normalized:
        return _not_found(original, normalized, "not_found", None, False,
                          index_state=_peek_index_state())

    try:
        load_status_index()
    except StatusIndexError as exc:
        # D4: индекс СЛОМАН. Это НЕ «нормы нет в индексе»: про норму мы
        # вообще ничего не выяснили, и в ручную очередь её ставить нельзя —
        # добавление документа в vault битый артефакт не чинит. Вердикт
        # unsupported_family здесь тоже недопустим: он означает «в индексе
        # нет И семейство не распознано», а первую половину этой конъюнкции
        # мы проверить не смогли.
        family = _detect_family(normalized)
        return _not_found(
            original, normalized, "index_unreadable",
            family, family in _SUPPORTED_FAMILIES,
            index_state=INDEX_STATE_BROKEN, index_defect=exc.defect,
        )

    index_state = _index_state_cache or INDEX_STATE_OK
    matched_code, kind = _resolve_in_index(normalized)
    if matched_code is None:
        family = _detect_family(normalized)
        if family is None:
            return _not_found(original, normalized, "unsupported_family",
                              None, False, index_state=index_state)
        return _not_found(original, normalized, "not_in_index", family, True,
                          index_state=index_state)

    assert _by_code_cache is not None
    entry = _by_code_cache[matched_code]
    doc_status = entry.get("doc_status", "unknown")
    edition_status = entry.get("edition_status")
    eff = _effective_status(doc_status, edition_status)

    if entry.get("source") == "override_only":
        resolution_reason = "manual_override"
    elif kind == "canonical":
        resolution_reason = "exact"
    else:
        # alias или substring fallback — трактуем как alias-уровень.
        resolution_reason = "alias"

    family = _detect_family(entry.get("code", "")) or _detect_family(normalized)

    return {
        "query": original,
        "normalized_query": normalized,
        "found": True,
        "matched_code": entry["code"],
        "status": eff,
        "doc_status": doc_status,
        "edition_status": edition_status,
        "authoritative": bool(entry.get("authoritative", True)),
        "resolution_reason": resolution_reason,
        "detected_family": family,
        "supported_family": family in _SUPPORTED_FAMILIES,
        "needs_manual_addition": False,
        "has_text": bool(entry.get("has_text", entry.get("source") == "vault")),
        "replacement_doc": entry.get("replacement_doc"),
        "current_version": entry.get("current_version"),
        "title": entry.get("title"),
        "file": entry.get("file"),
        "type": entry.get("type"),
        "year": entry.get("year"),
        "details": entry.get("details"),
        "source_url": entry.get("source_url"),
        "last_verified": entry.get("last_verified"),
        "parse_confidence": entry.get("parse_confidence"),
        "source": entry.get("source", "vault"),
        "index_state": index_state,
        "index_defect": None,
    }


__all__ = [
    "NORMS_STATUS_INDEX_PATH",
    "StatusIndexError",
    "load_status_index",
    "resolve_norm_status",
    "status_index_state",
]
