"""Real agent-loop closeout preserves inspected evidence and never creates a verdict."""

import json
from types import SimpleNamespace

import pytest

from server.agent import LLMResponse, ModelRole, ToolCall
from server.agent.engine import AgentEngine
from server.agent.iteration_budget import AgentIterationLimit
from server.agent.readonly_closeout import reserve_readonly_verdict
from server.agent.session_models import AgentSession, AgentStatus
from server.workflows.engine import WorkflowEngine, WorkflowRun


def reviewer(tmp_path, final):
    requests, reads = [], []

    class Provider:
        name = model = "local-review-fixture"
        streaming_enabled = False

        async def chat(self, **kwargs):
            requests.append(kwargs)
            if kwargs.get("tools"):
                return LLMResponse(stop_reason="tool_calls", tool_calls=[
                    ToolCall(f"read-{len(requests)}", "Read", {"path": "method.py"}),
                ])
            return final

    engine = AgentEngine(SimpleNamespace(
        _providers={"fixture": Provider()}, _strategy={ModelRole.EXECUTOR: "fixture"},
    ))

    async def read(path):
        reads.append(path)
        return "method.py: controls share the same identity map; this violates the declared control."

    engine.register_tool("Read", "inspect local fixture", {
        "type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"],
    }, read)
    session = engine.create_session()
    session.project_path = str(tmp_path)
    session.tool_policy = "workflow_artifacts"
    session.max_iterations = 3
    return engine, session, requests, reads


@pytest.mark.asyncio
async def test_last_turn_uses_prior_evidence_to_return_a_real_blocking_verdict(tmp_path):
    result = json.dumps({"verdict": "FAIL", "summary": "Control identity is shared.", "findings": [{
        "id": "CONTROL-1", "severity": "blocker", "message": "Controls share identity maps.",
        "evidence": ["method.py: control mapping"],
    }]})
    engine, session, requests, reads = reviewer(tmp_path, LLMResponse(content=result, stop_reason="stop"))
    events = []
    assert await engine.run(session.id, "Review controls; return JSON", tools=["Read"], on_event=events.append) == result
    assert len(requests) == 3 and len(reads) == 2 and requests[-1]["tools"] is None
    assert any(m.role == "tool" and "identity map" in str(m.content) for m in requests[-1]["messages"])
    assert any("Runtime read-only closeout" in str(m.content) for m in requests[-1]["messages"])
    assert session.max_iterations == session.iterations == 3
    assert session.status == AgentStatus.COMPLETED
    assert WorkflowEngine._parse_training_check_result(result, assurance="draft")["blocking"]
    assert any(e.type == "status" and e.data.get("status") == "review_closeout" for e in events)


@pytest.mark.asyncio
async def test_provider_ignoring_closeout_cannot_execute_an_extra_read_or_pass(tmp_path):
    response = LLMResponse(stop_reason="tool_calls", tool_calls=[ToolCall("extra-read", "Read", {"path": "new.py"})])
    engine, session, requests, reads = reviewer(tmp_path, response)
    with pytest.raises(AgentIterationLimit):
        await engine.run(session.id, "Return the review", tools=["Read"])
    assert len(reads) == 2 and len(requests) == 3
    assert session.status == AgentStatus.ERROR and session.last_stop_reason == "iteration_limit"


@pytest.mark.parametrize("tools,policy,used", [
    (["Read", "Write"], "workflow_artifacts", 2),
    (None, "workflow_artifacts", 2),
    ([], "workflow_artifacts", 2),
    (["Read"], None, 2),
    (["Read"], "workflow_artifacts", 1),
])
def test_closeout_never_restricts_authors_or_ordinary_sessions(tools, policy, used):
    state = SimpleNamespace(session=AgentSession(max_iterations=3, iterations=used, tool_policy=policy),
                            available_tools=["original"])
    assert not reserve_readonly_verdict(state, tools)
    assert state.available_tools == ["original"] and not state.session.messages


@pytest.mark.asyncio
async def test_two_malformed_review_responses_pause_without_a_fabricated_warning(tmp_path, monkeypatch):
    from server.agent import tools
    from server.services.skill_orchestrator import skill_orchestrator

    calls = []

    async def invalid(*args, **kwargs):
        calls.append(kwargs)
        return "not a structured review"

    monkeypatch.setattr(tools, "invoke_skill", invalid)
    monkeypatch.setattr(skill_orchestrator, "select", lambda *a, **k: None)
    monkeypatch.setattr(skill_orchestrator, "record", lambda *a, **k: None)
    monkeypatch.setattr(skill_orchestrator, "mark_execution", lambda *a, **k: None)
    engine = WorkflowEngine()
    monkeypatch.setattr(engine, "_skill_invocation_traces", lambda *a: [])
    run = WorkflowRun(id="review-fixture", project_path=str(tmp_path), nodes=[])
    with pytest.raises(RuntimeError, match="TRAINING_CHECK_PROTOCOL_ERROR"):
        await engine._run_code_review(run, "Fixture controls", "balanced", "draft")
    assert len(calls) == 2 and [c["max_iterations"] for c in calls] == [12, 6]
    assert calls[0]["allowed_tools_override"] == ["Read", "Glob", "Grep"]
    assert calls[1]["allowed_tools_override"] == []
