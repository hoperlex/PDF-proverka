import json,re
from pathlib import Path
import fitz,pytest
from backend.app.pipeline.stages.block_grounding.structural_geometry import ALL_KJ_PROFILES,ALL_KM_PROFILES,evaluate_structural_gate,render_structural_markdown
from backend.app.pipeline.stages.block_grounding.legend_geometry import (PROFILE_LEGEND,
    evaluate_legend_gate,render_legend_markdown)

# «Условные обозначения» — надведомственный профиль: легенда есть в любом
# разделе, в набор профилей дисциплины не входит, гейт и рендер у неё свои.
def _gate(g):return evaluate_legend_gate(g) if g["profile_id"]==PROFILE_LEGEND else evaluate_structural_gate(g)
def _render(g):return render_legend_markdown(g) if g["profile_id"]==PROFILE_LEGEND else render_structural_markdown(g)
ROOT=Path(__file__).resolve().parents[1];KJ=ROOT/"experiments"/"блоки разных дисциплин"/"КЖ";OUT=KJ/"kj_out"
# Внешний исследовательский корпус (~2 ГБ) в контракт CI не входит и на диске
# может отсутствовать. Читать манифест на импорте без гарда нельзя: отсутствие
# файла рушит СБОРКУ всего прогона, а не помечает пропущенными свои тесты.
# Самодостаточность production-каталога проверяет test_block_reference_catalog.py.
KJ_MANIFEST=KJ/"KJ_DIVERSE_CORPUS.json"
def cases():return json.loads(KJ_MANIFEST.read_text()) if KJ_MANIFEST.exists() else []
@pytest.fixture(scope="module")
def graphs():return {c["block_id"]:json.loads((OUT/f"{c['block_id']}.structure.json").read_text()) for c in cases()}
@pytest.mark.skipif(not KJ_MANIFEST.exists(),reason="внешний корпус КЖ не извлечён")
@pytest.mark.parametrize("case",cases(),ids=lambda c:c["block_id"])
def test_kj_corpus(case,graphs):
 with fitz.open(KJ/case["output"]) as d:assert d.page_count==1
 g=graphs[case["block_id"]];assert g["profile_id"]==case["profile_id"] and _gate(g)["use"]
@pytest.mark.skipif(not KJ_MANIFEST.exists(),reason="внешний корпус КЖ не извлечён")
def test_kj_coverage(graphs):
 assert len(graphs)==110 and {g["profile_id"] for g in graphs.values()}-{PROFILE_LEGEND}==set(ALL_KJ_PROFILES) and len({c["subtype"] for c in cases()})==15
 report=json.loads((KJ/"KJ_SEMANTIC_COVERAGE.json").read_text());assert sum(r["pdf_misses_total"] for r in report["records"])==0
@pytest.mark.skipif(not KJ_MANIFEST.exists(),reason="внешний корпус КЖ не извлечён")
def test_kj_integrity_and_russian_output(graphs):
 for g in graphs.values():
  ids={n["id"] for n in g["nodes"]}
  for c in g.get("containers",[]):assert set(c.get("member_ids",[]))<=ids
  text=_render(g);assert g["profile_id"] not in text
  if g["profile_id"]==PROFILE_LEGEND:assert "Расшифровка обозначений" in text
  else:assert "Эталонная текстовая разметка КЖ" in text and g["validation"]["subtype"] not in text
  assert not re.search(r"\b(?:node|view)-\d+\b",text)

KM=ROOT/"experiments"/"блоки разных дисциплин"/"КМ";KMOUT=KM/"km_out";KM_MANIFEST=KM/"KM_DIVERSE_CORPUS.json"
def km_cases():return json.loads(KM_MANIFEST.read_text()) if KM_MANIFEST.exists() else []
@pytest.mark.skipif(not KM_MANIFEST.exists(),reason="внешний корпус КМ не извлечён")
@pytest.mark.parametrize("case",km_cases(),ids=lambda c:c["block_id"])
def test_km_corpus(case):
 with fitz.open(KM/case["output"]) as d:assert d.page_count==1
 g=json.loads((KMOUT/f"{case['block_id']}.structure.json").read_text());assert g["profile_id"]==case["profile_id"] and evaluate_structural_gate(g)["use"]
 assert "Эталонная текстовая разметка КМ" in render_structural_markdown(g)
@pytest.mark.skipif(not KM_MANIFEST.exists(),reason="внешний корпус КМ не извлечён")
def test_km_coverage_and_semantics():
 gs=[json.loads((KMOUT/f"{c['block_id']}.structure.json").read_text()) for c in km_cases()]
 assert len(gs)==71 and {g["profile_id"] for g in gs}==set(ALL_KM_PROFILES) and len({c["subtype"] for c in km_cases()})==11
 report=json.loads((KM/"KM_SEMANTIC_COVERAGE.json").read_text());assert sum(r["pdf_misses_total"] for r in report["records"])==0
