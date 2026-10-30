from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from server.agent.tools.figure_storyboard_tools import (
    add_figure_storyboard_candidate,
    begin_figure_storyboard,
    load_selected_storyboard,
    select_figure_storyboard,
    submit_figure_storyboard,
)
from server.agent.tools.tool_registration import TOOL_SPECS
from server.services.api_visual_review_invocation import ApiVisualReview
from server.agent.tools.figure_draft_tools import (
    append_figure_svg_fragment,
    begin_figure_svg_draft,
    review_figure_svg_draft,
    draft_print_diagnostics,
)


def _candidates() -> list[dict]:
    return [{
        "id": identity, "topology": topology,
        "focal_message": f"The scientific mechanism is legible through {topology} structure",
        "regions": [
            {"id": "source_region", "purpose": "Show observed scientific inputs", "visual_grammar": "domain signal glyph", "relative_weight": 2},
            {"id": "mechanism_region", "purpose": "Depict the operative transformation", "visual_grammar": "tensor and equation", "relative_weight": 5},
            {"id": "readout_region", "purpose": "Show the registered readout", "visual_grammar": "distribution glyph", "relative_weight": 2},
        ],
        "reading_order": ["source_region", "mechanism_region", "readout_region"],
        "connections": [
            {"id": "source_to_mechanism", "from": "source_region", "to": "mechanism_region",
             "kind": "main", "scientific_meaning": "Observed source enters the focal process"},
            {"id": "mechanism_to_readout", "from": "mechanism_region", "to": "readout_region",
             "kind": "main", "scientific_meaning": "Focal process produces the scientific readout"},
        ],
        "strengths": ["Short scientific path"], "risks": ["Requires careful labels"],
    } for identity, topology in (
        ("parallel_focus", "parallel"),
        ("causal_spine", "causal"),
        ("hierarchy_focus", "hierarchical"),
    )]


def test_storyboard_persists_three_competing_layouts(tmp_path: Path) -> None:
    result = json.loads(submit_figure_storyboard(
        "method_architecture", _candidates(), "causal_spine",
        "The causal spine gives the shortest unambiguous scientific reading path.",
        str(tmp_path),
    ))
    loaded = load_selected_storyboard(tmp_path, "method_architecture")
    assert result["selected_id"] == "causal_spine"
    assert len(loaded["candidates"]) == 3
    assert loaded["selected_id"] == "causal_spine"


def test_storyboard_tool_exposes_nested_layout_contract_to_model() -> None:
    schema = next(item[2] for item in TOOL_SPECS if item[0] == "submit_figure_storyboard")
    candidate = schema["properties"]["candidates"]["items"]
    assert candidate["properties"]["topology"]["enum"] == [
        "linear", "parallel", "hierarchical", "radial", "matrix",
        "timeline", "spatial", "causal", "logical", "hybrid",
    ]
    region = candidate["properties"]["regions"]["items"]
    assert region["required"] == [
        "id", "purpose", "visual_grammar", "relative_weight",
    ]
    assert "connections" in candidate["required"]
    add_schema = next(
        item[2] for item in TOOL_SPECS
        if item[0] == "add_figure_storyboard_candidate"
    )
    assert add_schema["properties"]["candidate"]["properties"]["topology"]["enum"]


def test_storyboard_rejects_three_cosmetic_copies(tmp_path: Path) -> None:
    candidates = _candidates()
    candidates[1]["id"] = candidates[0]["id"]
    with pytest.raises(ValueError, match="already exists"):
        submit_figure_storyboard(
            "method_architecture", candidates, "parallel_focus",
            "A selected composition requires genuine candidate competition.", str(tmp_path),
        )


def test_storyboard_accepts_concise_selection_reason(tmp_path: Path) -> None:
    result = json.loads(submit_figure_storyboard(
        "method_architecture", _candidates(), "causal_spine", "最清晰",
        str(tmp_path),
    ))
    assert result["selected_id"] == "causal_spine"


def test_storyboard_accepts_one_character_selection_reason(tmp_path: Path) -> None:
    result = json.loads(submit_figure_storyboard(
        "method_architecture", _candidates(), "causal_spine", "好", str(tmp_path),
    ))
    assert result["selected_id"] == "causal_spine"


def test_storyboard_can_be_transmitted_as_small_calls(tmp_path: Path) -> None:
    begin_figure_storyboard("method_architecture", str(tmp_path))
    for index, candidate in enumerate(_candidates(), start=1):
        result = json.loads(add_figure_storyboard_candidate(
            "method_architecture", candidate, str(tmp_path),
        ))
        assert result["candidate_count"] == index
    selected = json.loads(select_figure_storyboard(
        "method_architecture", "causal_spine", "最清晰", str(tmp_path),
    ))
    assert selected["selected_id"] == "causal_spine"


def test_storyboard_policy_change_invalidates_old_layout(tmp_path: Path) -> None:
    path = tmp_path / ".merak" / "figure-storyboards" / "method_architecture.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({
        "schema": 1, "layout_policy_version": 1,
        "artifact_name": "method_architecture", "candidates": _candidates(),
        "selected_id": "causal_spine", "selection_reason": "最清晰",
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="policy is stale"):
        load_selected_storyboard(tmp_path, "method_architecture")


def test_storyboard_rejects_disconnected_or_dangling_relation(tmp_path: Path) -> None:
    candidates = _candidates()
    candidates[0]["connections"][1]["to"] = "missing_region"
    with pytest.raises(ValueError, match="invalid region endpoints"):
        submit_figure_storyboard(
            "method_architecture", candidates, "parallel_focus", "clear", str(tmp_path),
        )
    candidates = _candidates()
    candidates[0]["connections"][1]["kind"] = "side_output"
    with pytest.raises(ValueError, match="main connections must reach"):
        submit_figure_storyboard(
            "method_architecture", candidates, "parallel_focus", "clear", str(tmp_path),
        )


def test_storyboard_is_bound_to_current_semantic_projection(tmp_path: Path) -> None:
    digest = "a" * 64
    submit_figure_storyboard(
        "method_architecture", _candidates(), "causal_spine", "最清晰",
        str(tmp_path), semantic_projection_sha256=digest,
    )
    loaded = load_selected_storyboard(
        tmp_path, "method_architecture", expected_projection_sha256=digest,
    )
    assert loaded["semantic_projection_sha256"] == digest
    with pytest.raises(ValueError, match="semantic projection is stale"):
        load_selected_storyboard(
            tmp_path, "method_architecture",
            expected_projection_sha256="b" * 64,
        )


def test_in_progress_draft_receives_native_image_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    begin_figure_svg_draft(
        "method_architecture",
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 500">',
        str(tmp_path),
    )
    append_figure_svg_fragment(
        "method_architecture", "mechanism_region",
        '<g id="mechanism_region"><rect width="300" height="180" fill="#E8F1FB"/></g>',
        str(tmp_path),
    )

    def fake_convert(svg: Path, pdf: Path, png: Path):
        pdf.write_bytes(b"%PDF-1.4\n")
        png.write_bytes(b"PNG-preview")
        return True, ""

    async def fake_review(**kwargs):
        assert Path(kwargs["image_path"]).read_bytes() == b"PNG-preview"
        return ApiVisualReview(
            json.dumps({"score": 7.0, "verdict": "refine", "issues": ["mechanism is too generic"]}),
            "model-api:draft", "reviewer", "test", str(tmp_path / ".merak" / "trace"),
        )

    monkeypatch.setattr("server.services.svg_variant_conversion.convert_svg_variants", fake_convert)
    monkeypatch.setattr(
        "server.services.figure_svg_text_geometry.rendered_svg_text_geometry",
        lambda _path: [],
    )
    monkeypatch.setattr(
        "server.services.api_visual_reviewer.api_visual_reviewer.review_rich_svg",
        fake_review,
    )
    result = json.loads(asyncio.run(review_figure_svg_draft(
        "method_architecture", "mechanism_region",
        "Does this region depict the operative transformation rather than name it?",
        str(tmp_path),
    )))
    assert result["review"]["verdict"] == "refine"
    assert result["focus_fragment"] == "mechanism_region"
    manifest = json.loads((
        tmp_path / ".merak" / "figure-drafts" / "method_architecture" / "manifest.json"
    ).read_text(encoding="utf-8"))
    memory = manifest["fragment_reviews"]["mechanism_region"]
    assert memory["verdict"] == "refine"
    assert len(memory["fragment_sha256"]) == 64


def test_draft_review_reports_paper_scale_text_before_model_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    begin_figure_svg_draft(
        "method_architecture",
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1800 900">'
        '<style>.tiny{font-size:18px}</style>', str(tmp_path),
    )
    append_figure_svg_fragment(
        "method_architecture", "mechanism_region",
        '<g id="mechanism_region"><rect width="300" height="180" fill="#E8F1FB"/>'
        '<text class="tiny" x="20" y="40">Unreadable at paper scale</text></g>',
        str(tmp_path),
    )

    async def must_not_review(**_kwargs):
        raise AssertionError("Native reviewer must not receive known tiny text")

    monkeypatch.setattr(
        "server.services.api_visual_reviewer.api_visual_reviewer.review_rich_svg",
        must_not_review,
    )
    result = json.loads(asyncio.run(review_figure_svg_draft(
        "method_architecture", "mechanism_region",
        "Is the mechanism readable at its declared manuscript placement?",
        str(tmp_path),
    )))
    assert result["status"] == "local_repair_required"
    assert "falls below 8.0 pt" in result["issues"][0]
    assert result["small_text"][0]["fragment_id"] == "mechanism_region"
    assert result["small_text"][0]["required_font_units"] > 30
    diagnostic = json.loads(draft_print_diagnostics(
        "method_architecture", str(tmp_path),
    ))
    assert diagnostic["small_text"][0]["fragment_id"] == "mechanism_region"
