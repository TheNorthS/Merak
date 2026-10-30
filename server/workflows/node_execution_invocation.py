"""Run one primary agent session with typed timeout and artifact recovery paths."""

from __future__ import annotations

import asyncio
from typing import Any

from ..agent.engine import agent_engine
from ..agent.tool_response_protocol import ToolResponseProtocolError
from ..services.skill_orchestrator import skill_orchestrator
from .models import AgentNodeWatchdogTimeout
from .node_execution_context import NodeExecutionContext


async def _persist_partial(context: NodeExecutionContext) -> None:
    await context.flush(True)
    partial = "".join(context.observer.state.agent_text_history).strip()
    if partial:
        context.node.output = partial[-8000:]


def _mark_failed(context: NodeExecutionContext, error: str) -> None:
    state = context.observer.state
    skill_orchestrator.mark_execution(
        context.project_path,
        context.run.id,
        context.node.id,
        context.skill_plan.primary,
        "failed",
        role="primary",
        session_id=context.session.id,
        error=error,
        policy_loaded=bool(context.owner_skill_prompt),
        execution_kind=context.skill_plan.execution_kind,
        model_provider=state.model_provider_used,
        model_name=state.model_name_used,
    )


async def _failure_event(context: NodeExecutionContext, error: str) -> None:
    await context.host._emit(
        context.run,
        "skill_invocation_failed",
        {
            "node_id": context.node.id,
            "skill": context.skill_plan.primary,
            "role": "primary",
            "session_id": context.session.id,
            "error": error[:500],
        },
    )


def _changed_artifacts(context: NodeExecutionContext) -> list[Any]:
    return context.host._changed_nonempty_node_artifacts(context.node, context.run)


async def _watchdog_timeout(
    context: NodeExecutionContext,
    error: AgentNodeWatchdogTimeout,
) -> str:
    changed = _changed_artifacts(context)
    message = str(error)
    await context.host._emit(
        context.run,
        "node_agent_deadline_reached",
        {
            "node_id": context.node.id,
            "timeout_seconds": error.limit_seconds,
            "timeout_kind": error.kind,
            "elapsed_seconds": round(error.elapsed_seconds, 1),
            "idle_seconds": round(error.idle_seconds, 1),
            "is_revision": bool(context.revision_context.strip()),
            "artifact_changes_detected": len(changed),
        },
    )
    context.host._persist_search_evidence(
        context.run,
        context.node,
        context.opts,
        context.enabled_tools,
        context.search_tool_trace,
    )
    _mark_failed(context, message)
    await _failure_event(context, message)
    await _persist_partial(context)
    raise TimeoutError(message) from error


async def _transport_timeout(
    context: NodeExecutionContext,
    error: asyncio.TimeoutError,
) -> str:
    message = context.host._exception_summary(error)
    context.host._persist_search_evidence(
        context.run,
        context.node,
        context.opts,
        context.enabled_tools,
        context.search_tool_trace,
    )
    _mark_failed(context, message)
    await _failure_event(context, message)
    await _persist_partial(context)
    raise error


async def _other_failure(
    context: NodeExecutionContext, error: Exception, *, allow_text_fallback: bool = True,
) -> str:
    context.host._persist_search_evidence(
        context.run,
        context.node,
        context.opts,
        context.enabled_tools,
        context.search_tool_trace,
    )
    _mark_failed(context, str(error))
    await _failure_event(context, str(error))
    await _persist_partial(context)
    raise error


def node_partial_stream_timeout(node_id: str) -> float | None:
    """Only large figure payloads extend silence; ordinary nodes use shared policy."""
    return 180.0 if node_id == "figure" else None


def node_output_token_budget(node_id: str) -> int:
    """Reserve enough output space for source-native figure tool arguments."""
    return 16_384 if node_id == "figure" else 8_192


async def run_primary_session(
    context: NodeExecutionContext, *, user_message: str | None = None,
    allow_text_fallback: bool = True,
) -> str:
    try:
        task = asyncio.create_task(
            agent_engine.run(
                session_id=context.session.id,
                user_message=context.user_message if user_message is None else user_message,
                on_event=context.observer.dispatch,
                tools=context.enabled_tools,
                max_tokens=node_output_token_budget(context.node.id),
                partial_stream_timeout_seconds=node_partial_stream_timeout(context.node.id),
            )
        )
        return await context.host._await_agent_with_activity_watchdog(
            task=task,
            run=context.run,
            node=context.node,
            is_revision=bool(context.revision_context.strip()),
            last_activity=lambda: context.observer.state.last_agent_activity,
        )
    except AgentNodeWatchdogTimeout as error:
        return await _watchdog_timeout(context, error)
    except asyncio.TimeoutError as error:
        return await _transport_timeout(context, error)
    except Exception as error:
        return await _other_failure(context, error, allow_text_fallback=allow_text_fallback)
