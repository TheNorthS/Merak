"""Mock-only error, token usage and writer-diagnostic contracts."""
from types import SimpleNamespace
from unittest.mock import AsyncMock
import json
import pytest

from server.agent.remote_errors import RemoteCallError, read_only_get, response_error
from server.agent.openai_stream import _consume_response
from server.agent.engine import AgentEngine
from server.agent.agent_loop import AgentLoopCoordinator, LoopState
from server.agent.session_models import AgentSession, ToolResult
from server.agent.model_types import LLMResponse, StreamChunk, ToolCall
from server.agent.tool_harness import classify_result, tool_receipt


@pytest.mark.asyncio
async def test_rate_limit_honors_retry_after_and_preserves_http_metadata(monkeypatch):
    responses = [SimpleNamespace(status_code=429, headers={"retry-after": "3", "x-request-id": "req-123"}),
                 SimpleNamespace(status_code=200)]
    delays = []
    async def pause(delay): delays.append(delay)
    monkeypatch.setattr("server.agent.remote_errors.asyncio.sleep", pause)
    client = SimpleNamespace(get=AsyncMock(side_effect=responses))
    assert (await read_only_get(client, "unused", service="search")).status_code == 200
    assert delays == [3.0] and client.get.await_count == 2
    error = response_error(SimpleNamespace(status_code=429, headers={"retry-after": "120", "x-request-id": "bad\nsecret"}), "search")
    assert error.retryable and error.retry_after == 120 and not error.request_id
    client.get = AsyncMock(return_value=SimpleNamespace(status_code=429, headers={"retry-after": "120"}))
    with pytest.raises(RemoteCallError):
        await read_only_get(client, "unused", service="search")
    assert client.get.await_count == 1


@pytest.mark.asyncio
async def test_tool_result_distinguishes_rate_limits_from_permissions():
    async def fail(): raise RemoteCallError("search", 429, request_id="safe", retry_after=5)
    result = await AgentEngine(None)._call_tool_handler(fail, ToolCall("x", "search", {}), None, 0)
    classify_result(result)
    assert result.error_code == "REMOTE_RATE_LIMIT" and result.retryable
    assert tool_receipt(result)["http_status"] == 429
    result = ToolResult("x", False, "", "ARTIFACT_CONTRACT_ERROR: wrong kind", error_code="ARTIFACT_CONTRACT_ERROR")
    classify_result(result)
    assert result.retryable and result.error_code == "ARTIFACT_CONTRACT_ERROR"


@pytest.mark.asyncio
async def test_usage_only_final_stream_event_is_retained():
    class Response:
        status_code = 200
        async def aiter_lines(self):
            yield 'data: {"choices":[{"delta":{"content":"complete"},"finish_reason":"stop"}]}'
            yield 'data: {"choices":[],"usage":{"prompt_tokens":125,"completion_tokens":41}}'
            yield 'data: [DONE]'
    chunks = [chunk async for chunk in _consume_response(Response(), {})]
    usage = next(chunk.usage for chunk in chunks if chunk.type == "usage")
    assert usage == {"input_tokens": 125, "output_tokens": 41}
    session = AgentSession()
    AgentLoopCoordinator._record_tokens(session, LLMResponse(usage=usage))
    AgentLoopCoordinator._record_tokens(session, LLMResponse())
    assert session.total_tokens == 166 and session.usage_unknown_responses == 1


@pytest.mark.asyncio
async def test_http_failure_survives_agent_to_workflow_classification(monkeypatch):
    from server.workflows.engine import WorkflowEngine
    engine = AgentEngine(None)
    monkeypatch.setattr(engine, "_persist_session_transcript", lambda *a: None)
    session = AgentSession()
    loop = AgentLoopCoordinator(engine, session.id, "", None, None, 32, None, None)
    state = LoopState(session, [], False, [], "fake", None)
    error = RemoteCallError("fake", 502, request_id="request123")
    with pytest.raises(RemoteCallError) as raised:
        await loop._raise_provider_error(state, "fake", error)
    assert raised.value is error and WorkflowEngine._is_transport_research_error(error)


def test_scientific_scene_error_names_exact_field_and_valid_values():
    from server.services.scientific_scene import validate_scientific_scene
    from server.services.research_contract_versions import SCIENTIFIC_SCENE_SCHEMA
    scene = {"schema": SCIENTIFIC_SCENE_SCHEMA, "objects": [{"id": "a", "kind": "input", "label": "Signal", "source_path": "data"}],
             "relations": [{"kind": "comparison", "from": "a", "to": "a"}]}
    issues = validate_scientific_scene(scene)
    assert any("relations[0].kind" in issue and "allowed=" in issue for issue in issues)


@pytest.mark.asyncio
async def test_notification_preflight_warns_once_without_sending(tmp_path):
    from server.workflows.notification_readiness import notification_ready
    from server.workflows.run_state import RunState
    state = RunState(str(tmp_path), "notification-fixture")
    state.start([{"id": "lit"}], {})
    ctx = SimpleNamespace(run_state=state, run=SimpleNamespace(), host=SimpleNamespace(_emit=AsyncMock()))
    channel = SimpleNamespace(value="feishu")
    service = SimpleNamespace(_config=SimpleNamespace(enabled_channels=[channel]),
                              channel_verification=lambda _: {"verified": False, "configured": True})
    assert not await notification_ready(ctx, service)
    assert not await notification_ready(ctx, service)
    assert ctx.host._emit.await_count == 1
