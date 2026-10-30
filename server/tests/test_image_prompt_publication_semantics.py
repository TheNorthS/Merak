"""Pure semantic source projection for generated images without audit leakage."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from server.services.figure_artifacts import figure_artifact_registry
from server.services.figure_scientific_alignment import candidate_scientific_alignment_issues
from server.services.gemini_figure_protocol import _initial_prompt
from server.services.publication_figure_labels import concept_labels


def _metadata() -> dict:
    return {"id": "method_overview", "semantic_key": "method_overview", "scientific_role": "qualitative",
            "publication_labels": concept_labels(["Sensor encoder", "Fusion module", "Decision output"], namespace="method")}


def _idea(root: Path) -> None:
    ideas = root / "ideas"
    ideas.mkdir()
    (ideas / "SELECTED_IDEA.json").write_text(json.dumps({
        "schema": 2, "publication": {"title": "Sensor fusion decision representation"},
        "hypothesis": "Sensor encoder and fusion module produce the declared decision output.",
        "mechanisms": [], "claims": [],
    }), encoding="utf-8")


def _protocol(root: Path, *, scientific_text: str = "Sensor encoder -> Fusion module -> Decision output") -> Path:
    directory = root / "figures/ai_generated/method_overview/run_fixture"
    round_dir = directory / "round_01"
    round_dir.mkdir(parents=True)
    specification = round_dir / "style_spec.txt"
    specification.write_text(scientific_text, encoding="utf-8")
    source = directory / "method_overview.prompt.json"
    source.write_text(json.dumps({
        "schema": 1, "protocol": "merak-paperbanana-v1", "status": "accepted",
        "description": "Sensor encoder, Fusion module and Decision output",
        "initial_prompt": _initial_prompt("Sensor encoder, Fusion module and Decision output", _metadata()),
        "accepted_round": 1, "accepted_score": 9, "image_model": "runtime_generated_image",
        "rounds": [{"arrow_correctness": True, "arrow_labels": True, "arrow_visibility": True}],
        "artifacts": {"round_01/style_spec.txt": specification.relative_to(root).as_posix(),
                      "round_01/review.json": "figures/ai_generated/runtime_audit.json"},
        "artifact_sha256": {"round_01/style_spec.txt": hashlib.sha256(specification.read_bytes()).hexdigest()},
    }), encoding="utf-8")
    return source


def test_protocol_projection_retains_real_science_and_excludes_runtime_audit_fields(tmp_path: Path) -> None:
    source = _protocol(tmp_path)
    text = figure_artifact_registry._publication_semantic_text({"metadata": {}}, tmp_path, source)
    assert all(value in text for value in ("Sensor encoder", "Fusion module", "Decision output"))
    assert all(value not in text for value in ("accepted_round", "accepted_score", "ai_generated", "arrow_correctness", "arrow_visibility"))
    _idea(tmp_path)
    assert candidate_scientific_alignment_issues(figure_artifact_registry, tmp_path, _metadata(), source) == []


def test_public_code_symbol_in_the_accepted_specification_still_blocks(tmp_path: Path) -> None:
    _idea(tmp_path)
    source = _protocol(tmp_path, scientific_text="Sensor encoder -> experiments/src/train.py -> Decision output")
    issues = candidate_scientific_alignment_issues(figure_artifact_registry, tmp_path, _metadata(), source)
    assert any("code symbols or artifact paths" in issue for issue in issues)


@pytest.mark.parametrize("fault", ["empty-request", "missing-spec", "stale-spec", "foreign-spec", "wrong-round"])
def test_invalid_prompt_protocol_cannot_fall_back_to_empty_success(tmp_path: Path, fault: str) -> None:
    source = _protocol(tmp_path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if fault == "empty-request":
        payload["initial_prompt"] = "Runtime audit only"
    elif fault == "missing-spec":
        payload["artifacts"] = {}
    elif fault == "stale-spec":
        payload["artifact_sha256"]["round_01/style_spec.txt"] = "0" * 64
    elif fault == "foreign-spec":
        payload["artifacts"]["round_01/style_spec.txt"] = "../foreign/style_spec.txt"
    else:
        payload["accepted_round"] = 0
    source.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        figure_artifact_registry._publication_semantic_text({"metadata": {}}, tmp_path, source)


def test_gpt_prompt_source_keeps_only_authored_prompt_not_transport_metadata(tmp_path: Path) -> None:
    source = tmp_path / "qualitative.prompt.json"
    source.write_text(json.dumps({"prompt": "Sensor encoder -> Fusion module -> Decision output", "model": "gpt_image",
                                  "remote_url": "https://example.invalid/runtime_audit", "revised_prompt": "Sensor encoder with a fusion module"}), encoding="utf-8")
    text = figure_artifact_registry._publication_semantic_text({"metadata": {}}, tmp_path, source)
    assert "Sensor encoder" in text and "Fusion module" in text
    assert "remote_url" not in text and "runtime_audit" not in text and "gpt_image" not in text


def test_missing_frozen_idea_remains_blocking_before_prompt_projection(tmp_path: Path) -> None:
    source = _protocol(tmp_path)
    before = source.read_bytes()
    issues = candidate_scientific_alignment_issues(figure_artifact_registry, tmp_path, _metadata(), source)
    assert issues == ["frozen selected-idea contract is missing or invalid"]
    assert source.read_bytes() == before


def test_missing_domain_label_is_not_supplied_from_manifest_metadata(tmp_path: Path) -> None:
    _idea(tmp_path)
    source = tmp_path / "qualitative.prompt.json"
    source.write_text(json.dumps({"prompt": "Sensor encoder only"}), encoding="utf-8")
    issues = candidate_scientific_alignment_issues(figure_artifact_registry, tmp_path, _metadata(), source)
    assert any("omits required domain-facing terms" in issue for issue in issues)
