"""Pure evaluation-header label binding regressions for the real 106 topology."""

from __future__ import annotations

import copy
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from server.services.evaluation_design_svg import _bind_publication_labels, _evaluation_design_svg
from server.services.figure_print_policy import svg_print_contract_issues
from server.services.figure_svg_text_geometry import rendered_svg_text_geometry
from server.services.publication_figure_labels import concept_labels
from server.services.svg_variant_conversion import convert_svg_variants


NS = {"svg": "http://www.w3.org/2000/svg"}


def _metadata() -> dict:
    return {
        "id": "evaluation_design", "source_data": ["ideas/SELECTED_IDEA.json", "experiments/configs/main.yaml"],
        "publication_labels": concept_labels(["Channel-subset shared structure", "Evaluation split"], namespace="evaluation.term"),
        "design_brief": {"must_show": ["Channel-subset shared structure", "Evaluation split"]},
        "scene_contract": {"target_width_fraction": 1.0, "minimum_placed_font_pt": 8.0},
        "publication_language": "en",
        "method_brief": {
            "mechanism_nodes": [{"publication_name": "Channel-subset shared structure"}],
            "publication": {"method_name": "CSFS"},
            "evaluation_contract": {"comparators_or_controls": ["CSFS joint shared-private objective", "Random initialization"],
                                    "primary_outcomes": ["Leave-dataset-out transfer under matched controls"]},
            "evaluation_protocol": {
                "primary_split": "evaluation", "analysis_unit": "independent analysis unit, grouped within dataset",
                "declared_splits": [{"split_id": "dataset", "display_name": "dataset held-out",
                                     "source_path": "experiments/configs/main.yaml", "source_symbol": "evaluation.holdout_axes[0]"}],
                "active_holdout_axis": "dataset",
            },
        },
    }


def test_evaluation_split_heading_is_visible_and_bound_in_its_scientific_group() -> None:
    metadata = _metadata()
    original = copy.deepcopy(metadata)
    svg, mappings = _evaluation_design_svg(metadata)
    root = ET.fromstring(svg)
    group = root.find(".//svg:g[@id='eval_group_split']", NS)
    assert group is not None
    texts = list(group.findall(".//svg:text", NS))
    header = next(item for item in texts if item.text == "Evaluation split")
    assert header.get("data-label-id") == "evaluation.term.2"
    assert header.get("data-label-kind") == "concept"
    assert any(item.text == "Held-out test: separate evaluations" for item in texts)
    assert any(item.text == "dataset held-out" for item in texts)
    assert any(item["element_id"] == "eval_group_split" and item["source_path"] == "experiments/configs/main.yaml" for item in mappings)
    assert metadata == original


def test_current_106_topology_preserves_pixel_geometry_and_print_font(tmp_path: Path) -> None:
    metadata = _metadata()
    svg, _ = _evaluation_design_svg(metadata)
    root = ET.fromstring(svg)
    assert svg_print_contract_issues(svg, root, metadata) == []
    source, pdf, png = (tmp_path / f"evaluation_design.{suffix}" for suffix in ("svg", "pdf", "png"))
    source.write_text(svg, encoding="utf-8")
    converted, error = convert_svg_variants(source, pdf, png)
    assert converted, error
    assert rendered_svg_text_geometry(pdf) == []


def test_a_truly_missing_publication_label_remains_blocking() -> None:
    metadata = _metadata()
    svg, _ = _evaluation_design_svg(metadata)
    root = ET.fromstring(svg)
    for parent in root.iter():
        for child in list(parent):
            if child.tag.endswith("text") and child.text == "Evaluation split":
                parent.remove(child)
    with pytest.raises(ValueError, match="publication label is not visible: Evaluation split"):
        _bind_publication_labels(ET.tostring(root, encoding="unicode"), metadata["publication_labels"])


def test_missing_scientific_split_is_not_filled_by_the_column_heading() -> None:
    metadata = _metadata()
    metadata["method_brief"]["evaluation_protocol"].pop("primary_split")
    with pytest.raises(ValueError, match="primary evaluation split"):
        _evaluation_design_svg(metadata)
