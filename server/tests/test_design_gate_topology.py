"""Design acceptance precedes result production; preview gates cannot form a cycle."""

from pathlib import Path

import pytest

from server.workflows.engine import WorkflowEngine
from server.workflows.models import WorkflowRun


@pytest.mark.parametrize("mode", ["design_only", "synthetic_preview", "existing_results"])
def test_design_gate_does_not_require_downstream_result_manifest(tmp_path, mode):
    engine = WorkflowEngine()
    run = WorkflowRun(project_path=str(tmp_path), options={
        "run_experiment": False, "non_experiment_evidence_mode": mode,
        "staged_experiment_implementation": True,
    })
    design = engine._gate_requirements_for_node(run, "exp-design")
    relative = {path.relative_to(tmp_path).as_posix() for path in design}
    assert "experiments/IMPLEMENTATION_BUILD.json" in relative
    assert not any(path.startswith("experiments/results/") for path in relative)
    if mode != "existing_results":
        execution = engine._gate_requirements_for_node(run, "exp-run")
        assert tmp_path / "experiments/results/templates/PLANNED_RESULT_MANIFEST.json" in execution


def test_design_artifact_check_accepts_complete_owner_files_without_result_execution(tmp_path):
    engine = WorkflowEngine()
    run = WorkflowRun(project_path=str(tmp_path), options={"run_experiment": False})
    # Write only the producer's declared inventory; no downstream results directory.
    for path in engine._required_artifacts_for_node(str(tmp_path), "exp-design"):
        if path.suffix:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture")
        else:
            path.mkdir(parents=True, exist_ok=True)
            (path / "fixture.txt").write_text("fixture")
    requirements = engine._gate_requirements_for_node(run, "exp-design")
    assert all(path.exists() for path in requirements)
    assert not (tmp_path / "experiments/results").exists()


@pytest.mark.parametrize("mode", ["design_only", "synthetic_preview", "existing_results", "secondary_analysis"])
def test_public_design_risk_gate_never_requires_future_result_outputs(tmp_path, mode):
    from server.services.node_risk_audit import node_risk_audit_service

    options = {"run_experiment": False, "non_experiment_evidence_mode": mode}
    report = node_risk_audit_service.audit_node(tmp_path, "exp-design", options, persist=False)
    findings = report["findings"]
    assert not any(item["category"] == "risk_validator" for item in findings)
    assert any(item["id"] == "DESIGN-PLAN-001" for item in findings)
    assert report["blocking"]  # Missing design-owned artifacts still block acceptance.
    assert not any(
        path.startswith("experiments/results/")
        for item in findings for path in item.get("evidence", [])
    )
    assert not (tmp_path / "experiments/results").exists()

    if mode in {"design_only", "synthetic_preview"}:
        execution = node_risk_audit_service.audit_node(tmp_path, "exp-run", options, persist=False)
        missing = [item for item in execution["findings"] if item["id"] == "RUN-PLANNED-001"]
        assert execution["blocking"] and len(missing) == 1
        assert missing[0]["owner_node"] == "exp-run"
        assert missing[0]["evidence"] == [
            "experiments/results/templates/PLANNED_RESULT_MANIFEST.json"
        ]


def test_fresh_consumer_acceptance_ends_old_owner_transaction(tmp_path):
    from server.workflows.run_state import RunState
    from server.workflows.models import WorkflowNode
    from server.workflows.interruption_checkpoint import record_interruption

    state = RunState(str(tmp_path), "topology-repair")
    state.start([{"id": key, "name": key, "skill": key} for key in ("exp-design", "exp-run", "paper")], {})
    state.update_state(lambda value: value.update(active_owner_revision={
        "owner_node": "exp-run", "consumer_node": "exp-design", "stage": "acceptance",
    }))
    state.set_status("exp-design", "done")
    state.accept("exp-design", "fresh-design-verdict", "current-gates")
    assert "active_owner_revision" not in state.load()
    run = WorkflowRun(id=state.run_id, project_path=str(tmp_path), nodes=[
        WorkflowNode(id=key, name=key, skill=key) for key in ("exp-design", "exp-run", "paper")
    ])
    interrupted = record_interruption(run, run.nodes[-1], "paper timeout", kind="error")
    assert interrupted["node_id"] == "paper"


@pytest.mark.parametrize("current,owner_status", [("paper", "running"), ("paper", "accepted"), ("review", "accepted")])
def test_interruption_ignores_old_owner_transaction_outside_current_execution(tmp_path, current, owner_status):
    from server.workflows.run_state import RunState
    from server.workflows.models import WorkflowNode
    from server.workflows.interruption_checkpoint import mark_boundary, record_interruption

    nodes = [WorkflowNode(key, key, key, session_id=f"{key}-session") for key in ("lit", "paper", "review")]
    run = WorkflowRun(id="stale-owner", project_path=str(tmp_path), nodes=nodes)
    state = RunState(str(tmp_path), run.id)
    state.start([{"id": node.id} for node in nodes], {})
    if owner_status == "accepted":
        state.set_status("lit", "done")
        state.accept("lit", "lit-verdict", "validator")
    else:
        state.set_status("lit", owner_status)
    state.update_state(lambda saved: saved.update(active_owner_revision={
        "owner_node": "lit", "consumer_node": "review", "stage": "primary", "input_signature": "old-lit-scope",
    }))
    node = next(node for node in nodes if node.id == current)
    mark_boundary(run, node, "primary", result="saved section")
    before = state.load()["phases"]["lit"]
    receipt = record_interruption(run, node, "operator cancelled", kind="cancelled")
    assert receipt["node_id"] == receipt["owner_node"] == receipt["consumer_node"] == current
    assert receipt["session_id"] == node.session_id and receipt["input_signature"] == ""
    saved = state.load()
    assert saved["phases"]["lit"] == before
    assert saved["phases"][current]["details"]["interruption"] == receipt
