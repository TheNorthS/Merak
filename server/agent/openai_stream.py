"""Streaming transport for OpenAI-compatible providers."""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

from .model_types import StreamChunk, ToolCall
from .tool_response_protocol import (
    ToolResponseProtocolError, parse_tool_arguments, require_complete_tool_response,
)


def _check_provider_error(data: dict[str, Any]) -> None:
    if data.get("error") is None:
        return
    from .remote_errors import RemoteStreamError
    error = data["error"]
    code = (error.get("code") or error.get("type")) if isinstance(error, dict) else ""
    raise RemoteStreamError(code)


async def _response_lines(response: Any, completion: dict[str, bool]) -> AsyncIterator[str]:
    """A protocol-complete turn survives a proxy's missing HTTP trailer."""
    import httpx

    try:
        async for line in response.aiter_lines():
            yield line
    except (httpx.RemoteProtocolError, httpx.ReadError):
        if not completion["finished"]:
            raise


async def _consume_response(
    response: Any,
    parts: dict[int, dict[str, Any]],
) -> AsyncIterator[StreamChunk]:
    if response.status_code != 200:
        from .remote_errors import response_error
        raise response_error(response, "openai-compatible")
    completion = {"finished": False}
    finish_reason = ""
    async for line in _response_lines(response, completion):
        if not line or not line.startswith("data:"):
            continue
        raw = line[5:].strip()
        if raw == "[DONE]":
            completion["finished"] = True
            break
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            raise ToolResponseProtocolError(
                "MODEL_TOOL_RESPONSE_INCOMPLETE", "provider returned a malformed streaming event",
            ) from None
        if not isinstance(data, dict):
            raise ToolResponseProtocolError(
                "MODEL_TOOL_RESPONSE_INCOMPLETE", "streaming event must be a JSON object",
            )
        _check_provider_error(data)
        if isinstance(data.get("usage"), dict):
            usage = data["usage"]
            yield StreamChunk(type="usage", usage={
                "input_tokens": usage.get("prompt_tokens", 0), "output_tokens": usage.get("completion_tokens", 0),
            })
        if not data.get("choices"):
            continue
        choice = data["choices"][0]
        chunk_finish = choice.get("finish_reason")
        if chunk_finish:
            finish_reason = str(chunk_finish)
            completion["finished"] = True
            yield StreamChunk(
                type="finish",
                content=str(finish_reason),
                finish_reason=str(finish_reason),
            )
        delta = choice.get("delta", {})
        if delta.get("content"):
            yield StreamChunk(type="text", content=delta["content"])
        for call in delta.get("tool_calls") or []:
            index = int(call.get("index", len(parts)))
            part = parts.setdefault(index, {
                "index": index, "id": "", "name": "", "arguments": "",
            })
            function = call.get("function") or {}
            changed = False
            for target, value in (
                ("id", call.get("id")),
                ("name", function.get("name")),
                ("arguments", function.get("arguments")),
            ):
                if value:
                    previous = str(part[target])
                    incoming = str(value)
                    # Identity metadata may be repeated by compatible proxies;
                    # argument content remains literal deltas, never guessed.
                    part[target] = (
                        previous if target != "arguments" and previous == incoming
                        else previous + incoming
                    )
                    changed = True
            if changed:
                yield StreamChunk(type="tool_call_delta", content=str(index))
    if parts and not completion["finished"]:
        raise ToolResponseProtocolError(
            "MODEL_TOOL_RESPONSE_INCOMPLETE", "tool stream ended without a completion marker",
        )
    if not completion["finished"]:
        from .model_deadlines import ModelResponseInterrupted
        raise ModelResponseInterrupted("MODEL_STREAM_INTERRUPTED: stream ended without a completion marker; resume manually")
    require_complete_tool_response(finish_reason, has_tools=bool(parts))


def _completed_calls(parts: dict[int, dict[str, Any]]) -> list[StreamChunk]:
    chunks: list[StreamChunk] = []
    for part in sorted(parts.values(), key=lambda item: item["index"]):
        name = str(part.get("name") or "").strip()
        if not name:
            raise ToolResponseProtocolError(
                "MODEL_TOOL_RESPONSE_INCOMPLETE", "completed tool response omitted its function name",
            )
        arguments = parse_tool_arguments(part.get("arguments"), name)
        chunks.append(StreamChunk(
            type="tool_call_end",
            tool_call=ToolCall(
                id=str(part.get("id") or f"call_{part['index']}"),
                name=name,
                arguments=arguments,
            ),
        ))
    return chunks


async def stream_openai(
    *,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
) -> AsyncIterator[StreamChunk]:
    import httpx

    timeout = httpx.Timeout(connect=10.0, read=240.0, write=20.0, pool=5.0)
    parts: dict[int, dict[str, Any]] = {}
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        try:
            async with client.stream("POST", url, json=payload, headers=headers) as response:
                async for chunk in _consume_response(response, parts):
                    yield chunk
        except httpx.ConnectError as exc:
            from .remote_errors import RemoteTransportError
            raise RemoteTransportError("openai-compatible", type(exc).__name__) from exc
        except (httpx.RemoteProtocolError, httpx.ReadError) as exc:
            if parts:
                raise ToolResponseProtocolError(
                    "MODEL_TOOL_RESPONSE_INCOMPLETE", "connection closed while collecting tool calls",
                ) from exc
            from .remote_errors import RemoteTransportError
            raise RemoteTransportError("openai-compatible", type(exc).__name__) from exc
        except httpx.TimeoutException as exc:
            from .remote_errors import RemoteTransportError
            raise RemoteTransportError("openai-compatible", type(exc).__name__) from exc
    for chunk in _completed_calls(parts):
        yield chunk
    yield StreamChunk(type="done")
