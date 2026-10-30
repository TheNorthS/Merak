"""Real agent-loop exhaustion hands joined writes to the owning stage validator."""
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from server.agent import LLMResponse, ModelRole, ToolCall
from server.agent.engine import AgentEngine
from server.agent.agent_loop import AgentLoopCoordinator
from server.agent.session_models import AgentSession
from server.agent.iteration_budget import AgentIterationLimit
from server.agent.session_models import AgentStatus
from server.tests.test_implementation_owner_reconciliation import (
    _context, _accept_owners, _planned_method, _patch, DIRECTION, SERVICE,
)
from server.workflows.implementation_model_invocation import StageModelInvocation
from server.workflows.implementation_reconciliation import prepare_stage
from server.workflows.staged_implementation_coordinator import StagedImplementationCoordinator


def fixture_context(root):
    context = _context(root)
    _accept_owners(context)
    _planned_method(root)
    events = []

    async def emit(run, kind, data):
        events.append((kind, data))

    return replace(context, host=SimpleNamespace(
        _emit=emit, _is_transport_research_error=lambda error: False, _exception_summary=str,
    )), events


@pytest.mark.asyncio
async def test_final_tool_write_is_validated_without_faking_model_completion(tmp_path, monkeypatch):
    context, events = fixture_context(tmp_path)
    patch = tmp_path / "experiments/IMPLEMENTATION_EVIDENCE_PATCH.json"
    content = json.dumps(_patch(tmp_path, ["M1"]))
    patch.unlink()
    state = prepare_stage(context, context.stages[-1])

    class Provider:
        name = model = "local-fixture"
        streaming_enabled = False

        async def chat(self, **kwargs):
            return LLMResponse(stop_reason="tool_calls", tool_calls=[
                ToolCall("write-fixture", "Write", {"path": str(patch), "content": content}),
            ])

    engine = AgentEngine(SimpleNamespace(_providers={"fixture": Provider()}, _strategy={ModelRole.EXECUTOR: "fixture"}))

    async def write(path: str, content: str):
        assert path == str(patch)
        patch.write_text(content, encoding="utf-8")
        return "Written fixture evidence patch"

    engine.register_tool("Write", "write fixture", {"type": "object", "properties": {
        "path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}, write)
    session = engine.create_session()
    session.project_path = str(tmp_path)
    session.max_iterations = 1
    model_events, marks = [], []

    async def invoke(_self):
        return await engine.run(session.id, "Write only the fixture evidence patch", on_event=model_events.append)

    monkeypatch.setattr(StageModelInvocation, "_invoke", invoke)
    monkeypatch.setattr(StageModelInvocation, "mark", lambda self, status, **kwargs: marks.append(status))
    await StagedImplementationCoordinator(context.host, context.run, DIRECTION)._attempts(context, state)
    assert state.report["passed"], state.report
    assert SERVICE.load_build(tmp_path)["stages"]["integration"]["status"] == "accepted"
    assert session.status == AgentStatus.ERROR and session.last_stop_reason == "iteration_limit"
    assert not any(event.type == "done" for event in model_events)
    assert marks == ["running", "failed"]
    assert any(kind == "implementation_stage_budget_exhausted" for kind, _ in events)
    assert any(kind == "implementation_stage_accepted" for kind, _ in events)


@pytest.mark.asyncio
async def test_budget_stop_with_invalid_evidence_stays_blocked_and_records_findings(tmp_path, monkeypatch):
    context, events = fixture_context(tmp_path)
    (tmp_path / "experiments/IMPLEMENTATION_EVIDENCE_PATCH.json").unlink()
    state = prepare_stage(context, context.stages[-1])

    async def exhaust(_self):
        raise AgentIterationLimit("fixture", 24, 24)

    monkeypatch.setattr(StageModelInvocation, "run", exhaust)
    await StagedImplementationCoordinator(context.host, context.run, DIRECTION)._attempts(context, state)
    record = SERVICE.load_build(tmp_path)["stages"]["integration"]
    assert record["status"] == "needs_revision"
    assert any("evidence patch" in issue for issue in record["issues"])
    assert not any(kind == "implementation_stage_accepted" for kind, _ in events)


@pytest.mark.asyncio
async def test_budget_stop_cannot_accept_protected_input_changes(tmp_path, monkeypatch):
    context, events = fixture_context(tmp_path)
    state = prepare_stage(context, context.stages[-1])

    async def violate(_self):
        (tmp_path / "experiments/EXPERIMENT_PLAN.md").write_text("unauthorized change")
        raise AgentIterationLimit("fixture", 24, 24)

    monkeypatch.setattr(StageModelInvocation, "run", violate)
    await StagedImplementationCoordinator(context.host, context.run, DIRECTION)._attempts(context, state)
    assert not state.report["passed"] and state.report["ownership_violations"]
    assert not any(kind == "implementation_stage_accepted" for kind, _ in events)


@pytest.mark.asyncio
async def test_unrelated_failure_cannot_enter_budget_handoff(tmp_path, monkeypatch):
    context, _ = fixture_context(tmp_path)
    state = prepare_stage(context, context.stages[-1])

    async def unrelated(_self):
        raise RuntimeError("AGENT_ITERATION_LIMIT mentioned by a failing tool")

    monkeypatch.setattr(StageModelInvocation, "run", unrelated)
    with pytest.raises(RuntimeError, match="failing tool"):
        await StagedImplementationCoordinator(context.host, context.run, DIRECTION)._attempts(context, state)
    assert "integration" not in SERVICE.load_build(tmp_path)["stages"]


@pytest.mark.asyncio
async def test_model_receives_one_closeout_notice_before_hard_limit():
    engine = AgentEngine(None)
    session = AgentSession(max_iterations=24)
    events = []
    loop = AgentLoopCoordinator(engine, session.id, "fixture", events.append, None, 64, None, None)
    for used in range(24):
        session.iterations = used
        await loop._warn_remaining_iterations(session)
    assert len(events) == 1
    assert events[0].data["iterations_remaining"] == 3
    assert "Runtime budget notice" in session.messages[0].content
    assert session.max_iterations == 24


@pytest.mark.asyncio
async def test_fresh_gate_findings_drive_only_the_bounded_next_attempt(tmp_path, monkeypatch):
    context, _ = fixture_context(tmp_path)
    patch = tmp_path / "experiments/IMPLEMENTATION_EVIDENCE_PATCH.json"
    valid = _patch(tmp_path, ["M1"])
    patch.unlink()
    state = prepare_stage(context, context.stages[-1])
    attempts = []

    async def candidate(invocation):
        attempts.append(invocation.attempt)
        payload = json.loads(json.dumps(valid))
        if invocation.attempt == 1:
            payload["checks"][0]["evidence"].append({
                "path": "experiments/configs/main.yaml", "config_keys": ["missing.fixture.key"],
            })
            patch.write_text(json.dumps(payload), encoding="utf-8")
            raise AgentIterationLimit("fixture", 24, 24)
        assert any("missing.fixture.key" in issue for issue in invocation.state.report["issues"])
        patch.write_text(json.dumps(payload), encoding="utf-8")
        return "Corrected the specific evidence reference; runtime validation is still required."

    monkeypatch.setattr(StageModelInvocation, "run", candidate)
    monkeypatch.setattr(StageModelInvocation, "mark", lambda *_args, **_kwargs: None)
    await StagedImplementationCoordinator(context.host, context.run, DIRECTION)._attempts(context, state)
    assert attempts == [1, 2]
    assert state.report["passed"], state.report
