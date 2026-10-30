"""Late literature evidence repair preserves validated implementation and numerical results."""

from types import SimpleNamespace

import pytest

from server.workflows.engine import WorkflowEngine
from server.workflows.models import WorkflowRun
from server.workflows.owner_revision_transaction import begin_owner_revision
from server.workflows.owner_revision_scope import revalidate_unaffected_owner_phases
from server.workflows.run_state import RunState


def test_late_literature_start_and_reconciliation_share_the_same_dependents(tmp_path):
    host = WorkflowEngine()
    nodes = host._get_default_nodes()
    state = RunState(str(tmp_path), "late-lit")
    state.start([{"id": node.id, "name": node.name, "skill": node.skill} for node in nodes], {})
    state.update_state(lambda saved: [phase.update(status="accepted", verdict_id="prior") for phase in saved["phases"].values()])
    by_id = {node.id: node for node in nodes}
    ctx = SimpleNamespace(host=host, revision_owner=by_id["lit"], node=by_id["review"], run_state=state,
                           run=WorkflowRun(project_path=str(tmp_path), nodes=nodes), scope_signature="current")
    begin_owner_revision(ctx)
    phases = state.load()["phases"]
    assert all(phases[key]["status"] == "accepted" for key in ("idea", "novelty", "exp-design", "exp-run", "results", "figure"))
    assert all(phases[key]["status"] == "pending" for key in ("narrative", "paper", "review", "audit", "compile", "ppt"))


@pytest.mark.parametrize("snapshot_changed,gate_passed", [(False, True), (True, True), (False, False)])
def test_overinvalidated_phase_needs_current_snapshot_and_fresh_gate(tmp_path, monkeypatch, snapshot_changed, gate_passed):
    host = WorkflowEngine()
    state = RunState(str(tmp_path), "scope-recovery")
    state.start([{"id": key, "name": key, "skill": key} for key in ("lit", "exp-design", "review")], {})
    state.update_state(lambda saved: saved.update(active_owner_revision={"owner_node": "lit", "consumer_node": "review"}))
    state.update_state(lambda saved: saved["phases"]["exp-design"].update(status="pending", details={
        "revoked_acceptances": [{"owner": "lit", "verdict_id": "prior"}],
        "artifact_snapshot": {"experiments/EXPERIMENT_PLAN.md": {"sha256": "prior"}},
    }))
    monkeypatch.setattr(host, "_artifact_snapshot_issues", lambda *_args: ["changed"] if snapshot_changed else [])
    monkeypatch.setattr(host, "_acceptance_gate", lambda *_args, **_kwargs: {
        "accepted": gate_passed, "verdict_id": "fresh-verdict", "reviewer": "fresh-gate"})
    revalidate_unaffected_owner_phases(host, WorkflowRun(project_path=str(tmp_path)), state)
    assert (state.load()["phases"]["exp-design"]["status"] == "accepted") is (gate_passed and not snapshot_changed)
