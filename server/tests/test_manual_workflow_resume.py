"""Pure interruption checkpoints and mock authoring: no providers or scientific execution."""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from server.agent import Message, ToolCall, LLMResponse
from server.agent.engine import AgentEngine
from server.agent.session_models import AgentStatus
from server.agent.agent_loop import AgentLoopCoordinator, LoopState
from server.workflows.engine import WorkflowEngine
from server.workflows.models import WorkflowNode, WorkflowRun, NodeStatus
from server.workflows.run_state import RunState
from server.workflows.session_state import SessionState
from server.workflows.run_execution_context import RunExecutionContext, StopRunNodes
from server.workflows.interruption_checkpoint import (
    mark_boundary, record_interruption, resume_execution_stage, acknowledge_manual_resume,
)
from server.workflows.primary_session_resume import restore_primary_session


def _context(root):
    nodes = [WorkflowNode("idea", "Idea", "/idea-discovery", status=NodeStatus.COMPLETED),
             WorkflowNode("exp-design", "Design", "/domain-experiment-plan", status=NodeStatus.RUNNING)]
    run = WorkflowRun(id="manual-resume", project_path=str(root), nodes=nodes, status="running")
    state = RunState(str(root), run.id)
    state.start([{"id": n.id, "name": n.name, "skill": n.skill} for n in nodes], {})
    state.set_status("idea", "done")
    state.accept("idea", "verdict", "validator")
    state.set_status("exp-design", "running")
    ctx = RunExecutionContext(WorkflowEngine(), run, "offline", "balanced", "draft", {})
    ctx.node, ctx.run_state, ctx.session_state = nodes[-1], state, SessionState(str(root))
    ctx.max_revision_rounds = 6
    return ctx


@pytest.mark.asyncio
@pytest.mark.parametrize("node_id", ["lit", "idea", "novelty", "exp-design", "results", "narrative", "ppt"])
@pytest.mark.parametrize("error", [TimeoutError("model timeout"), RuntimeError("tool failure"), asyncio.CancelledError()])
async def test_failed_authoring_never_returns_a_replacement_artifact(tmp_path, node_id, error):
    from server.workflows.primary_model_execution import run_model_primary
    ctx = _context(tmp_path)
    ctx.node = WorkflowNode(node_id, node_id, "/offline")
    ctx.wandb_enabled, ctx.compact_mode = False, True
    async def fail(*args, **kwargs):
        raise error
    ctx.host._execute_node = fail
    ctx.host._emit = fail_if_recovered
    before = set(tmp_path.rglob("*"))
    with pytest.raises(type(error)):
        await run_model_primary(ctx, presentation=node_id == "ppt")
    assert not (tmp_path / "experiments/EXPERIMENT_PLAN.md").exists()
    assert ctx.result is None


async def fail_if_recovered(run, event, data):
    assert event not in {"node_recovered", "skill_invocation_recovered"}


@pytest.mark.parametrize("stage", ["preparation", "primary", "specialists", "acceptance"])
def test_restart_retains_exact_execution_boundary_and_upstream_acceptance(tmp_path, stage):
    ctx = _context(tmp_path)
    ctx.node.session_id = "conversation"
    mark_boundary(ctx.run, ctx.node, stage, result="authored result")
    record_interruption(ctx.run, ctx.node, "backend stopped", kind="interrupted")
    ctx.run_state.set_status(ctx.node.id, "failed", error="backend stopped")
    restarted = RunState(str(tmp_path), ctx.run.id)
    phase = restarted.load()["phases"][ctx.node.id]
    assert resume_execution_stage(phase) == stage
    assert phase["details"]["execution_checkpoint"]["result"] == "authored result"
    assert restarted.load()["phases"]["idea"]["status"] == "accepted"
    from server.services.workflow_recovery_policy import due_phase
    assert due_phase(engine=ctx.host, project_path=str(tmp_path), state=restarted.load(), now=10**12) == ""
    acknowledge_manual_resume(restarted)
    assert restarted.load()["interruption"]["manual_resume_required"] is False


@pytest.mark.asyncio
async def test_cancel_event_contains_immediately_usable_resume_state(tmp_path):
    from server.workflows.run_execution_final import handle_run_cancelled
    ctx = _context(tmp_path)
    mark_boundary(ctx.run, ctx.node, "primary")
    events = []
    async def emit(run, kind, data):
        events.append((kind, data))
    ctx.host._emit = emit
    await handle_run_cancelled(ctx)
    kind, data = events[-1]
    assert kind == "workflow_cancelled" and data["current_node"] == "exp-design"
    assert data["nodes_status"]["idea"] == "accepted"
    assert data["nodes_status"]["exp-design"] == "pending"
    assert data["manual_resume_required"] and ctx.session_state.load()["run_id"] == ctx.run.id


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [TimeoutError("model timeout"), RuntimeError("unexpected failure")])
async def test_every_failed_node_records_manual_interruption(tmp_path, error):
    from server.workflows.run_execution_execute import handle_node_error
    ctx = _context(tmp_path)
    mark_boundary(ctx.run, ctx.node, "specialists", result="completed primary")
    ctx.host._emit = fail_if_recovered
    with pytest.raises(StopRunNodes):
        await handle_node_error(ctx, error)
    saved = ctx.run_state.load()
    assert saved["interruption"]["manual_resume_required"]
    assert saved["interruption"]["stage"] == "specialists"
    assert saved["phases"]["idea"]["status"] == "accepted"


@pytest.mark.parametrize("restart", [False, True])
def test_restore_preserves_transcript_with_current_route_and_fresh_attempt(tmp_path, restart):
    engine = AgentEngine(None)
    session = engine.create_session(system_prompt="old")
    session.project_path = str(tmp_path)
    session.messages.extend([Message(role="assistant", content="saved work"), Message(role="user", content="continue")])
    session.status, session.iterations, session.provider_override = AgentStatus.ERROR, 99, "broken-provider"
    engine._persist_session_transcript(session)
    if restart:
        engine = AgentEngine(None)
    restored = restore_primary_session(engine, session.id, str(tmp_path), system_prompt="current contract")
    assert restored.id == session.id and restored.iterations == 0
    assert restored.provider_override is None
    assert restored.messages[0].content == "current contract"
    assert any(m.content == "saved work" for m in restored.messages)


@pytest.mark.asyncio
async def test_cancel_between_tools_does_not_lose_completed_write_receipt(tmp_path, monkeypatch):
    engine = AgentEngine(None)
    session = engine.create_session()
    session.project_path = str(tmp_path)
    entered = asyncio.Event()
    async def write():
        (tmp_path / "authored.txt").write_text("saved", encoding="utf-8")
        return "saved"
    async def hang():
        entered.set()
        await asyncio.Event().wait()
    engine.register_tool("WriteFixture", "write", {"type": "object", "properties": {}}, write)
    engine.register_tool("Hang", "wait", {"type": "object", "properties": {}}, hang)
    monkeypatch.setattr(engine, "_log_tool_event", lambda *args: None)
    monkeypatch.setattr(engine, "_record_execution_provenance", lambda *args: None)
    loop = AgentLoopCoordinator(engine, session.id, "", None, None, 64, None, None)
    state = LoopState(session, [], False, engine._tool_definitions, "offline", None)
    response = LLMResponse(content="", tool_calls=[ToolCall("write", "WriteFixture", {}), ToolCall("hang", "Hang", {})])
    task = asyncio.create_task(loop._execute_tool_calls(state, response))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    import json
    saved = json.loads((tmp_path / f".merak/agent-sessions/{session.id}.json").read_text(encoding="utf-8"))
    assert any(m.get("tool_call_id") == "write" and m["content"] == "saved" for m in saved["messages"])


@pytest.mark.asyncio
async def test_missing_design_never_creates_a_skeleton(tmp_path):
    from server.workflows.exp_design_artifacts import ensure_exp_design_artifacts
    ctx = _context(tmp_path)
    before = set(tmp_path.rglob("*"))
    with pytest.raises(ValueError, match="Missing"):
        await ensure_exp_design_artifacts(ctx.host, ctx.run, "partial", "offline", "draft")
    assert set(tmp_path.rglob("*")) == before


def test_delegate_resume_requires_same_run_stage_and_source(tmp_path):
    import hashlib
    import json
    from server.agent.skill_resume import workflow_scope, delegate_identity, restore_delegate
    engine = AgentEngine(None)
    session = engine.create_session()
    session.project_path, session.status = str(tmp_path), AgentStatus.ERROR
    session.messages = [Message(role="user", content="continue the current section")]
    engine._persist_session_transcript(session)
    loaded = SimpleNamespace(name="paper-method", root=tmp_path, source_bytes=b"current skill")
    token = workflow_scope.set(("run", "paper"))
    try:
        identity = delegate_identity(loaded, "workflow>paper", "method section", ["paper/method.tex"])
        directory = tmp_path / ".merak/skill-invocations"
        directory.mkdir()
        (directory / "trace_paper-method.json").write_text(json.dumps({
            **identity, "status": "failed", "session_id": session.id,
            "skill_sha256": hashlib.sha256(loaded.source_bytes).hexdigest(),
        }), encoding="utf-8")
        assert restore_delegate(engine, loaded, "new prompt", identity).id == session.id
        assert restore_delegate(engine, loaded, "new prompt", {**identity, "workflow_run_id": "other"}) is None
        assert restore_delegate(engine, loaded, "new prompt", {**identity, "resume_key": "other-stage"}) is None
    finally:
        workflow_scope.reset(token)


@pytest.mark.asyncio
async def test_manual_resume_waits_for_uncancelled_child(tmp_path):
    from server.agent.tool_deadline import cancel_tool_task, execution_session, ToolCancellationUnconfirmed
    engine = AgentEngine(None)
    session = engine.create_session()
    session.project_path, session.status = str(tmp_path), AgentStatus.ERROR
    entered, release = asyncio.Event(), asyncio.Event()
    async def uncooperative():
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await release.wait()
    token = execution_session.set(session.id)
    task = asyncio.create_task(uncooperative())
    try:
        await entered.wait()
        with pytest.raises(ToolCancellationUnconfirmed):
            await cancel_tool_task(task, 0.001)
        with pytest.raises(ValueError, match="uncancelled operation"):
            restore_primary_session(engine, session.id, str(tmp_path), system_prompt="current")
        release.set()
        await task
        assert restore_primary_session(engine, session.id, str(tmp_path), system_prompt="current").id == session.id
    finally:
        release.set()
        await task
        execution_session.reset(token)


def test_explicit_figure_resume_grants_only_one_attempt_per_manual_action(tmp_path, monkeypatch):
    from server.services import figure_delegate_budget as budget
    monkeypatch.setattr(budget, "_identity", lambda *args, **kwargs: {
        "semantic_projection_sha256": "a", "figure_spec_sha256": "b",
        "source_bundle_sha256": "c", "code_sha256": "d", "feedback_sha256": "",
    })
    asset = {"id": "method_architecture"}
    assert budget.begin_delegate_attempt(tmp_path, "run", asset).allowed
    assert not budget.begin_delegate_attempt(tmp_path, "run", asset).allowed
    assert budget.begin_delegate_attempt(tmp_path, "run", asset, manual_resume_id="user-action-1").allowed
    assert not budget.begin_delegate_attempt(tmp_path, "run", asset, manual_resume_id="user-action-1").allowed
    assert not budget.begin_delegate_attempt(tmp_path, "run", asset).allowed


@pytest.mark.asyncio
async def test_failed_figure_does_not_start_remaining_assets(tmp_path, monkeypatch):
    from server.workflows import figure_asset_delegates as figures
    ctx = SimpleNamespace(node=SimpleNamespace(id="figure"), project_path=str(tmp_path),
                          run=SimpleNamespace(id="run"), host=SimpleNamespace(_emit=fail_if_recovered))
    monkeypatch.setattr(figures, "_model_assets", lambda _: [{"id": "first"}, {"id": "second"}])
    invoked = []
    async def fail(context, asset, *args):
        invoked.append(asset["id"])
        raise TimeoutError("model timeout")
    monkeypatch.setattr(figures, "_process_asset", fail)
    with pytest.raises(TimeoutError):
        await figures.run_figure_asset_delegates(ctx)
    assert invoked == ["first"]


@pytest.mark.asyncio
async def test_review_fix_timeout_stays_incomplete(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock
    from server.workflows import review_loop, review_audit
    reviewer = SimpleNamespace(_run_fix_with_progress=AsyncMock(side_effect=TimeoutError("model timeout")),
                               _save_state=lambda *args: None)
    context = SimpleNamespace(project_path=str(tmp_path), reviewer=reviewer, on_progress=None)
    state = SimpleNamespace(is_complete=True, bounded_complete=True, phase="", fallback_reason="")
    monkeypatch.setattr(review_audit, "review_source_bundle", lambda _: ("original", []))
    monkeypatch.setattr(review_loop, "_fix_session_and_instruction", lambda *args: (SimpleNamespace(id="session"), "fix"))
    monkeypatch.setattr(review_loop, "_compile_output_snapshot", AsyncMock(side_effect=AssertionError("must stop")))
    with pytest.raises(TimeoutError, match="model timeout"):
        await review_loop._perform_fix(context, state, None, 1, [], [], [])
    assert not state.is_complete and not state.bounded_complete
    assert state.phase == "fix_interrupted"


@pytest.mark.asyncio
async def test_narrative_preparation_never_generates_missing_model_output(tmp_path, monkeypatch):
    from server.workflows.node_gate_preparation import _prepare_narrative
    from server.services.scientific_narrative import scientific_narrative_service
    from server.services.paper_plan import paper_plan_service
    monkeypatch.setattr(scientific_narrative_service, "ensure", lambda *args, **kwargs: pytest.fail("generated fallback narrative"))
    monkeypatch.setattr(paper_plan_service, "ensure", lambda *args, **kwargs: pytest.fail("generated fallback plan"))
    ctx = _context(tmp_path)
    with pytest.raises(ValueError, match="narrative is missing"):
        await _prepare_narrative(ctx.host, ctx.node, ctx.run, "offline", {})
    assert not (tmp_path / "NARRATIVE_REPORT.md").exists()
