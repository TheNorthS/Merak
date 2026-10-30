from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from server.agent.tools.figure_storyboard_tools import (
    load_selected_storyboard,
    submit_figure_storyboard,
)
from server.services.api_visual_review_invocation import ApiVisualReview
from server.services.figure_storyboard_review import visually_select_storyboard


def _candidates() -> list[dict]:
    return [{
        "id": identity, "topology": topology,
        "focal_message": f"A {topology} scientific mechanism with a visible focal path",
        "regions": [
            {"id": "input", "purpose": "Observed input", "visual_grammar": "signal", "relative_weight": 2},
            {"id": "mechanism", "purpose": "Operative transformation", "visual_grammar": "tensor equation", "relative_weight": 5},
            {"id": "output", "purpose": "Registered output", "visual_grammar": "distribution", "relative_weight": 2},
        ],
        "reading_order": ["input", "mechanism", "output"],
        "connections": [
            {"id": "input_to_method", "from": "input", "to": "mechanism",
             "kind": "main", "scientific_meaning": "Observed input enters the mechanism"},
            {"id": "method_to_output", "from": "mechanism", "to": "output",
             "kind": "main", "scientific_meaning": "The mechanism yields a measurable output"},
        ],
        "strengths": ["Readable"], "risks": ["Needs careful spacing"],
    } for identity, topology in (
        ("linear_candidate", "linear"),
        ("parallel_candidate", "parallel"),
        ("hierarchy_candidate", "hierarchical"),
    )]


@pytest.mark.asyncio
async def test_visual_reviewer_sees_three_rendered_candidates_and_can_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    submit_figure_storyboard(
        "method_architecture", _candidates(), "linear_candidate",
        "The text planner initially prefers the linear option.", str(tmp_path),
    )
    storyboard = load_selected_storyboard(tmp_path, "method_architecture")

    async def fake_invoke(**kwargs):
        paths = [Path(item) for item in kwargs["image_paths"]]
        assert len(paths) == 3
        assert all(Image.open(path).size == (1600, 900) for path in paths)
        return ApiVisualReview(
            json.dumps({
                "selected_id": "parallel_candidate",
                "scores": {"linear_candidate": 6.2, "parallel_candidate": 8.4, "hierarchy_candidate": 7.0},
                "selection_reason": "Parallel lanes expose the mechanism comparison most clearly.",
                "rejected_reasons": {"linear_candidate": "Weak branch comparison", "hierarchy_candidate": "Long reading path"},
            }),
            "model-api:storyboard", "reviewer", "test",
            str(tmp_path / ".merak" / "storyboard-review"),
        )

    monkeypatch.setattr(
        "server.services.api_visual_reviewer.api_visual_reviewer.invoke",
        fake_invoke,
    )
    reviewed = await visually_select_storyboard(
        tmp_path, "method_architecture", storyboard,
    )
    assert reviewed["selected_id"] == "parallel_candidate"
    assert reviewed["selected_by"] == "native-image-layout-reviewer-v1"
    persisted = load_selected_storyboard(tmp_path, "method_architecture")
    assert persisted["selected_id"] == "parallel_candidate"
    assert len(persisted["candidate_images"]) == 3
