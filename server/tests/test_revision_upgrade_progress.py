"""A changed implementation cannot inherit exhausted counters from an old repair history."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from server.workflows.models import WorkflowNode, WorkflowRun
from server.workflows.revision_loop_context import RevisionLoopContext
from server.workflows.revision_loop_phases import initialize_progress
from server.workflows.run_state import RunState


def test_narrative_recovery_fingerprints_real_reviewer_and_delegate_capabilities():
    from server.workflows.engine_revision_signature import _validator_source_paths
    names = {path.name for path in _validator_source_paths("narrative")}
    assert {"reviewer_scope.py", "review_and_domain_tools.py", "skill_tool.py", "delegate_activity.py",
        "narrative_prompt.py", "research_delivery_prompt.py"} <= names


@pytest.mark.asyncio
async def test_runtime_reset_archives_old_progress_without_restoring_it_from_history(tmp_path):
    state = RunState(str(tmp_path), "changed-runtime")
    state.start([{"id": "paper", "name": "Paper", "skill": "/paper-write"}], {})
    state.update_state(lambda saved: saved["phases"]["paper"]["details"].update(revision={
        "history": [{"repair_scope": {"target_files": ["paper/main.tex"]},
                     "revision_progress": {"consecutive_no_progress": 3}}],
        "last_gate": {"revision_progress": {"consecutive_no_progress": 3}}, "round": 3,
    }))
    state.reset_revision_for_runtime_change("paper", runtime_signature="new", reason="producer fixed")
    revision = state.revision_state("paper")
    node = WorkflowNode("paper", "Paper", "/paper-write")
    ctx = RevisionLoopContext(SimpleNamespace(), node, WorkflowRun(project_path=str(tmp_path)),
                              "draft", "fixture", "balanced", {}, 3, 30, "", False, 2,
                              saved_revision=revision)
    await initialize_progress(ctx)
    assert revision["history"][0]["revision_progress"]["consecutive_no_progress"] == 3
    assert ctx.persisted_progress == {} and ctx.persisted_scope == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending", "failed", "running", "awaiting_revision"])
@pytest.mark.parametrize("changed", [False, True])
async def test_manual_recovery_resets_old_budget_only_after_signature_change(tmp_path, monkeypatch, status, changed):
    from server.workflows import resume_execution

    durable = RunState(str(tmp_path), "upgrade-resume")
    durable.start([{"id": "paper", "name": "Paper", "skill": "/paper-write"}], {})
    previous = {"repair_scope": {"target_files": ["paper/main.tex"]},
                "revision_progress": {"consecutive_no_progress": 3}}
    def seed(saved):
        saved["phases"]["paper"].update(status=status, details={
            "interruption": {"kind": "cancelled"},
            "revision": {"history": [previous], "round": 3, "last_gate": previous,
                         "artifact_signature": "old", "runtime_signature": "old-runtime"},
        })
    durable.update_state(seed)
    async def validated(*_args):
        return durable, durable.load(), {}, ["paper"]
    monkeypatch.setattr(resume_execution, "_revalidated_resume_state", validated)
    host = SimpleNamespace(_revision_artifact_signature=lambda *_: "new" if changed else "old",
                           _revision_runtime_signature=lambda *_: "new-runtime",
                           execute=AsyncMock(return_value=durable.run_id))
    result = await resume_execution.resume_persisted_run_claimed(host, run_id=durable.run_id,
        project_path=str(tmp_path), node_ids=None, research_direction="fixture", effort="balanced",
        assurance="draft", pipeline_options=None, on_event=None, checkpoint_feedback="", resume_source="explicit")
    assert result == durable.run_id and host.execute.await_count == 1
    revision = durable.revision_state("paper")
    assert revision["history"] == [previous]
    assert revision.get("progress_history_start", 0) == int(changed)
    assert bool(revision.get("last_gate")) is not changed
