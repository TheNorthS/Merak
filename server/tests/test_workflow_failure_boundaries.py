"""Pure regressions for operator stops and transport/semantic repair boundaries."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from server.agent.tool_response_protocol import ToolResponseProtocolError
from server.workflows.engine import WorkflowEngine
from server.workflows.models import NodeStatus, WorkflowNode, WorkflowRun
from server.workflows.node_execution_invocation import _other_failure
from server.workflows.revision_loop_context import RevisionLoopContext
from server.workflows.revision_loop_phases import prepare_consumer_state
from server.workflows.run_execution_context import CompleteRun, RunExecutionContext
from server.workflows.run_execution_final import handle_run_cancelled
from server.workflows.run_execution_startup import startup_wait
from server.workflows.run_state import RunState
from server.workflows.session_state import SessionState


def run_fixture(root: Path) -> tuple[WorkflowRun, RunState]:
    nodes = [
        WorkflowNode("idea", "Idea", "/idea-discovery", status=NodeStatus.COMPLETED),
        WorkflowNode("exp-design", "Design", "/experiment-plan", status=NodeStatus.RUNNING),
    ]
    run = WorkflowRun(id="boundary-test", project_path=str(root), nodes=nodes, status="running")
    state = RunState(str(root), run.id)
    state.start([{"id": node.id, "name": node.name, "skill": node.skill} for node in nodes], {})
    state.set_status("idea", "done")
    state.accept("idea", "test-verdict", "test-reviewer")
    state.set_status("exp-design", "running")
    return run, state


@pytest.mark.asyncio
async def test_cancel_joins_worker_before_return_and_preserves_accepted_phase(tmp_path: Path) -> None:
    run, state = run_fixture(tmp_path)
    engine = WorkflowEngine()
    started = asyncio.Event()
    cleanup_finished = asyncio.Event()

    async def worker() -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await asyncio.sleep(0)
            state.set_status("exp-design", "pending", error="cancelled by operator")
            cleanup_finished.set()

    task = asyncio.create_task(worker())
    engine._runs[run.id] = run
    engine._running_tasks[run.id] = task
    await started.wait()
    await engine.cancel_run(run.id)

    assert cleanup_finished.is_set() and task.done()
    assert run.status == "cancelled" and run.finished_at
    assert run.nodes[1].status == NodeStatus.IDLE
    saved = state.load()
    assert saved["status"] == "cancelled"
    assert saved["phases"]["idea"]["status"] == "accepted"
    assert saved["phases"]["exp-design"]["status"] == "pending"


@pytest.mark.asyncio
async def test_cancel_without_worker_is_still_durable(tmp_path: Path) -> None:
    run, state = run_fixture(tmp_path)
    engine = WorkflowEngine()
    engine._runs[run.id] = run
    await engine.cancel_run(run.id)
    assert state.load()["status"] == "cancelled"
    assert state.load()["phases"]["exp-design"]["status"] == "pending"
    assert all(node.status != NodeStatus.RUNNING for node in run.nodes)


@pytest.mark.asyncio
@pytest.mark.parametrize("operator_stop", [True, False])
async def test_startup_cancellation_preserves_operator_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operator_stop: bool,
) -> None:
    run, state = run_fixture(tmp_path)
    if operator_stop:
        run.status = "cancelled"
    context = RunExecutionContext(WorkflowEngine(), run, "test", "balanced", "draft", {})

    async def cancelled_sleep(_seconds: float) -> None:
        raise asyncio.CancelledError()

    monkeypatch.setattr("server.workflows.run_execution_startup.asyncio.sleep", cancelled_sleep)
    with pytest.raises(CompleteRun):
        await startup_wait(context)
    expected = "cancelled" if operator_stop else "incomplete"
    assert run.status == expected
    assert state.load()["status"] == expected


@pytest.mark.asyncio
async def test_cancel_finalization_clears_live_node_and_keeps_resume_artifacts(tmp_path: Path) -> None:
    run, state = run_fixture(tmp_path)
    events = []

    async def emit(_run: WorkflowRun, event: str, _data: dict) -> None:
        events.append(event)

    context = RunExecutionContext(SimpleNamespace(_emit=emit), run, "test", "balanced", "draft", {})
    context.run_state = state
    context.session_state = SessionState(str(tmp_path))
    await handle_run_cancelled(context)
    assert events == ["workflow_cancelled"]
    assert run.nodes[1].status == NodeStatus.IDLE
    assert state.load()["phases"]["idea"]["status"] == "accepted"
    assert state.load()["phases"]["exp-design"]["status"] == "pending"
    assert context.session_state.load()["run_id"] == run.id


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [
    TimeoutError("model request timeout"),
    ToolResponseProtocolError("MODEL_TOOL_ARGUMENTS_INVALID", "incomplete JSON"),
    RuntimeError("Model transport exhausted for implementation/data"),
])
async def test_preparation_transport_failure_never_becomes_content_revision(
    tmp_path: Path, error: Exception,
) -> None:
    engine = WorkflowEngine()
    run, _state = run_fixture(tmp_path)

    async def preparation(*_args, **_kwargs) -> str:
        raise error

    engine._prepare_node_for_gate = preparation
    context = RevisionLoopContext(
        host=engine, node=run.nodes[1], run=run, assurance="draft",
        research_direction="test", effort="balanced", opts={},
        max_revision_rounds=3, checkpoint_timeout=30, initial_result="existing output",
        require_fresh=False, no_progress_limit=2,
    )
    context.result = context.initial_result
    with pytest.raises(type(error)) as raised:
        await prepare_consumer_state(context)
    assert raised.value is error
    assert context.preparation_error == ""
    assert context.result == "existing output"


@pytest.mark.asyncio
async def test_blocked_implementation_does_not_render_preview_or_rerun_specialists(tmp_path: Path) -> None:
    from server.workflows.node_gate_preparation import _prepare_primary_artifacts
    from server.workflows.revision_loop_phases import prepare_scientific_stage

    run, _state = run_fixture(tmp_path)
    report = {"blocking": True, "status": "blocked", "issues": ["integration mapping missing"]}

    async def no_design(*_args) -> None:
        return None

    async def implementation(**_kwargs) -> dict:
        return report

    async def forbidden(*_args, **_kwargs) -> None:
        pytest.fail("A blocked implementation cannot start unrelated downstream work")

    host = SimpleNamespace(
        _ensure_exp_design_artifacts=no_design,
        _execute_staged_experiment_implementation=implementation,
        _ensure_planned_result_templates=forbidden,
        _execute_profile_specialists=forbidden,
    )
    result = await _prepare_primary_artifacts(
        host, run.nodes[1], run, "design", "test", "draft",
        {"staged_experiment_implementation": True, "run_experiment": False},
    )
    assert "blocked" in result
    assert run.options["_staged_implementation_report"] is report
    await prepare_scientific_stage(SimpleNamespace(run=run, node=run.nodes[1]))


def test_staged_findings_preserve_specific_owner_targets_without_plan_rewrite(tmp_path: Path) -> None:
    from server.workflows.acceptance_context import build_context, prerequisite_failure
    from server.workflows.revision_execution import _implementation_only

    engine = WorkflowEngine()
    run, _state = run_fixture(tmp_path)
    finding = {
        "id": "STAGE-INTEGRATION-LINKS", "severity": "blocker",
        "category": "staged_implementation", "owner_node": "exp-design",
        "message": "Mechanism check links are missing",
        "target_files": ["experiments/implementation/EVIDENCE_PATCH.json"],
    }
    scope = {"finding_ids": [finding["id"]], "target_files": finding["target_files"], "asset_ids": []}
    run.options["_staged_implementation_report"] = {
        "blocking": True, "issues": [finding["message"]], "findings": [finding], "repair_scope": scope,
    }
    gate = prerequisite_failure(build_context(engine, run.nodes[1], run, "draft", "", False))
    assert gate and not gate["accepted"]
    diagnostics = engine._gate_revision_diagnostics(gate)
    assert diagnostics["repair_scope"]["target_files"] == finding["target_files"]
    assert "experiments/EXPERIMENT_PLAN.md" not in diagnostics["repair_scope"]["target_files"]
    assert _implementation_only(run.nodes[1], diagnostics["findings"])
    assert "_staged_implementation_report" not in run.options


@pytest.mark.parametrize("code", [
    "MODEL_TOOL_ARGUMENTS_INVALID", "MODEL_TOOL_RESPONSE_INCOMPLETE", "MODEL_TOOL_RESPONSE_TRUNCATED",
])
def test_protocol_failure_and_wrapped_protocol_failure_use_transport_budget(code: str) -> None:
    engine = WorkflowEngine()
    error = ToolResponseProtocolError(code, "provider failure")
    assert engine._is_transport_research_error(error)
    assert engine._is_transport_research_error(RuntimeError(f"Wrapped provider failure: {error}"))
    assert not engine._is_transport_research_error(RuntimeError("METHOD_CONTRACT schema invalid"))


@pytest.mark.asyncio
async def test_protocol_failure_cannot_fall_back_to_unstructured_artifact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.workflows import node_execution_invocation as invocation

    async def no_event(*_args, **_kwargs) -> None:
        return None

    async def forbidden_fallback(**_kwargs) -> str:
        pytest.fail("Rejected tool response cannot be converted to a text artifact")

    host = SimpleNamespace(
        _can_text_fallback=lambda *_args: True,
        _is_transport_research_error=lambda _error: True,
        _persist_search_evidence=lambda *_args: None,
        _execute_node_text_fallback=forbidden_fallback,
    )
    context = SimpleNamespace(host=host, node=None, run=None, opts={}, enabled_tools=[], search_tool_trace=[])
    monkeypatch.setattr(invocation, "_mark_failed", lambda *_args: None)
    monkeypatch.setattr(invocation, "_failure_event", no_event)
    monkeypatch.setattr(invocation, "_persist_partial", no_event)
    error = ToolResponseProtocolError("MODEL_TOOL_ARGUMENTS_INVALID", "provider failure")
    with pytest.raises(ToolResponseProtocolError) as raised:
        await _other_failure(context, error)
    assert raised.value is error


def test_missing_compiler_stays_with_platform_not_manuscript_owner() -> None:
    engine = WorkflowEngine()
    node = WorkflowNode("compile", "Compile", "/paper-compile")
    owner = engine._revision_owner_for_gate(node, WorkflowRun(nodes=[node]), {
        "reason": "latexmk not found. Install TeX Live.",
    })
    assert owner is node
