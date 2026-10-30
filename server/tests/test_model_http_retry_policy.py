"""Provider HTTP failures keep their metadata and respect the shared deadline."""

from types import SimpleNamespace

import pytest

from server.agent import ModelRole, ToolDefinition
from server.agent.engine import AgentEngine
from server.agent.remote_errors import RemoteCallError


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 403, 429, 502, 503])
async def test_http_rejection_does_not_become_a_nonstream_protocol_retry(status):
    error = RemoteCallError("test", status, request_id="request-1", retry_after=600)

    class Provider:
        name = model = "test"

        async def chat_stream(self, **kwargs):
            raise error
            yield  # pragma: no cover -- async generator protocol

        async def chat(self, **kwargs):
            pytest.fail("HTTP failures must reach the retry policy without a hidden request")

    engine = AgentEngine(SimpleNamespace(_providers={}, _strategy={}))
    with pytest.raises(RemoteCallError) as caught:
        await engine._chat_with_progress(
            Provider(), "test", [], [ToolDefinition("Read", "read", {})], 32, None,
        )
    assert caught.value is error
    assert caught.value.request_id == "request-1"
    assert caught.value.retry_after == 600


@pytest.mark.asyncio
@pytest.mark.parametrize("delay, expected_calls", [(600, 1), (2, 2)])
async def test_retry_after_does_not_get_shortened_or_outlive_request_budget(monkeypatch, delay, expected_calls):
    provider = SimpleNamespace(name="test", model="test")
    router = SimpleNamespace(_providers={"test": provider}, _strategy={ModelRole.EXECUTOR: "test"})
    engine = AgentEngine(router)
    monkeypatch.setattr(engine, "_persist_session_transcript", lambda *args: None)
    session = engine.create_session()
    calls, waits = [], []
    error = RemoteCallError("test", 429, request_id="rate-limited", retry_after=delay)

    async def reject(**kwargs):
        calls.append(True)
        raise error

    async def sleep(seconds):
        waits.append(seconds)

    monkeypatch.setattr(engine, "_chat_with_progress", reject)
    monkeypatch.setattr("server.agent.agent_loop.asyncio.sleep", sleep)
    with pytest.raises(RemoteCallError) as caught:
        await engine.run(session.id, "test request")
    assert caught.value is error
    assert len(calls) == expected_calls
    if expected_calls == 1:
        assert waits == []
    else:
        assert len(waits) == 1 and waits[0] >= delay
    assert session.status.value == "error"


def test_http_retryability_does_not_come_from_request_id_digits():
    engine = AgentEngine(SimpleNamespace(_providers={}, _strategy={}))
    error = RemoteCallError("test", 401, request_id="request-429-503")
    assert not engine._is_transient_model_error(error)


@pytest.mark.asyncio
@pytest.mark.parametrize('status,limit', [(502, 4), (503, 4), (504, 4), (429, 2), (401, 1)])
async def test_explicit_gateway_rejection_has_bounded_same_provider_retries(monkeypatch, status, limit):
    from server.agent.model_deadlines import active_model_budget
    provider = SimpleNamespace(name='test', model='test')
    engine = AgentEngine(SimpleNamespace(_providers={'test': provider}, _strategy={ModelRole.EXECUTOR: 'test'}))
    monkeypatch.setattr(engine, '_persist_session_transcript', lambda *args: None)
    session = engine.create_session()
    budgets = []
    async def reject(**kwargs):
        budgets.append(active_model_budget.get())
        assert kwargs['provider'] is provider
        raise RemoteCallError('test', status)
    async def sleep(_seconds):
        return None
    monkeypatch.setattr(engine, '_chat_with_progress', reject)
    monkeypatch.setattr('server.agent.agent_loop.asyncio.sleep', sleep)
    with pytest.raises(RemoteCallError):
        await engine.run(session.id, 'bounded request')
    assert len(budgets) == limit
    assert all(item is budgets[0] and item.total_seconds == 300 for item in budgets)
