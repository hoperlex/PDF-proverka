"""
test_batch_critic_v2.py
------------------------
Tests for batch_critic_v2.py batch runner.

All tests work without touching production artifacts.
Tests use fixtures and synthetic project directories.

Runs with:
    python -m pytest backend/tests/test_batch_critic_v2.py -v
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

# Primary lane §5: network — запускает настоящие дочерние процессы.
pytestmark = pytest.mark.network

# ─── Fixtures ─────────────────────────────────────────────────────────────────

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "findings_review"
BATCH_SCRIPT = Path("backend/scripts/batch_critic_v2.py")


def _make_project(tmp_path: Path, name: str, findings: list[dict],
                  section: str = "EOM", with_blocks: bool = False,
                  with_review: bool = False) -> Path:
    """Create a synthetic project directory with 03_findings.json."""
    project_dir = tmp_path / name
    output_dir = project_dir / "_output"
    output_dir.mkdir(parents=True)

    # project_info.json
    (project_dir / "project_info.json").write_text(
        json.dumps({"name": name, "section": section, "project_id": f"{section}/{name}"},
                   ensure_ascii=False), encoding="utf-8"
    )

    # 03_findings.json
    (output_dir / "03_findings.json").write_text(
        json.dumps({"findings": findings}, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Optional 01_blocks_analysis.json
    if with_blocks:
        block_ids = list({
            b.get("block_id") or b
            for f in findings
            for b in f.get("evidence", [])
            if isinstance(b, dict) and b.get("block_id")
        })
        (output_dir / "01_blocks_analysis.json").write_text(
            json.dumps({
                "block_analyses": [{"block_id": bid} for bid in block_ids],
            }, ensure_ascii=False), encoding="utf-8"
        )

    # Optional legacy 03_findings_review.json
    if with_review:
        reviews = [
            {"finding_id": f["id"], "verdict": "pass", "details": None,
             "suggested_action": None, "correct_page": None, "correct_sheet": None}
            for f in findings
        ]
        (output_dir / "03_findings_review.json").write_text(
            json.dumps({
                "meta": {"project_id": name, "total_reviewed": len(findings), "verdicts": {"pass": len(findings)}},
                "reviews": reviews,
            }, ensure_ascii=False), encoding="utf-8"
        )

    return project_dir


def _good_finding(fid: str) -> dict:
    return {
        "id": fid,
        "severity": "КРИТИЧЕСКОЕ",
        "category": "cable",
        "sheet": "Лист 1",
        "page": 1,
        "problem": f"Кабель {fid} без FR-исполнения — нарушение СП",
        "description": f"На листе 1 кабель {fid} ВВГнг-LS вместо FRLS 4x6",
        "solution": "Заменить на ВВГнг-FRLS 4x6",
        "risk": "Потеря работоспособности при пожаре. Нарушение пожарной безопасности.",
        "norm": "СП 6.13130.2021, п. 4.2",
        "norm_quote": "Кабельные линии систем противопожарной защиты...",
        "evidence": [{"block_id": f"BLK-{fid}-A", "type": "image", "page": 1},
                     {"block_id": f"BLK-{fid}-B", "type": "text", "page": 1}],
        "related_block_ids": [f"BLK-{fid}-A", f"BLK-{fid}-B"],
        "source_block_ids": [f"BLK-{fid}-A"],
    }


def _bad_finding(fid: str) -> dict:
    return {
        "id": fid,
        "severity": "РЕКОМЕНДАТЕЛЬНОЕ",
        "category": "documentation",
        "sheet": "Общие данные",
        "page": 1,
        "problem": "Необходимо проверить соответствие",
        "description": "Требуется уточнить актуальность применяемых норм",
        "solution": "Проверить",
        "risk": None,
        "evidence": [],
        "related_block_ids": [],
        "source_block_ids": [],
    }


# ─── Synthetic projects/ root ────────────────────────────────────────────────
#
# The batch runner used to be pointed at the customer corpus in <repo>/projects,
# which never exists in CI. Everything below builds an equivalent corpus in
# tmp_path so that CLI contract tests check batch LOGIC, not data presence.

# Distinct subjects on purpose: near-identical findings collapse in the dedup
# phase and are reported as `merged`, not `accepted`.
_TOPICS: list[tuple[str, str, str, str, str]] = [
    ("cable",
     "Кабель питания насосной станции выполнен ВВГнг-LS вместо ВВГнг-FRLS",
     "На листе 3 для линии противопожарного насоса применён кабель ВВГнг-LS 4х6, требуется FRLS",
     "Заменить кабель на ВВГнг-FRLS 4х6",
     "СП 6.13130.2021, п. 4.2"),
    ("grounding",
     "Отсутствует система уравнивания потенциалов в электрощитовой",
     "На листе 5 в помещении электрощитовой не показана основная система уравнивания потенциалов",
     "Предусмотреть ОСУП с подключением к ГЗШ",
     "СП 256.1325800.2016, п. 8.3"),
    ("lighting",
     "Аварийное освещение эвакуационных путей не запитано отдельной линией",
     "На листе 7 светильники эвакуационного освещения подключены к общей групповой линии",
     "Выделить отдельную группу аварийного освещения от панели ЩАО",
     "СП 52.13330.2016, п. 7.6"),
    ("switchboard",
     "Не указан тип вводного автоматического выключателя ВРУ",
     "На листе 2 в однолинейной схеме ВРУ у вводного аппарата отсутствует номинал и характеристика",
     "Указать тип, номинальный ток и отключающую способность вводного аппарата",
     "ГОСТ 32396-2013, п. 5.1"),
]


def _topic_finding(fid: str, topic: int) -> dict:
    """Finding with valid evidence on a distinct subject → deterministic accept."""
    category, problem, description, solution, norm = _TOPICS[topic % len(_TOPICS)]
    return {
        "id": fid,
        "severity": "КРИТИЧЕСКОЕ",
        "category": category,
        "sheet": f"Лист {topic + 1}",
        "page": topic + 1,
        "problem": problem,
        "description": description,
        "solution": solution,
        "risk": "Нарушение требований пожарной и электробезопасности при эксплуатации здания.",
        "norm": norm,
        "norm_quote": "Цитата пункта нормы для трассировки evidence...",
        "evidence": [{"block_id": f"BLK-{fid}-A", "type": "image", "page": topic + 1},
                     {"block_id": f"BLK-{fid}-B", "type": "text", "page": topic + 1}],
        "related_block_ids": [f"BLK-{fid}-A", f"BLK-{fid}-B"],
        "source_block_ids": [f"BLK-{fid}-A"],
    }


# Reproducible per-project mix: 4 accepted + 1 rejected (no_evidence).
CORPUS_TOTAL = 5
CORPUS_ACCEPTED = 4
CORPUS_REJECTED = 1


def _corpus_findings() -> list[dict]:
    findings = [_topic_finding(f"F-{i:03d}", i) for i in range(CORPUS_ACCEPTED)]
    findings.append(_bad_finding("F-900"))
    return findings


def _make_synthetic_root(tmp_path: Path) -> Path:
    """
    Build a synthetic projects/ root: 3 EOM projects + 1 AR project.

    Every project holds the same reproducible corpus (see _corpus_findings),
    a legacy 03_findings_review.json where every finding has verdict `pass`
    and a 01_blocks_analysis.json listing every evidence block.
    """
    root = tmp_path / "projects"
    for name in ("EOM-P1", "EOM-P2", "EOM-P3"):
        _make_project(root / "EOM", name, _corpus_findings(), section="EOM",
                      with_blocks=True, with_review=True)
    _make_project(root / "AR", "AR-P1", _corpus_findings(), section="AR",
                  with_blocks=True, with_review=True)
    return root


def _snapshot_tree(root: Path) -> dict[str, str]:
    return {
        str(p): p.read_text(encoding="utf-8")
        for p in sorted(root.rglob("*.json"))
    }


# ─── Import tests ─────────────────────────────────────────────────────────────

class TestBatchImports:
    def test_batch_script_imports(self):
        """batch_critic_v2.py must be importable without error."""
        import importlib.util
        spec = importlib.util.spec_from_file_location("batch_critic_v2", BATCH_SCRIPT)
        assert spec is not None
        mod = importlib.util.module_from_spec(spec)
        # Just verify it loads without ImportError
        spec.loader.exec_module(mod)
        assert hasattr(mod, "run_one_project")
        assert hasattr(mod, "discover_projects")
        assert hasattr(mod, "build_summary")
        assert hasattr(mod, "compare_with_legacy")


# ─── Project discovery ────────────────────────────────────────────────────────

class TestDiscoverProjects:
    # NOTE: `test_discovers_real_projects` and `test_section_filter` used to assert
    # that the customer corpus in <repo>/projects is present on disk. That corpus is
    # gitignored production data and never exists in CI, so both were removed.
    # Discovery LOGIC below is checked on a synthetic root instead.

    def _load_batch(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("batch_critic_v2", BATCH_SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_discovers_projects_under_given_root(self, tmp_path):
        mod = self._load_batch()
        root = _make_synthetic_root(tmp_path)
        projects = mod.discover_projects(projects_root=root)
        assert sorted(p.name for p in projects) == ["AR-P1", "EOM-P1", "EOM-P2", "EOM-P3"]

    def test_section_filter_keeps_only_matching_section(self, tmp_path):
        mod = self._load_batch()
        root = _make_synthetic_root(tmp_path)
        projects = mod.discover_projects(section="EOM", limit=10, projects_root=root)
        assert sorted(p.name for p in projects) == ["EOM-P1", "EOM-P2", "EOM-P3"]

    def test_limit_caps_discovery(self, tmp_path):
        mod = self._load_batch()
        root = _make_synthetic_root(tmp_path)
        projects = mod.discover_projects(section="EOM", limit=2, projects_root=root)
        assert len(projects) == 2

    def test_empty_result_for_nonexistent_section(self, tmp_path):
        mod = self._load_batch()
        root = _make_synthetic_root(tmp_path)
        projects = mod.discover_projects(section="XYZNONEXISTENT", projects_root=root)
        assert projects == []

    def test_default_root_is_repo_projects_dir(self):
        """Production default must stay <repo>/projects — the flag only overrides it."""
        mod = self._load_batch()
        assert mod.PROJECTS_ROOT.name == "projects"
        assert mod.PROJECTS_ROOT.parent == Path(__file__).resolve().parent.parent.parent


# ─── run_one_project ──────────────────────────────────────────────────────────

class TestRunOneProject:
    def _load_batch(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("batch_critic_v2", BATCH_SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_good_project_runs_successfully(self, tmp_path):
        mod = self._load_batch()
        project_dir = _make_project(
            tmp_path, "TEST-GOOD",
            [_good_finding(f"F-{i:03d}") for i in range(5)],
        )
        result = mod.run_one_project(project_dir, tmp_path / "out")
        assert not result.get("skipped")
        assert result["total_findings"] == 5
        assert isinstance(result["accepted"], int)
        assert isinstance(result["rejected"], int)

    def test_bad_project_rejects_mostly(self, tmp_path):
        mod = self._load_batch()
        project_dir = _make_project(
            tmp_path, "TEST-BAD",
            [_bad_finding(f"F-{i:03d}") for i in range(5)],
        )
        result = mod.run_one_project(project_dir, tmp_path / "out")
        assert not result.get("skipped")
        assert result["rejected"] >= 3  # mostly bad findings get rejected

    def test_missing_findings_returns_skipped(self, tmp_path):
        mod = self._load_batch()
        project_dir = tmp_path / "EMPTY-PROJECT"
        project_dir.mkdir()
        (project_dir / "_output").mkdir()
        result = mod.run_one_project(project_dir, tmp_path / "out")
        assert result["skipped"] is True
        assert result.get("error") is not None

    def test_artifacts_created(self, tmp_path):
        mod = self._load_batch()
        project_dir = _make_project(
            tmp_path, "TEST-ART",
            [_good_finding("F-001"), _good_finding("F-002")],
        )
        out_dir = tmp_path / "out"
        result = mod.run_one_project(project_dir, out_dir)
        assert not result.get("skipped")
        proj_out = Path(result["output_dir"])
        assert (proj_out / "critic_v2_decisions.json").exists()
        assert (proj_out / "critic_v2_metrics.json").exists()
        assert (proj_out / "critic_v2_accepted.json").exists()
        assert (proj_out / "critic_v2_rejected.json").exists()

    def test_production_artifacts_not_modified(self, tmp_path):
        """Production 03_findings.json and 03_findings_review.json must be untouched."""
        mod = self._load_batch()
        findings = [_good_finding("F-001"), _bad_finding("F-002")]
        project_dir = _make_project(tmp_path, "TEST-PROD", findings, with_review=True)

        original_findings = (project_dir / "_output" / "03_findings.json").read_text(encoding="utf-8")
        original_review = (project_dir / "_output" / "03_findings_review.json").read_text(encoding="utf-8")

        mod.run_one_project(project_dir, tmp_path / "out")

        # Production files must be IDENTICAL after batch run
        assert (project_dir / "_output" / "03_findings.json").read_text(encoding="utf-8") == original_findings
        assert (project_dir / "_output" / "03_findings_review.json").read_text(encoding="utf-8") == original_review

    def test_with_blocks_index(self, tmp_path):
        mod = self._load_batch()
        project_dir = _make_project(
            tmp_path, "TEST-BLOCKS",
            [_good_finding("F-001"), _good_finding("F-002")],
            with_blocks=True,
        )
        result = mod.run_one_project(project_dir, tmp_path / "out", with_blocks=True)
        assert not result.get("skipped")
        assert result["blocks_index_used"] is True

    def test_with_llm_gate_mock(self, tmp_path):
        mod = self._load_batch()
        project_dir = _make_project(
            tmp_path, "TEST-LLM",
            [_good_finding("F-001"), _good_finding("F-002"), _bad_finding("F-003")],
        )
        out_dir = tmp_path / "out"
        result = mod.run_one_project(
            project_dir, out_dir,
            llm_gate=True, llm_provider="mock",
        )
        assert not result.get("skipped")
        assert result["llm_gate_used"] is True
        # LLM-specific artifacts must exist
        proj_out = Path(result["output_dir"])
        assert (proj_out / "critic_v2_llm_decisions.json").exists()
        assert (proj_out / "critic_v2_final_decisions.json").exists()
        assert (proj_out / "critic_v2_borderline.json").exists()


# ─── Legacy comparison ────────────────────────────────────────────────────────

class TestLegacyComparison:
    def _load_batch(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("batch_critic_v2", BATCH_SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_compare_with_legacy_all_pass(self, tmp_path):
        mod = self._load_batch()
        findings = [_good_finding(f"F-{i:03d}") for i in range(4)]
        project_dir = _make_project(tmp_path, "LEGACY-TEST", findings, with_review=True)
        result = mod.run_one_project(
            project_dir, tmp_path / "out", compare_legacy=True
        )
        assert not result.get("skipped")
        cmp = result.get("comparison")
        assert cmp is not None
        assert cmp["total_compared"] > 0

    def test_compare_artifact_created(self, tmp_path):
        mod = self._load_batch()
        findings = [_good_finding("F-001"), _bad_finding("F-002")]
        project_dir = _make_project(tmp_path, "LEGACY-ART", findings, with_review=True)
        result = mod.run_one_project(
            project_dir, tmp_path / "out", compare_legacy=True
        )
        proj_out = Path(result["output_dir"])
        assert (proj_out / "critic_v2_legacy_comparison.json").exists()

    def test_no_legacy_skips_comparison(self, tmp_path):
        mod = self._load_batch()
        project_dir = _make_project(tmp_path, "NO-LEGACY", [_good_finding("F-001")])
        result = mod.run_one_project(
            project_dir, tmp_path / "out", compare_legacy=True
        )
        # comparison should be None when no legacy review exists
        assert result.get("comparison") is None

    def test_compare_structure(self):
        mod = self._load_batch()
        from backend.app.pipeline.stages.findings_review.critic_v2 import (
            run_critic_v2_offline, QualityDecision, EVIDENCE_VALID
        )
        findings = [_good_finding(f"F-{i:03d}") for i in range(3)]
        det = run_critic_v2_offline(findings)
        legacy_review = {
            "reviews": [
                {"finding_id": f["id"], "verdict": "pass"} for f in findings
            ]
        }
        comparison = mod.compare_with_legacy(det.decisions, legacy_review)
        assert "total_compared" in comparison
        assert "agreement" in comparison
        assert "rows" in comparison
        assert isinstance(comparison["rows"], list)


# ─── build_summary ────────────────────────────────────────────────────────────

class TestBuildSummary:
    def _load_batch(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("batch_critic_v2", BATCH_SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_summary_totals(self, tmp_path):
        mod = self._load_batch()
        results = [
            {
                "project": "P1", "section": "EOM",
                "total_findings": 10, "accepted": 7, "borderline": 2,
                "rejected": 1, "merged": 0, "rejected_by_rules": 1, "rejected_by_score": 0,
                "rejection_reasons": {"no_evidence": 1},
                "average_usefulness_score": 7.5,
                "evidence_breakdown": {"valid": 8, "partial": 1, "weak": 0, "none": 1},
                "blocks_index_used": False, "llm_gate_used": False,
                "llm_candidates_sent": 0, "det_ms": 10, "llm_ms": 0,
                "output_dir": str(tmp_path), "comparison": None, "skipped": False, "error": None,
            },
            {
                "project": "P2", "section": "EOM",
                "total_findings": 5, "accepted": 3, "borderline": 1,
                "rejected": 1, "merged": 0, "rejected_by_rules": 1, "rejected_by_score": 0,
                "rejection_reasons": {"ocr_artifact": 1},
                "average_usefulness_score": 8.0,
                "evidence_breakdown": {"valid": 4, "partial": 0, "weak": 1, "none": 0},
                "blocks_index_used": False, "llm_gate_used": False,
                "llm_candidates_sent": 0, "det_ms": 5, "llm_ms": 0,
                "output_dir": str(tmp_path), "comparison": None, "skipped": False, "error": None,
            },
        ]
        summary = mod.build_summary(results, tmp_path, compare_legacy=False)
        assert summary["totals"]["total_findings"] == 15
        assert summary["totals"]["accepted"] == 10
        assert summary["totals"]["rejected"] == 2
        assert "EOM" in summary["by_section"]

    def test_skipped_excluded_from_totals(self, tmp_path):
        mod = self._load_batch()
        results = [
            {
                "project": "P1", "section": "EOM",
                "total_findings": 10, "accepted": 7, "borderline": 2, "rejected": 1,
                "merged": 0, "rejected_by_rules": 1, "rejected_by_score": 0,
                "rejection_reasons": {}, "average_usefulness_score": 7.5,
                "evidence_breakdown": {"valid": 8, "partial": 1, "weak": 0, "none": 1},
                "blocks_index_used": False, "llm_gate_used": False,
                "llm_candidates_sent": 0, "det_ms": 10, "llm_ms": 0,
                "output_dir": str(tmp_path), "comparison": None, "skipped": False, "error": None,
            },
            {
                "project": "SKIP", "skipped": True, "error": "missing file",
                "section": "EOM",
            },
        ]
        summary = mod.build_summary(results, tmp_path, compare_legacy=False)
        assert summary["totals"]["total_findings"] == 10
        assert len(summary["skipped"]) == 1

    def test_summary_saved(self, tmp_path):
        mod = self._load_batch()
        results = []
        summary = mod.build_summary(results, tmp_path, compare_legacy=False)
        assert "totals" in summary
        assert "by_section" in summary
        assert "per_project" in summary


# ─── CLI integration ─────────────────────────────────────────────────────────

class TestCLIBatch:
    """
    CLI contract on a synthetic projects root (--projects-root).

    These tests used to point the CLI at the customer corpus in <repo>/projects.
    That corpus is gitignored and absent in CI, so the runner exited with rc=1 and
    no artifact was produced. The corpus is now built in tmp_path, which makes the
    checks stronger: exact counts are known up front.
    """

    def _run(self, root: Path, out_dir: Path, *extra: str):
        return subprocess.run(
            [
                sys.executable, str(BATCH_SCRIPT),
                "--projects-root", str(root),
                "--output-dir", str(out_dir),
                "--quiet",
                *extra,
            ],
            capture_output=True, text=True, timeout=60,
        )

    def test_cli_section_eom_limit_3(self, tmp_path):
        """CLI must run on exactly 3 EOM projects and ignore other sections."""
        root = _make_synthetic_root(tmp_path)
        out_dir = tmp_path / "out"
        result = self._run(root, out_dir, "--section", "EOM", "--limit", "3")
        assert result.returncode == 0, (
            f"CLI failed (rc={result.returncode}):\n{result.stdout}\n{result.stderr}"
        )
        assert (out_dir / "batch_summary.json").exists()
        assert (out_dir / "batch_results.json").exists()

        results = json.loads((out_dir / "batch_results.json").read_text(encoding="utf-8"))
        assert sorted(r["project"] for r in results) == ["EOM-P1", "EOM-P2", "EOM-P3"]
        assert all(r["section"] == "EOM" for r in results)

    def test_cli_summary_structure(self, tmp_path):
        """batch_summary.json must have expected keys and correct totals."""
        root = _make_synthetic_root(tmp_path)
        out_dir = tmp_path / "out"
        result = self._run(root, out_dir, "--section", "EOM", "--limit", "2")
        assert result.returncode == 0, result.stderr

        summary = json.loads((out_dir / "batch_summary.json").read_text(encoding="utf-8"))
        assert "totals" in summary
        assert "by_section" in summary
        assert "rejection_reasons" in summary
        assert "per_project" in summary
        assert "evidence_breakdown" in summary
        assert "run_config" in summary

        assert summary["run_config"]["projects_processed"] == 2
        assert summary["totals"]["total_findings"] == 2 * CORPUS_TOTAL
        assert summary["totals"]["accepted"] == 2 * CORPUS_ACCEPTED
        assert summary["totals"]["rejected"] == 2 * CORPUS_REJECTED
        assert summary["rejection_reasons"]["no_evidence"] == 2 * CORPUS_REJECTED
        assert list(summary["by_section"]) == ["EOM"]
        assert summary["by_section"]["EOM"]["projects"] == 2

    def test_cli_per_project_artifacts(self, tmp_path):
        """Each processed project must have its own artifact directory."""
        root = _make_synthetic_root(tmp_path)
        out_dir = tmp_path / "out"
        result = self._run(root, out_dir, "--section", "EOM", "--limit", "2")
        assert result.returncode == 0, result.stderr

        results = json.loads((out_dir / "batch_results.json").read_text(encoding="utf-8"))
        assert len(results) == 2
        seen = set()
        for r in results:
            proj_dir = Path(r["output_dir"])
            assert proj_dir.exists()
            assert proj_dir not in seen, "per-project artifact dirs must not collide"
            seen.add(proj_dir)
            assert (proj_dir / "critic_v2_decisions.json").exists()
            assert (proj_dir / "critic_v2_metrics.json").exists()
            assert (proj_dir / "critic_v2_accepted.json").exists()
            decisions = json.loads((proj_dir / "critic_v2_decisions.json").read_text(encoding="utf-8"))
            assert len(decisions) == CORPUS_TOTAL

    def test_cli_production_not_modified(self, tmp_path):
        """Source project files must NOT be modified after a batch run."""
        root = _make_synthetic_root(tmp_path)
        out_dir = tmp_path / "out"
        before = _snapshot_tree(root)
        assert before, "synthetic corpus must contain project files to compare"

        result = self._run(root, out_dir, "--section", "EOM", "--limit", "3")
        assert result.returncode == 0, result.stderr

        after = _snapshot_tree(root)
        assert after == before, "batch run must not touch project source files"

    def test_cli_with_llm_gate_mock(self, tmp_path):
        """CLI with --llm-gate --llm-provider mock must work and create LLM artifacts."""
        root = _make_synthetic_root(tmp_path)
        out_dir = tmp_path / "out"
        result = self._run(
            root, out_dir, "--section", "EOM", "--limit", "2",
            "--llm-gate", "--llm-provider", "mock",
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"

        summary = json.loads((out_dir / "batch_summary.json").read_text(encoding="utf-8"))
        assert summary["run_config"]["llm_gate_used"] is True
        assert summary["run_config"]["llm_provider"] == "mock"

        results = json.loads((out_dir / "batch_results.json").read_text(encoding="utf-8"))
        assert len(results) == 2
        for r in results:
            assert r["llm_gate_used"] is True
            proj_dir = Path(r["output_dir"])
            assert (proj_dir / "critic_v2_final_decisions.json").exists()
            assert (proj_dir / "critic_v2_llm_decisions.json").exists()
            assert (proj_dir / "critic_v2_borderline.json").exists()
            # Only findings with evidence may be sent to the gate.
            llm_decisions = json.loads(
                (proj_dir / "critic_v2_llm_decisions.json").read_text(encoding="utf-8")
            )
            assert "F-900" not in {d["finding_id"] for d in llm_decisions}

    def test_cli_compare_legacy(self, tmp_path):
        """CLI --compare-legacy must produce comparison artifacts."""
        root = _make_synthetic_root(tmp_path)
        out_dir = tmp_path / "out"
        result = self._run(root, out_dir, "--section", "EOM", "--limit", "2", "--compare-legacy")
        assert result.returncode == 0, f"CLI failed: {result.stderr}"

        results = json.loads((out_dir / "batch_results.json").read_text(encoding="utf-8"))
        with_cmp = [r for r in results if r.get("comparison")]
        assert len(with_cmp) == 2
        for r in with_cmp:
            cmp = r["comparison"]
            # legacy marks every finding `pass`; v2 accepts 4 and rejects the
            # evidence-less one → 4 agreements + 1 "v2 stricter"
            assert cmp["total_compared"] == CORPUS_TOTAL
            assert cmp["agreement"] == CORPUS_ACCEPTED
            assert cmp["disagree_v2_stricter"] == CORPUS_REJECTED
            assert cmp["disagree_v2_looser"] == 0
            assert (Path(r["output_dir"]) / "critic_v2_legacy_comparison.json").exists()

    def test_cli_with_blocks(self, tmp_path):
        """CLI --with-blocks must enable blocks_index per project."""
        root = _make_synthetic_root(tmp_path)
        out_dir = tmp_path / "out"
        result = self._run(root, out_dir, "--section", "EOM", "--limit", "2", "--with-blocks")
        assert result.returncode == 0, result.stderr

        results = json.loads((out_dir / "batch_results.json").read_text(encoding="utf-8"))
        assert len(results) == 2
        assert all(r["blocks_index_used"] for r in results)
        for r in results:
            metrics = json.loads(
                (Path(r["output_dir"]) / "critic_v2_metrics.json").read_text(encoding="utf-8")
            )
            assert metrics["blocks_index_used"] is True
            assert metrics["blocks_count"] > 0

    def test_cli_without_blocks_flag_leaves_index_unused(self, tmp_path):
        """Default run must NOT load the blocks index even when the file exists."""
        root = _make_synthetic_root(tmp_path)
        out_dir = tmp_path / "out"
        result = self._run(root, out_dir, "--section", "EOM", "--limit", "1")
        assert result.returncode == 0, result.stderr
        results = json.loads((out_dir / "batch_results.json").read_text(encoding="utf-8"))
        assert all(not r["blocks_index_used"] for r in results)

    def test_cli_no_accept_in_zero_evidence_batch(self, tmp_path):
        """No accepted finding may have evidence_quality=none; evidence-less one is rejected."""
        root = _make_synthetic_root(tmp_path)
        out_dir = tmp_path / "out"
        result = self._run(root, out_dir, "--section", "EOM", "--limit", "3")
        assert result.returncode == 0, result.stderr

        results = json.loads((out_dir / "batch_results.json").read_text(encoding="utf-8"))
        assert len(results) == 3
        total_accepted = 0
        for r in results:
            proj_dir = Path(r["output_dir"])
            decisions = json.loads((proj_dir / "critic_v2_decisions.json").read_text())
            by_id = {d["finding_id"]: d for d in decisions}
            for d in decisions:
                if d["decision"] == "accept":
                    total_accepted += 1
                    assert d["evidence_quality"] != "none", (
                        f"Accepted finding {d['finding_id']} has evidence_quality=none "
                        f"in project {r['project']}"
                    )
            # the evidence-less finding must be rejected, with the reason recorded
            assert by_id["F-900"]["decision"] == "reject"
            assert by_id["F-900"]["reject_reason"] == "no_evidence"
        # the check above is worthless if nothing was accepted at all
        assert total_accepted == 3 * CORPUS_ACCEPTED

    def test_cli_invalid_section_exits_1(self, tmp_path):
        """Invalid section must cause exit code 1 even when the root has projects."""
        root = _make_synthetic_root(tmp_path)
        result = subprocess.run(
            [
                sys.executable, str(BATCH_SCRIPT),
                "--projects-root", str(root),
                "--section", "DOESNOTEXIST999",
                "--output-dir", str(tmp_path / "out"),
            ],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 1

    def test_cli_default_root_used_when_flag_omitted(self, tmp_path):
        """Without --projects-root the CLI must still look into <repo>/projects."""
        result = subprocess.run(
            [
                sys.executable, str(BATCH_SCRIPT),
                "--section", "DOESNOTEXIST999",
                "--output-dir", str(tmp_path / "out"),
            ],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 1
        repo_projects = Path(__file__).resolve().parent.parent.parent / "projects"
        assert str(repo_projects) in result.stderr
