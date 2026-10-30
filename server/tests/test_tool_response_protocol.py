"""Tool transport regression tests use in-memory providers, never model calls."""

from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace

import pytest

from server.agent import LLMResponse, StreamChunk, ToolCall, ToolDefinition
from server.agent.engine import AgentEngine
from server.agent.openai_stream import _completed_calls, _consume_response, stream_openai
from server.agent.provider_messages import parse_openai_response
from server.agent.tool_response_protocol import ToolResponseProtocolError, parse_tool_arguments


def _event(delta: dict | None = None, finish: str | None = None) -> str:
    return "data: " + json.dumps({"choices": [{
        "delta": delta or {}, "finish_reason": finish,
    }]})


def _call(arguments: str, *, index: int = 0, name: str = "Write") -> dict:
    return {"index": index, "id": f"call_{index}", "function": {
        "name": name, "arguments": arguments,
    }}


class MemoryResponse:
    status_code = 200

    def __init__(self, lines: list[str]) -> None:
        self.lines = lines

    async def aiter_lines(self):
        for line in self.lines:
            yield line


async def _consume(lines: list[str]) -> tuple[list[StreamChunk], dict]:
    parts: dict = {}
    chunks = [chunk async for chunk in _consume_response(MemoryResponse(lines), parts)]
    return chunks, parts


@pytest.mark.parametrize("raw", ['{"content":"unfinished', "[]", "null", "42"])
def test_tool_arguments_must_be_complete_json_objects(raw: str) -> None:
    with pytest.raises(ToolResponseProtocolError) as failure:
        parse_tool_arguments(raw, "Write")
    assert failure.value.code == "MODEL_TOOL_ARGUMENTS_INVALID"
    assert raw not in str(failure.value)


def test_provider_argument_error_does_not_expose_partial_content() -> None:
    sensitive = '{"content":"private-token-123'
    with pytest.raises(ToolResponseProtocolError) as failure:
        parse_tool_arguments(sensitive, "Write")
    assert "private-token-123" not in str(failure.value)
    assert "offset" in str(failure.value)


@pytest.mark.asyncio
async def test_stream_eof_cannot_complete_even_valid_json_arguments() -> None:
    with pytest.raises(ToolResponseProtocolError) as failure:
        await _consume([_event({"tool_calls": [_call('{"content":"complete"}')]})])
    assert failure.value.code == "MODEL_TOOL_RESPONSE_INCOMPLETE"


@pytest.mark.asyncio
async def test_malformed_sse_event_is_not_silently_dropped() -> None:
    with pytest.raises(ToolResponseProtocolError):
        await _consume([_event({"tool_calls": [_call('{"content":')]}), "data: {bad"])


@pytest.mark.asyncio
async def test_nonobject_sse_event_is_rejected_without_partial_completion() -> None:
    with pytest.raises(ToolResponseProtocolError):
        await _consume(["data: []"])


def test_missing_function_name_cannot_silently_drop_a_completed_tool() -> None:
    with pytest.raises(ToolResponseProtocolError):
        _completed_calls({0: {"index": 0, "id": "call", "arguments": "{}"}})


@pytest.mark.asyncio
async def test_argument_fragments_and_repeated_identity_preserve_exact_content() -> None:
    _, parts = await _consume([
        _event({"tool_calls": [_call('{"content":"same ')]}),
        _event({"tool_calls": [_call('same same"}')]}),
        _event(finish="tool_calls"), "data: [DONE]",
    ])
    result = _completed_calls(parts)
    assert result[0].tool_call == ToolCall("call_0", "Write", {"content": "same same same"})


@pytest.mark.parametrize("finish", ["length", "max_tokens", "content_filter"])
@pytest.mark.asyncio
async def test_cutoff_response_cannot_authorize_valid_json_tools(finish: str) -> None:
    with pytest.raises(ToolResponseProtocolError) as failure:
        await _consume([
            _event({"tool_calls": [_call('{}')]}), _event(finish=finish),
        ])
    assert failure.value.code == "MODEL_TOOL_RESPONSE_TRUNCATED"


def test_non_streaming_parser_atomically_rejects_one_corrupt_sibling_call() -> None:
    with pytest.raises(ToolResponseProtocolError):
        parse_openai_response({"choices": [{
            "finish_reason": "tool_calls", "message": {"tool_calls": [
                _call('{"content":"complete"}'), _call('{"content":"partial', index=1),
            ]},
        }]}, "fake-model")


def test_non_streaming_parser_rejects_cutoff_even_when_arguments_are_valid() -> None:
    with pytest.raises(ToolResponseProtocolError) as failure:
        parse_openai_response({"choices": [{
            "finish_reason": "length", "message": {"tool_calls": [_call('{}')]},
        }]}, "fake-model")
    assert failure.value.code == "MODEL_TOOL_RESPONSE_TRUNCATED"


@pytest.mark.asyncio
async def test_stream_publishes_no_completed_calls_when_one_sibling_is_corrupt(monkeypatch) -> None:
    import httpx

    body = "\n".join([
        _event({"tool_calls": [_call('{}'), _call('{"content":"partial', index=1)]}),
        _event(finish="tool_calls"), "data: [DONE]",
    ])
    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda _: httpx.Response(200, text=body))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original_client(
        **kwargs, transport=transport,
    ))
    emitted = []
    with pytest.raises(ToolResponseProtocolError):
        async for chunk in stream_openai(url="https://in-memory.invalid", headers={}, payload={}):
            emitted.append(chunk.type)
    assert "tool_call_end" not in emitted


class RepairProvider:
    name = "memory"
    model = "memory-model"

    def __init__(self, *, retry_invalid: bool = False, stalled: bool = False) -> None:
        self.retry_invalid = retry_invalid
        self.stalled = stalled
        self.calls = []

    async def chat_stream(self, **kwargs):
        self.calls.append(("stream", kwargs))
        yield StreamChunk(type="text", content="Drafting a document.")
        yield StreamChunk(type="tool_call_delta", content="0")
        if self.stalled:
            await asyncio.Event().wait()
        raise ToolResponseProtocolError("MODEL_TOOL_ARGUMENTS_INVALID", "unfinished JSON")

    async def chat(self, **kwargs):
        self.calls.append(("nonstream", kwargs))
        if self.retry_invalid:
            raise ToolResponseProtocolError("MODEL_TOOL_ARGUMENTS_INVALID", "unfinished JSON")
        return LLMResponse(tool_calls=[ToolCall(
            "complete", "Write", {"path": "artifact.md", "content": "Complete content"},
        )], stop_reason="tool_calls")


async def _request(provider: RepairProvider, events: list, *, partial: float = 0.01):
    engine = AgentEngine(SimpleNamespace(_providers={}, _strategy={}))
    engine._transport_timeouts = lambda: (0.001, 0.02, 1.0, 0.02, 0.02)

    async def capture(event):
        events.append(event)

    return await engine._chat_with_progress(
        provider, provider.name, [], [ToolDefinition("Write", "write", {})],
        64, capture, partial_stream_timeout_seconds=partial,
    )


@pytest.mark.asyncio
async def test_invalid_tool_turn_gets_one_safe_nonstream_retry_before_execution() -> None:
    provider = RepairProvider()
    events = []
    response, streamed = await _request(provider, events)
    assert streamed is False
    assert response.tool_calls[0].arguments["content"] == "Complete content"
    assert [mode for mode, _ in provider.calls] == ["stream", "nonstream"]
    retry_prompt = provider.calls[1][1]["messages"][-1].content
    assert "before any tool execution" in retry_prompt
    assert "focused Edit operations after Read" in retry_prompt
    assert any(event.data.get("status") == "retrying_tool_response"
               for event in events if event.type == "status")


@pytest.mark.asyncio
async def test_second_invalid_response_stops_instead_of_retrying_indefinitely() -> None:
    provider = RepairProvider(retry_invalid=True)
    with pytest.raises(ToolResponseProtocolError):
        await _request(provider, [])
    assert [mode for mode, _ in provider.calls] == ["stream", "nonstream"]


@pytest.mark.asyncio
async def test_stalled_argument_deltas_are_not_accepted_as_partial_text() -> None:
    provider = RepairProvider(stalled=True)
    events = []
    response, _ = await _request(provider, events)
    assert response.tool_calls
    statuses = {event.data.get("status") for event in events if event.type == "status"}
    assert "partial_stream_recovered" not in statuses
    assert "retrying_tool_response" in statuses


@pytest.mark.asyncio
async def test_completed_tool_block_without_turn_completion_is_retried_atomically() -> None:
    class BlockOnlyProvider(RepairProvider):
        async def chat_stream(self, **kwargs):
            self.calls.append(("stream", kwargs))
            yield StreamChunk(type="tool_call_end", tool_call=ToolCall(
                "unconfirmed", "Write", {"path": "artifact.md", "content": "Unconfirmed"},
            ))

    provider = BlockOnlyProvider()
    events = []
    response, _ = await _request(provider, events)
    assert response.tool_calls[0].id == "complete"
    assert [mode for mode, _ in provider.calls] == ["stream", "nonstream"]
    assert any(event.data.get("error_code") == "MODEL_TOOL_RESPONSE_INCOMPLETE"
               for event in events if event.type == "status")


@pytest.mark.asyncio
async def test_expired_transport_budget_does_not_start_a_second_provider_call() -> None:
    provider = RepairProvider()
    engine = AgentEngine(SimpleNamespace(_providers={}, _strategy={}))
    engine._transport_timeouts = lambda: (0.001, 0.02, 0.02, 0.02, 0.02)
    with pytest.raises(TimeoutError):
        await engine._chat_non_streaming(
            provider, provider.name, [], [], 64, None, time.monotonic() - 1,
        )
    assert provider.calls == []


def test_legacy_invalid_call_guard_never_logs_raw_arguments() -> None:
    engine = AgentEngine(SimpleNamespace(_providers={}, _strategy={}))
    engine.register_tool("Write", "write", {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}, lambda **_: None)
    result = engine._validate_tool_call(ToolCall("bad", "Write", {
        "_parse_error": "invalid JSON", "_raw_arguments": "private-token-123",
    }))
    assert result is not None and result.success is False
    assert "private-token-123" not in result.error
    assert "complete JSON" in result.error
