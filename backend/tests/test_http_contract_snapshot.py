"""Тест дрейфа HTTP-контракта (этап 0, слой 1в).

Падает, когда поверхность API изменилась, а снапшот
`contracts/http/v1/openapi.snapshot.json` — нет. Это не запрет менять API:
это требование, чтобы изменение было заявлено в том же коммите.

Намеренное изменение:
    python scripts/contract/dump_openapi.py --record

Почему снапшот, а не сравнение с pydantic-моделями: у приложения 265 операций
и ноль типизированных схем ответа — сравнивать не с чем. Формы ответов
закрепляет отдельный слой 1б, см.
`docs/data_storage_modernization/00a_behaviour_freeze.md`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

sys.path.insert(0, str(ROOT / "scripts" / "contract"))
import dump_openapi as contract  # noqa: E402

# Primary lane §5: contract — сверяет схемы/proto из `contracts/**` с источником.
pytestmark = pytest.mark.contract

SNAPSHOT = ROOT / "contracts" / "http" / "v1" / "openapi.snapshot.json"
INDEX = ROOT / "contracts" / "http" / "v1" / "endpoints.md"

_RECORD_HINT = "python scripts/contract/dump_openapi.py --record"


@pytest.fixture(scope="module")
def stored() -> dict:
    if not SNAPSHOT.exists():
        pytest.fail(f"снапшот отсутствует: {SNAPSHOT}. Создайте его: {_RECORD_HINT}")
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def live() -> dict:
    return contract.load_live_spec()


def test_snapshot_matches_live_surface(stored, live):
    """Пути, методы, параметры и тела запросов совпадают со снапшотом."""
    delta = contract.diff(stored, live)
    if not any(delta.values()):
        return

    lines = ["HTTP-контракт разошёлся со снапшотом."]
    for kind, label in (
        ("removed", "исчезло из приложения"),
        ("added", "появилось в приложении"),
        ("changed", "изменилось"),
    ):
        items = delta[kind]
        if items:
            lines.append(f"\n{label} ({len(items)}):")
            lines.extend(f"  {key}" for key in items[:20])
            if len(items) > 20:
                lines.append(f"  … ещё {len(items) - 20}")
    lines.append(f"\nЕсли изменение намеренное: {_RECORD_HINT}")
    pytest.fail("\n".join(lines))


def test_snapshot_is_normalized(stored):
    """Снапшот не содержит волатильных полей.

    `info.version` и `servers` меняются от релиза и окружения, `operationId`
    строится из имени Python-функции. Их присутствие означает, что снапшот
    записан в обход `dump_openapi.normalize` и будет давать ложные падения.
    """
    assert "servers" not in stored, f"снапшот содержит `servers`; перезапишите: {_RECORD_HINT}"
    assert "version" not in (stored.get("info") or {}), (
        f"снапшот содержит `info.version`; перезапишите: {_RECORD_HINT}"
    )
    for key, op in contract.operations(stored).items():
        assert "operationId" not in op, (
            f"{key} содержит `operationId`; перезапишите снапшот: {_RECORD_HINT}"
        )


def test_index_is_in_sync(stored):
    """Человекочитаемый индекс перегенерирован вместе со снапшотом."""
    assert INDEX.exists(), f"индекс отсутствует: {INDEX}. {_RECORD_HINT}"
    assert INDEX.read_text(encoding="utf-8") == contract.build_index(stored), (
        f"`endpoints.md` отстал от снапшота; перегенерируйте: {_RECORD_HINT}"
    )


def test_no_response_schemas_yet(live):
    """Зафиксированный факт: типизированных схем ответа нет ни у одной операции.

    Это не пожелание, а исходная точка этапа 0 — она обосновывает существование
    слоя 1б (golden master форм ответа). Когда типизация начнёт появляться,
    тест упадёт и заставит зафиксировать новую цифру в
    `00a_behaviour_freeze.md` вместо молчаливого дрейфа документации.
    """
    typed = []
    for key, op in contract.operations(live).items():
        ok = (op.get("responses") or {}).get("200") or {}
        schema = ((ok.get("content") or {}).get("application/json") or {}).get("schema")
        if schema and (schema.get("$ref") or schema.get("properties")):
            typed.append(key)
    assert not typed, (
        f"появились типизированные ответы ({len(typed)}): {typed[:10]}. "
        "Обновите §2 в docs/data_storage_modernization/00a_behaviour_freeze.md."
    )
