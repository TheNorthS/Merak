from __future__ import annotations

import json

from server.services.method_contract import (
    method_contract_service,
    normalize_claim_evidence_plan,
    normalize_implementation_evidence,
)
from server.services.node_risk_audit import node_risk_audit_service


def test_claim_evidence_alternate_keys_are_not_promoted() -> None:
    normalized = normalize_claim_evidence_plan([{
        "claim_id": "C1",
        "discriminating_observation": "Outcome differs under the mechanism.",
        "analysis": "The claim fails when the outcome does not differ.",
    }])
    assert "idea_claim_id" not in normalized[0]
    assert "outcomes" not in normalized[0]
    assert "failure_conditions" not in normalized[0]


def test_claim_evidence_prose_does_not_create_required_fields() -> None:
    normalized = normalize_claim_evidence_plan([{
        "claim_id": "C1",
        "observation": "Compare the full method with matched controls.",
        "endpoint_and_decision": (
            "Support requires the confidence-interval lower bound to exceed zero."
        ),
        "alternative_explanations": ["capacity", "leakage"],
    }])

    assert "idea_claim_id" not in normalized[0]
    assert "outcomes" not in normalized[0]
    assert "failure_conditions" not in normalized[0]
    assert normalized[0]["alternative_explanations"] == ["capacity", "leakage"]


def test_structured_register_output_key_alias_is_normalized() -> None:
    normalized = normalize_implementation_evidence({
        "source_artifacts": ["experiments/src/models.py"],
        "output_keys": ["three_endpoint_payload"],
    })

    assert normalized == [{
        "path": "experiments/src/models.py",
        "_structured_register": True,
        "data_keys": ["three_endpoint_payload"],
    }]


def _write_idea(root):
    ideas = root / "ideas"
    experiments = root / "experiments"
    ideas.mkdir(parents=True)
    experiments.mkdir(parents=True)
    payload = {
        "schema": 2,
        "status": "accepted",
        "title": "A Contract-Bound Method",
        "problem_statement": "A concrete problem.",
        "hypothesis": "The method changes the primary outcome under the declared split.",
        "claims": [
            {"id": "C1", "statement": "The method improves the primary outcome.", "publication_statement": "The method improves the primary outcome."},
            {"id": "C2", "statement": "The mechanism is necessary.", "publication_statement": "The mechanism is necessary."},
        ],
        "mechanisms": [
            {"id": "M1", "name": "Mechanism one", "description": "Required operation.", "publication_name": "Mechanism one", "publication_description": "Required scientific operation.", "publication_evaluation": "Matched removal comparison.", "required": True},
            {"id": "M2", "name": "Mechanism two", "description": "Required control.", "publication_name": "Mechanism two", "publication_description": "Required scientific control.", "publication_evaluation": "Matched control comparison.", "required": True},
        ],
        "falsification_conditions": ["The primary outcome does not improve."],
        "nearest_prior_work": [{"title": "A strong baseline"}],
        "publication": {"language": "en", "title": "A Contract-Bound Method", "method_name": "Contract-bound method", "contribution_type": "objective_mechanism", "comparator_names": ["Contract-bound method", "Matched baseline"]},
    }
    (ideas / "SELECTED_IDEA.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    (ideas / "novelty_report.md").write_text(
        "# Novelty\n\nA Contract-Bound Method\n", encoding="utf-8"
    )
    (experiments / "EXPERIMENT_PLAN.md").write_text(
        "# Experiment Plan\n\nA Contract-Bound Method\n", encoding="utf-8"
    )
    (experiments / "METHOD_CONTRACT.json").write_text(
        json.dumps(method_contract_service.scaffold_method_contract("")),
        encoding="utf-8",
    )


def test_design_only_recovers_a_complete_planned_contract(tmp_path):
    _write_idea(tmp_path)

    assert method_contract_service.ensure_planned_method_contract(tmp_path)
    payload = json.loads(
        (tmp_path / "experiments" / "METHOD_CONTRACT.json").read_text(encoding="utf-8")
    )
    assert payload["status"] == "planned"
    assert payload["evidence_status"] == "design_only_not_evidence"
    assert len(payload["scientific_scene"]["objects"]) == 3
    assert {
        item["kind"] for item in payload["scientific_scene"]["relations"]
    } == {"containment"}
    assert {item["idea_mechanism_id"] for item in payload["mechanism_coverage"]} == {"M1", "M2"}
    assert {item["idea_claim_id"] for item in payload["claim_evidence_plan"]} == {"C1", "C2"}

    valid, issues, details = method_contract_service.validate_method_contract(
        tmp_path,
        "A Contract-Bound Method",
        allow_planned=True,
    )
    assert valid, issues
    assert details["implementation_pending"] is True

    strict_valid, strict_issues, _ = method_contract_service.validate_method_contract(
        tmp_path,
        "A Contract-Bound Method",
    )
    assert not strict_valid
    assert any("status" in issue for issue in strict_issues)


def test_method_owner_rejects_missing_scene_before_figure_planning(tmp_path):
    _write_idea(tmp_path)
    assert method_contract_service.ensure_planned_method_contract(tmp_path)
    path = tmp_path / "experiments" / "METHOD_CONTRACT.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.pop("scientific_scene")
    path.write_text(json.dumps(payload), encoding="utf-8")

    valid, issues, _ = method_contract_service.validate_method_contract(
        tmp_path,
        "A Contract-Bound Method",
        allow_planned=True,
    )

    assert valid is False
    assert "scientific_scene must use schema=1" in issues

    preflight = node_risk_audit_service.preflight_node(
        tmp_path,
        "figure",
        {"run_experiment": False, "gpu_target": "none"},
    )
    assert any(
        item.get("upstream_node") == "exp-design"
        and "scientific_scene" in str(item.get("message") or "")
        for item in preflight
    )


def test_integration_finalization_keeps_current_schema_and_scene(tmp_path):
    _write_idea(tmp_path)
    assert method_contract_service.ensure_planned_method_contract(tmp_path)
    path = tmp_path / "experiments" / "METHOD_CONTRACT.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["implementation_checks"] = [{
        "id": "I1",
        "description": "Bounded integration route",
        "evidence": [{
            "path": "experiments/src/controller.py",
            "symbols": ["controller"],
        }],
    }]
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert method_contract_service.finalize_integration_contract(
        tmp_path, {"passed": True, "output_sha256": "a" * 64},
    )
    payload = json.loads(
        (tmp_path / "experiments" / "METHOD_CONTRACT.json").read_text(
            encoding="utf-8"
        )
    )

    assert payload["schema"] == 2
    assert payload["status"] == "implemented"
    assert payload["scientific_scene"]["objects"]


def test_planned_contract_recovery_does_not_overwrite_authored_design(tmp_path):
    _write_idea(tmp_path)
    path = tmp_path / "experiments" / "METHOD_CONTRACT.json"
    authored = {
        "schema": 2,
        "status": "planned",
        "selected_idea": "A Contract-Bound Method",
        "mechanism_coverage": [{"idea_mechanism_id": "M1"}],
    }
    path.write_text(json.dumps(authored), encoding="utf-8")

    assert not method_contract_service.ensure_planned_method_contract(tmp_path)
    assert json.loads(path.read_text(encoding="utf-8")) == authored


def test_experiment_plan_scaffold_text_is_a_blocker(tmp_path):
    _write_idea(tmp_path)
    assert method_contract_service.ensure_planned_method_contract(tmp_path)
    (tmp_path / "experiments" / "EXPERIMENT_PLAN.md").write_text(
        "# Experiment Plan\n\nProblem: [What problem does your method solve?]\n",
        encoding="utf-8",
    )

    report = node_risk_audit_service.audit_node(
        tmp_path,
        "exp-design",
        {"run_experiment": False},
        persist=False,
    )
    finding = next(
        item for item in report["findings"]
        if item.get("id") == "DESIGN-TEMPLATE-001"
    )

    assert finding["severity"] == "blocker"
    assert report["blocking"] is True


def test_structured_implementation_evidence_register_is_validated(tmp_path):
    _write_idea(tmp_path)
    source = tmp_path / "experiments" / "src" / "controller.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "def invariant_controller(state):\n    return state\n",
        encoding="utf-8",
    )
    config = tmp_path / "experiments" / "configs" / "main.yaml"
    config.parent.mkdir(parents=True)
    config.write_text("seed: 1\n", encoding="utf-8")
    (tmp_path / "experiments" / "RUN_SPEC.json").write_text(
        json.dumps({"command": "python experiments/src/controller.py"}),
        encoding="utf-8",
    )
    accepted, idea_issues, idea_details = method_contract_service.validate_selected_idea(
        tmp_path,
        "A Contract-Bound Method",
    )
    assert accepted, idea_issues
    contract = {
        "schema": 2,
        "status": "implemented",
        "selected_idea": "A Contract-Bound Method",
        "idea_contract_path": "ideas/SELECTED_IDEA.json",
        "idea_contract_sha256": idea_details["sha256"],
        "implementation_checks": [{
            "id": "I1",
            "description": "Structured implementation evidence",
            "evidence": {
                "source_artifacts": [
                    "experiments/src/controller.py",
                    "experiments/configs/main.yaml",
                    "experiments/RUN_SPEC.json",
                ],
                "observable_outputs": ["integration_check.json"],
                "observation": "The controller and configuration are project-local.",
                "acceptance_criterion": "All registered source artifacts exist.",
                "evidence_status": "implementation_check_only",
            },
        }],
        "mechanism_coverage": [
            {"idea_mechanism_id": "M1", "implementation_check_ids": ["I1"]},
            {"idea_mechanism_id": "M2", "implementation_check_ids": ["I1"]},
        ],
        "claim_evidence_plan": [
            {
                "idea_claim_id": "C1",
                "outcomes": ["primary outcome"],
                "failure_conditions": ["no improvement"],
            },
            {
                "idea_claim_id": "C2",
                "outcomes": ["component effect"],
                "failure_conditions": ["component is unnecessary"],
            },
        ],
        "evaluation_contract": {
            "primary_outcomes": ["primary outcome"],
            "comparators_or_controls": ["baseline"],
            "component_tests": ["ablation"],
            "failure_conditions": ["no improvement"],
        },
        "scientific_scene": {"schema": 1, "objects": [{
            "id": "controller", "kind": "operation", "label": "Contract-bound controller",
            "source_path": "experiments/src/controller.py",
        }], "relations": []},
    }
    (tmp_path / "experiments" / "METHOD_CONTRACT.json").write_text(
        json.dumps(contract),
        encoding="utf-8",
    )

    valid, issues, details = method_contract_service.validate_method_contract(
        tmp_path,
        "A Contract-Bound Method",
    )

    assert valid, issues
    assert len(details["implementation_checks"]["I1"]) == 3
    assert all(
        item.get("source_artifact_verified") is True
        for item in details["implementation_checks"]["I1"]
    )


def test_staged_obligation_evidence_alias_is_validated(tmp_path):
    _write_idea(tmp_path)
    source = tmp_path / "experiments" / "src" / "controller.py"
    source.parent.mkdir(parents=True)
    source.write_text("def controller(value):\n    return value\n", encoding="utf-8")
    accepted, idea_issues, idea_details = method_contract_service.validate_selected_idea(
        tmp_path,
        "A Contract-Bound Method",
    )
    assert accepted, idea_issues
    contract = {
        "schema": 2,
        "status": "implemented",
        "selected_idea": "A Contract-Bound Method",
        "idea_contract_path": "ideas/SELECTED_IDEA.json",
        "idea_contract_sha256": idea_details["sha256"],
        "implementation_checks": [{
            "id": "I1",
            "description": "Staged implementation obligation",
            "status": "pending_stage_execution",
            "requirement": "The controller route must remain reachable.",
            "future_owner_targets": ["experiments/src/controller.py"],
            "required_runtime_evidence": [{"path": "results/check.json"}],
            "pass_observation": "The controller source is present and auditable.",
            "failure_action": "Fail closed.",
        }],
        "mechanism_coverage": [
            {"idea_mechanism_id": "M1", "implementation_check_ids": ["I1"]},
            {"idea_mechanism_id": "M2", "implementation_check_ids": ["I1"]},
        ],
        "claim_evidence_plan": [
            {"idea_claim_id": "C1", "outcomes": ["outcome"], "failure_conditions": ["failure"]},
            {"idea_claim_id": "C2", "outcomes": ["outcome"], "failure_conditions": ["failure"]},
        ],
        "evaluation_contract": {
            "primary_outcomes": ["outcome"],
            "comparators_or_controls": ["control"],
            "component_tests": ["ablation"],
            "failure_conditions": ["failure"],
        },
        "scientific_scene": {"schema": 1, "objects": [{
            "id": "controller", "kind": "operation", "label": "Contract-bound controller",
            "source_path": "experiments/src/controller.py",
        }], "relations": []},
    }
    (tmp_path / "experiments" / "METHOD_CONTRACT.json").write_text(
        json.dumps(contract), encoding="utf-8"
    )

    valid, issues, details = method_contract_service.validate_method_contract(
        tmp_path,
        "A Contract-Bound Method",
    )

    assert valid, issues
    assert details["implementation_checks"]["I1"][0]["source_artifact_verified"] is True


def test_alternate_check_keys_are_rejected_without_rewriting(tmp_path):
    _write_idea(tmp_path)
    source = tmp_path / "experiments" / "src" / "controller.py"
    source.parent.mkdir(parents=True)
    source.write_text("def controller(value):\n    return value\n", encoding="utf-8")
    accepted, idea_issues, idea_details = method_contract_service.validate_selected_idea(
        tmp_path,
        "A Contract-Bound Method",
    )
    assert accepted, idea_issues
    contract = {
        "schema": 2,
        "status": "implemented",
        "selected_idea": "A Contract-Bound Method",
        "idea_contract_path": "ideas/SELECTED_IDEA.json",
        "idea_contract_sha256": idea_details["sha256"],
        "implementation_checks": [{
            "check_id": "I1",
            "purpose": "Alias-shaped implementation check",
            "evidence": [{
                "path": "experiments/src/controller.py",
                "symbols": ["controller"],
                "anchors": ["optional explanatory prose that is not source evidence"],
            }],
        }],
        "mechanism_coverage": [
            {"idea_mechanism_id": "M1", "implementation_check_ids": ["I1"]},
            {"idea_mechanism_id": "M2", "implementation_check_ids": ["I1"]},
        ],
        "claim_evidence_plan": [
            {"idea_claim_id": "C1", "outcomes": ["outcome"], "failure_conditions": ["failure"]},
            {"idea_claim_id": "C2", "outcomes": ["outcome"], "failure_conditions": ["failure"]},
        ],
        "evaluation_contract": {
            "primary_outcomes": ["outcome"],
            "comparators_or_controls": ["control"],
            "component_tests": ["ablation"],
            "failure_conditions": ["failure"],
        },
        "scientific_scene": {"schema": 1, "objects": [{
            "id": "controller", "kind": "operation",
            "label": "Contract-bound controller",
            "source_path": "experiments/src/controller.py",
        }], "relations": []},
    }
    (tmp_path / "experiments" / "METHOD_CONTRACT.json").write_text(
        json.dumps(contract), encoding="utf-8"
    )

    valid, issues, details = method_contract_service.validate_method_contract(
        tmp_path,
        "A Contract-Bound Method",
    )

    assert valid is False
    assert "implementation_checks[0] requires id and description" in issues
    stored = json.loads(
        (tmp_path / "experiments/METHOD_CONTRACT.json").read_text(encoding="utf-8")
    )
    assert stored["implementation_checks"][0]["check_id"] == "I1"
    assert "id" not in stored["implementation_checks"][0]


def test_python_data_keys_are_structural_evidence_not_missing_symbols(tmp_path):
    source = tmp_path / "experiments" / "src" / "model.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "def real_function(batch):\n"
        "    mask = batch.get('channel_presence_mask')\n"
        "    return {\n"
        "        'three_endpoint_payload': mask,\n"
        "        'valid_patch_mask': batch['valid_patch_mask'],\n"
        "    }\n",
        encoding="utf-8",
    )

    issues, matched = method_contract_service._validate_evidence(
        tmp_path,
        "IC-M1",
        {
            "path": "experiments/src/model.py",
            "symbols": [
                "real_function",
                "channel_presence_mask",
                "three_endpoint_payload",
            ],
            "data_keys": ["valid_patch_mask"],
        },
    )

    assert issues == []
    assert matched["symbols"] == ["real_function"]
    assert set(matched["data_keys"]) == {
        "channel_presence_mask",
        "three_endpoint_payload",
        "valid_patch_mask",
    }
    assert set(matched["selector_kinds_passed"]) == {"data_keys", "symbols"}


def test_python_data_key_comment_cannot_satisfy_evidence(tmp_path):
    source = tmp_path / "experiments" / "src" / "model.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "# output key: valid_patch_mask\n"
        "def model(value):\n"
        "    return value\n",
        encoding="utf-8",
    )

    issues, matched = method_contract_service._validate_evidence(
        tmp_path,
        "IC-M3",
        {
            "path": "experiments/src/model.py",
            "data_keys": ["valid_patch_mask"],
        },
    )

    assert matched["passed"] is False
    assert any("missing declared data/output key" in issue for issue in issues)


def test_hyphenated_nested_yaml_config_key_is_validated(tmp_path):
    config = tmp_path / "experiments" / "configs" / "main.yaml"
    config.parent.mkdir(parents=True)
    config.write_text(
        "objectives:\n"
        "  ablations:\n"
        "    full_joint:\n"
        "      M-1: true\n",
        encoding="utf-8",
    )

    issues, matched = method_contract_service._validate_evidence(
        tmp_path,
        "IC-ABLATION",
        {
            "path": "experiments/configs/main.yaml",
            "config_keys": ["objectives.ablations.full_joint.M-1"],
        },
    )

    assert issues == []
    assert matched["config_keys"] == ["objectives.ablations.full_joint.M-1"]
