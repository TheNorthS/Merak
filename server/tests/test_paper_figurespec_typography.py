"""Pure temporary native FigureSpec typography and real PDF/PNG geometry."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from server.services.figure_engine import _load_figurespec_renderer
from server.services.paper_derived_figure_binding import pdf_print_geometry
from server.services.paper_figurespec_typography import (
    project_figurespec_typography, render_figurespec_typography,
)
from server.services.scientific_scene_figure import compile_scientific_scene_figure
from server.tests.test_scientific_scene_partition_consumption import _asset


def _spec(detail: bool = False) -> dict:
    asset = _asset()
    if detail:
        asset["narrative_level"] = "mechanism_detail"
    return compile_scientific_scene_figure(asset).spec


def _meaning(spec: dict) -> dict:
    result = deepcopy(spec)
    result.pop("canvas", None)
    result.pop("style", None)
    for node in result["nodes"]:
        for field in ("font_size", "width", "height", "y"):
            node.pop(field, None)
    for group in result.get("groups") or []:
        if group.get("bounds"):
            for field in ("height", "y"):
                group["bounds"].pop(field, None)
    for region in result.get("regions") or []:
        for field in ("height", "y"):
            region.pop(field, None)
    for label in result.get("labels") or []:
        for field in ("font_size", "y"):
            label.pop(field, None)
    return result


@pytest.mark.parametrize("detail,multiplier", [(False, 1.25), (True, 1.15), (False, 1.0)])
def test_paper_copy_keeps_graph_glyphs_text_groups_and_cross_panel_relations(detail, multiplier):
    renderer = _load_figurespec_renderer()
    spec = _spec(detail)
    before = deepcopy(spec)
    original_renderer = renderer._SEMANTIC_RENDERER.render_node_text
    projected = project_figurespec_typography(spec, renderer, multiplier)
    svg = render_figurespec_typography(spec, renderer, multiplier)
    assert spec == before and _meaning(projected) == _meaning(spec)
    assert renderer._SEMANTIC_RENDERER.render_node_text is original_renderer
    assert len(projected["nodes"]) == (6 if detail else 9)
    assert len(projected["edges"]) == (5 if detail else 9)
    assert all(new["font_size"] >= old["font_size"] and new["y"] >= old["y"]
               and new["height"] >= old["height"] and new["width"] >= old["width"]
               for old, new in zip(spec["nodes"], projected["nodes"], strict=True))
    assert ET.fromstring(svg).tag.rsplit("}", 1)[-1] == "svg"


@pytest.mark.parametrize("value", [0.99, 4.01, float("nan"), float("inf")])
def test_font_growth_scope_is_bounded_without_clamping(value):
    with pytest.raises(ValueError, match="1..4"):
        render_figurespec_typography(_spec(), _load_figurespec_renderer(), value)


def test_fractional_font_keeps_complete_compound_word_at_native_width_boundary():
    renderer = _load_figurespec_renderer()
    spec = _spec()
    spec["nodes"][-1]["label"] = "Evidence-bounded conclusion"
    multiplier = 1.2347880399742102
    projected = project_figurespec_typography(spec, renderer, multiplier)
    node = projected["nodes"][-1]
    assert node["width"] - 28 > renderer.estimate_text_width("Evidence-bounded", node["font_size"])
    root = ET.fromstring(render_figurespec_typography(spec, renderer, multiplier))
    assert any("Evidence-bounded" in str(element.text or "") for element in root.iter())


def test_audit_text_stays_below_probe_header_and_above_native_shield_taper(tmp_path):
    import fitz
    from server.services.svg_variant_conversion import convert_svg_variants

    renderer = _load_figurespec_renderer()
    spec = _spec()
    projected = project_figurespec_typography(spec, renderer, 1.25)
    audit = next(node for node in projected["nodes"] if node.get("visual_kind") == "audit")
    source = tmp_path / "audit.svg"
    source.write_text(render_figurespec_typography(spec, renderer, 1.25), encoding="utf-8")
    pdf, png = tmp_path / "audit.pdf", tmp_path / "audit.png"
    converted, issue = convert_svg_variants(source, pdf, png)
    assert converted, issue
    top = audit["y"] - audit["height"] / 2
    with fitz.open(pdf) as document:
        spans = [span for block in document[0].get_text("dict")["blocks"] if block.get("lines")
                 for line in block["lines"] for span in line["spans"]
                 if audit["x"] - audit["width"] / 2 < span["origin"][0] < audit["x"] + audit["width"] / 2
                 and top < span["origin"][1] < top + audit["height"]]
    assert len(spans) == 2
    assert min(span["bbox"][1] for span in spans) >= top + 33
    assert max(span["bbox"][3] for span in spans) <= top + audit["height"] * 0.74 - 6


@pytest.mark.parametrize("detail,multiplier", [(False, 1.25), (True, 1.15)])
def test_complete_native_svg_to_product_pdf_passes_actual_placed_font_and_overlap_gate(tmp_path, detail, multiplier):
    import fitz
    from server.services.svg_variant_conversion import convert_svg_variants

    renderer = _load_figurespec_renderer()
    spec = _spec(detail)
    original = json.dumps(spec, ensure_ascii=False, sort_keys=True)
    svg = render_figurespec_typography(spec, renderer, multiplier).encode()
    source = tmp_path / "figure.svg"
    source.write_bytes(svg)
    pdf = tmp_path / "figure.pdf"
    preview = tmp_path / "figure.png"
    accepted, issue = convert_svg_variants(source, pdf, preview)
    assert accepted, issue
    geometry = pdf_print_geometry(pdf, {"width_bp": 372.24})
    assert geometry["minimum_placed_font_bp"] >= 8.5
    assert geometry["text_geometry_findings"] == []
    assert json.dumps(spec, ensure_ascii=False, sort_keys=True) == original
    with fitz.open(pdf) as document:
        text = " ".join(document[0].get_text().split())
    assert all(" ".join(node["label"].split()) in text for node in spec["nodes"])


@pytest.mark.parametrize("multiplier", [1.3, 1.5, 1.65])
def test_mixed_control_scene_qualifier_survives_paper_font_growth(tmp_path, multiplier):
    from server.services.svg_variant_conversion import convert_svg_variants
    asset = json.loads((Path(__file__).parent / "fixtures/mixed_control_scene.json").read_text(encoding="utf-8"))
    spec = compile_scientific_scene_figure(asset).spec
    before = deepcopy(spec)
    renderer = _load_figurespec_renderer()
    projected = project_figurespec_typography(spec, renderer, multiplier)
    source = tmp_path / "paper.svg"
    source.write_text(render_figurespec_typography(spec, renderer, multiplier), encoding="utf-8")
    pdf, png = source.with_suffix(".pdf"), source.with_suffix(".png")
    ok, error = convert_svg_variants(source, pdf, png)
    assert ok, error
    geometry = pdf_print_geometry(pdf, {"width_bp": 372.24})
    assert geometry["minimum_placed_font_bp"] >= 8.5
    assert geometry["text_geometry_findings"] == []
    assert spec == before and _meaning(projected) == _meaning(spec)
