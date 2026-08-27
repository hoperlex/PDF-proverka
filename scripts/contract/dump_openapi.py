#!/usr/bin/env python3
"""Снапшот HTTP-контракта приложения (этап 0, слой 1а).

Зачем. У приложения 265 операций и НОЛЬ типизированных схем ответа: все
обработчики возвращают голый `dict`. Поэтому OpenAPI здесь закрепляет ровно то,
что он реально знает — поверхность: пути, методы, параметры, тела запросов,
коды ответов. Формы ответов закрепляются отдельно (слой 1б,
`record_response_shapes.py`), потому что вывести их из кода нельзя.

Снапшот нормализуется, чтобы диф показывал изменение контракта, а не шум:

  * убираются `info.version` и `servers` — они меняются от релиза и окружения;
  * ключи сортируются рекурсивно;
  * `operationId` отбрасывается: FastAPI строит его из имени функции, и
    переименование приватной функции не является изменением контракта.

READ-ONLY по умолчанию. Без `--record` ничего не пишет: печатает отчёт и
завершается ненулевым кодом, если снапшот разошёлся с приложением.

Использование:
    python scripts/contract/dump_openapi.py            # проверка (для CI)
    python scripts/contract/dump_openapi.py --record   # перезаписать снапшот
    python scripts/contract/dump_openapi.py --diff     # показать расхождения
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SNAPSHOT = ROOT / "contracts" / "http" / "v1" / "openapi.snapshot.json"
INDEX = ROOT / "contracts" / "http" / "v1" / "endpoints.md"

#: Поля верхнего уровня, которые не являются контрактом.
_VOLATILE_TOP = ("servers",)
#: Поля операции, которые не являются контрактом.
_VOLATILE_OP = ("operationId", "summary", "description")

_METHODS = ("get", "post", "put", "patch", "delete", "head", "options")


def _sorted(value: Any) -> Any:
    """Рекурсивная сортировка ключей. Порядок списков сохраняется: в OpenAPI он
    значим (`parameters`, `required`, `enum`)."""
    if isinstance(value, dict):
        return {k: _sorted(value[k]) for k in sorted(value)}
    if isinstance(value, list):
        return [_sorted(v) for v in value]
    return value


def normalize(spec: dict) -> dict:
    spec = json.loads(json.dumps(spec, ensure_ascii=False))
    for key in _VOLATILE_TOP:
        spec.pop(key, None)
    info = spec.get("info")
    if isinstance(info, dict):
        info.pop("version", None)
    for item in (spec.get("paths") or {}).values():
        if not isinstance(item, dict):
            continue
        for method, op in list(item.items()):
            if method not in _METHODS or not isinstance(op, dict):
                continue
            for key in _VOLATILE_OP:
                op.pop(key, None)
    return _sorted(spec)


def load_live_spec() -> dict:
    from backend.app.main import app  # импорт внутри: тяжёлый и с побочными эффектами

    return normalize(app.openapi())


def operations(spec: dict) -> dict[str, dict]:
    """`METHOD path` → операция. Плоский вид, по которому считается диф."""
    out: dict[str, dict] = {}
    for path, item in (spec.get("paths") or {}).items():
        if not isinstance(item, dict):
            continue
        for method, op in item.items():
            if method in _METHODS and isinstance(op, dict):
                out[f"{method.upper()} {path}"] = op
    return out


def _param_sig(op: dict) -> str:
    parts = []
    for p in op.get("parameters") or []:
        if not isinstance(p, dict):
            continue
        mark = "!" if p.get("required") else "?"
        parts.append(f"{p.get('in', '?')}:{p.get('name', '?')}{mark}")
    body = op.get("requestBody")
    if isinstance(body, dict):
        mark = "!" if body.get("required") else "?"
        parts.append(f"body{mark}")
    return ", ".join(sorted(parts)) or "—"


def diff(old: dict, new: dict) -> dict[str, list[str]]:
    old_ops, new_ops = operations(old), operations(new)
    removed = sorted(set(old_ops) - set(new_ops))
    added = sorted(set(new_ops) - set(old_ops))
    changed = sorted(
        key for key in set(old_ops) & set(new_ops) if old_ops[key] != new_ops[key]
    )
    return {"removed": removed, "added": added, "changed": changed}


def build_index(spec: dict) -> str:
    ops = operations(spec)
    lines = [
        "# HTTP-контракт: индекс операций",
        "",
        "Сгенерировано `scripts/contract/dump_openapi.py`. Не редактировать вручную.",
        "",
        "Ни одна операция не имеет типизированной схемы ответа — все обработчики",
        "возвращают голый `dict`. Формы ответов закрепляются отдельно, слоем 1б",
        "(см. `docs/data_storage_modernization/00a_behaviour_freeze.md`).",
        "",
        f"Всего операций: **{len(ops)}**.",
        "",
        "| Метод | Путь | Параметры | Теги |",
        "| --- | --- | --- | --- |",
    ]
    for key in sorted(ops, key=lambda k: (k.split(" ", 1)[1], k)):
        method, path = key.split(" ", 1)
        op = ops[key]
        tags = ", ".join(op.get("tags") or []) or "—"
        lines.append(f"| `{method}` | `{path}` | {_param_sig(op)} | {tags} |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--record", action="store_true", help="перезаписать снапшот")
    ap.add_argument("--diff", action="store_true", help="показать расхождения подробно")
    args = ap.parse_args()

    live = load_live_spec()
    live_ops = operations(live)

    if not SNAPSHOT.exists():
        if not args.record:
            print(f"снапшот отсутствует: {SNAPSHOT.relative_to(ROOT)}")
            print("создайте его: python scripts/contract/dump_openapi.py --record")
            return 2
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT.write_text(
            json.dumps(live, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        INDEX.write_text(build_index(live), encoding="utf-8")
        print(f"снапшот создан: {len(live_ops)} операций")
        return 0

    stored = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    delta = diff(stored, live)
    total = sum(len(v) for v in delta.values())

    if total == 0:
        print(f"контракт совпадает: {len(live_ops)} операций")
        return 0

    print(f"контракт разошёлся со снапшотом: {total} операций")
    for kind, label in (
        ("removed", "исчезло"),
        ("added", "добавлено"),
        ("changed", "изменилось"),
    ):
        items = delta[kind]
        if not items:
            continue
        print(f"\n  {label} ({len(items)}):")
        shown = items if args.diff else items[:10]
        for key in shown:
            print(f"    {key}")
        if len(items) > len(shown):
            print(f"    … ещё {len(items) - len(shown)}; полный список — с --diff")

    if args.record:
        SNAPSHOT.write_text(
            json.dumps(live, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        INDEX.write_text(build_index(live), encoding="utf-8")
        print("\nснапшот перезаписан")
        return 0

    print("\nесли изменение намеренное — перезапишите снапшот и включите его в коммит:")
    print("  python scripts/contract/dump_openapi.py --record")
    return 1


if __name__ == "__main__":
    sys.exit(main())
