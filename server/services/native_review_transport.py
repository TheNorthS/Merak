"""Honor explicit provider transport for stateless review without accepting partial streams."""

from contextlib import aclosing
from typing import Any, Awaitable, Callable

from ..agent.model_types import LLMResponse


def response_mode(provider: Any) -> str:
    return "stream" if getattr(provider, "streaming_enabled", False) is True else "non_stream"


async def call_native_review(provider: Any, messages: list[Any],
    activity: Callable[[], Awaitable[None]], record_retry: Callable[[dict], None] | None = None) -> LLMResponse:
    """Retry only explicit transient HTTP failures before any reviewer text."""
    from .native_review_retry import retry_read_only_review
    return await retry_read_only_review(
        lambda observe: _call_once(provider, messages, observe), activity, record_retry)


async def _call_once(provider: Any, messages: list[Any],
    activity: Callable[[], Awaitable[None]]) -> LLMResponse:
    """Keep native images and no-tool policy; partial streams are never accepted."""
    if response_mode(provider) == "non_stream":
        response = await provider.chat(messages, tools=None, temperature=0.0, max_tokens=8192)
        if getattr(response, "tool_calls", None):
            raise RuntimeError("Independent review returned forbidden tool calls")
        if getattr(response, "stop_reason", "") in {"length", "max_tokens", "content_filter"}:
            raise RuntimeError("Independent review response was incomplete; resume manually")
        return response
    chunks, usage, finish, done = [], {}, "", False
    async with aclosing(provider.chat_stream(messages, tools=None, temperature=0.0, max_tokens=8192)) as stream:
        async for chunk in stream:
            if chunk.type.startswith("tool_call") or chunk.tool_call is not None:
                raise RuntimeError("Independent review returned forbidden tool calls")
            if chunk.type == "text" and chunk.content:
                chunks.append(chunk.content)
                await activity()
            elif chunk.type == "usage":
                usage.update(chunk.usage)
            elif chunk.type == "finish":
                finish = chunk.finish_reason or chunk.content
            elif chunk.type == "done":
                done = True
    if not done or finish in {"length", "max_tokens", "content_filter"}:
        raise RuntimeError("Independent review stream was incomplete; resume manually")
    return LLMResponse(content="".join(chunks), usage=usage,
        stop_reason=finish or "end_turn", model=str(getattr(provider, "model", "")))
