"""In-memory event adapter tests: no agents, tools, workflow, or project writes."""

from types import SimpleNamespace
from typing import Any

import pytest

from server.workflows.engine import WorkflowEngine
from server.workflows.models import WorkflowNode, WorkflowRun
from server.workflows.node_agent_events import NodeAgentEventObserver


class MemoryHost(WorkflowEngine):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[tuple[str, dict[str, Any]]] = []

    async def _emit(
        self, run: WorkflowRun, event_type: str, data: dict[str, Any]
    ) -> None:
        self.events.append((event_type, data))

    @staticmethod
    def _agent_event_counts_as_progress(event: Any) -> bool:
        return event.type in {"text", "tool_call", "tool_result"}

    @staticmethod
    def _tool_artifact_path(payload: dict[str, Any]) -> str:
        args = payload.get("args")
        return str(args.get("file_path") or "") if isinstance(args, dict) else ""

    @staticmethod
    def _skill_invocation_traces(*args: Any) -> list[dict[str, Any]]:
        return [{"session_id": "delegate-session"}]


class MemoryTracer:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def mark_execution(
        self,
        project_path: str,
        run_id: str,
        node_id: str,
        skill: str,
        status: str,
        **metadata: Any,
    ) -> None:
        self.records.append({"skill": skill, "status": status, **metadata})


def _observer() -> tuple[NodeAgentEventObserver, MemoryHost, MemoryTracer]:
    host, tracer = MemoryHost(), MemoryTracer()
    node = WorkflowNode("figure", "Figure", "/figure-spec")
    run = WorkflowRun(
        id="event-fixture", nodes=[node], project_path="fixture-not-written"
    )
    observer = NodeAgentEventObserver(
        host,
        run,
        node,
        SimpleNamespace(id="primary-session"),
        tracer,
        {"web_search"},
    )
    return observer, host, tracer


@pytest.mark.asyncio
async def test_status_updates_model_identity_without_resetting_semantic_watchdog() -> (
    None
):
    observer, host, _ = _observer()
    before = observer.state.last_agent_activity

    await observer.dispatch(
        SimpleNamespace(
            type="status",
            data={
                "provider": "provider-A",
                "model": "model-B",
                "status": "waiting",
            },
        )
    )

    assert observer.state.model_provider_used == "provider-A"
    assert observer.state.model_name_used == "model-B"
    assert observer.state.last_agent_activity == before
    assert host.events[-1][0] == "agent_status"


@pytest.mark.asyncio
async def test_tool_calls_preserve_artifact_target_and_finish_exact_trace() -> None:
    observer, host, _ = _observer()
    await observer.dispatch(
        SimpleNamespace(
            type="tool_call",
            data={
                "name": "Write",
                "args": {"file_path": "paper/main.tex"},
            },
        )
    )
    await observer.dispatch(
        SimpleNamespace(
            type="tool_result",
            data={
                "name": "Write",
                "success": True,
                "output": "written",
            },
        )
    )

    assert observer.state.artifact_tool_trace[0]["finished"] is True
    assert host.events[-1][1]["artifact_path"] == "paper/main.tex"
    assert host.events[-1][1]["session_id"] == "primary-session"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("success", "expected"),
    [(True, "completed"), (False, "failed"), (None, "failed"), ("false", "failed")],
)
async def test_delegate_completion_requires_runtime_boolean_success(
    success: Any, expected: str
) -> None:
    observer, _, tracer = _observer()
    await observer.dispatch(
        SimpleNamespace(
            type="tool_call",
            data={
                "name": "Skill",
                "args": '{"skill_name": "/figure-spec"}',
            },
        )
    )
    data = {"name": "Skill", "output": "delegate output"}
    if success is not None:
        data["success"] = success
    await observer.dispatch(SimpleNamespace(type="tool_result", data=data))

    assert observer.state.skill_delegate_trace[0]["finished"] is True
    assert tracer.records[-1]["status"] == expected
    assert tracer.records[-1]["session_id"] == "delegate-session"


@pytest.mark.asyncio
async def test_search_result_records_retrieval_failure_kind_without_network_calls() -> (
    None
):
    observer, _, _ = _observer()
    await observer.dispatch(
        SimpleNamespace(
            type="tool_call", data={"name": "web_search", "args": {"q": "fixture"}}
        )
    )
    await observer.dispatch(
        SimpleNamespace(
            type="tool_result",
            data={
                "name": "web_search",
                "success": False,
                "output": "HTTP 429 rate limit",
            },
        )
    )

    record = observer.state.search_tool_trace[0]
    assert record["success"] is False
    assert record["failure_kind"] == "platform_unavailable"
    assert record["finished_at"] >= record["called_at"]


@pytest.mark.asyncio
async def test_text_history_and_flush_keep_the_same_shared_buffer() -> None:
    observer, host, _ = _observer()
    buffer = observer.state.agent_text_buffer
    await observer.dispatch(SimpleNamespace(type="text", data="Readable output."))
    await observer.flush(True)

    assert observer.state.agent_text_buffer is buffer
    assert observer.state.agent_text_history == ["Readable output."]
    assert host.events[-1][1]["text"] == "Readable output."
