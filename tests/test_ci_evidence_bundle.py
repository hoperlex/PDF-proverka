"""Манифест первички обязан ловить подмену артефактов, а не просто существовать.

Проверяется ровно то, ради чего инструмент заведён (ревью среза 0.0.03): числа
приёмки должны быть независимо пересчитываемы. Значит манифест обязан замечать
изменённый, пропавший и лишний файл — иначе он украшение, а не свидетельство.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

# Primary lane §5: временные файлы и сверка схемы манифеста, без сети и процессов.
pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parent.parent


def _module():
    path = ROOT / "scripts" / "ci_evidence_bundle.py"
    spec = importlib.util.spec_from_file_location("ci_evidence_bundle_under_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def run_dir(tmp_path):
    d = tmp_path / "reports"
    (d / "nested").mkdir(parents=True)
    (d / "lane.unit.json").write_text(json.dumps({
        "exit_code": 1, "probe_mode": "ci", "report_status": "ok",
        "selected": 10, "passed": 8, "failed": 2, "errors": 0, "skipped": 0,
        "source_commit": "a" * 40, "source_commit_origin": "QR_SOURCE_COMMIT",
    }), encoding="utf-8")
    (d / "lane.unit.xml").write_text("<testsuite/>", encoding="utf-8")
    (d / "nested" / "gate.log").write_text("[gate] OK\n", encoding="utf-8")
    return d


def test_manifest_records_every_file_with_its_own_checksum(run_dir):
    m = _module().build_manifest(run_dir, label="проверка")
    assert m["file_count"] == 3
    paths = {f["path"] for f in m["files"]}
    assert paths == {"lane.unit.json", "lane.unit.xml", "nested/gate.log"}
    assert all(len(f["sha256"]) == 64 for f in m["files"])
    assert len(m["tree_sha256"]) == 64


def test_provenance_is_read_from_lane_receipts_not_retyped(run_dir):
    m = _module().build_manifest(run_dir)
    assert m["lanes"]["unit"]["source_commit"] == "a" * 40
    assert m["lanes"]["unit"]["source_commit_origin"] == "QR_SOURCE_COMMIT"
    assert m["lanes"]["unit"]["selected"] == 10


def test_unreadable_receipt_is_named_not_skipped(run_dir):
    (run_dir / "lane.broken.json").write_text("{не json", encoding="utf-8")
    m = _module().build_manifest(run_dir)
    assert "receipt_unreadable" in m["lanes"]["broken"]


def test_empty_run_dir_is_refused(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ValueError):
        _module().build_manifest(empty)


def test_missing_run_dir_is_refused(tmp_path):
    with pytest.raises(FileNotFoundError):
        _module().build_manifest(tmp_path / "нет-такого")


def test_verify_passes_on_untouched_tree(run_dir, tmp_path):
    mod = _module()
    manifest = tmp_path / "MANIFEST.json"
    manifest.write_text(json.dumps(mod.build_manifest(run_dir)), encoding="utf-8")
    assert mod.verify(manifest)["ok"] is True


@pytest.mark.parametrize("mutate,key", [
    (lambda d: (d / "lane.unit.xml").write_text("<testsuite tests='999'/>", encoding="utf-8"), "changed"),
    (lambda d: (d / "lane.unit.xml").unlink(), "missing"),
    (lambda d: (d / "лишний.log").write_text("подброшено", encoding="utf-8"), "extra"),
])
def test_verify_catches_substitution(run_dir, tmp_path, mutate, key):
    mod = _module()
    manifest = tmp_path / "MANIFEST.json"
    manifest.write_text(json.dumps(mod.build_manifest(run_dir)), encoding="utf-8")
    mutate(run_dir)
    report = mod.verify(manifest)
    assert report["ok"] is False
    assert report[key], f"подмена типа {key} не замечена"


def test_archive_is_deterministic(run_dir, tmp_path):
    mod = _module()
    first = mod.build_manifest(run_dir, archive=tmp_path / "a.tar.gz")["archive"]["sha256"]
    second = mod.build_manifest(run_dir, archive=tmp_path / "b.tar.gz")["archive"]["sha256"]
    assert first == second, "архив одного дерева обязан давать одну сумму"


def test_tree_digest_rule_is_the_shared_one():
    mod = _module()
    sys.path.insert(0, str(ROOT / "scripts"))
    import ci_runtime_probe as probe
    assert mod.tree_digest is probe._norm_artifact_digest, (
        "правило суммы дерева обязано быть общим: вторая реализация разойдётся молча"
    )
