"""Evaluation figure labels remain publication-facing through planning and review."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.services.figure_artifacts import figure_artifact_registry
from server.services.evaluation_design_contract import (
    declared_removal_conditions, is_heldout_split,
)
from server.services.figure_scientific_alignment import candidate_scientific_alignment_issues
from server.services.figure_semantic_projection import semantic_projection_sha256
from server.services.figure_spec_repository import persist_figure_specs
from server.services.scientific_asset_builders import _evaluation_protocol
from server.services.scientific_assets import scientific_asset_service


def _write_contract(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_evaluation_protocol_omits_undeclared_facts() -> None:
    assert _evaluation_protocol({"conditions": ["hybrid"]}) == {}
    assert _evaluation_protocol({
        "scientific_outputs": {"analysis_unit": 12},
        "data_dependency": {"analysis_unit": "subject", "require_external_group": False},
    }) == {"analysis_unit": "subject", "require_external_group": False}


def test_evaluation_labels_reflect_only_declared_split_and_removal() -> None:
    assert declared_removal_conditions(["hybrid", "remove temporal", "ablation channel"])
    assert declared_removal_conditions(["hybrid", "temporal-only"]) == []
    assert is_heldout_split("external_test")
    assert is_heldout_split("held-out cohort")
    assert not is_heldout_split("follow_up")


@pytest.mark.parametrize("conditions,expected_labels", [
    (["hybrid", "remove temporal"],
     ["Masked prediction", "Matched removal", "Held-out test"]),
    (["hybrid"], ["Masked prediction", "Held-out test"]),
])
def test_evaluation_plan_spec_and_alignment_use_public_name_not_mechanism_id(
    tmp_path: Path, conditions: list[str], expected_labels: list[str],
) -> None:
    _write_contract(tmp_path / "ideas/SELECTED_IDEA.json", {
        "schema": 2, "status": "accepted", "title": "Masked prediction transfer",
        "hypothesis": "Masked prediction improves held-out transfer.",
        "claims": [{"id": "C1", "publication_statement":
                    "Masked prediction improves held-out transfer."}],
        "mechanisms": [{"id": "M1", "publication_name": "Masked prediction",
                        "publication_description": "Predicts missing observations."}],
        "recommended_baselines_or_comparators": ["Temporal-only control"],
        "publication": {"language": "en", "method_name": "Masked transfer",
                        "contribution_type": "objective_mechanism"},
    })
    _write_contract(tmp_path / "experiments/METHOD_CONTRACT.json", {
        "schema": 2, "status": "implemented",
        "evaluation_contract": {"comparators_or_controls": ["Temporal-only control"],
            "primary_comparator": "Temporal-only control", "focal_condition": "Masked prediction",
            "primary_outcomes": ["Held-out transfer"]},
        "scientific_scene": {
            "schema": 1,
            "objects": [
                {"id": "source", "kind": "input", "label": "Observed signal",
                 "source_path": "ideas/SELECTED_IDEA.json"},
                {"id": "prediction", "kind": "operation", "label": "Masked prediction",
                 "source_path": "experiments/METHOD_CONTRACT.json"},
            ],
            "relations": [{"from": "source", "to": "prediction", "kind": "data"}],
        },
    })
    _write_contract(tmp_path / "experiments/RUN_SPEC.json", {
        "schema": 1, "conditions": conditions,
        "data_dependency": {
            "analysis_unit": "subject",
            "required_splits": ["pretrain", "validation", "external_test"],
            "require_subject_isolation": True,
            "require_session_isolation": True,
            "require_external_group": True,
        },
        "scientific_outputs": {
            "primary_split": "external_test", "analysis_unit": "subject",
        },
    })

    plan = scientific_asset_service.build_plan(
        tmp_path, experiment_requested=False, requested_evidence_mode="design_only",
    )
    planned = next(item for item in plan["assets"] if item["id"] == "evaluation_design")
    specs = persist_figure_specs(tmp_path, plan)
    spec = next(item for item in specs if item["id"] == "evaluation_design")
    public_labels = [item["display_text"] for item in spec["publication_labels"]]

    assert public_labels == expected_labels
    assert planned["design_brief"]["must_show"] == public_labels
    assert spec["design_brief"]["must_show"] == public_labels
    assert spec["method_brief"]["mechanism_nodes"][0]["id"] == "M1"
    assert spec["method_brief"]["study_conditions"] == conditions
    assert spec["method_brief"]["evaluation_protocol"] == {
        "primary_split": "external_test", "analysis_unit": "subject",
        "required_splits": ["pretrain", "validation", "external_test"],
        "require_subject_isolation": True,
        "require_session_isolation": True,
        "require_external_group": True,
    }
    assert "M1" not in " ".join(public_labels)
    old_contract = {**spec, "publication_labels": [
        {**spec["publication_labels"][0], "display_text": "M1 Masked prediction"},
        *spec["publication_labels"][1:],
    ]}
    assert semantic_projection_sha256(old_contract) != semantic_projection_sha256(spec)

    source = tmp_path / "figures/evaluation_design.svg"
    source.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg">'
        + "".join(f"<text>{label}</text>" for label in expected_labels)
        + '</svg>',
        encoding="utf-8",
    )
    metadata = {**spec, "semantic_key": "evaluation_design"}
    issues = candidate_scientific_alignment_issues(
        figure_artifact_registry, tmp_path, metadata, source,
    )
    assert issues == []

    source.write_text(source.read_text(encoding="utf-8").replace(
        "Masked prediction", "Mechanism M1 Masked prediction",
    ), encoding="utf-8")
    issues = candidate_scientific_alignment_issues(
        figure_artifact_registry, tmp_path, metadata, source,
    )
    assert any("internal contract IDs" in issue for issue in issues)
