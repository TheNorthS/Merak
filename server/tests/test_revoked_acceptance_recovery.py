"""Revoked outputs require both unchanged bytes and a fresh gate before restoration."""

import pytest

from server.workflows.engine import WorkflowEngine
from server.workflows.models import WorkflowRun
from server.workflows.run_state import RunState
from server.workflows.revoked_acceptance_recovery import revalidate_unchanged_revoked_outputs


@pytest.mark.parametrize("changed,passed,active", [(False,True,False),(True,True,False),(False,False,False),(False,True,True)])
def test_recovery_never_restores_changed_failed_or_active_repair_outputs(tmp_path, monkeypatch, changed, passed, active):
    host = WorkflowEngine()
    state = RunState(str(tmp_path), "revoked")
    state.start([{"id":"lit"}], {})
    state.update_state(lambda d: d["phases"]["lit"].update(details={
        "artifact_snapshot":{"literature/survey.md":{"sha256":"old"}},
        "revoked_acceptances":[{"verdict_id":"old","owner":"lit"}]}))
    if active:
        state.update_state(lambda d: d.update(active_owner_revision={"owner_node":"lit"}))
    monkeypatch.setattr(host,"_artifact_snapshot_issues",lambda *a: ["changed"] if changed else [])
    monkeypatch.setattr(host,"_acceptance_gate",lambda *a,**k:{"accepted":passed,"verdict_id":"fresh","reviewer":"fresh-gate"})
    revalidate_unchanged_revoked_outputs(host,WorkflowRun(project_path=str(tmp_path)),state)
    assert (state.load()["phases"]["lit"]["status"] == "accepted") is (passed and not changed)
    if active and passed and not changed:
        assert not state.load().get("active_owner_revision")
