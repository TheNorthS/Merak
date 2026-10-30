"""Pure regressions for current-only cross-node integration contracts."""

from __future__ import annotations

from pathlib import Path

import pytest

from server.contracts.entrypoints import (
    parse_python_entrypoint,
    python_entrypoint_refs,
)
from server.contracts.registry import (
    artifact_contract_registry,
    integration_contract_registry,
    workflow_artifact_contracts,
)
from server.contracts.writers import (
    versioned_artifact_write_error,
    versioned_payload_issues,
    write_versioned_artifact,
)
from server.contracts.repairs import repair_capability_for
from server.services.project_scaffold import WORKFLOW_ARTIFACT_CONTRACT, WORKFLOW_PATHS
from server.services.experiment_implementation import ExperimentImplementationService
from server.services.implementation_stage_validation import _validate_training
from server.services.implementation_stage_validation import integration_candidate_report
from server.contracts.implementation_evidence import ImplementationEvidencePatch
from server.services.implementation_dependencies import stage_semantic_inputs


def test_entrypoint_reference_splits_path_and_symbol() -> None:
    ref = parse_python_entrypoint("experiments/src/train.py:main")

    assert ref.path.as_posix() == "experiments/src/train.py"
    assert ref.symbol == "main"
    assert ref.serialized == "experiments/src/train.py:main"


def test_entrypoint_reference_accepts_typed_mapping() -> None:
    ref = parse_python_entrypoint({
        "path": "experiments/src/verify.py",
        "symbol": "Verifier.run",
    })

    assert ref.serialized == "experiments/src/verify.py:Verifier.run"


@pytest.mark.parametrize("value", [
    "../train.py:main",
    "C:/project/train.py:main",
    "experiments/src/train.txt:main",
    "experiments/src/train.py:not valid",
])
def test_entrypoint_reference_rejects_ambiguous_or_external_forms(value: str) -> None:
    with pytest.raises(ValueError):
        parse_python_entrypoint(value)


def test_entrypoint_validation_checks_file_and_symbol(tmp_path: Path) -> None:
    source = tmp_path / "experiments/src/train.py"
    source.parent.mkdir(parents=True)
    source.write_text("def run():\n    return 1\n\ndef main():\n    return run()\n")

    assert parse_python_entrypoint(
        "experiments/src/train.py:main"
    ).validation_issues(tmp_path) == []
    assert "symbol is absent" in parse_python_entrypoint(
        "experiments/src/train.py:missing"
    ).validation_issues(tmp_path)[0]


def test_command_and_direct_entrypoints_share_one_parser(tmp_path: Path) -> None:
    source = tmp_path / "experiments/src/train.py"
    source.parent.mkdir(parents=True)
    source.write_text("def main():\n    return None\n")
    values = [
        "experiments/src/train.py:main",
        "python experiments/src/train.py --config experiments/configs/main.yaml",
    ]

    refs = python_entrypoint_refs(values)
    resolved = ExperimentImplementationService._entrypoints(
        tmp_path,
        {"entrypoint": values[0], "command": values[1]},
    )

    assert [item.serialized for item in refs] == [
        "experiments/src/train.py:main",
        "experiments/src/train.py",
    ]
    assert resolved == [source.resolve()]


def test_training_gate_accepts_path_symbol_entrypoint(tmp_path: Path) -> None:
    source = tmp_path / "experiments/src/train.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "def main():\n"
        "    optimizer = Optimizer()\n"
        "    for batch in batches:\n"
        "        loss = objective(batch)\n"
        "        loss.backward()\n"
        "        optimizer.step()\n",
        encoding="utf-8",
    )

    issues = _validate_training(
        "machine_learning",
        tmp_path,
        source.read_text(encoding="utf-8"),
        source.read_text(encoding="utf-8").casefold(),
        {"entrypoint": "experiments/src/train.py:main"},
    )

    assert issues == []


def test_central_registry_declares_owner_validator_and_failure_policy() -> None:
    selected = artifact_contract_registry["selected_idea"]
    method = artifact_contract_registry["method_contract"]
    entrypoint = integration_contract_registry["python_entrypoint"]

    assert selected.owner == "novelty" and selected.validator == "selected-idea-v2"
    assert method.owner == "exp-design" and "figure" in method.consumers
    assert entrypoint.failure_policy == "route_to_owner"
    assert entrypoint.owner == "exp-design"


def test_project_scaffold_uses_central_workflow_artifact_registry() -> None:
    projected = {
        node_id: {"primary": value.primary, "required": value.required}
        for node_id, value in workflow_artifact_contracts.items()
    }

    assert WORKFLOW_ARTIFACT_CONTRACT == projected
    assert set(WORKFLOW_ARTIFACT_CONTRACT) == {
        "lit", "idea", "novelty", "exp-design", "exp-run", "results",
        "figure", "narrative", "paper", "review", "audit", "compile", "ppt",
    }


def test_exp_design_owns_the_typed_integration_patch() -> None:
    contract = WORKFLOW_ARTIFACT_CONTRACT["exp-design"]
    assert "experiments/IMPLEMENTATION_EVIDENCE_PATCH.json" in contract["required"]
    assert "experiments/IMPLEMENTATION_EVIDENCE_PATCH.json" in WORKFLOW_PATHS[
        "exp-design"
    ]["write"]


def test_core_versioned_artifacts_have_one_owner_and_validator() -> None:
    paths = [contract.path for contract in artifact_contract_registry.values()]

    assert len(paths) == len(set(paths))
    assert all(contract.owner for contract in artifact_contract_registry.values())
    assert all(contract.validator for contract in artifact_contract_registry.values())


def test_selected_idea_is_rejected_before_old_schema_write(tmp_path: Path) -> None:
    target = tmp_path / "ideas/SELECTED_IDEA.json"
    content = '{"schema": 1, "title": "old"}'

    error = versioned_artifact_write_error(tmp_path, target, content)

    assert "current schema=2" in error
    assert not target.exists()


def test_implemented_method_requires_canonical_evidence(tmp_path: Path) -> None:
    payload = {
        "schema": 2,
        "status": "implemented",
        "scientific_scene": {"schema": 1, "objects": [], "relations": []},
        "implementation_checks": [{"id": "I1", "description": "route"}],
    }

    issues = versioned_payload_issues("method_contract", payload)

    assert "implementation_checks[0].evidence is required when implemented" in issues
    with pytest.raises(ValueError, match="evidence is required"):
        write_versioned_artifact(tmp_path, "method_contract", payload)


def test_run_spec_uses_current_schema_and_required_execution_contract() -> None:
    payload = {
        "schema": 1,
        "implementation_family": "machine_learning",
        "entrypoint": "experiments/src/train.py:main",
        "outputs": {"per_run_files": ["metrics.json"]},
    }

    assert versioned_payload_issues("run_spec", payload) == []
    payload.pop("outputs")
    assert "outputs object is required" in versioned_payload_issues("run_spec", payload)


def test_evidence_patch_is_validated_by_the_registered_writer() -> None:
    payload = {
        "schema": 1,
        "checks": [{
            "check_id": "I1",
            "description": "entrypoint reaches evaluation",
            "evidence": [{
                "path": "experiments/src/train.py",
                "symbols": ["main"],
            }],
        }],
    }

    assert versioned_payload_issues("implementation_evidence_patch", payload) == []
    payload["checks"][0]["evidence"][0].pop("symbols")
    assert "typed selector" in versioned_payload_issues(
        "implementation_evidence_patch", payload,
    )[0]


def test_repair_capability_routes_entrypoint_to_contract_owner() -> None:
    capability = repair_capability_for(
        message="training stage did not create the declared entrypoint",
        target_files=["experiments/src/train.py"],
        category="staged_implementation",
    )

    assert capability is not None
    assert capability.identity == "python-entrypoint-contract"
    assert capability.owner == "exp-design"


def test_repair_capability_routes_font_failure_to_figure_layout() -> None:
    capability = repair_capability_for(
        message="placed SVG text falls below 8 pt",
        target_files=["figures/diagrams/evaluation_design.svg"],
        category="visual_layout",
    )

    assert capability is not None
    assert capability.identity == "figure-layout"


def test_stage_dependencies_do_not_bind_every_stage_to_plan_prose(
    tmp_path: Path,
) -> None:
    data = {path.relative_to(tmp_path).as_posix() for path in stage_semantic_inputs(tmp_path, "data")}
    integration = {
        path.relative_to(tmp_path).as_posix()
        for path in stage_semantic_inputs(tmp_path, "integration")
    }

    assert "experiments/EXPERIMENT_PLAN.md" not in data
    assert "experiments/EXPERIMENT_PLAN.md" in integration
    assert "experiments/METHOD_CONTRACT.json" not in data
    assert "experiments/METHOD_CONTRACT.json" in integration


def test_integration_candidate_ignores_only_runtime_owned_status() -> None:
    candidate = integration_candidate_report({
        "passed": False,
        "output_sha256": "d" * 64,
        "issues": [
            "integration stage did not finalize METHOD_CONTRACT.status as implemented",
            "integration METHOD_CONTRACT: method contract status must be implemented, ready, or complete",
        ],
    })
    blocked = integration_candidate_report({
        "passed": False,
        "output_sha256": "d" * 64,
        "issues": ["implementation check has no evidence"],
    })

    assert candidate["passed"] is True
    assert blocked["passed"] is False


def test_typed_evidence_patch_rejects_untyped_or_empty_evidence() -> None:
    with pytest.raises(ValueError, match="typed selector"):
        ImplementationEvidencePatch.parse({
            "check_id": "I1",
            "description": "route",
            "evidence": [{"path": "experiments/src/train.py"}],
        })


def test_model_cannot_finalize_method_lifecycle(tmp_path: Path) -> None:
    target = tmp_path / "experiments/METHOD_CONTRACT.json"
    target.parent.mkdir(parents=True)
    target.write_text('{"schema":2,"status":"implementation_in_progress"}')
    content = (
        '{"schema":2,"status":"implemented",'
        '"scientific_scene":{},"implementation_checks":[]}'
    )

    error = versioned_artifact_write_error(
        tmp_path, target, content, model_authored=True,
    )

    assert "runtime-owned" in error


def test_model_cannot_downgrade_completed_method_lifecycle(tmp_path: Path) -> None:
    target = tmp_path / "experiments/METHOD_CONTRACT.json"
    target.parent.mkdir(parents=True)
    target.write_text('{"schema":2,"status":"implemented"}')
    content = (
        '{"schema":2,"status":"implementation_in_progress",'
        '"scientific_scene":{"schema":1,"objects":[{'
        '"id":"method","kind":"operation","label":"Method",'
        '"source_path":"experiments/src/model.py"}],"relations":[]},'
        '"implementation_checks":[]}'
    )

    error = versioned_artifact_write_error(
        tmp_path, target, content, model_authored=True,
    )

    assert "lifecycle status is runtime-owned" in error


def test_method_writer_rejects_unsupported_scene_kinds() -> None:
    payload = {
        "schema": 2, "status": "implementation_in_progress",
        "implementation_checks": [],
        "scientific_scene": {
            "schema": 1,
            "objects": [{
                "id": "probability", "kind": "intermediate",
                "label": "Probability", "source_path": "experiments/src/model.py",
            }],
            "relations": [],
        },
    }

    issues = versioned_payload_issues("method_contract", payload)

    assert "probability: unsupported scientific object kind" in issues
