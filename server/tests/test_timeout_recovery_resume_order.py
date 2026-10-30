"""Validate persisted timeout Writes before selecting generic revalidation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.tests.test_workflow_timeout_recovery import _timed_out_fixture
from server.workflows.engine import WorkflowEngine
from server.workflows.run_execution_context import RunExecutionContext
from server.workflows.run_execution_node import load_resume_state
from server.workflows.run_state import RunState


@pytest.mark.asyncio
@pytest.mark.parametrize("evidence_case", ["primary", "wrong_session", "wrong_run", "wrong_node", "delegate", "unrelated"])
async def test_resume_recovery_closes_only_same_run_primary_write(
    tmp_path: Path, evidence_case: str,
) -> None:
    options = {
        "wrong_session": {"event_session_id": "different-session"},
        "wrong_run": {"event_run_id": "different-run"},
        "wrong_node": {"event_node_id": "different-node"},
        "delegate": {"delegate_active": True},
        "unrelated": {"artifact_relative": "misc/notes.md"},
    }
    node, run, phase = _timed_out_fixture(tmp_path, **options.get(evidence_case, {}))
    host = WorkflowEngine()
    assert host._phase_requires_revalidation(phase) is True
    state = RunState(str(tmp_path), run.id)
    context = RunExecutionContext(host, run, "fixture", "balanced", "draft", {})
    context.node, context.run_state = node, state
    artifact = tmp_path / ("misc/notes.md" if evidence_case == "unrelated" else "ideas/ideas.md")
    before = artifact.read_bytes()
    await load_resume_state(context)
    current = state.load()["phases"][node.id]
    trace = json.loads((tmp_path / ".merak/runs" / f"{run.id}.skills.json").read_text(encoding="utf-8"))
    primary = trace["stages"][node.id]["invocations"][-1]
    assert context.revalidate_done is True
    assert artifact.read_bytes() == before
    assert current["status"] != "accepted"
    if evidence_case == "primary":
        assert current["status"] == "done"
        assert current["details"]["timeout_artifact_recovery"]["session_id"] == "primary-session"
        assert primary["status"] == "completed"
        assert primary["completion_mode"] == "artifact_persisted_before_timeout"
    else:
        assert current["status"] == "failed"
        assert "timeout_artifact_recovery" not in current["details"]
        assert primary["status"] == "running"
