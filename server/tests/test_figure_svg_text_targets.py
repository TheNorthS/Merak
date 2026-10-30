"""Text geometry feedback names model-owned SVG groups after draft rollback."""

from __future__ import annotations

import hashlib
import json
import asyncio
import xml.etree.ElementTree as ET
from pathlib import Path

from server.agent.tools.figure_draft_review import (
    _blueprint_sha256,
    _bind_restored_local_failure,
    _geometry_fragments,
    _regressed_response,
    _review_composition_candidate,
    review_figure_svg_composition,
)
from server.agent.tools.figure_draft_tools import DRAFT_POLICY_VERSION, _small_text_details
from server.services.figure_svg_text_targets import attach_text_targets, text_group_targets
from server.services.figure_draft_best import preserve_best_draft
from server.services.rich_svg_visual_review import REVIEW_POLICY_VERSION
from server.workflows.figure_asset_delegates import _draft_review_guidance


_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 400">'
    '<g id="outer"><g id="m2_probe"><text x="10" y="20" font-size="10">'
    'Conditional probe</text></g></g>'
    '<g id="loss"><text x="60" y="20" font-size="10">Shared loss</text></g>'
    '</svg>'
)


def _model_directory(root: Path, source: str = _SVG) -> Path:
    directory = root / ".merak" / "figure-drafts" / "method_architecture"
    directory.mkdir(parents=True)
    (directory / "method_architecture.svg").write_text(source, encoding="utf-8")
    (directory / "manifest.json").write_text(json.dumps({
        "artifact_name": "method_architecture",
        "authoring_mode": "model_composed",
        "production_strategy": "model_composed_full_svg",
        "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "draft_policy_version": DRAFT_POLICY_VERSION,
        "source_bundle_sha256": "source-bundle",
        "figure_spec_sha256": "spec",
        "storyboard_selected_sha256": None,
        "storyboard_candidate_sha256": None,
    }), encoding="utf-8")
    return directory


def test_model_text_feedback_uses_deepest_group_ids(tmp_path: Path) -> None:
    directory = _model_directory(tmp_path)
    assert text_group_targets(ET.fromstring(_SVG))["Conditional probe"] == "m2_probe"

    small = _small_text_details(_SVG, directory)
    assert {item["fragment_id"] for item in small} == {"m2_probe", "loss"}
    assert {tuple(item["target_ids"]) for item in small} == {
        ("m2_probe",), ("loss",),
    }

    findings = [{
        "kind": "text_collision", "labels": ["Conditional probe", "Shared loss"],
    }]
    assert _geometry_fragments(directory, findings)[0]["target_ids"] == [
        "m2_probe", "loss",
    ]
    assert attach_text_targets(_SVG, findings)[0]["fragment_ids"] == [
        "m2_probe", "loss",
    ]


def test_repeated_label_does_not_claim_a_single_owner() -> None:
    repeated = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<g id="first"><text>Audit</text></g>'
        '<g id="second"><text>Audit</text></g></svg>'
    )
    assert text_group_targets(ET.fromstring(repeated))["Audit"] == "full_svg"


def test_rolled_back_local_feedback_is_bound_to_restored_source(
    tmp_path: Path,
) -> None:
    directory = _model_directory(tmp_path)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    rejected_hash = "rejected-candidate"
    (directory / "last-local-failure.json").write_text(json.dumps({
        "source_sha256": rejected_hash,
        "draft_policy_version": manifest["draft_policy_version"],
        "source_bundle_sha256": manifest["source_bundle_sha256"],
        "figure_spec_sha256": manifest["figure_spec_sha256"],
        "storyboard_selected_sha256": None,
        "storyboard_candidate_sha256": None,
        "issues": ["rendered SVG has clipped or colliding text"],
        "text_geometry": [{
            "kind": "text_collision", "labels": ["Conditional probe", "Shared loss"],
            "target_ids": ["m2_probe", "loss"],
        }],
    }), encoding="utf-8")
    _bind_restored_local_failure(directory)
    guidance = _draft_review_guidance(str(tmp_path), "method_architecture")
    assert "restored from the best reviewed source" in guidance
    assert '"target_ids": ["m2_probe", "loss"]' in guidance

    manifest["source_sha256"] = "new-candidate"
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert "text geometry" not in _draft_review_guidance(
        str(tmp_path), "method_architecture",
    )


def test_exact_failed_svg_reuses_findings_without_new_visual_call(
    tmp_path: Path, monkeypatch,
) -> None:
    directory = _model_directory(tmp_path)
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    blueprint = {"primitives": [{"id": "m2_probe"}]}
    review = {
        "score": 7.8, "verdict": "refine",
        "issues": ["clarify conditional probe"],
        "review_policy_version": REVIEW_POLICY_VERSION,
    }
    manifest["composition_review"] = {
        "source_sha256": manifest["source_sha256"],
        "visual_blueprint_sha256": _blueprint_sha256(blueprint),
        "source_bundle_sha256": manifest["source_bundle_sha256"],
        "figure_spec_sha256": manifest["figure_spec_sha256"],
        "element_mappings_sha256": None,
        "independent_visual_review": review, "issues": review["issues"],
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    async def unexpected_review(**_kwargs):
        raise AssertionError("identical failed SVG must not consume another model review")

    monkeypatch.setattr(
        "server.services.rich_svg_visual_review.review_candidate", unexpected_review,
    )
    source = directory / "method_architecture.svg"
    result = json.loads(asyncio.run(_review_composition_candidate(
        tmp_path, directory, "method_architecture", blueprint, _SVG, 1,
        (source, source.with_suffix(".pdf"), source.with_suffix(".png"),
         manifest["source_sha256"]),
    )))
    assert result["status"] == "refine"
    assert result["cached_review"] is True
    assert result["issues"] == ["clarify conditional probe"]


def test_local_failure_restores_best_and_preserves_exact_feedback(
    tmp_path: Path, monkeypatch,
) -> None:
    directory = _model_directory(tmp_path)
    source = directory / "method_architecture.svg"
    blueprint = {"primitives": [{"id": "m2_probe"}]}
    (directory / "visual-blueprint.json").write_text(json.dumps(blueprint), encoding="utf-8")
    best_source = source.read_bytes()
    preserve_best_draft(
        directory, source, {"score": 7.8, "verdict": "refine"},
        ["clarify conditional probe"], _blueprint_sha256(blueprint),
    )
    candidate = _SVG.replace("Conditional probe", "Colliding label")
    source.write_text(candidate, encoding="utf-8")
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_sha256"] = hashlib.sha256(candidate.encode("utf-8")).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    failure = {
        "status": "local_repair_required", "issues": ["text collision"],
        "text_geometry": [{"labels": ["Colliding label"], "target_ids": ["m2_probe"]}],
    }
    monkeypatch.setattr(
        "server.agent.tools.figure_draft_review._require_current_mechanism_canvas",
        lambda _directory: json.loads(manifest_path.read_text(encoding="utf-8")),
    )
    monkeypatch.setattr(
        "server.agent.tools.figure_draft_review._validated_composition_blueprint",
        lambda _directory, value: value,
    )
    monkeypatch.setattr(
        "server.agent.tools.figure_draft_review._composition_local_failure",
        lambda *_args: (json.dumps(failure), None),
    )
    result = json.loads(asyncio.run(review_figure_svg_composition(
        "method_architecture", blueprint, str(tmp_path),
    )))
    assert result["status"] == "local_repair_required"
    assert result["restored_best"] is True
    assert source.read_bytes() == best_source
    persisted = json.loads((directory / "last-local-failure.json").read_text(encoding="utf-8"))
    assert persisted["source_sha256"] == manifest["source_sha256"]
    assert persisted["restored_best_source_sha256"] == hashlib.sha256(best_source).hexdigest()
    assert '"target_ids": ["m2_probe"]' in _draft_review_guidance(
        str(tmp_path), "method_architecture",
    )


def test_regression_feedback_uses_restored_blueprint(tmp_path: Path, monkeypatch) -> None:
    directory = _model_directory(tmp_path)
    restored = {"primitives": [{"id": "m2_probe"}]}
    rejected = {"primitives": [{"id": "rejected_branch"}]}
    (directory / "visual-blueprint.json").write_text(json.dumps(restored), encoding="utf-8")
    monkeypatch.setattr(
        "server.agent.tools.figure_draft_review._repair_routing",
        lambda _review, value, _artifact, **_kwargs: {"routed_blueprint": value},
    )
    result = json.loads(_regressed_response(
        directory, "method_architecture", rejected,
        {"score": 6.0}, ["old issue"], 7.8,
    ))
    assert result["routed_blueprint"] == restored
