from __future__ import annotations

from server.tests._workflow_checkpoints_support import (
    NodeStatus as NodeStatus,
    Path as Path,
    RunState as RunState,
    WorkflowEngine as WorkflowEngine,
    WorkflowNode as WorkflowNode,
    WorkflowRun as WorkflowRun,
    asyncio as asyncio,
    pytest as pytest,
)


@pytest.mark.asyncio
async def test_initial_paper_transport_exhaustion_is_incomplete_not_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    paper = WorkflowNode(id="paper", name="Paper", skill="/paper-write")
    run = WorkflowRun(
        id="paper-transport-checkpoint",
        project_path=str(tmp_path),
        nodes=[paper],
        status="running",
    )
    engine._runs[run.id] = run
    RunState(str(tmp_path), run.id).start(
        [{"id": paper.id, "name": paper.name, "skill": paper.skill}],
        {
            "direction": "test direction",
            "effort": "balanced",
            "assurance": "submission",
            "options": {"run_experiment": False},
        },
    )
    events: list[tuple[str, dict]] = []

    async def staged_paper(**_kwargs) -> str:
        raise RuntimeError(
            "Model transport exhausted for paper/blueprint after 2 attempts. "
            "Last error: OpenAI API error 502"
        )

    async def planned_templates(*_args, **_kwargs) -> None:
        return None

    async def emit(_run, event: str, payload: dict) -> None:
        events.append((event, payload))

    monkeypatch.setattr(engine, "_execute_staged_paper", staged_paper)
    monkeypatch.setattr(engine, "_ensure_planned_result_templates", planned_templates)
    monkeypatch.setattr(engine, "_emit", emit)
    monkeypatch.setattr(
        "server.services.node_risk_audit.node_risk_audit_service.preflight_node",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        "server.services.node_risk_audit.node_risk_audit_service.audit_workflow",
        lambda *_args, **_kwargs: {"status": "clear", "counts": {}, "findings": []},
    )

    await engine._execute_run(
        run,
        "test direction",
        "balanced",
        "submission",
        {
            "run_experiment": False,
            "code_review": False,
            "research_quality_mode": "off",
            "model_transport_max_attempts": 2,
        },
    )

    phase = RunState(str(tmp_path), run.id).load()["phases"]["paper"]
    assert run.status == "incomplete"
    assert paper.status == NodeStatus.IDLE
    assert phase["status"] == "awaiting_revision"
    assert phase["details"]["revision"]["error_category"] == "transport"
    assert "node_failed" not in [event for event, _ in events]
    assert "workflow_failed" not in [event for event, _ in events]
    assert "workflow_incomplete" in [event for event, _ in events]


@pytest.mark.asyncio
async def test_transport_retry_reuses_valid_artifact_written_before_disconnect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    node = WorkflowNode(id="paper", name="Paper", skill="/paper-write")
    run = WorkflowRun(
        id="transport-artifact-recovery",
        project_path=str(tmp_path),
        nodes=[node],
        status="running",
        options={"model_transport_max_attempts": 4},
    )
    RunState(str(tmp_path), run.id).start(
        [{"id": node.id, "name": node.name, "skill": node.skill}],
        {"options": run.options},
    )
    events: list[str] = []
    attempts = 0

    async def operation() -> str:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("peer closed connection without complete message body")

    async def emit(_run, event: str, _payload: dict) -> None:
        events.append(event)

    monkeypatch.setattr(engine, "_emit", emit)
    with pytest.raises(RuntimeError, match="peer closed"):
        await engine._execute_with_model_transport_retry(
            run=run,
            node_id=node.id,
            operation_name="paper/method",
            stage_id="method",
            operation=operation,
            opts=run.options,
            recovery_probe=lambda: "validated persisted method section",
        )


    assert attempts == 1
    assert events == ["node_transport_exhausted"]
