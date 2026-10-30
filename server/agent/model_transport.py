"""Timed streaming and fallback transport for model provider calls."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Optional

import structlog

from . import LLMResponse, Message, ModelProvider, ToolCall, ToolDefinition
from .session_models import AgentEvent
from .model_deadlines import active_model_budget, active_attempt_deadline, bounded_model_attempt, ModelResponseInterrupted
from .tool_response_protocol import (
    ToolResponseProtocolError, require_complete_tool_response,
    tool_response_retry_instruction,
)

logger = structlog.get_logger()


class ModelTransportMixin:
    async def _chat_with_progress(
        self, provider: ModelProvider, provider_name: str,
        messages: list[Message], tools: Optional[list[ToolDefinition]],
        max_tokens: int, on_event: Optional[Callable[[AgentEvent], Any]],
        partial_stream_timeout_seconds: Optional[float] = None,
    ) -> tuple[LLMResponse, bool]:
        budget = active_model_budget.get()
        timeout = budget.remaining() if budget else self._transport_timeouts()[2]
        return await bounded_model_attempt(self._chat_attempt(
            provider, provider_name, messages, tools, max_tokens, on_event,
            partial_stream_timeout_seconds,
        ), timeout)

    async def _chat_attempt(
        self, provider: ModelProvider, provider_name: str,
        messages: list[Message], tools: Optional[list[ToolDefinition]],
        max_tokens: int, on_event: Optional[Callable[[AgentEvent], Any]],
        partial_stream_timeout_seconds: Optional[float] = None,
    ) -> tuple[LLMResponse, bool]:
        started = time.monotonic()
        if getattr(provider, "streaming_enabled", True) is False:
            return await self._chat_non_streaming(
                provider, provider_name, messages, tools, max_tokens, on_event, started,
                count_attempt=False,
            )
        if tools is None:
            return await self._chat_text_stream(
                provider, provider_name, messages, max_tokens,
                on_event, started,
            )
        try:
            return await self._chat_tool_stream(
                provider, provider_name, messages, tools, max_tokens,
                on_event, started, partial_stream_timeout_seconds,
            )
        except ToolResponseProtocolError as exc:
            await self._waiting_event(
                on_event, "retrying_tool_response", provider, provider_name,
                time.monotonic() - started, error_code=exc.code,
            )
            logger.warning(
                "Rejected incomplete tool response; retrying once before execution",
                provider=provider_name, error_code=exc.code,
            )
            retry_messages = [*messages, Message(
                role="user", content=tool_response_retry_instruction(exc),
            )]
            return await self._chat_non_streaming(
                provider, provider_name, retry_messages, tools, max_tokens,
                on_event, started, "waiting_tool_response_retry",
            )

    @staticmethod
    async def _dispose_provider_task(task: asyncio.Task[Any]) -> None:
        from .tool_deadline import cancel_tool_task
        if not task.done():
            await cancel_tool_task(task, 5.0)
        elif not task.cancelled():
            task.exception()

    async def _dispose_provider_stream(self, task: asyncio.Task[Any], iterator: Any) -> None:
        await self._dispose_provider_task(task)
        close = getattr(iterator, "aclose", None)
        if close is not None:
            from .tool_deadline import cancel_tool_task, ToolCancellationUnconfirmed
            closing = asyncio.create_task(close())
            done, _ = await asyncio.wait({closing}, timeout=5.0)
            if not done:
                await cancel_tool_task(closing, 1.0)
                raise ToolCancellationUnconfirmed("Model stream cleanup did not complete")
            await closing

    @staticmethod
    def _transport_timeouts() -> tuple[float, float, float, float, float]:
        from . import engine

        return (
            float(engine.MODEL_WAIT_STATUS_INTERVAL),
            float(engine.MODEL_FIRST_RESPONSE_TIMEOUT),
            float(engine.MODEL_TOOL_RESPONSE_TIMEOUT),
            float(engine.MODEL_STREAM_SILENCE_TIMEOUT),
            float(engine.MODEL_TOOL_STREAM_SILENCE_TIMEOUT),
        )

    async def _chat_text_stream(
        self, provider: ModelProvider, provider_name: str,
        messages: list[Message], max_tokens: int,
        on_event: Optional[Callable[[AgentEvent], Any]], started: float,
    ) -> tuple[LLMResponse, bool]:
        chunks: list[str] = []
        streamed = False
        usage: dict = {}
        finish_reason = ""
        completed = False
        wait_interval, first_timeout, _, silence_timeout, _ = self._transport_timeouts()
        iterator = provider.chat_stream(
            messages=messages, tools=None, temperature=0.7, max_tokens=max_tokens
        ).__aiter__()
        pending = asyncio.create_task(iterator.__anext__())
        last_chunk_at = started
        last_progress_at = started
        try:
            while True:
                deadline = last_chunk_at + silence_timeout if streamed else started + first_timeout
                done, _ = await asyncio.wait({pending}, timeout=max(0, min(wait_interval, deadline - time.monotonic())))
                elapsed = time.monotonic() - started
                if not done:
                    if not streamed and elapsed >= first_timeout:
                        pending.cancel()
                        raise TimeoutError(
                            f"Model request timeout after {int(first_timeout)}s before first token: {provider_name}"
                        )
                    if streamed and time.monotonic() - last_chunk_at >= silence_timeout:
                        pending.cancel()
                        await self._waiting_event(
                            on_event, "stream_closed_after_silence",
                            provider, provider_name, elapsed,
                        )
                        raise ModelResponseInterrupted("MODEL_STREAM_INTERRUPTED: text stream became silent; resume manually")
                    await self._waiting_event(
                        on_event, "waiting_model", provider, provider_name, elapsed
                    )
                    continue
                try:
                    chunk = pending.result()
                except StopAsyncIteration:
                    break
                last_chunk_at = time.monotonic()
                if last_chunk_at - last_progress_at >= wait_interval:
                    await self._waiting_event(on_event, "streaming_model", provider, provider_name, last_chunk_at - started)
                    last_progress_at = last_chunk_at
                usage.update(chunk.usage)
                if chunk.type == "text" and chunk.content:
                    streamed = True
                    delta = self._dedupe_stream_text("".join(chunks), chunk.content)
                    if delta:
                        chunks.append(delta)
                        await self._emit(on_event, AgentEvent(type="text", data=delta))
                if chunk.finish_reason or chunk.type == "finish":
                    finish_reason = str(chunk.finish_reason or chunk.content or "")
                    completed = True
                if chunk.type == "done":
                    completed = True
                    break
                pending = asyncio.create_task(iterator.__anext__())
        finally:
            await self._dispose_provider_stream(pending, iterator)
        if streamed and not completed:
            raise ModelResponseInterrupted("MODEL_STREAM_INTERRUPTED: text stream ended without completion; resume manually")
        if not streamed:
            return await self._chat_non_streaming(
                provider, provider_name, messages, None,
                max_tokens, on_event, started, "waiting_model_fallback",
            )
        return LLMResponse(
            content="".join(chunks), stop_reason=finish_reason or "end_turn",
            model=getattr(provider, "model", provider.name),
            usage=usage,
        ), True

    async def _chat_non_streaming(
        self, provider: ModelProvider, provider_name: str,
        messages: list[Message], tools: Optional[list[ToolDefinition]],
        max_tokens: int, on_event: Optional[Callable[[AgentEvent], Any]],
        started: float, waiting_status: str = "waiting_model",
        *, count_attempt: bool = True,
    ) -> tuple[LLMResponse, bool]:
        wait_interval, _, timeout, _, _ = self._transport_timeouts()
        deadline = active_attempt_deadline.get()
        if deadline is not None:
            timeout = max(0.0, deadline - started)
        if time.monotonic() - started >= timeout:
            raise TimeoutError(
                f"Model request timeout after {int(timeout)}s before tool/text retry: {provider_name}"
            )
        budget = active_model_budget.get()
        if budget and count_attempt:
            budget.begin_attempt()
        task = asyncio.create_task(provider.chat(
            messages=messages, tools=tools, temperature=0.7, max_tokens=max_tokens
        ))
        try:
            while True:
                remaining = max(0, timeout - (time.monotonic() - started))
                done, _ = await asyncio.wait({task}, timeout=min(wait_interval, remaining))
                elapsed = time.monotonic() - started
                if done:
                    response = await task
                    require_complete_tool_response(
                        response.stop_reason, has_tools=bool(response.tool_calls),
                    )
                    return response, False
                if elapsed >= timeout:
                    task.cancel()
                    raise TimeoutError(
                        f"Model request timeout after {int(timeout)}s before tool/text response: {provider_name}"
                    )
                await self._waiting_event(
                    on_event, waiting_status, provider, provider_name, elapsed
                )
        finally:
            await self._dispose_provider_task(task)

    async def _chat_tool_stream(
        self, provider: ModelProvider, provider_name: str,
        messages: list[Message], tools: list[ToolDefinition], max_tokens: int,
        on_event: Optional[Callable[[AgentEvent], Any]], started: float,
        partial_timeout: Optional[float],
    ) -> tuple[LLMResponse, bool]:
        chunks: list[str] = []
        tool_calls: list[ToolCall] = []
        usage: dict = {}
        saw_tool_data = False
        streamed = False
        finish_reason = ""
        completed = False
        iterator = provider.chat_stream(
            messages=messages, tools=tools, temperature=0.7, max_tokens=max_tokens
        ).__aiter__()
        pending = asyncio.create_task(iterator.__anext__())
        last_chunk_at = started
        last_progress_at = started
        try:
            while True:
                action = await self._next_tool_stream_chunk(
                    pending, provider, provider_name, on_event, started,
                    last_chunk_at, streamed, bool(chunks),
                    bool(tool_calls) or saw_tool_data, partial_timeout,
                )
                if action["status"] == "wait":
                    continue
                if action["status"] in {"stop", "partial"}:
                    if action["status"] == "partial":
                        return self._partial_response(provider, chunks), True
                    break
                chunk = action["chunk"]
                usage.update(chunk.usage)
                last_chunk_at = time.monotonic()
                if last_chunk_at - last_progress_at >= self._transport_timeouts()[0]:
                    await self._waiting_event(on_event, "streaming_model", provider, provider_name, last_chunk_at - started)
                    last_progress_at = last_chunk_at
                saw_tool_data = saw_tool_data or chunk.type in {
                    "tool_call_start", "tool_call_delta", "tool_call_end",
                }
                streamed = streamed or chunk.type in {
                    "text", "tool_call_start", "tool_call_delta", "tool_call_end"
                }
                if chunk.type == "text" and chunk.content:
                    delta = self._dedupe_stream_text("".join(chunks), chunk.content)
                    if delta:
                        chunks.append(delta)
                        await self._emit(on_event, AgentEvent(type="text", data=delta))
                elif chunk.type == "tool_call_end" and chunk.tool_call:
                    tool_calls.append(chunk.tool_call)
                if chunk.finish_reason or chunk.type == "finish":
                    finish_reason = str(chunk.finish_reason or chunk.content or "")
                    completed = True
                if chunk.type == "done":
                    completed = True
                    break
                pending = asyncio.create_task(iterator.__anext__())
        except Exception as exc:
            return await self._recover_tool_stream_error(
                exc, provider, provider_name, messages, tools, max_tokens,
                on_event, started, chunks, tool_calls, streamed, partial_timeout,
                saw_tool_data,
            )
        finally:
            await self._dispose_provider_stream(pending, iterator)
        if not streamed:
            return await self._chat_non_streaming(
                provider, provider_name, messages, tools, max_tokens, on_event, started
            )
        self._validate_stream_completion(saw_tool_data, tool_calls, chunks, completed, finish_reason)
        return self._tool_stream_response(
            provider, chunks, tool_calls, finish_reason=finish_reason, usage=usage,
        ), bool(chunks)

    @staticmethod
    def _validate_stream_completion(
        saw_tool_data: bool, tool_calls: list[ToolCall], chunks: list[str], completed: bool, finish_reason: str,
    ) -> None:
        if saw_tool_data and not tool_calls:
            raise ToolResponseProtocolError(
                "MODEL_TOOL_RESPONSE_INCOMPLETE", "tool argument stream ended before a completed call",
            )
        if tool_calls and not completed:
            raise ToolResponseProtocolError(
                "MODEL_TOOL_RESPONSE_INCOMPLETE", "tool response ended without turn completion",
            )
        if chunks and not completed:
            raise ModelResponseInterrupted("MODEL_STREAM_INTERRUPTED: missing completion marker; resume manually")
        require_complete_tool_response(finish_reason, has_tools=bool(tool_calls))

    async def _next_tool_stream_chunk(
        self, pending: asyncio.Task[Any], provider: ModelProvider,
        provider_name: str, on_event: Optional[Callable[[AgentEvent], Any]],
        started: float, last_chunk_at: float, streamed: bool,
        has_text: bool, has_tools: bool, partial_timeout: Optional[float],
    ) -> dict[str, Any]:
        wait_interval, first_default, _, _, silence_default = self._transport_timeouts()
        first_timeout = max(first_default, partial_timeout or first_default)
        silence = partial_timeout or silence_default
        deadline = (last_chunk_at + silence) if streamed else (started + first_timeout)
        done, _ = await asyncio.wait({pending}, timeout=max(0, min(wait_interval, deadline - time.monotonic())))
        elapsed = time.monotonic() - started
        if done:
            try:
                return {"status": "chunk", "chunk": pending.result()}
            except StopAsyncIteration:
                return {"status": "stop"}
        if not streamed and elapsed >= first_timeout:
            pending.cancel()
            raise TimeoutError(
                f"Model request timeout after {int(first_timeout)}s before first tool/text chunk: {provider_name}"
            )
        if streamed and time.monotonic() - last_chunk_at >= silence:
            pending.cancel()
            if partial_timeout is not None and has_text and not has_tools:
                await self._waiting_event(
                    on_event, "partial_stream_interrupted",
                    provider, provider_name, elapsed,
                )
                raise ModelResponseInterrupted("MODEL_STREAM_INTERRUPTED: partial text without completed tool call; resume manually")
            raise TimeoutError(
                f"Model tool stream stalled after {int(silence)}s without chunks: {provider_name}"
            )
        await self._waiting_event(
            on_event, "waiting_model", provider, provider_name, elapsed
        )
        return {"status": "wait"}

    async def _recover_tool_stream_error(
        self, exc: Exception, provider: ModelProvider, provider_name: str,
        messages: list[Message], tools: list[ToolDefinition], max_tokens: int,
        on_event: Optional[Callable[[AgentEvent], Any]], started: float,
        chunks: list[str], tool_calls: list[ToolCall], streamed: bool,
        partial_timeout: Optional[float], saw_tool_data: bool,
    ) -> tuple[LLMResponse, bool]:
        if isinstance(exc, ModelResponseInterrupted):
            raise exc
        if isinstance(exc, ToolResponseProtocolError):
            raise exc
        if tool_calls or saw_tool_data:
            raise ToolResponseProtocolError(
                "MODEL_TOOL_RESPONSE_INCOMPLETE", "tool response was interrupted before turn completion",
            )
        if chunks:
            from .remote_errors import safe_exception_chain
            reason = "stream silence deadline reached" if isinstance(exc, TimeoutError) else "connection ended"
            raise ModelResponseInterrupted(
                f"MODEL_STREAM_INTERRUPTED: {reason} after partial output "
                f"({safe_exception_chain(exc)}); resume manually"
            ) from exc
        if isinstance(exc, TimeoutError) or partial_timeout is not None:
            raise exc
        from .remote_errors import RemoteCallError, RemoteStreamError
        if isinstance(exc, RemoteCallError) and (exc.status or isinstance(exc, RemoteStreamError)):
            # HTTP policy belongs to the outer budget; changing stream mode
            # cannot repair credentials, quota, or a rejected request schema.
            raise exc
        logger.warning(
            "Streaming tool call failed before executable tool call; falling back to non-streaming",
            provider=provider_name, error=str(exc), streamed_any=streamed,
        )
        await self._waiting_event(
            on_event, "stream_fallback_non_streaming", provider, provider_name, 0
        )
        return await self._chat_non_streaming(
            provider, provider_name, messages, tools,
            max_tokens, on_event, started,
        )

    @staticmethod
    def _tool_stream_response(
        provider: ModelProvider, chunks: list[str], tool_calls: list[ToolCall],
        *, finish_reason: str = "", usage: dict | None = None,
    ) -> LLMResponse:
        return LLMResponse(
            content="".join(chunks), tool_calls=tool_calls,
            stop_reason=finish_reason or ("tool_use" if tool_calls else "end_turn"),
            model=getattr(provider, "model", provider.name),
            usage=usage or {},
        )

    @staticmethod
    def _partial_response(provider: ModelProvider, chunks: list[str]) -> LLMResponse:
        return LLMResponse(
            content="".join(chunks), stop_reason="partial_timeout",
            model=getattr(provider, "model", provider.name),
        )

    async def _waiting_event(
        self, on_event: Optional[Callable[[AgentEvent], Any]], status: str,
        provider: ModelProvider, provider_name: str, elapsed: float,
        *, error_code: str = "",
    ) -> None:
        data = {
            "status": status, "provider": provider_name,
            "model": getattr(provider, "model", provider.name),
        }
        budget = active_model_budget.get()
        if budget:
            data.update(budget.status())
        deadline = active_attempt_deadline.get()
        if deadline is not None:
            data["attempt_remaining_seconds"] = round(max(0, deadline - time.monotonic()), 1)
        if elapsed:
            data["elapsed"] = int(elapsed)
        if error_code:
            data["error_code"] = error_code
        await self._emit(on_event, AgentEvent(type="status", data=data))
