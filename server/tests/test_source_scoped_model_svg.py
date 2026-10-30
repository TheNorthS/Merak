"""Focused source-scoped model SVG contract regressions."""

from __future__ import annotations

import json
from pathlib import Path

from server.agent.tools.figure_draft_tools import (
    prepare_model_svg_draft,
    submit_model_svg_draft,
)
from server.services.rich_svg_backend import _generation_blueprint
from server.services.rich_svg_visual_review import _minimum_readback_relations


def _project(root: Path) -> None:
    (root / "ideas").mkdir()
    (root / "figures").mkdir()
    (root / "ideas" / "SELECTED_IDEA.json").write_text(
        '{"hypothesis":"compact source-scoped method"}', encoding="utf-8",
    )
    spec = {
        "figures": [{
            "id": "compact_method", "kind": "figure",
            "producer_kind": "model", "recommended_backend": "rich_svg",
            "recommended_skill": "model-svg-figure",
            "production_strategy": "model_composed_full_svg",
            "composition_owner": "model", "scientific_role": "method",
            "scientific_question": "How does the method transform the input?",
            "reading_goal": "Read the input-to-method transformation.",
            "design_brief": {
                "schema": 1,
                "scientific_question": "How does the method transform the input?",
                "reading_goal": "Read the input-to-method transformation.",
                "must_show": ["Input", "Method"],
                "minimum_font_pt": 8.0, "maximum_primary_objects": 7,
            },
            "source_artifacts": ["ideas/SELECTED_IDEA.json"],
            "scientific_scene": {
                "schema": 1,
                "objects": [
                    {"id": "input", "kind": "input", "label": "Input",
                     "source_path": "ideas/SELECTED_IDEA.json"},
                    {"id": "method", "kind": "operation", "label": "Method",
                     "source_path": "ideas/SELECTED_IDEA.json"},
                ],
                "relations": [
                    {"from": "input", "to": "method", "kind": "data"},
                ],
            },
            "scene_contract": {
                "target_width_fraction": 1.0,
                "minimum_placed_font_pt": 8.0,
                "maximum_primary_nodes": 7,
            },
        }],
    }
    (root / "figures" / "FIGURE_SPECS.json").write_text(
        json.dumps(spec), encoding="utf-8",
    )


def _blueprint() -> dict:
    return {
        "schema": 1, "compiler": "model-authored-svg-v1",
        "narrative_level": "method_overview",
        "figure_label": "Compact method",
        "focal_message": "Input is transformed by the method",
        "primitives": [
            {"id": "input", "scientific_object_id": "input",
             "visual_form": "signal", "public_label": "Input",
             "role": "source", "scientific_meaning": "Input", "annotations": []},
            {"id": "method", "scientific_object_id": "method",
             "visual_form": "algorithm", "public_label": "Method",
             "role": "focal_process", "scientific_meaning": "Method", "annotations": []},
        ],
        "reading_order": ["input", "method"],
        "flows": [{"from": "input", "to": "method", "kind": "data"}],
    }


def _svg() -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 420 180">'
        '<g id="input"><rect x="20" y="50" width="140" height="70"/>'
        '<text x="90" y="90">Input</text></g>'
        '<g id="method"><rect x="260" y="50" width="140" height="70"/>'
        '<text x="330" y="90">Method</text></g>'
        '<path data-from="input" data-to="method" d="M160 85H260" '
        'stroke="#000"/></svg>'
    )


def test_compact_scene_prepares_and_submits_without_padding(tmp_path: Path) -> None:
    _project(tmp_path)
    prepared = json.loads(prepare_model_svg_draft(
        "compact_method", str(tmp_path),
    ))
    contract = prepared["visual_blueprint_contract"]
    assert contract["minimum_primitives"] == 2
    assert contract["minimum_distinct_visual_forms"] == 2
    assert contract["minimum_reading_order"] == 2
    assert contract["minimum_relations"] == 1
    assert _minimum_readback_relations(
        json.loads((tmp_path / "figures" / "FIGURE_SPECS.json").read_text(
            encoding="utf-8",
        ))["figures"][0],
    ) == 1

    staged = json.loads(submit_model_svg_draft(
        "compact_method", _svg(), _blueprint(), str(tmp_path),
        element_mappings=[
            {"element_id": "input", "source_path": "ideas/SELECTED_IDEA.json"},
            {"element_id": "method", "source_path": "ideas/SELECTED_IDEA.json"},
        ],
    ))
    assert staged["status"] == "finalized"


def test_three_object_scene_uses_two_edge_minimum(tmp_path: Path) -> None:
    _project(tmp_path)
    spec_path = tmp_path / "figures" / "FIGURE_SPECS.json"
    payload = json.loads(spec_path.read_text(encoding="utf-8"))
    scene = payload["figures"][0]["scientific_scene"]
    scene["objects"].append({
        "id": "output", "kind": "output", "label": "Output",
        "source_path": "ideas/SELECTED_IDEA.json",
    })
    scene["relations"].append(
        {"from": "method", "to": "output", "kind": "causal"},
    )
    spec_path.write_text(json.dumps(payload), encoding="utf-8")
    prepared = json.loads(prepare_model_svg_draft(
        "compact_method", str(tmp_path),
    ))
    contract = prepared["visual_blueprint_contract"]
    assert contract["minimum_primitives"] == 3
    assert contract["minimum_reading_order"] == 3
    assert contract["minimum_relations"] == 2
    blueprint = _blueprint()
    blueprint["primitives"].append({
        "id": "output", "scientific_object_id": "output",
        "visual_form": "distribution", "public_label": "Output",
        "role": "output", "scientific_meaning": "Output", "annotations": [],
    })
    blueprint["reading_order"].append("output")
    blueprint["flows"].append(
        {"from": "method", "to": "output", "kind": "causal"},
    )
    normalized, issues = _generation_blueprint({
        **payload["figures"][0], "visual_blueprint": blueprint,
    })
    assert normalized == blueprint
    assert issues == []


def test_hybrid_rich_svg_does_not_inherit_compact_model_minima() -> None:
    metadata = {
        "production_strategy": "hybrid_canvas",
        "scientific_scene": {
            "objects": [{"id": "a"}, {"id": "b"}],
            "relations": [{"from": "a", "to": "b", "kind": "data"}],
        },
        "visual_blueprint": _blueprint(),
    }
    assert _minimum_readback_relations(metadata) == 3
    _normalized, issues = _generation_blueprint(metadata)
    assert any("at least 4 identified" in issue for issue in issues)


def test_projected_scene_sets_mapping_floor_not_excluded_full_scene(
    tmp_path: Path,
) -> None:
    _project(tmp_path)
    spec_path = tmp_path / "figures" / "FIGURE_SPECS.json"
    payload = json.loads(spec_path.read_text(encoding="utf-8"))
    scene = payload["figures"][0]["scientific_scene"]
    scene["objects"].extend([
        {"id": f"evaluation_{index}", "kind": "operation", "label": "Held-out audit",
         "source_path": "ideas/SELECTED_IDEA.json"}
        for index in range(3)
    ])
    scene["relations"].extend([
        {"from": "method", "to": f"evaluation_{index}", "kind": "data"}
        for index in range(3)
    ])
    spec_path.write_text(json.dumps(payload), encoding="utf-8")
    prepared = json.loads(prepare_model_svg_draft("compact_method", str(tmp_path)))
    assert prepared["visual_blueprint_contract"]["minimum_primitives"] == 2
    assert prepared["element_mapping_contract"]["minimum_mapped_groups"] == 2
    staged = json.loads(submit_model_svg_draft(
        "compact_method", _svg(), _blueprint(), str(tmp_path),
        element_mappings=[
            {"element_id": "input", "source_path": "ideas/SELECTED_IDEA.json"},
            {"element_id": "method", "source_path": "ideas/SELECTED_IDEA.json"},
        ],
    ))
    assert staged["status"] == "finalized"


def test_formal_blueprint_gate_uses_same_compact_scene(tmp_path: Path) -> None:
    _project(tmp_path)
    payload = json.loads((
        tmp_path / "figures" / "FIGURE_SPECS.json"
    ).read_text(encoding="utf-8"))
    blueprint = _blueprint()
    normalized, issues = _generation_blueprint({
        **payload["figures"][0], "visual_blueprint": blueprint,
    })
    assert normalized == blueprint
    assert issues == []
