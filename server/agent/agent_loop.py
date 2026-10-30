"""Bounded agent-loop coordination independent from provider and tool adapters."""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import structlog

from . import LLMResponse, Message, ModelProvider, ToolDefinition
from .session_models import AgentEvent, AgentSession, AgentStatus, ToolResult
from .tool_harness import FailureBudget, classify_result, argument_fingerprint, argument_shape, tool_receipt
from .model_deadlines import ModelRequestBudget, active_model_budget, ModelResponseInterrupted
from .iteration_budget import AgentIterationLimit
from .readonly_closeout import reserve_readonly_verdict, warn_remaining_iterations

logger = structlog.get_logger()


@dataclass
class LoopState:
    session: AgentSession
    providers: list[tuple[str, ModelProvider]]
    allow_fallback: bool
    available_tools: list[ToolDefinition]
    provider_name: str
    provider: ModelProvider
    final_response: str = ""
    protocol_retries: int = 0
    schema_error_streak: int = 0
    partial_continuations: int = 0
    exhausted_notified: set[str] = field(default_factory=set)
    failure_budget: FailureBudget = field(default_factory=FailureBudget)


class AgentLoopCoordinator:
    def __init__(
        self, service: Any, session_id: str, user_message: str,
        on_event: Optional[Callable[[AgentEvent], Any]],
        tools: Optional[list[str]], max_tokens: int,
        system_prompt_override: Optional[str],
        partial_stream_timeout_seconds: Optional[float],
    ) -> None:
        self.service = service
        self.session_id = session_id
        self.user_message = user_message
        self.on_event = on_event
        self.tools = tools
        self.max_tokens = max_tokens
        self.system_prompt_override = system_prompt_override
        self.partial_timeout = partial_stream_timeout_seconds

    async def run(self) -> str:
        from .tool_deadline import execution_session
        token = execution_session.set(self.session_id)
        try:
            return await self._run_loop()
        except asyncio.CancelledError:
            self._persist_failure(AgentStatus.CANCELLED)
            raise
        except Exception:
            self._persist_failure(AgentStatus.ERROR)
            raise
        finally:
            execution_session.reset(token)

    def _persist_failure(self, status: AgentStatus) -> None:
        session = self.service._sessions.get(self.session_id)
        if session:
            session.status = status
            self.service._persist_session_transcript(session)

    async def _run_loop(self) -> str:
        state = await self._initialize()
        while state.session.iterations < state.session.max_iterations:
            await self._warn_remaining_iterations(state.session)
            if reserve_readonly_verdict(state, self.tools):
                await self.service._emit(self.on_event, AgentEvent(type="status", data={
                    "status": "review_closeout", "iterations_remaining": 1,
                }))
            state.session.iterations += 1
            await self._step_event(
                "model", f"Agent 内部步骤 {state.session.iterations}",
                "请求模型根据上下文给出下一步响应或工具调用。",
            )
            response, streamed = await self._request_model(state)
            state.session.last_stop_reason = str(response.stop_reason or "")
            self._record_tokens(state.session, response)
            protocol_action = await self._repair_response_protocol(state, response)
            if protocol_action == "retry":
                continue
            if await self._continue_partial_stream(state, response):
                continue
            if not response.tool_calls:
                await self._accept_final_response(state, response, streamed)
                break
            await self._execute_tool_calls(state, response)
        await self._complete(state)
        return state.final_response

    async def _warn_remaining_iterations(self, session: AgentSession) -> None:
        await warn_remaining_iterations(session, lambda event: self.service._emit(self.on_event, event))

    async def _initialize(self) -> LoopState:
        session = self.service._sessions.get(self.session_id)
        if not session:
            raise ValueError(f"Session {self.session_id} not found")
        session.messages.append(Message(role="user", content=self.user_message))
        session.status = AgentStatus.THINKING
        self.service._persist_session_transcript(session)
        providers, allow_fallback = self.service._candidate_providers(session)
        name, provider = providers[0]
        await self._provider_status(name, provider, "thinking", "选择模型")
        await self._step_event(
            "plan", "理解任务", "整理用户请求、当前上下文和可用工具。"
        )
        available = self.service._tool_definitions
        if self.tools is not None:
            allowed = set(self.tools)
            available = [item for item in available if item.name in allowed]
        return LoopState(
            session, providers, allow_fallback, available, name, provider,
            failure_budget=FailureBudget(session.tool_failure_counts),
        )

    async def _request_model(
        self, state: LoopState
    ) -> tuple[LLMResponse, bool]:
        token = active_model_budget.set(ModelRequestBudget())
        try:
            return await self._request_model_with_budget(state)
        finally:
            active_model_budget.reset(token)

    async def _request_model_with_budget(self, state: LoopState) -> tuple[LLMResponse, bool]:
        last_error: Optional[Exception] = None
        for index, (name, provider) in enumerate(state.providers):
            state.provider_name, state.provider = name, provider
            if index > 0:
                await self._provider_status(name, provider, "thinking", "切换模型")
            result, last_error, switch = await self._try_provider(
                state, index, name, provider
            )
            if result is not None:
                if index > 0:
                    state.providers = state.providers[index:] + state.providers[:index]
                return result
            if switch:
                continue
        state.session.status = AgentStatus.ERROR
        self.service._persist_session_transcript(state.session)
        message = self.service._model_error_message(
            last_error or RuntimeError("Model provider failed"),
            state.provider_name, state.allow_fallback,
        )
        await self.service._emit(
            self.on_event, AgentEvent(type="error", data=message)
        )
        raise RuntimeError(message)

    async def _try_provider(
        self, state: LoopState, index: int,
        name: str, provider: ModelProvider,
    ) -> tuple[tuple[LLMResponse, bool] | None, Optional[Exception], bool]:
        last_error: Optional[Exception] = None
        budget = active_model_budget.get() or ModelRequestBudget()
        while budget.attempts < budget.max_attempts:
            attempt = budget.attempts
            from .model_observation import ModelAttemptObservation
            observation = ModelAttemptObservation(self.service, state.session, self.on_event)
            try:
                budget.begin_attempt()
                messages = await self.service._prepare_messages_for_model(
                    session=state.session, provider=provider,
                    system_prompt_override=self.system_prompt_override,
                    max_tokens=self.max_tokens, on_event=observation.emit,
                )
                response = await self.service._chat_with_progress(
                    provider=provider, provider_name=name, messages=messages,
                    tools=state.available_tools if state.available_tools else None,
                    max_tokens=self.max_tokens, on_event=observation.emit,
                    partial_stream_timeout_seconds=self.partial_timeout,
                )
                return response, last_error, False
            except asyncio.CancelledError:
                observation.persist_interrupted()
                raise
            except Exception as exc:
                state.session.usage_unknown_responses += 1
                from .tool_deadline import ToolCancellationUnconfirmed
                if isinstance(exc, ToolCancellationUnconfirmed):
                    raise
                if observation.persist_interrupted() and not isinstance(exc, ModelResponseInterrupted):
                    exc = ModelResponseInterrupted(f"MODEL_STREAM_INTERRUPTED: {exc}")
                last_error = exc
                budget.allow_rejected_request_retry(exc)
                transient = self.service._is_transient_model_error(exc)
                retry_after = max(0.0, float(getattr(exc, "retry_after", None) or 0.0))
                retry_fits_budget = budget.remaining() > max(4.0, retry_after)
                can_fallback = bool(
                    state.allow_fallback and transient
                    and budget.attempts < budget.max_attempts and retry_fits_budget
                    and not retry_after
                    and index < len(state.providers) - 1
                )
                retry_limit = 0 if can_fallback else budget.max_attempts - 1
                if isinstance(exc, ModelResponseInterrupted):
                    await self._raise_provider_error(state, name, exc)
                if transient and attempt < retry_limit and budget.attempts < budget.max_attempts and retry_fits_budget:
                    await self._retry_provider(name, provider, exc, attempt, retry_limit)
                    continue
                if can_fallback:
                    await self._switch_provider(state, index, name, exc)
                    return None, last_error, True
                await self._raise_provider_error(state, name, exc)
        return None, last_error, False

    async def _retry_provider(
        self, name: str, provider: ModelProvider,
        exc: Exception, attempt: int, retry_limit: int,
    ) -> None:
        delay = min(8.0, 1.5 * (2 ** attempt) + random.uniform(0.0, 0.4))
        delay = max(delay, float(getattr(exc, "retry_after", None) or 0.0))
        budget = active_model_budget.get()
        if budget:
            delay = min(delay, budget.remaining())
        logger.warning(
            "Model provider failed, retrying same provider",
            provider=name, error=str(exc),
        )
        await self.service._emit(self.on_event, AgentEvent(type="status", data={
            "status": "retrying_provider", "provider": name,
            "model": getattr(provider, "model", provider.name),
            "attempt": attempt + 2, "max_attempts": retry_limit + 1,
            "retry_in_seconds": round(delay, 2), "error_category": "transport",
            **(budget.status() if budget else {}), "next_attempt": (budget.attempts + 1) if budget else attempt + 2,
        }))
        await asyncio.sleep(delay)

    async def _switch_provider(
        self, state: LoopState, index: int, name: str, exc: Exception
    ) -> None:
        next_name, next_provider = state.providers[index + 1]
        logger.warning(
            "Model provider failed, falling back", from_provider=name,
            to_provider=next_name, error=str(exc),
        )
        await self.service._emit(self.on_event, AgentEvent(type="status", data={
            "status": "switching_provider", "from": name, "to": next_name,
            "model": getattr(next_provider, "model", next_provider.name),
        }))

    async def _raise_provider_error(
        self, state: LoopState, name: str, exc: Exception
    ) -> None:
        state.session.status = AgentStatus.ERROR
        self.service._persist_session_transcript(state.session)
        message = self.service._model_error_message(
            exc, name, state.allow_fallback
        )
        await self.service._emit(
            self.on_event, AgentEvent(type="error", data=message)
        )
        if isinstance(exc, (TimeoutError, ConnectionError)):
            raise type(exc)(message) from exc
        from .remote_errors import RemoteCallError
        if isinstance(exc, RemoteCallError):
            raise exc
        raise RuntimeError(message) from exc

    async def _repair_response_protocol(
        self, state: LoopState, response: LLMResponse
    ) -> str:
        if response.tool_calls or not response.content:
            return "continue"
        calls = self.service._parse_text_tool_calls(
            response.content, state.available_tools
        )
        if calls:
            response.tool_calls = calls
            response.content = self.service._strip_text_tool_calls(response.content)
            return "continue"
        if not self.service._looks_like_tool_protocol_failure(
            response.content, state.available_tools
        ):
            return "continue"
        if state.protocol_retries >= 2:
            raise RuntimeError(
                "模型没有按工具协议调用工具，已停止该轮以避免把伪工具文本当作产物输出。"
            )
        state.protocol_retries += 1
        state.session.messages.extend([
            Message(role="assistant", content=response.content[:4000]),
            Message(
                role="user",
                content=self.service._tool_protocol_retry_message(state.available_tools),
            ),
        ])
        self.service._persist_session_transcript(state.session)
        await self._step_event(
            "route", "修正工具协议",
            "模型没有按工具协议调用工具，已隐藏错误正文并要求重试。",
        )
        return "retry"

    async def _continue_partial_stream(
        self, state: LoopState, response: LLMResponse
    ) -> bool:
        partial = response.stop_reason in {
            "partial_timeout", "partial_connection_error"
        }
        # Earlier writes may only have produced a plan/specification. They are
        # not proof that the interrupted model turn finished the actual task.
        if not partial or response.tool_calls or not state.available_tools:
            return False
        state.session.messages.append(Message(role="assistant", content=(response.content or "")[:16000]))
        self.service._persist_session_transcript(state.session)
        raise ModelResponseInterrupted("MODEL_STREAM_INTERRUPTED: unfinished response preserved; resume manually")


    async def _accept_final_response(
        self, state: LoopState, response: LLMResponse, streamed: bool
    ) -> None:
        if response.content:
            state.final_response = response.content
            if not streamed:
                await self.service._emit(
                    self.on_event, AgentEvent(type="text", data=response.content)
                )
        state.session.messages.append(
            Message(role="assistant", content=response.content or "")
        )

    async def _execute_tool_calls(
        self, state: LoopState, response: LLMResponse
    ) -> None:
        session = state.session
        ids = [call.id for call in response.tool_calls]
        previous = {call.get("id") for msg in session.messages for call in msg.tool_calls or []}
        if any(not identity or identity in previous for identity in ids) or len(set(ids)) != len(ids):
            session.status = AgentStatus.ERROR
            raise RuntimeError("TOOL_CALL_ID_INVALID: duplicate or empty call IDs; no tools in this batch executed")
        assistant = Message(role="assistant", content=response.content or "")
        assistant.tool_calls = [
            {"id": call.id, "name": call.name, "arguments": call.arguments}
            for call in response.tool_calls
        ]
        session.messages.append(assistant)
        self.service._persist_session_transcript(session)
        session.status = AgentStatus.TOOL_CALLING
        results = []
        for call in response.tool_calls:
            if results and results[-1].error_code in {"TOOL_REPEAT_LIMIT", "TOOL_BATCH_ABORTED"}:
                results.append(ToolResult(call.id, False, "", "TOOL_BATCH_ABORTED: prior call exhausted failure budget",
                                          error_code="TOOL_BATCH_ABORTED", phase="policy"))
                continue
            result = await self._execute_one_tool(state, call)
            results.append(result)
        await self._update_exhausted_tools(state)
        self._append_tool_results(state, results)
        if any(result.error_code == "TOOL_REPEAT_LIMIT" for result in results):
            session.status = AgentStatus.ERROR
            self.service._persist_session_transcript(session)
            raise RuntimeError("TOOL_REPEAT_LIMIT: identical failing call reached three attempts; inspect the persisted receipt")
        session.status = AgentStatus.THINKING
        self.service._persist_session_transcript(session)
        await self.service._emit(
            self.on_event,
            AgentEvent(type="status", data={
                "status": "thinking", "iteration": session.iterations,
            }),
        )

    async def _execute_one_tool(self, state: LoopState, call: Any) -> ToolResult:
        await self._step_event(
            "tool", f"调用工具：{call.name}",
            "读取信息、检索证据，或生成待审批的研究产物变更。",
        )
        await self.service._emit(self.on_event, AgentEvent(
            type="tool_call", data={"name": call.name, "args": call.arguments,
                                    "tool_call_id": call.id, "argument_shape": argument_shape(call.arguments)},
        ))
        fingerprint = argument_fingerprint(call.name, call.arguments)
        if state.failure_budget.exhausted(fingerprint):
            result = ToolResult(call.id, False, "", "TOOL_REPEAT_LIMIT: this unchanged call exhausted its persisted budget", error_code="TOOL_REPEAT_LIMIT", phase="budget")
        elif call.name not in {definition.name for definition in state.available_tools}:
            result = ToolResult(call.id, False, "", f"TOOL_NOT_ALLOWED: {call.name} is unavailable in this turn", phase="policy")
        else:
            result = await self.service._execute_tool(state.session, call, self.on_event)
        classify_result(result)
        result.argument_fingerprint = fingerprint
        if state.failure_budget.observe(result.argument_fingerprint, result):
            result.error_code = "TOOL_REPEAT_LIMIT"
        state.session.tool_receipts.append({"tool": call.name, "success": result.success, **tool_receipt(result)})
        state.session.tool_receipts[:] = state.session.tool_receipts[-200:]
        state.session.messages.append(Message(role="tool", content=result.output or result.error or "", tool_call_id=result.tool_call_id))
        self.service._persist_session_transcript(state.session)
        await self.service._emit(self.on_event, AgentEvent(
            type="tool_result", data={
                "name": call.name, "success": result.success,
                "output": (result.output or result.error or "")[:500],
                **tool_receipt(result),
            },
        ))
        await self._step_event(
            "observe", f"观察结果：{call.name}",
            "成功" if result.success else (result.error or "工具返回失败"),
        )
        return result

    async def _update_exhausted_tools(self, state: LoopState) -> None:
        session = state.session
        exhausted = {
            name for name, limit in session.tool_call_limits.items()
            if session.tool_call_counts.get(name, 0) >= limit
        }
        newly = exhausted - state.exhausted_notified
        if not newly:
            return
        state.available_tools = [
            definition for definition in state.available_tools
            if definition.name not in exhausted
        ]
        names = ", ".join(sorted(newly))
        state.exhausted_notified.update(newly)
        session.messages.append(Message(
            role="user",
            content=(
                f"Hard tool-call budget reached for: {names}. Do not request those "
                "tools again. Inspect or validate existing artifacts, then provide "
                "the final concise response."
            ),
        ))
        await self._step_event(
            "limit", "工具调用已达硬上限",
            f"已禁用 {names}；本轮只允许校验现有产物并结束。",
        )

    def _append_tool_results(
        self, state: LoopState, results: list[ToolResult]
    ) -> None:
        schema_errors = [
            result for result in results
            if (result.error or result.output).startswith("TOOL_SCHEMA_ERROR:")
        ]
        state.session.messages.extend(
            Message(
                role="tool", content=result.output or result.error or "",
                tool_call_id=result.tool_call_id,
            )
            for result in results
            if not any(message.role == "tool" and message.tool_call_id == result.tool_call_id for message in state.session.messages)
        )
        if not schema_errors:
            state.schema_error_streak = 0
            return
        state.schema_error_streak += 1
        state.session.messages.append(Message(
            role="user",
            content=(
                "上一轮工具调用参数无效且未执行。按错误中的 JSON 路径和 schema 修正参数；"
                "不要原样重复。Edit.new_text 允许空字符串表示删除；old_text 必须精确且唯一。"
            ),
        ))
        if state.schema_error_streak >= 3:
            state.session.status = AgentStatus.ERROR
            self.service._persist_session_transcript(state.session)
            last = schema_errors[-1]
            raise RuntimeError(
                "模型连续生成无效工具调用参数，已停止以避免空 Write/错误工具循环。"
                f"最后错误: {last.error or last.output}"
            )

    async def _complete(self, state: LoopState) -> None:
        session = state.session
        if not state.final_response and session.iterations >= session.max_iterations:
            session.status = AgentStatus.ERROR
            session.last_stop_reason = "iteration_limit"
            state.final_response = (
                f"Agent stopped at the hard internal iteration limit ({session.max_iterations}). "
                "Existing artifacts and tool results were preserved for deterministic validation."
            )
            session.messages.append(
                Message(role="assistant", content=state.final_response)
            )
            await self.service._emit(
                self.on_event, AgentEvent(type="text", data=state.final_response)
            )
            self.service._persist_session_transcript(session)
            raise AgentIterationLimit(session.id, session.iterations, session.max_iterations)
        session.status = AgentStatus.COMPLETED
        self.service._persist_session_transcript(session)
        await self.service._emit(self.on_event, AgentEvent(type="done", data={
            "response": state.final_response, "tokens": session.total_tokens,
            "usage_status": "partial_or_unknown" if session.usage_unknown_responses else "reported",
        }))

    @staticmethod
    def _record_tokens(session: AgentSession, response: LLMResponse) -> None:
        session.total_tokens += (
            response.usage.get("input_tokens", 0)
            + response.usage.get("output_tokens", 0)
        )
        if not response.usage:
            session.usage_unknown_responses += 1

    async def _provider_status(
        self, name: str, provider: ModelProvider,
        status: str, title: str,
    ) -> None:
        await self.service._emit(self.on_event, AgentEvent(type="status", data={
            "status": status, "provider": name,
            "model": getattr(provider, "model", provider.name),
        }))
        await self._step_event(
            "route", title,
            f"使用 {name} / {getattr(provider, 'model', provider.name)}。",
        )

    async def _step_event(self, kind: str, title: str, detail: str) -> None:
        await self.service._emit(
            self.on_event,
            AgentEvent(type="step", data={
                "kind": kind, "title": title, "detail": detail,
            }),
        )
