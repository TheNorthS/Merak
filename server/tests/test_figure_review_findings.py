"""Reviewer findings must name the layer that can actually repair them."""

import json
from pathlib import Path

from server.agent.tools.figure_draft_review import (
    _persist_composition_review, _repair_routing,
)
from server.services.api_visual_review_schemas import RICH_SVG_REVIEW_SCHEMA
from server.services.api_visual_reviewer import ApiVisualReviewer
from server.services.figure_review_findings import normalize_review_findings


def _metadata() -> dict:
    return {
        "visual_blueprint": {
            "primitives": [
                {"id": "encoder"},
                {"id": "decision_gate"},
            ],
        },
    }


def test_runtime_finding_cannot_target_a_model_owned_glyph() -> None:
    review = {
        "verdict": "refine",
        "findings": [{
            "target_layer": "runtime",
            "target_ids": ["encoder"],
            "severity": "blocker",
            "message": "The connector arrow misses its merge port.",
            "repair_action": "Reroute the connector to the merge port.",
        }],
        "issues": [],
    }

    findings = normalize_review_findings(
        review, _metadata(), artifact_id="method_architecture",
    )

    assert findings[0]["target_layer"] == "runtime"
    assert findings[0]["target_ids"] == ["composition"]
    assert "connector" in findings[0]["repair_action"].casefold()


def test_legacy_visual_issue_gets_deterministic_owner_and_action() -> None:
    findings = normalize_review_findings({
        "verdict": "refine",
        "issues": ["Labels collide beside the outgoing arrow."],
    }, _metadata(), artifact_id="method_architecture")

    assert findings == [{
        "target_layer": "runtime",
        "target_ids": ["composition"],
        "severity": "blocker",
        "message": "Labels collide beside the outgoing arrow.",
        "repair_action": (
            "Repair the deterministic labels, connectors, frames, or composition "
            "owned by the SVG runtime; do not redraw a domain glyph for this issue."
        ),
    }]


def test_rich_svg_schema_requires_typed_findings() -> None:
    payload = {
        "score": 7.0,
        "verdict": "refine",
        "issues": ["Arrow is unclear."],
        "strengths": [],
        "improvement_prompt": "Repair the arrow.",
        "checklist": {
            key: False for key in RICH_SVG_REVIEW_SCHEMA["properties"][
                "checklist"
            ]["required"]
        },
    }
    errors = ApiVisualReviewer.schema_validation_errors(
        payload, RICH_SVG_REVIEW_SCHEMA,
    )
    assert "$.findings is required" in errors

    payload["findings"] = [{
        "target_layer": "runtime",
        "target_ids": ["mechanism_connections"],
        "severity": "blocker",
        "message": "Arrow is unclear.",
        "repair_action": "Increase route separation.",
    }]
    assert ApiVisualReviewer.schema_validation_errors(
        payload, RICH_SVG_REVIEW_SCHEMA,
    ) == []


def test_runtime_routing_is_persisted_and_excludes_glyph_repairs(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "draft"
    directory.mkdir()
    (directory / "manifest.json").write_text(
        '{"artifact_name":"method_architecture"}', encoding="utf-8",
    )
    preview = directory / "preview.png"
    preview.write_bytes(b"PNG")
    blueprint = _metadata()["visual_blueprint"]
    review = {
        "score": 6.8,
        "verdict": "refine",
        "issues": ["The branch connector ends outside the merge port."],
        "findings": [{
            "target_layer": "runtime",
            "target_ids": ["mechanism_connections"],
            "severity": "blocker",
            "message": "The branch connector ends outside the merge port.",
            "repair_action": "Route the line into the declared merge port.",
        }],
    }
    routing = _repair_routing(review, blueprint, "method_architecture")
    _persist_composition_review(
        directory, "<svg/>", blueprint, review,
        list(review["issues"]), preview,
    )

    persisted = json.loads(
        (directory / "manifest.json").read_text(encoding="utf-8")
    )["composition_review"]
    assert persisted["findings"] == routing["findings"]
    assert routing["repair_plan"]["runtime"]
    assert routing["repair_plan"]["glyph"] == []
    assert routing["repair_routing"]["glyph_target_ids"] == []
    assert routing["repair_routing"]["runtime_owned"] is True
    assert "Do not replace a domain glyph" in routing[
        "repair_routing"
    ]["runtime_instruction"]
