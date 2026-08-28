# -*- coding: utf-8 -*-
"""Domain contract v1: машиночитаемая форма не расходится с markdown-источником.

Источник истины — `docs/architecture/DOMAIN_CONTRACT_V1.md` (§8: markdown и JSON
расходиться не должны). Тест проверяет `contracts/domain/v1/**`: формы и
префиксы идентификаторов, замкнутость и достижимость состояний, каталог ошибок,
конверт §5.1 и его схему, а также согласие с `GLOSSARY.md` и
`contracts/agent_stream/v1/common.proto`. Задача W0-ARC-02.

Нормативного содержания у теста нет: всё ожидаемое вычисляется из markdown.
Зависимости — только стандартная библиотека и pytest (`jsonschema` не нужен:
минимальный валидатор подмножества draft 2020-12 реализован здесь же).
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MARKDOWN = ROOT / "docs" / "architecture" / "DOMAIN_CONTRACT_V1.md"
GLOSSARY = ROOT / "docs" / "architecture" / "GLOSSARY.md"
PROTO = ROOT / "contracts" / "agent_stream" / "v1" / "common.proto"
CONTRACT_DIR = ROOT / "contracts" / "domain" / "v1"

IDENTIFIERS_JSON = "identifiers.json"
STATES_JSON = "states.json"
ERRORS_JSON = "errors.json"
ENVELOPE_JSON = "error_envelope.schema.json"
JSON_FILES = (IDENTIFIERS_JSON, STATES_JSON, ERRORS_JSON, ENVELOPE_JSON)
CONTRACT_FILES = ("README.md",) + JSON_FILES

TOP_LEVEL_KEYS = {
    IDENTIFIERS_JSON: ("ulid", "forms", "identifier_error_rules", "identifiers",
                       "composite_keys", "legacy_aliases", "forbidden_synonyms"),
    STATES_JSON: ("state_machines", "enumerations", "decision_required_fields"),
    ERRORS_JSON: ("envelope", "grpc_alignment", "http_status_allowlist", "errors"),
    ENVELOPE_JSON: ("$schema", "type", "required", "properties",
                    "additionalProperties"),
}

ULID_CLASS = "[0-9A-HJKMNP-TV-Z]{26}"
ULID_SAMPLE = "01J9Z2M0RS3P4T5V6W7X8Y9Z0A"
MACHINE_SECTIONS = ("4.2", "4.3", "4.4", "4.5")
ALIAS_MODES = {"read_only", "mapping", "not_migrated"}
SNAKE_CASE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
EMPTY_CELLS = {"—", "–", "-", ""}


# --------------------------------------------------------------------------
# JSON контракта
# --------------------------------------------------------------------------
@lru_cache(maxsize=None)
def load(name: str) -> dict:
    path = CONTRACT_DIR / name
    assert path.is_file(), "нет файла контракта: %s" % path
    return json.loads(path.read_text(encoding="utf-8"))


def identifiers() -> list:
    return load(IDENTIFIERS_JSON)["identifiers"]


def known_fields() -> set:
    return {entry["field"] for entry in identifiers() if entry["field"]}


def machines() -> list:
    return load(STATES_JSON)["state_machines"]


def machine(section: str) -> dict:
    found = [m for m in machines() if m["section"] == section]
    assert len(found) == 1, (
        "в %s должна быть ровно одна машина состояний из §%s, найдено %d"
        % (STATES_JSON, section, len(found))
    )
    return found[0]


def enumeration(name: str) -> dict:
    found = [e for e in load(STATES_JSON)["enumerations"] if e["name"] == name]
    assert len(found) == 1, "перечисление %r не найдено в %s" % (name, STATES_JSON)
    return found[0]


def error_entries() -> list:
    return load(ERRORS_JSON)["errors"]


def error_codes() -> set:
    return {entry["error_code"] for entry in error_entries()}


# --------------------------------------------------------------------------
# разбор markdown
# --------------------------------------------------------------------------
def norm(text: str) -> str:
    """Незначащие пробелы не должны влиять на сравнение."""
    return re.sub(r"\s+", " ", text.replace(" ", " ")).strip()


def plain(cell: str) -> str:
    """Ячейка без обратных кавычек: «`none`» -> «none»."""
    return norm(cell.replace("`", ""))


def ticked(cell: str) -> list:
    return [norm(token) for token in re.findall(r"`([^`]+)`", cell)]


@lru_cache(maxsize=None)
def md_lines(path: Path = MARKDOWN) -> tuple:
    assert path.is_file(), "нет источника истины: %s" % path
    return tuple(path.read_text(encoding="utf-8").splitlines())


@lru_cache(maxsize=None)
def md_section(number: str, path: Path = MARKDOWN) -> tuple:
    """(заголовок без номера, строки раздела) для «## <number>. …»."""
    lines = md_lines(path)
    start = None
    for index, line in enumerate(lines):
        if re.match(r"^(#{2,4})\s+%s\.\s" % re.escape(number), line):
            start = index
            break
    assert start is not None, "в %s нет раздела §%s" % (path.name, number)
    level = len(lines[start].split(" ", 1)[0])
    heading = lines[start].split(" ", 2)[2]
    body = []
    for line in lines[start + 1:]:
        deeper = re.match(r"^(#{1,6})\s", line)
        if deeper and len(deeper.group(1)) <= level:
            break
        body.append(line)
    return heading, tuple(body)


def md_tables(number: str, path: Path = MARKDOWN) -> list:
    tables, current = [], []
    for line in md_section(number, path)[1]:
        stripped = line.strip()
        if stripped.startswith("|"):
            cells = [norm(cell) for cell in stripped.strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", cell) for cell in cells):
                continue
            current.append(cells)
        elif current:
            tables.append(current)
            current = []
    if current:
        tables.append(current)
    return tables


def md_rows(number: str, table_index: int = 0, path: Path = MARKDOWN) -> list:
    tables = md_tables(number, path)
    assert len(tables) > table_index, (
        "в §%s ожидалась таблица №%d, найдено %d"
        % (number, table_index + 1, len(tables))
    )
    return tables[table_index][1:]


def md_bullets(number: str) -> list:
    """Пункты «- …» с учётом переноса строк; блоки ``` пропускаются."""
    out, current, fenced = [], None, False
    for line in md_section(number)[1]:
        if line.strip().startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        if re.match(r"^-\s+", line):
            if current:
                out.append(norm(current))
            current = re.sub(r"^-\s+", "", line)
        elif current is not None and line.startswith("  ") and line.strip():
            current += " " + line.strip()
        elif not line.strip():
            if current:
                out.append(norm(current))
            current = None
    if current:
        out.append(norm(current))
    return out


def md_code_block(number: str) -> str:
    out, fenced = [], False
    for line in md_section(number)[1]:
        if line.strip().startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            out.append(line)
    return "\n".join(out)


def md_prose(number: str) -> str:
    return norm(" ".join(
        line for line in md_section(number)[1]
        if not line.strip().startswith("|") and not line.strip().startswith("-")
    ))


# --------------------------------------------------------------------------
# сверка
# --------------------------------------------------------------------------
def duplicates(items) -> list:
    seen, twice = set(), []
    for item in items:
        if item in seen and item not in twice:
            twice.append(item)
        seen.add(item)
    return twice


def assert_same(section: str, what: str, md_items, json_items, json_file: str) -> None:
    """Симметричная сверка множеств плюс контроль дублей и количества."""
    md_items, json_items = list(md_items), list(json_items)
    report = []
    md_twice, json_twice = duplicates(md_items), duplicates(json_items)
    if md_twice:
        report.append("в markdown продублированы строки: %r" % (md_twice,))
    if json_twice:
        report.append("в JSON продублированы записи: %r" % (json_twice,))
    extra = sorted(set(json_items) - set(md_items), key=repr)
    missing = sorted(set(md_items) - set(json_items), key=repr)
    if extra:
        report.append("лишнее в JSON (в markdown такого нет):")
        report += ["  + %r" % (item,) for item in extra]
    if missing:
        report.append("потеряно в JSON (есть в markdown):")
        report += ["  - %r" % (item,) for item in missing]
    if not report and len(md_items) != len(json_items):
        report.append("markdown даёт %d записей, JSON — %d"
                      % (len(md_items), len(json_items)))
    if not report:
        return
    head = [
        "§%s: %s расходятся между markdown и JSON." % (section, what),
        "источник истины: %s (§%s)" % (MARKDOWN.relative_to(ROOT), section),
        "машиночитаемая форма: %s" % (CONTRACT_DIR / json_file).relative_to(ROOT),
    ]
    raise AssertionError("\n".join(head + report))


# --------------------------------------------------------------------------
# минимальный валидатор подмножества JSON Schema draft 2020-12
# --------------------------------------------------------------------------
TYPES = {"object": dict, "string": str, "boolean": bool, "integer": int,
         "number": (int, float), "array": list}


def schema_errors(instance, schema, path="$") -> list:
    """Поддержано ровно то, чем пользуется конверт: type, required,
    additionalProperties, properties, enum, pattern, minLength."""
    found = []
    expected = schema.get("type")
    if expected:
        python_type = TYPES[expected]
        ok = isinstance(instance, python_type)
        if expected != "boolean" and isinstance(instance, bool):
            ok = False
        if not ok:
            return ["%s: ожидался тип %s, получено %r" % (path, expected, instance)]
    if "enum" in schema and instance not in schema["enum"]:
        found.append("%s: значение %r вне enum" % (path, instance))
    if isinstance(instance, str):
        if "pattern" in schema and not re.search(schema["pattern"], instance):
            found.append("%s: значение %r не подходит под pattern %s"
                         % (path, instance, schema["pattern"]))
        if "minLength" in schema and len(instance) < schema["minLength"]:
            found.append("%s: строка короче minLength %d" % (path, schema["minLength"]))
    if isinstance(instance, dict):
        properties = schema.get("properties", {})
        for name in schema.get("required", []):
            if name not in instance:
                found.append("%s: нет обязательного поля %r" % (path, name))
        if schema.get("additionalProperties") is False:
            for name in instance:
                if name not in properties:
                    found.append("%s: посторонее поле %r" % (path, name))
        for name, value in instance.items():
            if name in properties:
                found += schema_errors(value, properties[name], "%s.%s" % (path, name))
    return found


# --------------------------------------------------------------------------
# 1. файлы контракта
# --------------------------------------------------------------------------
@pytest.mark.parametrize("name", CONTRACT_FILES)
def test_contract_file_exists(name):
    path = CONTRACT_DIR / name
    assert path.is_file(), "файл контракта отсутствует: %s" % path
    assert path.stat().st_size > 0, "файл контракта пуст: %s" % path


@pytest.mark.parametrize("name", JSON_FILES)
def test_json_file_has_expected_sections(name):
    document = load(name)
    missing = [key for key in TOP_LEVEL_KEYS[name] if key not in document]
    assert not missing, "%s: нет обязательных секций %r" % (name, missing)


@pytest.mark.parametrize("name", (IDENTIFIERS_JSON, STATES_JSON, ERRORS_JSON))
def test_json_file_declares_source(name):
    document = load(name)
    assert document["version"] == "v1", "%s: версия контракта должна быть v1" % name
    assert document["source"] == "docs/architecture/DOMAIN_CONTRACT_V1.md", (
        "%s: ссылка на источник истины должна вести на markdown-контракт" % name
    )


def test_markdown_tables_have_no_duplicate_rows():
    """Дубль строки в markdown прячется при сравнении множествами."""
    tables = [("2", 0), ("3.2", 0), ("3.3", 0), ("3.4", 0), ("4.6", 0), ("4.7", 0),
              ("5.3", 0)]
    tables += [(section, index) for section in MACHINE_SECTIONS for index in (0, 1)]
    for section, index in tables:
        rows = [tuple(row) for row in md_rows(section, index)]
        twice = duplicates(rows)
        assert not twice, "§%s, таблица №%d: строки продублированы: %r" % (
            section, index + 1, twice
        )


# --------------------------------------------------------------------------
# 2. правила именования (§2)
# --------------------------------------------------------------------------
def derive_forbidden_items(cell: str) -> list:
    items = []
    for part in cell.split(","):
        part = norm(part)
        names = ticked(part)
        items.append((part, names[0] if names else None,
                      len(names) == 1 and plain(part) == names[0]))
    return items


def test_forbidden_synonyms_match_markdown():
    assert_same(
        "2", "запрещённые синонимы",
        [tuple(row) for row in md_rows("2")],
        [(item["canonical_cell"], item["forbidden_cell"])
         for item in load(IDENTIFIERS_JSON)["forbidden_synonyms"]],
        IDENTIFIERS_JSON,
    )


def test_forbidden_synonym_items_are_derived_from_cells():
    for item in load(IDENTIFIERS_JSON)["forbidden_synonyms"]:
        expected = derive_forbidden_items(item["forbidden_cell"])
        actual = [(part["name_cell"], part["name"], part["unconditional"])
                  for part in item["forbidden"]]
        assert actual == expected, (
            "§2, канон %s: разбор запрещённых имён разошёлся с ячейкой markdown\n"
            "  markdown: %r\n  JSON:     %r"
            % (item["canonical_cell"], expected, actual)
        )
        assert ticked(item["canonical_cell"])[0] == item["canonical"]


def test_forbidden_names_are_not_used_in_contract():
    """Безусловно запрещённое имя не должно попасть в машинные значения."""
    used = set(known_fields()) | error_codes()
    for state in machines():
        used |= {value["value"] for value in state["values"]}
        used.add(state["field"])
    for enum in load(STATES_JSON)["enumerations"]:
        used.add(enum["name"])
        used |= {value["value"] for value in enum["values"]}
    for item in load(IDENTIFIERS_JSON)["forbidden_synonyms"]:
        for part in item["forbidden"]:
            if not part["unconditional"]:
                continue
            assert part["name"] not in used, (
                "§2: имя %r запрещено как синоним %r, но используется в контракте"
                % (part["name"], item["canonical"])
            )


# --------------------------------------------------------------------------
# 3. идентификаторы (§3.1—§3.4)
# --------------------------------------------------------------------------
@lru_cache(maxsize=None)
def md_forms() -> tuple:
    """Формы, отличные от `<prefix>_<ULID>`, из §3.1: (subject_cell, rule_cell)."""
    bullet = [b for b in md_bullets("3.1") if b.startswith("формы, отличные")]
    assert bullet, "§3.1: не найден пункт с явными формами идентификаторов"
    _, _, tail = bullet[0].partition("заданы явно:")
    out = []
    for item in tail.strip().rstrip(".").split(";"):
        subject, _, rule = norm(item).partition(" — ")
        out.append((norm(subject), norm(rule)))
    return tuple(out)


@lru_cache(maxsize=None)
def md_form_by_field() -> dict:
    out = {}
    for subject, rule in md_forms():
        for name in ticked(subject):
            out[name] = rule
    return out


@lru_cache(maxsize=None)
def md_role_form() -> str:
    rules = [rule for subject, rule in md_forms() if not ticked(subject)]
    assert len(rules) == 1, "§3.1: ожидалось одно правило для ролей, найдено %r" % rules
    return ticked(rules[0])[0]


def expected_field(cell: str) -> str:
    """Имя поля выводится из ячейки «Идентификатор» §3.2 механически."""
    if "+" in cell:
        return None
    names = ticked(cell)
    if len(names) != 1:
        return None
    name = names[0]
    if name.startswith("(") and name.endswith(")"):
        return norm(name.strip("()").split(",")[-1])
    return name


def test_forms_match_markdown():
    assert_same(
        "3.1", "формы, отличные от `<prefix>_<ULID>`",
        md_forms(),
        [(form["subject_cell"], form["rule_cell"])
         for form in load(IDENTIFIERS_JSON)["forms"]],
        IDENTIFIERS_JSON,
    )
    for form in load(IDENTIFIERS_JSON)["forms"]:
        expected = ticked(form["rule_cell"])
        assert form["regex"] == (expected[0] if expected else None), (
            "§3.1: у формы %s regex %r не совпадает с правилом %r"
            % (form["subject_cell"], form["regex"], form["rule_cell"])
        )
        if form["regex"] is None:
            found = re.search(r"целое не меньше (\d+)", form["rule_cell"])
            assert found, "§3.1: правило %r не разобрано" % form["rule_cell"]
            assert form["minimum"] == int(found.group(1))
        else:
            re.compile(form["regex"])


def test_ulid_block_matches_markdown():
    ulid = load(IDENTIFIERS_JSON)["ulid"]
    bullet = [b for b in md_bullets("3.1") if "каноническая форма" in b]
    assert bullet, "§3.1: не найден пункт о канонической форме"
    found = re.search(r"(\d+) символов Crockford base32", bullet[0])
    assert found, "§3.1: длина ULID не указана"
    assert ulid["length"] == int(found.group(1)), (
        "§3.1: длина ULID в JSON (%d) не совпадает с markdown (%s)"
        % (ulid["length"], found.group(1))
    )
    charset = re.compile("^%s$" % ulid["char_class"])
    for letter in "ILOU":
        assert not charset.match(letter), (
            "char_class принимает %r, запрещённый в Crockford base32" % letter
        )
    for letter in "0123456789ABCDEFGHJKMNPQRSTVWXYZ":
        assert charset.match(letter), "char_class отвергает допустимый %r" % letter
    assert ulid["prefix_ulid_regex_template"] == "^{prefix}_%s$" % ULID_CLASS


def test_identifier_prefixes_are_unique():
    seen = {}
    for entry in identifiers():
        prefix = entry["prefix"]
        if prefix is None:
            continue
        assert prefix not in seen, (
            "префикс %r занят дважды: %s и %s" % (prefix, seen[prefix], entry["field"])
        )
        seen[prefix] = entry["field"]


def test_identifier_fields_are_unique_snake_case():
    fields = [entry["field"] for entry in identifiers() if entry["field"]]
    twice = duplicates(fields)
    assert not twice, "поля идентификаторов повторяются: %r" % twice
    for field in fields:
        assert SNAKE_CASE.fullmatch(field), "поле %r не в snake_case (§2)" % field


def test_identifier_field_is_derived_from_markdown():
    for entry in identifiers():
        expected = expected_field(entry["identifier_cell"])
        assert entry["field"] == expected, (
            "§3.2, «%s»: имя поля в JSON %r не выводится из ячейки markdown %r "
            "(ожидалось %r)"
            % (entry["entity"], entry["field"], entry["identifier_cell"], expected)
        )


def test_identifier_form_prefix_and_regex_follow_markdown():
    """Префикс и regex берутся из §3.2/§3.1, а не объявляются в JSON произвольно."""
    for entry in identifiers():
        cell, field = entry["format_cell"], entry["field"]
        ulid_form = re.fullmatch(r"`([a-z]{3,4})_<ULID>`", cell)
        prefixed = re.match(r"^`([a-z]{3,4})_<", cell)
        expected_prefix = prefixed.group(1) if prefixed else None
        assert entry["prefix"] == expected_prefix, (
            "§3.2, «%s»: префикс в JSON %r, а формат markdown %r даёт %r"
            % (entry["entity"], entry["prefix"], cell, expected_prefix)
        )
        if ulid_form:
            assert entry["form"] == "prefix_ulid", (
                "§3.2, «%s»: формат %r — каноническая форма, а form в JSON %r"
                % (entry["entity"], cell, entry["form"])
            )
            assert entry["regex"] == "^%s_%s$" % (ulid_form.group(1), ULID_CLASS), (
                "§3.2, «%s»: regex %r не соответствует форме `<prefix>_<ULID>`"
                % (entry["entity"], entry["regex"])
            )
        elif field in md_form_by_field():
            rule = md_form_by_field()[field]
            expected = ticked(rule)
            assert entry["regex"] == (expected[0] if expected else None), (
                "§3.1, «%s»: regex %r не совпадает с правилом markdown %r"
                % (entry["entity"], entry["regex"], rule)
            )
            if expected:
                assert entry["form"] == "explicit_form"
            else:
                assert entry["form"] == "integer"
                assert entry["minimum"] == int(
                    re.search(r"целое не меньше (\d+)", rule).group(1)
                )
        elif field is None:
            assert entry["form"] == "composite_key", (
                "§3.2, «%s»: у сущности без собственного поля form должен быть "
                "composite_key, а не %r" % (entry["entity"], entry["form"])
            )
            keys = [k["key"] for k in load(IDENTIFIERS_JSON)["composite_keys"]]
            assert entry["composite_key"] in keys, (
                "§3.3: составной ключ %r не объявлен" % entry["composite_key"]
            )
        else:
            assert entry["form"] == "role", (
                "§3.2, «%s»: формат %r — роль из реестра, а form в JSON %r"
                % (entry["entity"], cell, entry["form"])
            )
            assert entry["regex"] == md_role_form(), (
                "§3.1: regex роли %r не совпадает с markdown %r"
                % (entry["regex"], md_role_form())
            )
        if entry["regex"]:
            re.compile(entry["regex"])
        assert entry["uniqueness_scope"], "«%s»: нет области уникальности" % entry["entity"]
        assert entry["owner_module"], "«%s»: нет владеющего модуля" % entry["entity"]


def test_prefix_ulid_regex_rejects_wrong_values():
    for entry in identifiers():
        if entry["form"] != "prefix_ulid":
            continue
        prefix, compiled = entry["prefix"], re.compile(entry["regex"])
        assert compiled.fullmatch("%s_%s" % (prefix, ULID_SAMPLE))
        for bad in ("%s_%s" % (prefix, ULID_SAMPLE.lower()),
                    "%s_%s" % (prefix, ULID_SAMPLE[:-1]),
                    "%s_%sI" % (prefix, ULID_SAMPLE[:-1]),
                    "x%s_%s" % (prefix, ULID_SAMPLE)):
            assert not compiled.fullmatch(bad), (
                "%s: regex принял недопустимое значение %r" % (entry["entity"], bad)
            )


def test_identifier_prefix_shape():
    for entry in identifiers():
        if entry["prefix"] is None:
            continue
        assert re.fullmatch(r"[a-z]{3,4}", entry["prefix"]), (
            "«%s»: префикс %r нарушает §3.1 (три-четыре строчных латинских символа)"
            % (entry["entity"], entry["prefix"])
        )


def test_identifier_error_rules_match_markdown():
    rules = load(IDENTIFIERS_JSON)["identifier_error_rules"]
    bullet = [b for b in md_bullets("3.1") if "неизвестный идентификатор" in b]
    assert bullet, "§3.1: не найден пункт об ошибке для неизвестного идентификатора"
    assert rules["rule_cell"] == bullet[0], (
        "§3.1: правило ошибок в JSON разошлось с markdown\n  markdown: %r\n"
        "  JSON:     %r" % (bullet[0], rules["rule_cell"])
    )
    unknown = [code for code in rules["codes"] if code not in error_codes()]
    assert not unknown, "§3.1 ссылается на коды вне каталога §5.3: %r" % unknown


def test_error_codes_referenced_by_rules_exist():
    """Коды, названные в правилах §3.1 и §4.1, обязаны быть в каталоге §5.3."""
    for section in ("3.1", "4.1"):
        for bullet in md_bullets(section):
            if "ошибк" not in bullet:
                continue
            for token in ticked(bullet):
                if not SNAKE_CASE.fullmatch(token):
                    continue
                assert token in error_codes(), (
                    "§%s ссылается на код %r, которого нет в каталоге §5.3"
                    % (section, token)
                )


def test_identifier_registry_matches_markdown():
    rows = md_rows("3.2")
    assert len(rows[0]) == 5, "§3.2: ожидалось пять столбцов, получено %r" % rows[0]
    assert_same("3.2", "сущности реестра идентификаторов",
                [row[0] for row in rows],
                [entry["entity"] for entry in identifiers()], IDENTIFIERS_JSON)
    assert_same("3.2", "имена идентификаторов",
                [row[1] for row in rows],
                [entry["identifier_cell"] for entry in identifiers()], IDENTIFIERS_JSON)
    assert_same("3.2", "строки реестра идентификаторов",
                [tuple(row) for row in rows],
                [(entry["entity"], entry["identifier_cell"], entry["format_cell"],
                  entry["uniqueness_scope"], entry["owner_module"])
                 for entry in identifiers()], IDENTIFIERS_JSON)


def test_composite_keys_match_markdown():
    assert_same("3.3", "составные ключи",
                [tuple(row) for row in md_rows("3.3")],
                [(key["key"], key["parts_cell"], key["rationale"])
                 for key in load(IDENTIFIERS_JSON)["composite_keys"]], IDENTIFIERS_JSON)


def test_composite_key_parts_are_derived_from_markdown():
    fields = known_fields()
    for key in load(IDENTIFIERS_JSON)["composite_keys"]:
        parts, prose = [], []
        for component in key["parts_cell"].split("+"):
            component = norm(component)
            names = ticked(component)
            if len(names) == 1 and plain(component) == names[0] and names[0] in fields:
                parts.append(names[0])
            else:
                prose.append(component)
        assert (key["parts"], key["prose_parts"]) == (parts, prose), (
            "§3.3, ключ «%s»: состав в JSON (%r, %r) не выводится из ячейки %r "
            "(ожидалось %r, %r)"
            % (key["key"], key["parts"], key["prose_parts"], key["parts_cell"],
               parts, prose)
        )
        unknown = [part for part in key["parts"] if part not in fields]
        assert not unknown, (
            "§3.3, ключ «%s»: неизвестные поля %r" % (key["key"], unknown)
        )


def test_legacy_aliases_match_markdown():
    assert_same("3.4", "legacy-алиасы",
                [tuple(row) for row in md_rows("3.4")],
                [(alias["alias_cell"], alias["canonical_cell"], alias["mode_cell"])
                 for alias in load(IDENTIFIERS_JSON)["legacy_aliases"]],
                IDENTIFIERS_JSON)


def test_legacy_alias_modes_follow_mode_cell():
    for alias in load(IDENTIFIERS_JSON)["legacy_aliases"]:
        mode, cell = alias["mode"], alias["mode_cell"]
        assert mode in ALIAS_MODES, (
            "алиас %r: режим %r вне закрытого списка %s"
            % (alias["alias_cell"], mode, sorted(ALIAS_MODES))
        )
        expected = None
        if cell.startswith("только чтение"):
            expected = "read_only"
        elif cell.startswith("не переносится"):
            expected = "not_migrated"
        elif "mapping" in cell:
            expected = "mapping"
        if expected:
            assert mode == expected, (
                "§3.4, алиас %r: колонка «Режим» говорит %r, значит режим %r, "
                "а в JSON %r" % (alias["alias_cell"], cell, expected, mode)
            )
        assert alias["alias_tokens"] == ticked(alias["alias_cell"]) or \
            set(alias["alias_tokens"]) <= set(ticked(alias["alias_cell"])), (
            "§3.4, алиас %r: alias_tokens %r не выводятся из ячейки"
            % (alias["alias_cell"], alias["alias_tokens"])
        )


# --------------------------------------------------------------------------
# 4. состояния (§4.1—§4.7)
# --------------------------------------------------------------------------
def md_machine_heading(section: str) -> tuple:
    heading = md_section(section)[0]
    entity, _, field_cell = heading.partition(":")
    names = ticked(field_cell)
    assert len(names) == 1, "§%s: в заголовке нет имени поля состояния" % section
    return norm(entity), names[0]


def md_owner_cell(section: str) -> str:
    body = list(md_section(section)[1])
    index = [i for i, line in enumerate(body) if line.startswith("Владелец записи")]
    assert index, "§%s: нет строки «Владелец записи»" % section
    sentence = norm(" ".join(body[index[0]:index[0] + 2]))
    return sentence.split(".")[0] + "."


@pytest.mark.parametrize("section", MACHINE_SECTIONS)
def test_state_machine_identity_matches_markdown(section):
    entity, field = md_machine_heading(section)
    state = machine(section)
    assert (state["entity"], state["field"], state["name"]) == (entity, field, field), (
        "§%s: заголовок markdown даёт «%s» и поле %r, а JSON — «%s», поле %r, "
        "имя %r" % (section, entity, field, state["entity"], state["field"],
                    state["name"])
    )


@pytest.mark.parametrize("section", MACHINE_SECTIONS)
def test_state_machine_owner_matches_markdown(section):
    state, cell = machine(section), md_owner_cell(section)
    assert state["owner_cell"] == cell, (
        "§%s: строка владельца в JSON разошлась с markdown\n  markdown: %r\n"
        "  JSON:     %r" % (section, cell, state["owner_cell"])
    )
    assert state["owner_module"] == ticked(cell)[0], (
        "§%s: владелец %r не выводится из строки markdown %r"
        % (section, state["owner_module"], cell)
    )


@pytest.mark.parametrize("section", MACHINE_SECTIONS)
def test_state_values_match_markdown(section):
    rows = md_rows(section, 0)
    assert len(rows[0]) == 4, (
        "§%s: в таблице значений ожидались столбцы «Значение», «Смысл», "
        "«Начальное», «Терминальное», получено %r" % (section, rows[0])
    )
    assert_same(
        section, "значения состояния `%s`" % machine(section)["field"],
        [(plain(row[0]), row[1], plain(row[2]).lower() == "да",
          plain(row[3]).lower() == "да") for row in rows],
        [(value["value"], value["meaning"], value["initial"], value["terminal"])
         for value in machine(section)["values"]],
        STATES_JSON,
    )
    for value in machine(section)["values"]:
        assert SNAKE_CASE.fullmatch(value["value"]), (
            "§%s: значение %r не в snake_case (§2)" % (section, value["value"])
        )


@pytest.mark.parametrize("section", MACHINE_SECTIONS)
def test_state_transitions_match_markdown(section):
    expected = []
    for source_cell, target_cell, initiator, condition in md_rows(section, 1):
        sources = [None] if plain(source_cell) in EMPTY_CELLS else [
            plain(part) for part in source_cell.split(",")
        ]
        for source in sources:
            for target in [plain(part) for part in target_cell.split(",")]:
                expected.append((source, target, initiator, condition))
    assert_same(
        section, "переходы `%s`" % machine(section)["field"], expected,
        [(item["from"], item["to"], item["initiator"], item["condition"])
         for item in machine(section)["transitions"]],
        STATES_JSON,
    )


@pytest.mark.parametrize("section", MACHINE_SECTIONS)
def test_transitions_reference_known_values(section):
    state = machine(section)
    known = {value["value"] for value in state["values"]}
    for item in state["transitions"]:
        source, target = item["from"], item["to"]
        assert source is None or source in known, (
            "§%s: переход из неизвестного значения %r (известны %s)"
            % (section, source, sorted(known))
        )
        assert target in known, (
            "§%s: переход в неизвестное значение %r (известны %s)"
            % (section, target, sorted(known))
        )
        assert item["initiator"], "§%s: переход %r->%r без инициатора" % (
            section, source, target)
        assert item["condition"], "§%s: переход %r->%r без условия" % (
            section, source, target)


@pytest.mark.parametrize("section", MACHINE_SECTIONS)
def test_no_transition_out_of_terminal_value(section):
    state = machine(section)
    terminal = {value["value"] for value in state["values"] if value["terminal"]}
    leaving = sorted({item["from"] for item in state["transitions"]
                      if item["from"] in terminal})
    assert not leaving, (
        "§%s: терминальное состояние не покидается (§4.1), а переход есть из %r"
        % (section, leaving)
    )


@pytest.mark.parametrize("section", MACHINE_SECTIONS)
def test_every_value_is_reachable(section):
    """Значение либо начальное, либо в него ведёт хотя бы один переход."""
    state = machine(section)
    incoming = {item["to"] for item in state["transitions"]}
    unreachable = [
        value["value"] for value in state["values"]
        if not value["initial"] and value["value"] not in incoming
    ]
    assert not unreachable, (
        "§%s: в значения %r не ведёт ни один переход, и начальными они не "
        "объявлены — машина недостижима" % (section, unreachable)
    )


@pytest.mark.parametrize("section", MACHINE_SECTIONS)
def test_non_terminal_value_has_outgoing_transition(section):
    """Нетерминальное значение без исхода — тупик, которого §4.1 не допускает."""
    state = machine(section)
    outgoing = {item["from"] for item in state["transitions"]}
    stuck = [
        value["value"] for value in state["values"]
        if not value["terminal"] and value["value"] not in outgoing
    ]
    assert not stuck, (
        "§%s: значения %r не терминальны, но выхода из них нет" % (section, stuck)
    )


@pytest.mark.parametrize("section", MACHINE_SECTIONS)
def test_initial_values_are_declared_and_not_terminal(section):
    state = machine(section)
    initial = [value["value"] for value in state["values"] if value["initial"]]
    assert initial, "§%s: markdown не объявил ни одного начального значения" % section
    both = [value["value"] for value in state["values"]
            if value["initial"] and value["terminal"]]
    assert not both, "§%s: значения %r одновременно начальные и терминальные" % (
        section, both)


def test_decision_verdicts_match_markdown():
    assert_same("4.6", "значения `decision_verdict`",
                [(plain(row[0]), row[1]) for row in md_rows("4.6")],
                [(item["value"], item["meaning"])
                 for item in enumeration("decision_verdict")["values"]], STATES_JSON)


def test_finding_review_states_match_markdown():
    found = re.search(
        r"`finding_review_state`\s+принимает\s+значения\s+(.+?)\s+и\s+перестраивается",
        md_prose("4.6"),
    )
    assert found, "§4.6: не найдено перечисление значений `finding_review_state`"
    assert_same("4.6", "значения `finding_review_state`", ticked(found.group(1)),
                [item["value"] for item in enumeration("finding_review_state")["values"]],
                STATES_JSON)


def test_decision_required_fields_match_markdown():
    bullets = md_bullets("4.6")
    assert bullets, "§4.6: не найден список обязательных полей решения"
    assert_same("4.6", "обязательные поля решения", bullets,
                [item["item_cell"] for item in load(STATES_JSON)["decision_required_fields"]],
                STATES_JSON)
    for item in load(STATES_JSON)["decision_required_fields"]:
        assert item["tokens"] == ticked(item["item_cell"]), (
            "§4.6: имена в пункте %r разошлись с разбором ячейки" % item["item_cell"]
        )


def test_severity_matches_markdown():
    rows = md_rows("4.7")
    assert_same("4.7", "значения `severity` с подписями",
                [(plain(row[0]), row[1], row[2]) for row in rows],
                [(item["value"], item["display"], item["legacy_source_cell"])
                 for item in enumeration("severity")["values"]], STATES_JSON)
    for item in enumeration("severity")["values"]:
        assert item["display"], "severity %r: нет display-подписи (§4.7)" % item["value"]
        assert item["legacy_values"] == ticked(item["legacy_source_cell"]), (
            "severity %r: legacy_values не выводятся из ячейки markdown"
            % item["value"]
        )


def test_enumeration_values_are_unique_snake_case():
    for name in ("decision_verdict", "finding_review_state", "severity"):
        values = [item["value"] for item in enumeration(name)["values"]]
        twice = duplicates(values)
        assert not twice, "%s: значения повторяются: %r" % (name, twice)
        for value in values:
            assert SNAKE_CASE.fullmatch(value), "%s: значение %r не в snake_case" % (
                name, value)


# --------------------------------------------------------------------------
# 5. ошибки (§5.1—§5.4)
# --------------------------------------------------------------------------
def test_error_codes_are_unique_snake_case():
    codes = [entry["error_code"] for entry in error_entries()]
    twice = duplicates(codes)
    assert not twice, "коды ошибок повторяются: %r" % twice
    for code in codes:
        assert SNAKE_CASE.fullmatch(code), "код %r не в snake_case (§5.2)" % code


def test_http_status_allowlist_matches_markdown():
    bullet = [b for b in md_bullets("5.2") if "статусами" in b]
    assert bullet, "§5.2: не найден пункт с допустимыми статусами"
    expected = sorted({int(value) for value in re.findall(r"\b\d{3}\b", bullet[0])})
    assert load(ERRORS_JSON)["http_status_allowlist"] == expected, (
        "§5.2: allowlist в JSON %r не совпадает со списком markdown %r"
        % (load(ERRORS_JSON)["http_status_allowlist"], expected)
    )
    assert not [status for status in expected if status < 400], (
        "§5.1: в allowlist попал статус, которым ошибка отвечать не может: %r"
        % expected
    )


def test_error_http_statuses_are_in_allowlist():
    allowlist = load(ERRORS_JSON)["http_status_allowlist"]
    for entry in error_entries():
        status = entry["http_status"]
        assert isinstance(status, int) and not isinstance(status, bool), (
            "%s: http_status должен быть целым, получено %r"
            % (entry["error_code"], status)
        )
        assert status in allowlist, (
            "%s: статус %d вне allowlist §5.2 %r"
            % (entry["error_code"], status, allowlist)
        )


def test_error_retryable_is_boolean():
    for entry in error_entries():
        assert isinstance(entry["retryable"], bool), (
            "%s: retryable должен быть булевым, получено %r"
            % (entry["error_code"], entry["retryable"])
        )
        assert entry["description"], "%s: нет описания причины" % entry["error_code"]


def test_error_catalog_matches_markdown():
    rows = md_rows("5.3")
    assert_same("5.3", "коды ошибок", [plain(row[0]) for row in rows],
                [entry["error_code"] for entry in error_entries()], ERRORS_JSON)
    assert_same("5.3", "строки каталога ошибок",
                [(plain(row[0]), int(plain(row[1])), plain(row[2]).lower() == "да",
                  row[3]) for row in rows],
                [(entry["error_code"], entry["http_status"], entry["retryable"],
                  entry["description"]) for entry in error_entries()], ERRORS_JSON)


def md_envelope_bullets() -> tuple:
    fields, rules = [], []
    for bullet in md_bullets("5.1"):
        names = ticked(bullet)
        if names and bullet.startswith("`%s`" % names[0]):
            fields.append((names[0], bullet))
        else:
            rules.append(bullet)
    return tuple(fields), tuple(rules)


def test_envelope_fields_match_markdown():
    fields, rules = md_envelope_bullets()
    envelope = load(ERRORS_JSON)["envelope"]
    assert_same("5.1", "поля конверта", fields,
                [(item["field"], item["rule_cell"]) for item in envelope["fields"]],
                ERRORS_JSON)
    assert_same("5.1", "правила конверта", rules, envelope["rules"], ERRORS_JSON)
    for item in envelope["fields"]:
        assert item["requirement"] in ("required", "conditional"), (
            "поле %r: неизвестный признак обязательности %r"
            % (item["field"], item["requirement"])
        )
        conditional = "обязателен для" in item["rule_cell"]
        assert (item["requirement"] == "conditional") == conditional, (
            "§5.1, поле %r: правило %r и признак %r не согласованы"
            % (item["field"], item["rule_cell"], item["requirement"])
        )


def test_envelope_schema_matches_errors_json():
    envelope = load(ERRORS_JSON)["envelope"]
    schema = load(ENVELOPE_JSON)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False, (
        "конверт закрыт: additionalProperties должно быть false"
    )
    required = [item["field"] for item in envelope["fields"]
                if item["requirement"] == "required"]
    assert sorted(schema["required"]) == sorted(required), (
        "обязательные поля конверта в %s и %s разошлись: %r и %r"
        % (ERRORS_JSON, ENVELOPE_JSON, sorted(required), sorted(schema["required"]))
    )
    assert sorted(schema["properties"]) == sorted(
        item["field"] for item in envelope["fields"]
    ), "состав полей конверта в %s и %s разошёлся" % (ERRORS_JSON, ENVELOPE_JSON)


def test_envelope_enum_matches_error_catalog():
    schema_codes = load(ENVELOPE_JSON)["properties"]["error_code"]["enum"]
    assert_same("5.3", "коды ошибок в enum конверта",
                [entry["error_code"] for entry in error_entries()], schema_codes,
                ENVELOPE_JSON)


def test_envelope_correlation_id_pattern():
    pattern = load(ENVELOPE_JSON)["properties"]["correlation_id"]["pattern"]
    prefix = [entry["prefix"] for entry in identifiers()
              if entry["field"] == "correlation_id"][0]
    assert pattern == "^%s_%s$" % (prefix, ULID_CLASS), (
        "correlation_id в схеме должен требовать `%s_` и 26 символов Crockford "
        "base32, получено %r" % (prefix, pattern)
    )
    compiled = re.compile(pattern)
    assert compiled.fullmatch("corr_%s" % ULID_SAMPLE)
    for bad in ("corr_%s" % ULID_SAMPLE.lower(), "corr_%s" % ULID_SAMPLE[:-1],
                "run_%s" % ULID_SAMPLE, "corr_%sU" % ULID_SAMPLE[:-1]):
        assert not compiled.fullmatch(bad), "pattern принял недопустимое %r" % bad


def test_envelope_example_from_markdown_validates():
    example = json.loads(md_code_block("5.1"))
    errors = schema_errors(example, load(ENVELOPE_JSON))
    assert not errors, (
        "пример конверта §5.1 не проходит собственную схему %s:\n  %s"
        % (ENVELOPE_JSON, "\n  ".join(errors))
    )
    assert example["error_code"] in error_codes(), (
        "§5.1: код примера %r отсутствует в каталоге §5.3" % example["error_code"]
    )


def test_envelope_validator_rejects_broken_examples():
    """Валидатор обязан ловить нарушения, иначе предыдущая проверка пуста."""
    schema = load(ENVELOPE_JSON)
    example = json.loads(md_code_block("5.1"))
    cases = {
        "нет обязательного поля": {k: v for k, v in example.items() if k != "stage"},
        "посторонее поле": dict(example, unexpected=1),
        "код вне каталога": dict(example, error_code="not_a_code"),
        "битый correlation_id": dict(example, correlation_id="corr_lowercase"),
        "не тот тип": dict(example, retryable="false"),
        "пустое сообщение": dict(example, message=""),
    }
    for label, broken in cases.items():
        assert schema_errors(broken, schema), (
            "валидатор пропустил случай «%s»: %r" % (label, broken)
        )


def test_grpc_alignment_matches_markdown_and_proto():
    alignment = load(ERRORS_JSON)["grpc_alignment"]
    prose = md_prose("5.4")
    expected = ticked(prose.split("common.proto`:")[1].split(".")[0])
    assert alignment["fields"] == expected, (
        "§5.4: поля конверта в JSON %r не совпадают с markdown %r"
        % (alignment["fields"], expected)
    )
    assert alignment["proto"] in prose or alignment["proto"] in " ".join(md_section("5.4")[1])
    proto_path = ROOT / alignment["proto"]
    assert proto_path.is_file(), "нет proto-файла: %s" % proto_path
    body = proto_path.read_text(encoding="utf-8")
    found = re.search(r"message\s+%s\s*\{(.+?)\}" % alignment["message"], body, re.S)
    assert found, "в %s нет сообщения %s" % (alignment["proto"], alignment["message"])
    proto_fields = re.findall(r"^\s*[\w.]+\s+(\w+)\s*=\s*\d+;", found.group(1), re.M)
    missing = [name for name in alignment["fields"] if name not in proto_fields]
    assert not missing, (
        "§5.4: поля %r не найдены в %s (%s содержит %r)"
        % (missing, alignment["proto"], alignment["message"], proto_fields)
    )


# --------------------------------------------------------------------------
# 6. согласие с глоссарием (GLOSSARY.md §2)
# --------------------------------------------------------------------------
@lru_cache(maxsize=None)
def glossary_rows(number: str) -> tuple:
    return tuple(tuple(row) for row in md_rows(number, 0, GLOSSARY))


def test_glossary_registry_matches_contract_registry():
    """§2.1 глоссария объявляет себя дословной копией §3.2 контракта."""
    rows = glossary_rows("2.1")
    assert len(rows[0]) == 5, (
        "GLOSSARY.md §2.1: ожидалось пять столбцов, получено %r" % (rows[0],)
    )
    glossary_items = [(row[0], row[3], row[4]) for row in rows]
    contract_items = [(entry["entity"], entry["identifier_cell"],
                       entry["owner_module"]) for entry in identifiers()]
    md_twice = duplicates(glossary_items)
    assert not md_twice, "GLOSSARY.md §2.1: строки продублированы: %r" % (md_twice,)
    extra = sorted(set(glossary_items) - set(contract_items), key=repr)
    missing = sorted(set(contract_items) - set(glossary_items), key=repr)
    report = []
    if extra:
        report.append("есть в глоссарии, нет в реестре §3.2:")
        report += ["  + %r" % (item,) for item in extra]
    if missing:
        report.append("есть в реестре §3.2, нет в глоссарии:")
        report += ["  - %r" % (item,) for item in missing]
    assert not report, "\n".join(
        ["GLOSSARY.md §2.1 и §3.2 контракта разошлись "
         "(колонки «Термин (RU)», «Идентификатор», «Владелец записи»).",
         "глоссарий: %s" % GLOSSARY.relative_to(ROOT),
         "контракт: %s (§3.2)" % MARKDOWN.relative_to(ROOT)] + report
    )


def test_glossary_extra_terms_have_no_registry_identifier():
    """§2.2 глоссария — понятия без идентификатора; реестр их не выдаёт."""
    entities = {entry["entity"] for entry in identifiers()}
    named = [row[0] for row in glossary_rows("2.2") if row[0] in entities]
    assert not named, (
        "GLOSSARY.md §2.2 объявляет понятия без идентификатора, но %r есть в "
        "реестре §3.2 контракта" % named
    )
