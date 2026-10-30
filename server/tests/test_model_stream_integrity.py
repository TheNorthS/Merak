"""Malformed/aborted streams cannot manufacture success or expose provider URLs."""

import json
from types import SimpleNamespace

import httpx
import pytest

from server.agent import StreamChunk
from server.agent.engine import AgentEngine
from server.agent.model_deadlines import ModelResponseInterrupted
from server.agent.openai_stream import _consume_response
from server.agent.remote_errors import RemoteCallError
from server.tests.test_tool_response_protocol import MemoryResponse, _event


@pytest.mark.asyncio
async def test_text_eof_without_completion_is_an_interruption():
    with pytest.raises(ModelResponseInterrupted, match="completion"):
        _ = [chunk async for chunk in _consume_response(MemoryResponse([_event({"content": "partial"})]), {})]


@pytest.mark.asyncio
@pytest.mark.parametrize("ending", [[_event(finish="stop")], ["data: [DONE]"]])
async def test_explicit_text_completion_still_succeeds(ending):
    chunks = [chunk async for chunk in _consume_response(
        MemoryResponse([_event({"content": "complete"}), *ending]), {},
    )]
    assert any(chunk.content == "complete" for chunk in chunks)


@pytest.mark.asyncio
@pytest.mark.parametrize("finished", [False, True])
async def test_proxy_disconnect_after_finish_does_not_discard_complete_response(finished):
    class Response:
        status_code = 200

        async def aiter_lines(self):
            yield _event({"content": "model output"})
            if finished:
                yield _event(finish="stop")
            raise httpx.RemoteProtocolError("peer closed without terminating chunk")

    if finished:
        chunks = [chunk async for chunk in _consume_response(Response(), {})]
        assert any(chunk.finish_reason == "stop" for chunk in chunks)
    else:
        with pytest.raises(httpx.RemoteProtocolError):
            _ = [chunk async for chunk in _consume_response(Response(), {})]


@pytest.mark.asyncio
async def test_sse_provider_error_is_not_silently_dropped():
    response = MemoryResponse(["data: " + json.dumps({"error": {
        "code": "server_error", "message": "private-token https://private.invalid?key=secret",
    }}), "data: [DONE]"])
    with pytest.raises(RemoteCallError) as caught:
        _ = [chunk async for chunk in _consume_response(response, {})]
    assert "server_error" in str(caught.value)
    assert "private-token" not in str(caught.value) and "secret" not in str(caught.value)


@pytest.mark.asyncio
async def test_generic_text_provider_eof_cannot_be_accepted_as_final():
    class Provider:
        name = model = "fixture"

        async def chat_stream(self, **kwargs):
            yield StreamChunk(type="text", content="unfinished")

    engine = AgentEngine(SimpleNamespace(_providers={}, _strategy={}))
    with pytest.raises(ModelResponseInterrupted):
        await engine._chat_with_progress(Provider(), "fixture", [], None, 32, None)


@pytest.mark.asyncio
async def test_partial_stream_diagnostic_retains_safe_root_cause():
    class Provider:
        name = model = "fixture"

        async def chat_stream(self, **kwargs):
            yield StreamChunk(type="text", content="partial")
            try:
                raise httpx.RemoteProtocolError("private-token https://private.invalid?key=secret")
            except httpx.RemoteProtocolError as error:
                raise RuntimeError("wrapper private-token") from error

    engine = AgentEngine(SimpleNamespace(_providers={}, _strategy={}))
    with pytest.raises(ModelResponseInterrupted) as caught:
        await engine._chat_with_progress(Provider(), "fixture", [], [], 32, None)
    assert "RemoteProtocolError" in str(caught.value)
    assert "private-token" not in str(caught.value) and "secret" not in str(caught.value)
