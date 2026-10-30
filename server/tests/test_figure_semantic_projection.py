from __future__ import annotations

from server.services.figure_semantic_projection import (
    project_figure_semantics,
    semantic_projection_sha256,
)
from server.services.scientific_asset_routing import _design_brief


def _asset(
    contribution: str, role: str, objects: list[dict], relations: list[dict],
) -> dict:
    return {
        "scientific_role": role,
        "scientific_question": "What is the focal scientific relation?",
        "intended_comparison": "The focal transformation under controlled conditions",
        "scene_contract": {"contribution_type": contribution},
        "scientific_scene": {"objects": objects, "relations": relations},
    }


def test_method_projection_removes_downstream_evaluation_without_domain_terms() -> None:
    asset = _asset("system_architecture", "method", [
        {"id": "requests", "kind": "input", "label": "Incoming request stream", "source_path": "src/input.py"},
        {"id": "scheduler", "kind": "operation", "label": "Adaptive work scheduler", "source_path": "src/scheduler.py"},
        {"id": "workers", "kind": "state", "label": "Distributed worker state", "source_path": "src/workers.py"},
        {"id": "benchmark_inference", "kind": "operation", "label": "Held-out evaluation inference", "source_path": "src/evaluation.py"},
        {"id": "latency_endpoint", "kind": "output", "label": "Registered latency endpoint", "source_path": "src/evaluation.py"},
    ], [
        {"from": "requests", "to": "scheduler", "kind": "data"},
        {"from": "scheduler", "to": "workers", "kind": "data"},
        {"from": "workers", "to": "benchmark_inference", "kind": "data"},
        {"from": "benchmark_inference", "to": "latency_endpoint", "kind": "data"},
    ])
    projected = project_figure_semantics(asset)
    ids = {item["id"] for item in projected["entities_states_transformations"]}
    assert {"requests", "scheduler", "workers"} <= ids
    assert "benchmark_inference" not in ids
    assert "latency_endpoint" not in ids
    assert "downstream evaluation" in projected["excluded"]["latency_endpoint"]


def test_clinical_mechanism_keeps_intervention_and_state_but_not_endpoint_analysis() -> None:
    asset = _asset("clinical_biological_mechanism", "method", [
        {"id": "specimen", "kind": "input", "label": "Eligible specimen", "source_path": "protocol.md"},
        {"id": "intervention", "kind": "operation", "label": "Controlled intervention", "source_path": "protocol.md"},
        {"id": "cell_state", "kind": "state", "label": "Cell-state transition", "source_path": "analysis.py"},
        {"id": "outcome_analysis", "kind": "operation", "label": "Held-out outcome analysis", "source_path": "evaluation.py"},
        {"id": "clinical_endpoint", "kind": "output", "label": "Primary clinical endpoint", "source_path": "evaluation.py"},
    ], [
        {"from": "specimen", "to": "intervention", "kind": "data"},
        {"from": "intervention", "to": "cell_state", "kind": "causal"},
        {"from": "cell_state", "to": "outcome_analysis", "kind": "data"},
        {"from": "outcome_analysis", "to": "clinical_endpoint", "kind": "data"},
    ])
    projected = project_figure_semantics(asset)
    ids = {item["id"] for item in projected["entities_states_transformations"]}
    assert {"specimen", "intervention", "cell_state"} <= ids
    assert "clinical_endpoint" not in ids


def test_evaluation_projection_keeps_isolation_measurement_and_decision() -> None:
    asset = _asset("experimental_protocol", "evaluation_design", [
        {"id": "method_internal", "kind": "operation", "label": "Internal transformation block", "source_path": "method.py"},
        {"id": "heldout_partition", "kind": "input", "label": "Held-out partition", "source_path": "protocol.md"},
        {"id": "locked_measurement", "kind": "operation", "label": "Locked evaluation measurement", "source_path": "evaluation.py"},
        {"id": "unit_aggregation", "kind": "operation", "label": "Analysis unit aggregation", "source_path": "evaluation.py"},
        {"id": "decision", "kind": "output", "label": "Prespecified decision endpoint", "source_path": "protocol.md"},
    ], [
        {"from": "method_internal", "to": "locked_measurement", "kind": "data"},
        {"from": "heldout_partition", "to": "locked_measurement", "kind": "constraint"},
        {"from": "locked_measurement", "to": "unit_aggregation", "kind": "data"},
        {"from": "unit_aggregation", "to": "decision", "kind": "data"},
    ])
    projected = project_figure_semantics(asset)
    ids = {item["id"] for item in projected["entities_states_transformations"]}
    assert {"heldout_partition", "locked_measurement", "unit_aggregation", "decision"} <= ids
    assert "method_internal" in ids  # one-hop compact interface remains available


def test_theory_scene_is_preserved_without_ml_assumptions() -> None:
    asset = _asset("theory_proof", "method", [
        {"id": "assumption", "kind": "input", "label": "Assumption A", "source_path": "proof.tex"},
        {"id": "lemma", "kind": "operation", "label": "Lemma construction", "source_path": "proof.tex"},
        {"id": "theorem", "kind": "output", "label": "Main theorem", "source_path": "proof.tex"},
    ], [
        {"from": "assumption", "to": "lemma", "kind": "logical"},
        {"from": "lemma", "to": "theorem", "kind": "logical"},
    ])
    projected = project_figure_semantics(asset)
    assert {item["id"] for item in projected["entities_states_transformations"]} == {
        "assumption", "lemma", "theorem",
    }
    assert projected["excluded"] == {}


def test_prediction_objective_is_not_mistaken_for_downstream_evaluation() -> None:
    asset = _asset("objective_mechanism", "method", [
        {"id": "samples", "kind": "input", "label": "Observed samples", "source_path": "data.py"},
        {"id": "prediction_objective", "kind": "operation", "label": "Masked prediction objective", "source_path": "objectives.py"},
        {"id": "budget_guard", "kind": "input", "label": "Matched budget constraint", "source_path": "protocol.md"},
        {"id": "task_interface", "kind": "operation", "label": "Downstream task interface", "source_path": "model.py"},
        {"id": "heldout_evaluation", "kind": "operation", "label": "Held-out evaluation", "source_path": "evaluation.py"},
    ], [
        {"from": "samples", "to": "prediction_objective", "kind": "data"},
        {"from": "budget_guard", "to": "prediction_objective", "kind": "constraint"},
        {"from": "prediction_objective", "to": "task_interface", "kind": "data"},
        {"from": "task_interface", "to": "heldout_evaluation", "kind": "data"},
    ])
    asset["scientific_question"] = "How does the prediction objective transform observed samples?"
    projected = project_figure_semantics(asset)
    roles = projected["presentation_roles"]
    assert "prediction_objective" in roles["primary"]
    assert "budget_guard" in projected["excluded"]
    assert "task_interface" in projected["excluded"]
    assert "heldout_evaluation" in projected["excluded"]


def test_focal_control_remains_when_question_is_about_that_constraint() -> None:
    asset = _asset("clinical_biological_mechanism", "method", [
        {"id": "specimen", "kind": "input", "label": "Eligible specimen", "source_path": "protocol.md"},
        {"id": "intervention", "kind": "operation", "label": "Intervention response", "source_path": "method.md"},
        {"id": "eligibility_guard", "kind": "input", "label": "Eligibility constraint", "source_path": "protocol.md"},
    ], [
        {"from": "specimen", "to": "intervention", "kind": "data"},
        {"from": "eligibility_guard", "to": "intervention", "kind": "constraint"},
    ])
    asset["scientific_question"] = "How does eligibility constrain the intervention response?"
    projected = project_figure_semantics(asset)
    assert "eligibility_guard" in projected["presentation_roles"]["annotation_only"]


def test_method_projection_moves_audit_and_endpoint_to_companion_figure() -> None:
    asset = _asset("empirical_discovery", "method", [
        {"id": "source", "kind": "input", "label": "Observed signal", "source_path": "data.py"},
        {"id": "method", "kind": "operation", "label": "Matched objective process", "source_path": "method.py"},
        {"id": "audit", "kind": "operation", "label": "Proxy reliance audit", "source_path": "evaluation.py"},
        {"id": "decision", "kind": "output", "label": "Registered decision endpoint", "source_path": "protocol.md"},
    ], [
        {"from": "source", "to": "method", "kind": "data"},
        {"from": "method", "to": "audit", "kind": "data"},
        {"from": "audit", "to": "decision", "kind": "data"},
    ])
    asset.update({
        "figure_type": "evidence_pipeline",
        "narrative_level": "method_overview",
        "content_boundary": "Show the method; leave validation and audit to evaluation_design.",
        "production_strategy": "model_composed_full_svg",
        "composition_owner": "model",
        "full_svg_authority": True,
    })

    projected = project_figure_semantics(asset)
    identities = {
        item["id"] for item in projected["entities_states_transformations"]
    }

    assert identities == {"source", "method"}
    assert projected["excluded"]["audit"].startswith("downstream evaluation")
    assert projected["content_boundary"] == asset["content_boundary"]
    assert projected["full_svg_authority"] is True


def test_storyboard_hash_changes_with_portfolio_boundary_and_authority() -> None:
    asset = _asset("model_architecture", "method", [
        {"id": "source", "kind": "input", "label": "Input", "source_path": "a"},
        {"id": "process", "kind": "operation", "label": "Process", "source_path": "a"},
    ], [{"from": "source", "to": "process", "kind": "data"}])
    before = semantic_projection_sha256(asset)
    asset.update({
        "figure_type": "method_architecture",
        "narrative_level": "method_overview",
        "content_boundary": "Exclude downstream evaluation.",
        "production_strategy": "model_composed_full_svg",
        "composition_owner": "model",
        "full_svg_authority": True,
    })

    assert semantic_projection_sha256(asset) != before


def test_probe_mode_change_invalidates_storyboard_and_exposes_active_state() -> None:
    asset = _asset("objective_mechanism", "method", [
        {"id": "source", "kind": "input", "label": "Input", "source_path": "a"},
        {"id": "process", "kind": "operation", "label": "Process", "source_path": "a"},
    ], [{"from": "source", "to": "process", "kind": "data"}])
    state = {
        "name": "subject_session_probe", "mechanism_id": "M2",
        "training_mode": "unspecified", "head_status": "unverified_mode",
        "joint_objective_status": "inactive",
    }
    asset["method_brief"] = {"probe_configuration": [state]}
    before = semantic_projection_sha256(asset)
    projected = project_figure_semantics(asset)
    assert projected["probe_configuration"][0]["training_mode"] == "unspecified"

    state["training_mode"] = "frozen_downstream"
    state["head_status"] = "not_required"
    assert semantic_projection_sha256(asset) != before


def test_design_brief_excludes_only_labels_projected_to_companion_figure() -> None:
    asset = _asset("objective_mechanism", "method", [
        {
            "id": "m1_geometry", "kind": "operation",
            "label": "M1 normalized transportable geometry conditioning",
            "source_path": "method.py",
        },
        {
            "id": "m2_masked_prediction", "kind": "operation",
            "label": "M2 cross-time cross-channel masked prediction",
            "source_path": "method.py",
        },
        {
            "id": "m3_evaluation", "kind": "operation",
            "label": "M3 leakage-safe grouped transfer evaluation",
            "source_path": "evaluation.py",
        },
    ], [
        {"from": "m1_geometry", "to": "m2_masked_prediction", "kind": "data"},
        {"from": "m2_masked_prediction", "to": "m3_evaluation", "kind": "data"},
    ])
    asset["publication_labels"] = [
        {"display_text": "Transportable geometry conditioning"},
        {"display_text": "Spatiotemporal masked prediction"},
        {"display_text": "Leakage-safe transfer evaluation"},
    ]
    asset["content_boundary"] = (
        "Show the method; leave validation and evaluation to a companion figure."
    )

    projected = project_figure_semantics(asset)
    brief = _design_brief(asset)

    assert "m2_masked_prediction" not in projected["excluded"]
    assert "m3_evaluation" in projected["excluded"]
    assert brief["must_show"] == [
        "Transportable geometry conditioning",
        "Spatiotemporal masked prediction",
    ]
