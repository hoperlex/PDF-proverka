#!/usr/bin/env python3
"""Регресс-гейт: прогнать тесты и упасть ТОЛЬКО на НОВЫХ падениях против baseline.

Зачем (см. reserc.md #104):
    `pytest.ini` исключал `backend/tests`, а `.github/workflows` не было — поэтому
    канонический набор тестов давно подгнил незаметно: ~76 падений + ~33 ошибки
    (устаревшие тесты, frontend-drift, ожидания старых флагов/версий) — это НЕ
    регрессии прода, а долг по тестам. Чинить весь долг — отдельный backlog.

    Этот гейт фиксирует ТЕКУЩИЙ набор падений как baseline
    (`scripts/ci_known_failures.txt`). Любая НОВАЯ поломка от правки ловится сразу,
    а известный долг просто отслеживается (и сокращается по мере починки).

Использование:
    python scripts/ci_regression_gate.py            # check: exit 1 при НОВЫХ падениях
    python scripts/ci_regression_gate.py --record   # записать текущие падения как baseline

ВАЖНО: baseline — общий контракт, а НЕ слепок конкретной машины. Пересоздавать
его в каждом свежем окружении нельзя: так локальное состояние закрепляется как
норма, и гейт перестаёт ловить регрессии.

Правило: окружение приводится к контракту CI, а необязательные наборы данных
объявляются optional в самих тестах — модуль, которому нужен внешний корпус,
обязан давать `skip` с причиной, а не ошибку сбора (иначе отсутствие данных
рушит прогон целиком; см. `tests/test_structural_geometry.py`,
`tests/test_technology_geometry.py`, `tests/test_alia_scheme_geometry.py`).

`--record` применяется только осознанно — когда меняется сам контракт набора
тестов, и полученный baseline коммитится с обоснованием. Расхождение из-за
отсутствующего optional-датасета чинится тестом, а не перезаписью baseline.

Baseline обязан описывать сам себя: заголовок объявляет `# Кол-во: N`, и это
число сверяется с фактическим списком ДО прогона (см. `load_baseline`).
Расхождение — отказ, а не предупреждение: сравнивать прогон с эталоном,
который врёт о собственном содержимом, бессмысленно. Приём тот же, что у
`fileset_sha256` в release-manifest (`scripts/deploy_center_release.py`).
"""
from __future__ import annotations

import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "scripts" / "ci_known_failures.txt"
JUNIT = ROOT / ".ci_last_report.xml"
TEST_PATHS = ["tests", "backend/tests"]
# Заголовок baseline обязан описывать сам себя: строка `# Кол-во: N` сверяется
# с числом фактических записей при каждой загрузке (см. load_baseline).
_DECLARED_COUNT_RE = re.compile(r"^#\s*Кол-во:\s*(\d+)\s*$")


def run_pytest() -> None:
    # Старый отчёт удаляется ДО запуска. Иначе ранняя смерть pytest (обрыв сбора,
    # internal error, ошибка аргументов) оставляет отчёт прошлого прогона, и гейт
    # разбирает его как свежий — сравнение молча уезжает на устаревшие данные.
    JUNIT.unlink(missing_ok=True)
    cmd = [
        sys.executable, "-m", "pytest", *TEST_PATHS,
        "--junitxml", str(JUNIT),
        "-q", "-p", "no:cacheprovider", "--tb=no", "--no-header",
    ]
    code = subprocess.run(cmd, cwd=str(ROOT)).returncode
    # Пригодны для сравнения с baseline только 0 (всё прошло) и 1 (есть падения).
    # 2 — прогон прерван (в т.ч. обрыв сбора), 3 — внутренняя ошибка pytest,
    # 4 — ошибка аргументов, 5 — не собрано ни одного теста.
    #
    # Раньше код возврата игнорировался, и это дало ложный вердикт: прерванный
    # сбор (код 2) оставлял junit с одними ошибками сбора, гейт считал его
    # полноценным прогоном и докладывал «2 новых падения» вместо «прогон
    # непригоден». 78 реальных падений при этом не были видны вовсе.
    if code not in (0, 1):
        raise SystemExit(
            f"[gate] FATAL: pytest завершился с кодом {code} — прогон непригоден "
            f"для сравнения с baseline (допустимы 0 и 1)"
        )


def collect_outcomes() -> tuple[set[str], set[str], set[str]]:
    """Вернуть (упавшие, пропущенные, все встреченные в прогоне).

    Одного множества падений недостаточно. Раньше «стало зелёных» считалось как
    `baseline - падения`, и туда попадало всё, что просто ПЕРЕСТАЛО ПАДАТЬ:
    удалённые и переименованные тесты, отфильтрованные маркером (`-m "not chaos"`)
    и — что опаснее — ставшие `skip`. Гейт советовал убрать их из baseline со
    словами «теперь ПРОХОДЯТ», хотя проверка могла вообще исчезнуть.

    Разница существенна: пропущенный тест ничего не доказывает, и вычёркивать
    его из известного долга как починенный — значит терять сам долг.
    """
    if not JUNIT.exists():
        raise SystemExit("[gate] FATAL: junit-отчёт не создан — pytest упал на сборе тестов")
    tree = ET.parse(JUNIT)
    failed: set[str] = set()
    skipped: set[str] = set()
    seen: set[str] = set()
    for tc in tree.iter("testcase"):
        tid = f"{tc.get('classname', '')}::{tc.get('name', '')}"
        seen.add(tid)
        tags = {child.tag for child in tc}
        if tags & {"failure", "error"}:
            failed.add(tid)
        elif "skipped" in tags:
            skipped.add(tid)
    return failed, skipped, seen


def load_baseline() -> set[str]:
    """Прочитать baseline и СВЕРИТЬ его с собственным заголовком.

    Заголовок объявляет `# Кол-во: N`, а список ниже правят руками (тест
    починили — строку убрали, добавился долг — дописали), и заявленный
    счётчик разъезжается с содержимым. Baseline — эталон сравнения: если он
    врёт о себе, гейт молча меряет прогон по неизвестно какому списку.

    Приём тот же, что у `fileset_sha256` в release-manifest
    (`scripts/deploy_center_release.py`): отпечаток не берётся на веру, а
    пересчитывается по фактическому дереву; расхождение — отказ, отсутствие
    отпечатка — предупреждение (у старых файлов его просто нет, отказывать
    из-за этого нельзя, но и молчать не следует).
    """
    if not BASELINE.exists():
        return set()
    declared: int | None = None
    entries: set[str] = set()
    for line in BASELINE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            match = _DECLARED_COUNT_RE.match(stripped)
            if match:
                declared = int(match.group(1))
            continue
        entries.add(stripped)
    if declared is None:
        print(
            f"[gate] ВНИМАНИЕ: в заголовке {BASELINE} нет строки "
            f"'# Кол-во: N' — целостность baseline не проверяется",
            file=sys.stderr,
        )
    elif declared != len(entries):
        raise SystemExit(
            f"[gate] FATAL: baseline противоречит сам себе — заголовок "
            f"{BASELINE} заявляет '# Кол-во: {declared}', а фактических "
            f"записей {len(entries)}. Baseline — эталон сравнения, сверка с "
            f"ним при таком расхождении недостоверна. Починить: привести "
            f"счётчик в заголовке к фактическому списку (правка вручную) "
            f"либо осознанно пересобрать baseline "
            f"(`python scripts/ci_regression_gate.py --record`) на окружении, "
            f"удовлетворяющем контракту CI"
        )
    return entries


def write_baseline(failed: set[str]) -> None:
    header = [
        "# Baseline известных падающих тестов (регресс-гейт, reserc.md #104).",
        "# Предсуществующие падения/ошибки на момент уборки 'нет CI'.",
        "# В основном устаревшие тесты / frontend-drift / ожидания старых флагов —",
        "# это НЕ регрессии прода. CI зелёный, если НЕТ новых падений сверх этого списка.",
        "# Baseline принадлежит профилю CI, а не машине разработчика: расхождение из-за",
        "# отсутствующего optional-датасета чинится тестом, а не перезаписью списка.",
        f"# Кол-во: {len(failed)}",
        "",
    ]
    BASELINE.write_text("\n".join(header + sorted(failed)) + "\n", encoding="utf-8")


def main() -> int:
    record = "--record" in sys.argv
    # Целостность baseline проверяется ДО прогона: незачем тратить полный
    # прогон набора, чтобы потом отказаться сравнивать с испорченным эталоном.
    # В режиме --record файл всё равно перезаписывается, читать его не нужно.
    baseline = set() if record else load_baseline()
    run_pytest()
    current, skipped, seen = collect_outcomes()

    if record:
        write_baseline(current)
        print(f"[gate] baseline записан: {len(current)} известных падений -> {BASELINE}")
        return 0

    new = sorted(current - baseline)
    # Три разных исхода для записи baseline, переставшей падать. Смешивать их
    # нельзя: убрать из долга можно только по-настоящему зелёный тест.
    passed_now = seen - current - skipped
    fixed = sorted(baseline & passed_now)
    now_skipped = sorted(baseline & skipped)
    vanished = sorted(baseline - seen)
    print(
        f"[gate] падений сейчас: {len(current)} | baseline: {len(baseline)} | "
        f"новых: {len(new)} | стало зелёных: {len(fixed)} | "
        f"ушло в skip: {len(now_skipped)} | исчезло из прогона: {len(vanished)}"
    )
    if fixed:
        print("[gate] эти baseline-тесты теперь ПРОХОДЯТ (можно убрать из baseline):")
        for t in fixed:
            print(f"    - {t}")
    if now_skipped:
        print(
            "[gate] эти baseline-тесты теперь ПРОПУСКАЮТСЯ — они ничего не "
            "доказывают. Убирать из baseline нельзя: долг не починен, а скрыт:"
        )
        for t in now_skipped:
            print(f"    ~ {t}")
    if vanished:
        print(
            "[gate] этих baseline-тестов НЕТ в прогоне (удалены, переименованы "
            "или отфильтрованы маркером). Убрать из baseline, если удаление "
            "осознанное:"
        )
        for t in vanished:
            print(f"    ? {t}")
    if new:
        print("[gate] НОВЫЕ падения (регрессия — починить или обосновать):")
        for t in new:
            print(f"    + {t}")
        return 1
    print("[gate] OK — новых падений сверх известного baseline нет.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
