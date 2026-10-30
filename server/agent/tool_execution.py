"""Validated tool execution, nested-skill deadlines, and provenance logging."""

from __future__ import annotations

import asyncio
import inspect
import copy
from dataclasses import replace
import time
from pathlib import Path
from typing import Any, Callable, Optional

import structlog

from . import ToolCall
from .session_models import AgentEvent, AgentSession, ToolResult
from .tool_deadline import run_with_deadline, cancel_tool_task, ToolCancellationUnconfirmed

logger = structlog.get_logger()


class ToolExecutionMixin:
    async def _execute_tool(
        self, session: AgentSession, tool_call: ToolCall,
        on_event: Optional[Callable[[AgentEvent], Any]] = None,
    ) -> ToolResult:
        from .tool_harness import argument_fingerprint, classify_result

        # Runtime injection must not alter the model transcript or its schema.
        call = replace(tool_call, arguments=copy.deepcopy(tool_call.arguments))
        fingerprint = argument_fingerprint(call.name, call.arguments)
        started_at, started_clock = time.time(), time.monotonic()
        try:
            result = await self._execute_checked_tool(session, call, on_event)
        except asyncio.CancelledError:
            result = ToolResult(call.id, False, "", "TOOL_CANCELLED: execution cancelled",
                                error_code="TOOL_CANCELLED")
            self._record_execution_provenance(session, call, result, started_at)
            raise
        except ToolCancellationUnconfirmed as exc:
            result = ToolResult(call.id, False, "", str(exc), error_code="TOOL_CLEANUP_UNCONFIRMED")
            self._record_execution_provenance(session, call, result, started_at)
            raise
        classify_result(result)
        result.duration_ms = max(0, int((time.monotonic() - started_clock) * 1000))
        result.argument_fingerprint = fingerprint
        self._log_tool_event(call, result)
        self._record_execution_provenance(session, call, result, started_at)
        return result

    async def _execute_checked_tool(
        self, session: AgentSession, tool_call: ToolCall,
        on_event: Optional[Callable[[AgentEvent], Any]] = None,
    ) -> ToolResult:
        schema_result = self._validate_tool_call(tool_call)
        if schema_result:
            schema_result.phase = "validation"
            return schema_result
        self._inject_runtime_arguments(session, tool_call)
        handler = self._tools.get(tool_call.name)
        if not handler:
            return ToolResult(
                tool_call_id=tool_call.id, success=False, output="",
                error=f"Unknown tool: {tool_call.name}",
            )
        self._inject_figure_lineage(session, tool_call, handler)
        policy_result = self._apply_tool_policy(session, tool_call)
        if policy_result:
            policy_result.phase = "policy"
            policy_result.error_code = "ARTIFACT_CONTRACT_ERROR" if (policy_result.error or "").startswith("ARTIFACT_CONTRACT_ERROR") else "TOOL_POLICY_DENIED"
            policy_result.retryable = policy_result.error_code == "ARTIFACT_CONTRACT_ERROR"
            return policy_result
        limit_result = self._consume_tool_budget(session, tool_call)
        if limit_result:
            limit_result.phase = "budget"
            return limit_result
        staged_change = await self._stage_file_change(session, tool_call, on_event)
        if staged_change:
            return staged_change
        started_at = time.time()
        from ..services.chat_runtime_revision import chat_runtime_revision

        async with chat_runtime_revision(session, tool_call.name, tool_call.arguments) as revision:
            result = await self._call_tool_handler(handler, tool_call, on_event, started_at)
            if revision is not None:
                revision["status"] = "produced" if result.success else "failed"
                await self._emit(on_event, AgentEvent(type="research_changed", data=revision))
        return result

    @staticmethod
    def _inject_runtime_arguments(
        session: AgentSession, tool_call: ToolCall
    ) -> None:
        if tool_call.name == "Skill":
            tool_call.arguments.update({
                "project_path": session.project_path,
                "parent_context": session.context_key,
                "workflow_node_id": session.workflow_node_id,
            })
        elif tool_call.name in {"WritePart", "AssembleDocument"}:
            tool_call.arguments["project_path"] = session.project_path
        elif tool_call.name in {
            "begin_figure_svg_draft", "append_figure_svg_fragment",
            "finalize_figure_svg_draft", "replace_figure_svg_fragment",
            "review_figure_svg_draft", "review_figure_svg_composition",
            "begin_figure_storyboard",
            "add_figure_storyboard_candidate", "select_figure_storyboard",
            "draft_print_diagnostics",
            "prepare_figure_svg_canvas", "append_figure_canvas_primitive",
            "replace_figure_canvas_primitive", "finalize_figure_svg_canvas",
            "refresh_figure_canvas_runtime",
            "prepare_model_svg_draft", "submit_model_svg_draft",
        }:
            tool_call.arguments["project_path"] = session.project_path
        elif tool_call.name in {"reviewer_api", "reviewer_api_reply", "meta_optimize_propose", "figure_manifest"}:
            tool_call.arguments["project_path"] = session.project_path
        elif (
            tool_call.name == "Bash"
            and session.tool_policy == "workflow_artifacts"
            and not str(tool_call.arguments.get("cwd") or "").strip()
        ):
            tool_call.arguments["cwd"] = session.project_path

    @staticmethod
    def _inject_figure_lineage(
        session: AgentSession, tool_call: ToolCall, handler: Any
    ) -> None:
        if tool_call.name != "generate_figure":
            return
        if "generator_skill" not in inspect.signature(handler).parameters:
            return
        lineage = [
            item
            for item in session.context_key.removeprefix("skill-chain:").split(">")
            if item
        ]
        tool_call.arguments["generator_skill"] = lineage[-1] if lineage else ""

    def _consume_tool_budget(
        self, session: AgentSession, tool_call: ToolCall
    ) -> Optional[ToolResult]:
        limit = session.tool_call_limits.get(tool_call.name)
        count = session.tool_call_counts.get(tool_call.name, 0)
        if limit is not None and count >= limit:
            return self._blocked_tool_result(
                tool_call,
                f"TOOL_CALL_LIMIT_REACHED: `{tool_call.name}` is limited to {limit} calls "
                "in this agent session. Reuse the existing semantic artifacts, validate "
                "the manifest/specification, and finish without generating another variant.",
            )
        session.tool_call_counts[tool_call.name] = count + 1
        return None

    async def _call_tool_handler(
        self, handler: Any, tool_call: ToolCall,
        on_event: Optional[Callable[[AgentEvent], Any]], started_at: float,
    ) -> ToolResult:
        try:
            if not asyncio.iscoroutinefunction(handler):
                output = handler(**tool_call.arguments)
            elif tool_call.name == "Skill":
                output = await self._run_nested_skill(
                    handler, tool_call, on_event, started_at
                )
            else:
                output = await run_with_deadline(handler(**tool_call.arguments))
            return ToolResult(
                tool_call_id=tool_call.id, success=True,
                output=str(output) if output is not None else "",
            )
        except asyncio.CancelledError:
            raise
        except ToolCancellationUnconfirmed:
            raise
        except TimeoutError as exc:
            return ToolResult(tool_call.id, False, "", str(exc), error_code="TOOL_TIMEOUT")
        except Exception as exc:
            from .remote_errors import RemoteCallError
            if isinstance(exc, RemoteCallError):
                return ToolResult(tool_call.id, False, "", str(exc), error_code=exc.code,
                                  retryable=exc.retryable, http_status=exc.status,
                                  request_id=exc.request_id, retry_after=exc.retry_after)
            logger.error(
                "Tool execution failed", tool=tool_call.name, error=str(exc)
            )
            return ToolResult(
                tool_call_id=tool_call.id, success=False, output="", error=str(exc)
            )

    async def _run_nested_skill(
        self, handler: Any, tool_call: ToolCall,
        on_event: Optional[Callable[[AgentEvent], Any]], started_at: float,
    ) -> Any:
        wall_timeout, heartbeat_interval, cancel_grace = self._nested_skill_limits()
        from .delegate_activity import run_observed_delegate
        task = asyncio.create_task(run_observed_delegate(handler, tool_call.arguments, on_event))
        try:
            while True:
                elapsed = time.time() - started_at
                remaining = wall_timeout - elapsed
                if remaining <= 0:
                    await self._cancel_nested_skill(
                        task, tool_call, on_event, started_at,
                        wall_timeout, cancel_grace,
                    )
                done, _ = await asyncio.wait(
                    {task}, timeout=max(0.01, min(heartbeat_interval, remaining))
                )
                if done:
                    return await task
                await self._emit(on_event, AgentEvent(type="status", data={
                    "status": "skill_delegate_running",
                    "skill": str(tool_call.arguments.get("skill_name") or ""),
                    "elapsed": int(time.time() - started_at),
                }))
        except asyncio.CancelledError:
            await cancel_tool_task(task, cancel_grace)
            raise

    async def _cancel_nested_skill(
        self, task: asyncio.Task[Any], tool_call: ToolCall,
        on_event: Optional[Callable[[AgentEvent], Any]], started_at: float,
        wall_timeout: float, cancel_grace: float,
    ) -> None:
        await cancel_tool_task(task, cancel_grace)
        skill = str(tool_call.arguments.get("skill_name") or "")
        await self._emit(on_event, AgentEvent(type="status", data={
            "status": "skill_delegate_timeout", "skill": skill,
            "elapsed": int(time.time() - started_at), "timeout": wall_timeout,
        }))
        raise TimeoutError(
            "Nested skill wall-clock deadline exceeded after "
            f"{int(wall_timeout)}s: {skill or 'unknown skill'}"
        )

    @staticmethod
    def _nested_skill_limits() -> tuple[float, float, float]:
        from . import engine

        return (
            float(engine.NESTED_SKILL_WALL_TIMEOUT),
            float(engine.NESTED_SKILL_HEARTBEAT_INTERVAL),
            float(engine.NESTED_SKILL_CANCEL_GRACE),
        )

    @staticmethod
    def _log_tool_event(tool_call: ToolCall, result: ToolResult) -> None:
        try:
            from ..ws.router import log_tool_event

            project_path = (
                tool_call.arguments.get("project_path", "")
                or tool_call.arguments.get("path", "") or "."
            )
            if project_path and ("/" in project_path or "\\" in project_path):
                path = Path(project_path)
                project_path = next(
                    (str(parent) for parent in [path, *path.parents]
                     if (parent / ".merak").exists()),
                    ".",
                )
            log_tool_event(
                project_path, tool_call.name, tool_call.arguments,
                result.output[:200], result.success,
            )
        except Exception as exc:
            logger.warning("Tool event logging failed", tool=tool_call.name, error=str(exc))

    @staticmethod
    def _record_execution_provenance(
        session: AgentSession, tool_call: ToolCall,
        result: ToolResult, started_at: float,
    ) -> None:
        try:
            from ..services.execution_provenance import execution_provenance_service

            execution_provenance_service.record(
                project_path=session.project_path, session_id=session.id,
                tool=tool_call.name, arguments=tool_call.arguments,
                success=result.success, started_at=started_at,
                finished_at=time.time(), output=result.output or result.error or "",
            )
        except Exception as exc:
            logger.warning("Execution provenance logging failed", error=str(exc))
