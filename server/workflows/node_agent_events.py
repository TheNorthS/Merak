"""Observe agent events with explicit per-node state and immutable ownership IDs.

Any payloads are confined to the external agent-event adapter boundary.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from .models import WorkflowNode, WorkflowRun


class SessionIdentity(Protocol):
    id: str


class ExecutionTracer(Protocol):
    def mark_execution(
        self,
        project_path: str,
        run_id: str,
        node_id: str,
        skill: str,
        status: str,
        **metadata: Any,
    ) -> Any: ...


class AgentEventHost(Protocol):
    async def _emit(
        self, run: WorkflowRun, event_type: str, data: dict[str, Any]
    ) -> None: ...
    def _agent_event_counts_as_progress(self, event: Any) -> bool: ...
    def _tool_artifact_path(self, payload: dict[str, Any]) -> str: ...
    def _skill_invocation_traces(
        self, project_path: str, skill: str, started_at: float
    ) -> list[dict[str, Any]]: ...
    def _search_tool_result_succeeded(self, success: bool, output: str) -> bool: ...
    def _search_tool_failure_kind(self, success: bool, output: str) -> str: ...


@dataclass
class AgentEventState:
    agent_text_buffer: list[str] = field(default_factory=list)
    agent_text_history: list[str] = field(default_factory=list)
    search_tool_trace: list[dict[str, Any]] = field(default_factory=list)
    skill_delegate_trace: list[dict[str, Any]] = field(default_factory=list)
    artifact_tool_trace: list[dict[str, Any]] = field(default_factory=list)
    last_agent_text_emit: float = 0.0
    last_agent_activity: float = field(default_factory=time.monotonic)
    model_provider_used: str = ""
    model_name_used: str = ""


class NodeAgentEventObserver:
    def __init__(
        self,
        host: AgentEventHost,
        run: WorkflowRun,
        node: WorkflowNode,
        session: SessionIdentity,
        tracer: ExecutionTracer,
        search_tools: set[str],
    ):
        self.host = host
        self.run = run
        self.node = node
        self.session = session
        self.tracer = tracer
        self.search_tools = search_tools
        self.state = AgentEventState()

    async def dispatch(self, event: Any) -> None:

        if self.host._agent_event_counts_as_progress(event):
            self.state.last_agent_activity = time.monotonic()

        event_type = getattr(event, "type", "")

        handlers = {
            "text": self._text,
            "tool_call": self._tool_call,
            "tool_result": self._tool_result,
            "step": self._step,
            "status": self._status,
            "context_compacted": self._context,
            "context_repaired": self._context,
            "error": self._error,
        }

        handler = handlers.get(event_type)

        if handler is not None:
            await handler(event)

    async def flush(self, force: bool = False) -> None:

        if not self.state.agent_text_buffer:
            return

        joined = "".join(self.state.agent_text_buffer)

        now = time.time()

        should_flush = (
            force
            or len(joined) >= 600
            or (
                now - self.state.last_agent_text_emit >= 0.8
                and any((ch in joined for ch in "\n。！？.!?"))
            )
        )

        if not should_flush:
            return

        self.state.agent_text_buffer.clear()

        self.state.last_agent_text_emit = now

        if "<tool_use" in joined or "<arg name=" in joined:
            return

        cleaned = " ".join(joined.replace("\r", "").split())

        if cleaned:
            await self.host._emit(
                self.run,
                "agent_output",
                {"node_id": self.node.id, "text": cleaned[:1200]},
            )

    async def _text(self, event: Any) -> None:

        text = str(event.data or "")

        if "<tool_use" in text or "<arg name=" in text:
            return

        self.state.agent_text_history.append(text)

        self.state.agent_text_buffer.append(text)

        await self.flush(False)

    def _delegate_started(self, raw_args: Any) -> None:

        parsed_args = raw_args if isinstance(raw_args, dict) else {}

        if not parsed_args and isinstance(raw_args, str):
            try:
                candidate_args = json.loads(raw_args)

            except json.JSONDecodeError:
                candidate_args = {}

            parsed_args = candidate_args if isinstance(candidate_args, dict) else {}

        delegate_name = str(
            parsed_args.get("skill_name") or parsed_args.get("name") or ""
        ).lstrip("/")

        if delegate_name:
            delegate_record = {
                "skill": delegate_name,
                "started_at": time.time(),
                "finished": False,
            }

            self.state.skill_delegate_trace.append(delegate_record)

            self.tracer.mark_execution(
                self.run.project_path,
                self.run.id,
                self.node.id,
                delegate_name,
                "running",
                role="delegate",
                policy_loaded=True,
                execution_kind="model_owned",
            )

    def _delegate_finished(self, raw_success: bool, output: str) -> None:

        delegate = next(
            (
                item
                for item in reversed(self.state.skill_delegate_trace)
                if not item.get("finished")
            ),
            None,
        )

        if delegate:
            delegate["finished"] = True

            traces = self.host._skill_invocation_traces(
                self.run.project_path,
                str(delegate.get("skill") or ""),
                float(delegate.get("started_at") or time.time()),
            )

            trace = traces[-1] if traces else {}

            self.tracer.mark_execution(
                self.run.project_path,
                self.run.id,
                self.node.id,
                str(delegate.get("skill") or ""),
                "completed" if raw_success else "failed",
                role="delegate",
                session_id=str(trace.get("session_id") or ""),
                output=output if raw_success else "",
                error="" if raw_success else output,
                policy_loaded=raw_success,
                execution_kind="model_owned",
            )

    def _search_finished(self, tool_name: str, raw_success: bool, output: str) -> None:

        for call in reversed(self.state.search_tool_trace):
            if call.get("tool") == tool_name and (not call.get("finished_at")):
                call["success"] = self.host._search_tool_result_succeeded(
                    raw_success, output
                )

                call["failure_kind"] = self.host._search_tool_failure_kind(
                    raw_success, output
                )

                call["output_preview"] = output[:500]

                call["finished_at"] = time.time()

                break

    def _artifact_finished(self, tool_name: str, output: str) -> str:

        artifact_path = ""

        if tool_name in {"Write", "Edit"}:
            artifact_call = next(
                (
                    item
                    for item in reversed(self.state.artifact_tool_trace)
                    if item.get("tool") == tool_name and (not item.get("finished"))
                ),
                None,
            )

            if artifact_call:
                artifact_call["finished"] = True

                artifact_path = self.host._tool_artifact_path(
                    {"output": output}
                ) or str(artifact_call.get("artifact_path") or "")

        return artifact_path

    async def _tool_call(self, event: Any) -> None:

        await self.flush(True)

        data = event.data if isinstance(event.data, dict) else {}

        tool_name = str(data.get("name") or "")

        raw_args = data.get("args")

        if tool_name == "Skill":
            self._delegate_started(raw_args)

        if tool_name in self.search_tools:
            self.state.search_tool_trace.append(
                {
                    "tool": tool_name,
                    "args": raw_args
                    if isinstance(raw_args, (dict, list, str, int, float, bool))
                    or raw_args is None
                    else str(raw_args),
                    "called_at": time.time(),
                }
            )

        artifact_path = ""

        if tool_name in {"Write", "Edit"}:
            artifact_path = self.host._tool_artifact_path({"args": raw_args})

            self.state.artifact_tool_trace.append(
                {
                    "tool": tool_name,
                    "artifact_path": artifact_path,
                    "session_id": self.session.id,
                    "finished": False,
                }
            )

        tool_payload = {
            "node_id": self.node.id,
            "tool": tool_name,
            "args": str(data.get("args", ""))[:400],
            "session_id": self.session.id,
            **{key: data[key] for key in ("tool_call_id", "argument_shape") if key in data},
        }

        if artifact_path:
            tool_payload["artifact_path"] = artifact_path

        await self.host._emit(self.run, "agent_tool_call", tool_payload)

    async def _tool_result(self, event: Any) -> None:

        await self.flush(True)

        data = event.data if isinstance(event.data, dict) else {}

        tool_name = str(data.get("name") or "")

        output = str(data.get("output") or "")

        raw_success = data.get("success") is True

        if tool_name == "Skill":
            self._delegate_finished(raw_success, output)

        self._search_finished(tool_name, raw_success, output)

        artifact_path = self._artifact_finished(tool_name, output)

        result_payload = {
            "node_id": self.node.id,
            "tool": tool_name,
            "success": raw_success,
            "output": output[:600],
            "session_id": self.session.id,
            **{key: data[key] for key in ("tool_call_id", "error_code", "phase", "retryable",
                                         "duration_ms", "argument_fingerprint", "http_status", "request_id", "retry_after") if key in data},
        }

        if artifact_path:
            result_payload["artifact_path"] = artifact_path

        await self.host._emit(self.run, "agent_tool_result", result_payload)

    async def _step(self, event: Any) -> None:

        await self.flush(True)

        await self.host._emit(
            self.run, "agent_step", {"node_id": self.node.id, **(event.data or {})}
        )

    async def _status(self, event: Any) -> None:

        await self.flush(True)

        data = event.data if isinstance(event.data, dict) else {}

        provider = str(data.get("provider") or "").strip()

        model = str(data.get("model") or "").strip()

        if provider:
            self.state.model_provider_used = provider

        if model:
            self.state.model_name_used = model

        await self.host._emit(
            self.run,
            "agent_status",
            {
                "node_id": self.node.id,
                "status": data.get("status", ""),
                "provider": provider,
                "model": model,
                **{key: data[key] for key in ("attempt", "max_attempts", "next_attempt", "retry_in_seconds",
                                             "total_elapsed_seconds", "remaining_seconds", "total_budget_seconds",
                                             "elapsed", "error_code", "from", "to") if key in data},
            },
        )

    async def _context(self, event: Any) -> None:

        await self.flush(True)

        data = event.data if isinstance(event.data, dict) else {}

        await self.host._emit(self.run, event.type, {"node_id": self.node.id, **data})

    async def _error(self, event: Any) -> None:

        await self.flush(True)

        await self.host._emit(
            self.run,
            "agent_error",
            {"node_id": self.node.id, "error": str(event.data or "")},
        )
