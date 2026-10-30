from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from server.agent.tools.figure_draft_tools import (
    append_figure_svg_fragment,
    begin_figure_svg_draft,
    finalize_figure_svg_draft,
    replace_figure_svg_fragment,
    current_draft_matches_storyboard,
    require_current_composition_review,
    review_figure_svg_composition,
)
from server.services.api_visual_review_schemas import RICH_SVG_CHECKS
from server.services.rich_svg_visual_review import REVIEW_POLICY_VERSION
from server.agent.tools.figure_storyboard_tools import submit_figure_storyboard
from server.agent.tools.figure_tool import FigureRequest, _figure_code


class _Registry:
    @staticmethod
    def project_root(_figures_root: Path) -> Path:
        return _figures_root.parent


def test_staged_svg_assembly_preserves_model_fragments(tmp_path: Path) -> None:
    opening = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 500"><defs></defs>'
    begin_figure_svg_draft("method_architecture", opening, str(tmp_path))
    for identity, shape in (
        ("input_layer", '<g id="input_layer"><path d="M0 0L10 10"/></g>'),
        ("mechanism_layer", '<g id="mechanism_layer"><circle cx="20" cy="20" r="5"/></g>'),
        ("relation_layer", '<g id="relation_layer"><line x1="10" y1="10" x2="20" y2="20"/></g>'),
    ):
        append_figure_svg_fragment(
            "method_architecture", identity, shape, str(tmp_path),
        )
    finalized = json.loads(finalize_figure_svg_draft(
        "method_architecture", str(tmp_path),
    ))
    source = tmp_path / finalized["source_path"]
    assert finalized["fragment_count"] == 3
    assert source.read_text(encoding="utf-8").endswith("</svg>\n")
    assert all(token in source.read_text(encoding="utf-8") for token in (
        'id="input_layer"', 'id="mechanism_layer"', 'id="relation_layer"',
    ))


def test_fragment_repair_preserves_unrelated_layers(tmp_path: Path) -> None:
    begin_figure_svg_draft(
        "method_architecture", '<svg xmlns="http://www.w3.org/2000/svg">',
        str(tmp_path),
    )
    fragments = {
        "input_layer": '<g id="input_layer"><path d="M0 0L1 1"/></g>',
        "mechanism_layer": '<g id="mechanism_layer"><circle r="2"/></g>',
        "relation_layer": '<g id="relation_layer"><line x2="3"/></g>',
    }
    for identity, fragment in fragments.items():
        append_figure_svg_fragment(
            "method_architecture", identity, fragment, str(tmp_path),
        )
    replace_figure_svg_fragment(
        "method_architecture", "mechanism_layer",
        '<g id="mechanism_layer"><rect width="8" height="8"/></g>', str(tmp_path),
    )
    payload = json.loads(finalize_figure_svg_draft(
        "method_architecture", str(tmp_path),
    ))
    assembled = (tmp_path / payload["source_path"]).read_text(encoding="utf-8")
    assert 'id="input_layer"' in assembled and 'id="relation_layer"' in assembled
    assert '<rect width="8" height="8"' in assembled
    assert '<circle r="2"' not in assembled


def test_body_fragment_rejects_global_style_patch(tmp_path: Path) -> None:
    begin_figure_svg_draft(
        "method_architecture", '<svg xmlns="http://www.w3.org/2000/svg">',
        str(tmp_path),
    )
    with pytest.raises(ValueError, match="global CSS overrides"):
        append_figure_svg_fragment(
            "method_architecture", "font_patch",
            '<g><style>text{font-size:31px!important}</style></g>', str(tmp_path),
        )


@pytest.mark.parametrize("visible", [
    '<text x="10" y="20">Figure title</text>',
    '<path d="M0 0L10 10"/>',
])
def test_opening_rejects_visible_non_region_content(
    tmp_path: Path, visible: str,
) -> None:
    with pytest.raises(ValueError, match="visible scientific content"):
        begin_figure_svg_draft(
            "method_architecture",
            '<svg xmlns="http://www.w3.org/2000/svg">' + visible,
            str(tmp_path),
        )


def test_fragment_rejects_unrelated_top_level_groups(tmp_path: Path) -> None:
    begin_figure_svg_draft(
        "method_architecture", '<svg xmlns="http://www.w3.org/2000/svg">',
        str(tmp_path),
    )
    with pytest.raises(ValueError, match="exactly one top-level SVG group"):
        append_figure_svg_fragment(
            "method_architecture", "task_interface",
            '<g id="task_interface"><path d="M0 0L1 1"/></g>'
            '<g id="unrelated_title"><text>Extra prose</text></g>',
            str(tmp_path),
        )
    with pytest.raises(ValueError, match="must equal fragment_id"):
        append_figure_svg_fragment(
            "method_architecture", "task_interface",
            '<g id="unrelated_title"><path d="M0 0L1 1"/></g>',
            str(tmp_path),
        )


def test_legacy_style_patch_makes_staged_draft_non_reusable(tmp_path: Path) -> None:
    begin_figure_svg_draft(
        "method_architecture", '<svg xmlns="http://www.w3.org/2000/svg">',
        str(tmp_path),
    )
    for identity in ("input_layer", "mechanism_layer", "output_layer"):
        append_figure_svg_fragment(
            "method_architecture", identity,
            f'<g id="{identity}"><path d="M0 0L1 1"/></g>', str(tmp_path),
        )
    finalize_figure_svg_draft("method_architecture", str(tmp_path))
    part = (
        tmp_path / ".merak" / "figure-drafts" / "method_architecture"
        / "parts" / "003_output_layer.svgfrag"
    )
    part.write_text('<g><style>text{font-size:31px!important}</style></g>', encoding="utf-8")
    assert current_draft_matches_storyboard(tmp_path, "method_architecture") is False


def test_production_rich_svg_requires_finalized_source_path(tmp_path: Path) -> None:
    request = FigureRequest(
        description="method", artifact_name="method_architecture",
        figure_type="rich_svg", code="<svg/>", generator_skill="rich-svg-figure",
    )
    with pytest.raises(ValueError, match="finalize a staged SVG"):
        _figure_code(request, _Registry(), tmp_path / "figures")


def test_finalized_source_cannot_escape_project(tmp_path: Path) -> None:
    request = FigureRequest(
        description="method", artifact_name="method_architecture",
        figure_type="rich_svg", source_path="../outside.svg",
    )
    with pytest.raises(ValueError, match="escapes the project"):
        _figure_code(request, _Registry(), tmp_path / "figures")


def test_draft_reuse_is_bound_to_selected_storyboard(tmp_path: Path) -> None:
    begin_figure_svg_draft(
        "method_architecture", '<svg xmlns="http://www.w3.org/2000/svg">',
        str(tmp_path),
    )
    for identity in ("input_layer", "mechanism_layer", "output_layer"):
        append_figure_svg_fragment(
            "method_architecture", identity,
            f'<g id="{identity}"><path d="M0 0L1 1"/></g>', str(tmp_path),
        )
    finalize_figure_svg_draft("method_architecture", str(tmp_path))
    assert current_draft_matches_storyboard(tmp_path, "method_architecture") is True
    candidates = [{
        "id": f"layout_{index}", "topology": topology,
        "focal_message": "One method mechanism follows a readable path",
        "regions": [
            {"id": "input", "purpose": "Show inputs", "visual_grammar": "signal", "relative_weight": 2},
            {"id": "mechanism", "purpose": "Show mechanism", "visual_grammar": "equation", "relative_weight": 5},
        ],
        "reading_order": ["input", "mechanism"],
        "connections": [{"id": "input_to_mechanism", "from": "input",
                         "to": "mechanism", "kind": "main",
                         "scientific_meaning": "Source enters the focal mechanism"}],
        "strengths": [], "risks": [],
    } for index, topology in enumerate(("linear", "parallel", "hierarchical"), 1)]
    submit_figure_storyboard(
        "method_architecture", candidates, "layout_1", "clear", str(tmp_path),
    )
    assert current_draft_matches_storyboard(tmp_path, "method_architecture") is False
    begin_figure_svg_draft(
        "method_architecture", '<svg xmlns="http://www.w3.org/2000/svg">',
        str(tmp_path),
    )
    for identity in ("input_layer", "mechanism_layer", "output_layer"):
        append_figure_svg_fragment(
            "method_architecture", identity,
            f'<g id="{identity}"><path d="M0 0L1 1"/></g>', str(tmp_path),
        )
    finalize_figure_svg_draft("method_architecture", str(tmp_path))
    assert current_draft_matches_storyboard(tmp_path, "method_architecture") is True


def _composition_blueprint() -> dict:
    roles = ("source", "context", "focal_process", "interaction", "synthesis")
    forms = ("signal", "tensor", "graph", "matrix", "equation")
    primitives = [{
        "id": f"stage_{index}", "role": role, "visual_form": form,
        "public_label": f"Stage {index}", "scientific_meaning": f"Meaning {index}",
        "annotations": [], "notation": (
            "y=L_2+L_4" if form == "equation" else
            "L_4" if role == "interaction" else
            "L_2" if role == "context" else ""
        ),
    } for index, (role, form) in enumerate(zip(roles, forms), 1)]
    return {
        "schema": 1, "compiler": "model-authored-svg-v1",
        "narrative_level": "method_overview", "figure_label": "Scientific process",
        "focal_message": "One focal process transforms the scientific source",
        "primitives": primitives,
        "reading_order": [item["id"] for item in primitives],
        "flows": [
            {"from": "stage_1", "to": "stage_3", "kind": "data"},
            {"from": "stage_3", "to": "stage_2", "kind": "data"},
            {"from": "stage_3", "to": "stage_4", "kind": "data"},
            {"from": "stage_2", "to": "stage_5", "kind": "data"},
            {"from": "stage_4", "to": "stage_5", "kind": "data"},
        ],
    }


def test_formal_submission_requires_accepted_full_composition_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    figures = tmp_path / "figures"
    figures.mkdir()
    (figures / "FIGURE_SPECS.json").write_text(json.dumps({
        "schema": 4, "figures": [{
            "id": "method_architecture", "scientific_role": "method",
            "scientific_question": "How does the focal process transform its source?",
        }],
    }), encoding="utf-8")
    begin_figure_svg_draft(
        "method_architecture",
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 500">',
        str(tmp_path),
    )
    for index in range(1, 6):
        append_figure_svg_fragment(
            "method_architecture", f"stage_{index}",
            f'<g id="stage_{index}"><path d="M0 0L{index} {index}"/></g>',
            str(tmp_path),
        )
    finalized = json.loads(finalize_figure_svg_draft(
        "method_architecture", str(tmp_path),
    ))
    manifest_path = (
        tmp_path / ".merak" / "figure-drafts" / "method_architecture" / "manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["canvas_layout_schema"] = 13
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    blueprint = _composition_blueprint()
    mechanism_primitives = [{
        "id": item["id"], "region_id": "main",
        "public_label": item["public_label"], "role": item["role"],
        "visual_form": item["visual_form"], "notation": item["notation"],
        "semantic_cues": [f"cue {item['id']}"],
    } for item in blueprint["primitives"]]
    mechanism_flows = [{
        "id": f"flow_{index}", **item,
        "label": (
            "L_4" if item["from"] == "stage_4" else
            "L_2" if item["from"] == "stage_2" else "carried state"
        ),
    } for index, item in enumerate(blueprint["flows"], 1)]
    (manifest_path.parent / "mechanism-ir.json").write_text(json.dumps({
        "schema": 2, "primitives": mechanism_primitives,
        "reading_order": [item["id"] for item in mechanism_primitives],
        "flows": mechanism_flows,
    }), encoding="utf-8")
    (manifest_path.parent / "canvas-layout.json").write_text(json.dumps({
        "schema": 1, "regions": [{"id": "main"}],
    }), encoding="utf-8")
    source = tmp_path / finalized["source_path"]
    with pytest.raises(ValueError, match="has not passed native-image preflight"):
        require_current_composition_review(
            tmp_path, "method_architecture", source, blueprint,
        )

    def fake_convert(_svg: Path, pdf: Path, png: Path):
        pdf.write_bytes(b"%PDF-1.4\n")
        png.write_bytes(b"PNG")
        return True, ""

    async def fake_review_candidate(**_kwargs):
        return {
            "score": 8.5, "verdict": "accept", "issues": [],
            "findings": [], "review_policy_version": REVIEW_POLICY_VERSION,
            "improvement_prompt": "", "checklist": {
                key: True for key in RICH_SVG_CHECKS
            },
            "blind_readback": {
                "mechanism_recoverable": True,
                "directed_relations": [
                    {"from": "source", "to": "process", "meaning": "source enters process"},
                    {"from": "process", "to": "mechanism", "meaning": "process supplies mechanism"},
                    {"from": "mechanism", "to": "readout", "meaning": "mechanism yields readout"},
                ],
            },
            "blind_readback_issues": [],
            "blind_readback_trace_path": str(tmp_path / ".merak" / "blind-trace"),
        }, []

    monkeypatch.setattr(
        "server.services.svg_variant_conversion.convert_svg_variants", fake_convert,
    )
    monkeypatch.setattr(
        "server.services.figure_svg_text_geometry.rendered_svg_text_geometry",
        lambda _path: [],
    )
    monkeypatch.setattr(
        "server.services.rich_svg_visual_review.review_candidate", fake_review_candidate,
    )
    result = json.loads(asyncio.run(review_figure_svg_composition(
        "method_architecture", blueprint, str(tmp_path),
    )))
    assert result["status"] == "accepted"
    require_current_composition_review(
        tmp_path, "method_architecture", source, blueprint,
    )
