#!/usr/bin/env python3
"""Манифест первички приёмочного прогона: SHA-256 каждого артефакта и всего дерева.

Зачем:
    Ревью среза 0.0.03 поймало ровно эту дыру: числа приёмки («2658 отобрано»,
    «865/859», «35 = 35») существовали только внутри расписки. Они внутренне
    согласованы, но независимо не пересчитываются: первичные JUnit, lane receipt
    и логи лежат вне репозитория и живут ровно до следующего `rm -rf`. Расписка,
    которая ссылается на исчезнувшие артефакты, доказывает не больше, чем
    расписка без ссылок.

    Этот инструмент делает первичку проверяемой: он не пересказывает её, а
    фиксирует контрольные суммы. Манифест мал, коммитится в git и позволяет
    позже ответить на единственный важный вопрос — «те же самые это артефакты
    или уже другие».

Почему правило контрольной суммы дерева импортируется, а не написано здесь:
    оно живёт в `ci_runtime_probe._norm_artifact_digest` и уже применяется к
    корпусу норм. Две реализации «суммы дерева» расходятся молча, и тогда
    совпадение перестаёт что-либо значить. Здесь то же правило: относительный
    путь плюс содержимое каждого файла, порядок детерминированный.

Интерфейс:

    python scripts/ci_evidence_bundle.py --run-dir DIR [--out FILE]
                                         [--archive FILE] [--label TEXT] [--json]
    python scripts/ci_evidence_bundle.py --verify MANIFEST [--run-dir DIR]

    --run-dir  каталог первички приёмочного прогона
    --out      куда записать манифест (по умолчанию — только на stdout)
    --archive  дополнительно собрать ДЕТЕРМИНИРОВАННЫЙ tar.gz всего каталога и
               записать его SHA-256 в манифест; сам архив в git не кладётся —
               он тяжёлый, его место рядом с прогоном
    --verify   пересчитать суммы и сравнить с манифестом

Коды возврата — те же, что у остальных инструментов полосы:
    0 — манифест собран (или проверка сошлась);
    1 — проверка не сошлась либо каталог непригоден;
    2 — ошибка употребления.

Наружу не ходит: только чтение каталога и запись манифеста/архива.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import sys
import tarfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import ci_runtime_probe as probe  # noqa: E402

#: Одно правило суммы дерева на весь проект (см. шапку).
tree_digest = probe._norm_artifact_digest

MANIFEST_VERSION = "1"
EXIT_OK = 0
EXIT_MISMATCH = 1
EXIT_USAGE = 2

#: Имена, по которым узнаются расписки полос: из них берётся provenance прогона.
#: Провенанс не переписывается руками — §8 требует его в самих расписках, и
#: манифест обязан отражать то, что там записано, а не то, что помнит человек.
LANE_RECEIPT_SUFFIX = ".json"
LANE_RECEIPT_PREFIX = "lane."


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collect_files(run_dir: Path) -> list[dict[str, Any]]:
    """Все файлы каталога в детерминированном порядке, с размером и суммой."""
    files = sorted((p for p in run_dir.rglob("*") if p.is_file()),
                   key=lambda p: p.relative_to(run_dir).as_posix())
    return [
        {
            "path": p.relative_to(run_dir).as_posix(),
            "bytes": p.stat().st_size,
            "sha256": _sha256_file(p),
        }
        for p in files
    ]


def lane_provenance(run_dir: Path) -> dict[str, Any]:
    """Provenance и итоги полос — прочитанные из расписок, а не переписанные.

    Если расписки нет или она не читается, это НЕ молчаливый пропуск: полоса
    попадает в манифест с явной пометкой. Отсутствующая расписка — сама по себе
    факт о прогоне.
    """
    lanes: dict[str, Any] = {}
    for path in sorted(run_dir.glob(f"{LANE_RECEIPT_PREFIX}*{LANE_RECEIPT_SUFFIX}")):
        lane = path.stem[len(LANE_RECEIPT_PREFIX):]
        try:
            r = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            lanes[lane] = {"receipt_unreadable": f"{type(exc).__name__}: {exc}"}
            continue
        lanes[lane] = {
            "exit_code": r.get("exit_code"),
            "probe_mode": r.get("probe_mode"),
            "report_status": r.get("report_status"),
            "selected": r.get("selected"),
            "passed": r.get("passed"),
            "failed": r.get("failed"),
            "errors": r.get("errors"),
            "skipped": r.get("skipped"),
            "source_commit": r.get("source_commit"),
            "source_commit_origin": r.get("source_commit_origin"),
        }
    return lanes


def _deterministic_archive(run_dir: Path, target: Path) -> str:
    """tar.gz, побайтово одинаковый при повторной сборке того же дерева.

    Обнуляются владелец, права-«шум» и время: иначе архив одного и того же
    каталога получал бы разную сумму на разных машинах, и записывать её в
    манифест было бы бессмысленно.
    """
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as tar:
        for path in sorted((p for p in run_dir.rglob("*") if p.is_file()),
                           key=lambda p: p.relative_to(run_dir).as_posix()):
            info = tar.gettarinfo(str(path), arcname=path.relative_to(run_dir).as_posix())
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mtime = 0
            info.mode = 0o644
            with path.open("rb") as handle:
                tar.addfile(info, handle)
    payload = raw.getvalue()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as out:
        # filename="" обязателен: без него gzip кладёт в заголовок имя целевого
        # файла (он берёт его у fileobj), и один и тот же каталог, упакованный в
        # a.tar.gz и b.tar.gz, давал бы РАЗНЫЕ суммы. Поймано тестом
        # test_archive_is_deterministic.
        with gzip.GzipFile(filename="", fileobj=out, mode="wb", mtime=0) as gz:
            gz.write(payload)
    return _sha256_file(target)


def _refuse_archive_inside_run_dir(run_dir: Path, archive: Path) -> None:
    """Архив не должен лежать внутри каталога первички.

    Найдено на собственной шкуре: архив приёмки был положен рядом с отчётами, в
    `<run>/evidence.tar.gz`, а следующий прогон начинается с `rm -rf <run>` —
    и снёс единственную копию. Манифест при этом остался, но сверять его стало
    не с чем: контрольные суммы без артефактов доказывают ровно ничего.
    Поэтому это отказ, а не предупреждение.
    """
    try:
        resolved_run = run_dir.resolve()
        resolved_archive = archive.resolve()
    except OSError:  # pragma: no cover — недоступный путь
        return
    if resolved_run == resolved_archive.parent or resolved_run in resolved_archive.parents:
        raise ValueError(
            f"архив {archive} лежит ВНУТРИ каталога первички {run_dir}. Так уже "
            "теряли evidence: прогон, который начинается с очистки этого "
            "каталога, уносит единственную копию вместе с ним. Положите архив "
            "рядом, а не внутрь"
        )


def build_manifest(run_dir: Path, *, label: str = "", archive: Path | None = None) -> dict[str, Any]:
    if not run_dir.is_dir():
        raise FileNotFoundError(f"каталог первички не найден: {run_dir}")
    if archive is not None:
        _refuse_archive_inside_run_dir(run_dir, archive)
    files = collect_files(run_dir)
    if not files:
        raise ValueError(
            f"в {run_dir} нет ни одного файла — пустой bundle не отличим от "
            "потерянной первички, поэтому это отказ, а не пустой манифест"
        )
    manifest: dict[str, Any] = {
        "tool": "ci_evidence_bundle",
        "manifest_version": MANIFEST_VERSION,
        "label": label,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "run_dir": str(run_dir),
        "file_count": len(files),
        "total_bytes": sum(f["bytes"] for f in files),
        "tree_digest_rule": "ci_runtime_probe._norm_artifact_digest (путь + содержимое, детерминированный порядок)",
        "tree_sha256": tree_digest(run_dir),
        "lanes": lane_provenance(run_dir),
        "files": files,
    }
    if archive is not None:
        manifest["archive"] = {
            "path": str(archive),
            "sha256": _deterministic_archive(run_dir, archive),
            "note": "детерминированный tar.gz: владелец, права и время обнулены",
        }
    return manifest


def verify(manifest_path: Path, run_dir: Path | None = None) -> dict[str, Any]:
    """Сверить дерево с манифестом. Расхождение называется поимённо."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    target = run_dir or Path(manifest["run_dir"])
    result: dict[str, Any] = {
        "manifest": str(manifest_path),
        "run_dir": str(target),
        "missing": [],
        "changed": [],
        "extra": [],
        "tree_sha256_expected": manifest.get("tree_sha256"),
        "tree_sha256_actual": None,
    }
    if not target.is_dir():
        result["missing"] = [f["path"] for f in manifest["files"]]
        result["ok"] = False
        result["detail"] = f"каталог {target} отсутствует целиком"
        return result

    actual = {f["path"]: f for f in collect_files(target)}
    for entry in manifest["files"]:
        got = actual.pop(entry["path"], None)
        if got is None:
            result["missing"].append(entry["path"])
        elif got["sha256"] != entry["sha256"]:
            result["changed"].append(entry["path"])
    result["extra"] = sorted(actual)
    result["tree_sha256_actual"] = tree_digest(target)
    result["ok"] = (
        not result["missing"]
        and not result["changed"]
        and not result["extra"]
        and result["tree_sha256_actual"] == result["tree_sha256_expected"]
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--label", default="")
    parser.add_argument("--verify", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.verify:
        report = verify(args.verify, args.run_dir)
        print(json.dumps(report, ensure_ascii=False, indent=2) if args.json
              else _render_verify(report))
        return EXIT_OK if report["ok"] else EXIT_MISMATCH

    if not args.run_dir:
        parser.error("нужен --run-dir (или --verify MANIFEST)")
    try:
        manifest = build_manifest(args.run_dir, label=args.label, archive=args.archive)
    except (FileNotFoundError, ValueError) as exc:
        print(f"[evidence] отказ: {exc}", file=sys.stderr)
        return EXIT_MISMATCH
    payload = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload, encoding="utf-8")
    if args.json or not args.out:
        print(payload, end="")
    else:
        print(f"[evidence] {manifest['file_count']} файлов, "
              f"{manifest['total_bytes']} байт, дерево {manifest['tree_sha256'][:16]}… "
              f"→ {args.out}")
    return EXIT_OK


def _render_verify(report: dict[str, Any]) -> str:
    if report["ok"]:
        return (f"[evidence] сходится: дерево {report['tree_sha256_actual'][:16]}… "
                f"совпадает с манифестом")
    lines = ["[evidence] НЕ сходится с манифестом:"]
    for kind, key in (("отсутствуют", "missing"), ("изменены", "changed"), ("лишние", "extra")):
        if report[key]:
            lines.append(f"  {kind}: {', '.join(report[key][:10])}"
                         + (" …" if len(report[key]) > 10 else ""))
    if report.get("detail"):
        lines.append(f"  {report['detail']}")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
