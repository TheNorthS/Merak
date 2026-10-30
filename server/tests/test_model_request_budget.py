"""Tiny-clock, fake-provider checks for a shared retry deadline and manual stops."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from server.agent import LLMResponse, ModelRole, StreamChunk, ToolDefinition
from server.agent.engine import AgentEngine
from server.agent.agent_loop import AgentLoopCoordinator, LoopState
from server.agent.model_deadlines import ModelRequestBudget, active_model_budget, ModelResponseInterrupted, bounded_model_attempt


def _engine(monkeypatch, provider):
    router = SimpleNamespace(_providers={"fake": provider}, _strategy={ModelRole.EXECUTOR: "fake"})
    engine = AgentEngine(router)
    monkeypatch.setattr(engine, "_persist_session_transcript", lambda *args: None)
    engine._transport_timeouts = lambda: (0.002, 0.02, 0.08, 0.02, 0.02)
    return engine


@pytest.mark.asyncio
async def test_dripping_stream_cannot_extend_absolute_request_deadline(monkeypatch):
    closed = []
    class Provider:
        name = model = "fake"
        async def chat_stream(self, **kwargs):
            try:
                while True:
                    await asyncio.sleep(0.005)
                    yield StreamChunk(type="text", content="x")
            finally:
                closed.append(True)
    engine = _engine(monkeypatch, Provider())
    with pytest.raises(TimeoutError, match="MODEL_REQUEST_DEADLINE"):
        await engine._chat_with_progress(Provider(), "fake", [], None, 32, None)
    assert closed


@pytest.mark.asyncio
async def test_first_response_timeout_has_no_hidden_nonstream_fallback(monkeypatch):
    class Provider:
        name = model = "fake"
        async def chat_stream(self, **kwargs):
            await asyncio.Event().wait()
            yield StreamChunk(type="text", content="unreachable")
        async def chat(self, **kwargs):
            pytest.fail("timeout must not launch an unbudgeted fallback request")
    provider = Provider()
    engine = _engine(monkeypatch, provider)
    engine._transport_timeouts = lambda: (0.005, 0.03, 1.0, 0.03, 0.03)
    with pytest.raises(TimeoutError, match="before first"):
        await engine._chat_with_progress(provider, "fake", [], [ToolDefinition("Read", "read", {})], 32, None)


@pytest.mark.asyncio
async def test_request_budget_is_not_reset_for_attempts_or_provider_switches(monkeypatch):
    import server.agent.model_deadlines as deadlines
    clock = [10.0]
    monkeypatch.setattr(deadlines.time, "monotonic", lambda: clock[0])
    budget = ModelRequestBudget(total_seconds=5, started=clock[0])
    budget.begin_attempt()
    clock[0] += 4
    budget.begin_attempt()
    assert budget.remaining() == 1 and budget.attempts == 2
    with pytest.raises(TimeoutError, match="BUDGET_EXHAUSTED"):
        budget.begin_attempt()


@pytest.mark.asyncio
async def test_partial_output_is_persisted_and_not_automatically_retried(monkeypatch):
    provider = SimpleNamespace(name="fake", model="fake")
    engine = _engine(monkeypatch, provider)
    session = engine.create_session()
    calls = []
    async def fake_chat(**kwargs):
        calls.append(True)
        await kwargs["on_event"](SimpleNamespace(type="text", data="authored partial"))
        raise ConnectionError("connection reset")
    monkeypatch.setattr(engine, "_chat_with_progress", fake_chat)
    with pytest.raises(TimeoutError, match="MODEL_STREAM_INTERRUPTED"):
        await engine.run(session.id, "offline")
    assert len(calls) == 1
    assert any(m.content == "authored partial" for m in session.messages)
    assert session.status.value == "error"


@pytest.mark.asyncio
async def test_empty_request_retries_once_and_reports_shared_budget(monkeypatch):
    provider = SimpleNamespace(name="fake", model="fake")
    engine = _engine(monkeypatch, provider)
    session = engine.create_session()
    events, calls = [], []
    async def fake_chat(**kwargs):
        calls.append(True)
        raise TimeoutError("Model request timeout before first token")
    async def no_wait(*args):
        return None
    monkeypatch.setattr(engine, "_chat_with_progress", fake_chat)
    monkeypatch.setattr("server.agent.agent_loop.asyncio.sleep", no_wait)
    with pytest.raises(TimeoutError, match="timeout"):
        await engine.run(session.id, "offline", on_event=events.append)
    assert len(calls) == 2
    retry = next(event.data for event in events if event.type == "status" and event.data.get("status") == "retrying_provider")
    assert retry["next_attempt"] == 2 and retry["max_attempts"] == 2
    assert 0 < retry["remaining_seconds"] <= retry["total_budget_seconds"] == 300


@pytest.mark.asyncio
async def test_cancellation_propagates_after_provider_cleanup():
    entered, cleaned = asyncio.Event(), asyncio.Event()
    async def operation():
        try:
            entered.set()
            await asyncio.Event().wait()
        finally:
            cleaned.set()
    task = asyncio.create_task(bounded_model_attempt(operation(), 2))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cleaned.is_set()


@pytest.mark.asyncio
async def test_active_tool_stream_uses_shared_deadline_and_emits_safe_progress(monkeypatch):
    from server.agent.model_deadlines import active_attempt_deadline
    from server.agent import ToolCall

    class Provider:
        name = model = "fake"

        async def chat_stream(self, **kwargs):
            for _ in range(8):
                await asyncio.sleep(0.015)
                yield StreamChunk(type="tool_call_delta", content="private argument fragment")
            yield StreamChunk(type="tool_call_end", tool_call=ToolCall(id="call", name="Read", arguments={}))
            yield StreamChunk(type="finish", finish_reason="tool_calls")
            yield StreamChunk(type="done")

    provider = Provider()
    engine = _engine(monkeypatch, provider)
    engine._transport_timeouts = lambda: (0.02, 0.1, 0.03, 0.1, 0.1)
    budget = ModelRequestBudget(total_seconds=1.0)
    budget.begin_attempt()
    token = active_model_budget.set(budget)
    events = []
    try:
        response, _ = await engine._chat_with_progress(provider, "fake", [], [ToolDefinition("Read", "read", {})], 32, events.append)
    finally:
        active_model_budget.reset(token)
    assert response.tool_calls[0].name == "Read"
    progress = [event.data for event in events if event.type == "status" and event.data.get("status") == "streaming_model"]
    assert progress and all(0 < item["attempt_remaining_seconds"] <= 1.0 for item in progress)
    assert "private argument" not in str(progress)
    assert active_attempt_deadline.get() is None


@pytest.mark.asyncio
async def test_shared_budget_still_bounds_a_continuously_active_stream(monkeypatch):
    class Provider:
        name = model = "fake"

        async def chat_stream(self, **kwargs):
            while True:
                await asyncio.sleep(0.005)
                yield StreamChunk(type="tool_call_delta", content="0")

    provider = Provider()
    engine = _engine(monkeypatch, provider)
    token = active_model_budget.set(ModelRequestBudget(total_seconds=0.06))
    try:
        with pytest.raises(TimeoutError, match="MODEL_REQUEST_DEADLINE"):
            await engine._chat_with_progress(provider, "fake", [], [ToolDefinition("Read", "read", {})], 32, None)
    finally:
        active_model_budget.reset(token)


@pytest.mark.asyncio
async def test_non_streaming_attempt_has_the_same_shared_budget(monkeypatch):
    class Provider:
        name = model = "fake"
        streaming_enabled = False

        async def chat(self, **kwargs):
            await asyncio.sleep(0.08)
            return LLMResponse(content="done", stop_reason="stop")

    provider = Provider()
    engine = _engine(monkeypatch, provider)
    engine._transport_timeouts = lambda: (0.01, 0.03, 0.02, 0.03, 0.03)
    token = active_model_budget.set(ModelRequestBudget(total_seconds=1.0))
    try:
        response, _ = await engine._chat_with_progress(provider, "fake", [], None, 32, None)
        assert response.content == "done"
    finally:
        active_model_budget.reset(token)
