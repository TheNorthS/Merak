from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import pytest

from server.agent.engine import AgentEvent, agent_engine
from server.services.skill_orchestrator import skill_orchestrator
from server.services.skill_registry import skill_registry
from server.workflows.engine import (
    AgentNodeWatchdogTimeout,
    WorkflowEngine,
    WorkflowNode,
    WorkflowRun,
)
from server.workflows.run_state import RunState


def _event(
    project: Path,
    run_id: str,
    timestamp: float,
    event: str,
    data: dict[str, Any],
) -> None:
    path = project / ".merak" / "runs" / f"{run_id}.events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps({
            "schema": 1,
            "timestamp": timestamp,
            "run_id": run_id,
            "event": event,
            "data": data,
        }, ensure_ascii=False) + "\n")


def _timed_out_fixture(
    project: Path,
    *,
    run_id: str = "timeout-recovery",
    artifact_relative: str = "ideas/ideas.md",
    event_session_id: str = "primary-session",
    event_node_id: str = "idea",
    event_run_id: str | None = None,
    delegate_active: bool = False,
) -> tuple[WorkflowNode, WorkflowRun, dict[str, Any]]:
    node = WorkflowNode(
        id="idea",
        name="Idea",
        skill="/idea-discovery",
        execution_kind="model_owned",
    )
    run = WorkflowRun(
        id=run_id,
        project_path=str(project),
        nodes=[node],
        status="running",
    )
    state = RunState(str(project), run_id)
    state.start(
        [{
            "id": node.id,
            "name": node.name,
            "skill": node.skill,
            "execution_kind": "model_owned",
            "policy_required": True,
        }],
        {"direction": "test", "options": {"research_quality_mode": "off"}},
    )
    state.set_status(node.id, "running")
    state.set_status(
        node.id,
        "failed",
        error="TimeoutError: Agent node wall-time limit reached after 300.0s: idea",
    )

    artifact = project / artifact_relative
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("# Candidate ideas\n\nA complete candidate set.\n", encoding="utf-8")

    skills_path = project / ".merak" / "runs" / f"{run_id}.skills.json"
    skills_path.write_text(json.dumps({
        "schema": 2,
        "run_id": run_id,
        "registry_total": 1,
        "stages": {
            "idea": {
                "node_id": "idea",
                "primary": "domain-idea-discovery",
                "execution_kind": "model_owned",
                "policy_required": True,
                "invocations": [{
                    "skill": "domain-idea-discovery",
                    "role": "primary",
                    "status": "running",
                    "session_id": "primary-session",
                    "execution_kind": "model_owned",
                    "policy_loaded": True,
                    "skill_source": "test/SKILL.md",
                    "skill_sha256": "a" * 64,
                    "skill_bytes": 123,
                    "updated_at": 10.0,
                }],
                "runtime_invocations": [],
            }
        },
    }, ensure_ascii=False), encoding="utf-8")

    journal_run_id = event_run_id or run_id
    _event(project, journal_run_id, 10.0, "skill_invocation_started", {
        "node_id": event_node_id,
        "skill": "domain-idea-discovery",
        "role": "primary",
        "session_id": "primary-session",
    })
    if delegate_active:
        _event(project, journal_run_id, 10.5, "skill_invocation_started", {
            "node_id": event_node_id,
            "skill": "idea-creator",
            "role": "delegate",
            "session_id": "delegate-session",
        })
    _event(project, journal_run_id, 11.0, "agent_tool_call", {
        "node_id": event_node_id,
        "tool": "Write",
        "args": str({"path": str(artifact), "content": "candidate set"}),
        "session_id": event_session_id,
        "artifact_path": str(artifact),
    })
    _event(project, journal_run_id, 12.0, "agent_tool_result", {
        "node_id": event_node_id,
        "tool": "Write",
        "success": True,
        "output": f"Written {artifact.stat().st_size} bytes to {artifact}",
        "session_id": event_session_id,
        "artifact_path": str(artifact),
    })
    phase = (state.load() or {})["phases"][node.id]
    return node, run, phase


def test_agent_status_heartbeat_is_not_semantic_progress() -> None:
    engine = WorkflowEngine()

    assert engine._agent_event_counts_as_progress(AgentEvent(
        type="status",
        data={"status": "skill_delegate_running"},
    )) is False
    assert engine._agent_event_counts_as_progress(AgentEvent(
        type="status",
        data={"status": "waiting_model"},
    )) is False
    assert engine._agent_event_counts_as_progress(AgentEvent(
        type="tool_result",
        data={"name": "Skill", "success": True},
    )) is True


@pytest.mark.asyncio
async def test_activity_watchdog_does_not_cancel_an_active_agent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    node = WorkflowNode(id="idea", name="Idea", skill="/idea-discovery")
    run = WorkflowRun(
        id="active-watchdog",
        project_path=str(tmp_path),
        nodes=[node],
        status="running",
    )
    activity = {"at": time.monotonic()}

    async def active_worker() -> str:
        for _ in range(6):
            await asyncio.sleep(0.02)
            activity["at"] = time.monotonic()
        return "completed after repeated activity"

    async def no_emit(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(
        engine,
        "_agent_node_timeout_seconds",
        lambda *_args, **_kwargs: 0.04,
    )
    monkeypatch.setattr(
        engine,
        "_agent_node_hard_timeout_seconds",
        lambda *_args, **_kwargs: 0.5,
    )
    monkeypatch.setattr(engine, "_emit", no_emit)

    result = await engine._await_agent_with_activity_watchdog(
        task=asyncio.create_task(active_worker()),
        run=run,
        node=node,
        is_revision=False,
        last_activity=lambda: activity["at"],
    )

    assert result == "completed after repeated activity"


@pytest.mark.asyncio
async def test_activity_watchdog_hard_ceiling_bounds_continuous_activity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    node = WorkflowNode(id="idea", name="Idea", skill="/idea-discovery")
    run = WorkflowRun(
        id="hard-watchdog",
        project_path=str(tmp_path),
        nodes=[node],
        status="running",
    )
    activity = {"at": time.monotonic()}
    cancelled = asyncio.Event()

    async def endless_active_worker() -> None:
        try:
            while True:
                await asyncio.sleep(0.01)
                activity["at"] = time.monotonic()
        finally:
            cancelled.set()

    async def no_emit(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(
        engine,
        "_agent_node_timeout_seconds",
        lambda *_args, **_kwargs: 1.0,
    )
    monkeypatch.setattr(
        engine,
        "_agent_node_hard_timeout_seconds",
        lambda *_args, **_kwargs: 0.06,
    )
    monkeypatch.setattr(engine, "_emit", no_emit)

    with pytest.raises(AgentNodeWatchdogTimeout) as captured:
        await engine._await_agent_with_activity_watchdog(
            task=asyncio.create_task(endless_active_worker()),
            run=run,
            node=node,
            is_revision=False,
            last_activity=lambda: activity["at"],
        )

    assert captured.value.kind == "hard"
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_timeout_after_changed_canonical_artifact_continues_to_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skill_registry.scan_directory(Path(__file__).parents[2] / "merak-skills")
    engine = WorkflowEngine()
    node = WorkflowNode(id="idea", name="Idea", skill="/idea-discovery")
    run = WorkflowRun(
        id="same-attempt-timeout",
        project_path=str(tmp_path),
        nodes=[node],
        status="running",
    )
    node.artifact_baseline = engine._snapshot_node_artifacts(node, run)
    events: list[tuple[str, dict[str, Any]]] = []

    async def fake_agent_run(**_kwargs) -> str:
        artifact = tmp_path / "ideas" / "ideas.md"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text("# Ideas\n\nChanged by the model.\n", encoding="utf-8")
        raise asyncio.TimeoutError

    async def fake_emit(_run, event_type: str, payload: dict[str, Any]) -> None:
        events.append((event_type, payload))

    async def no_delegates(**_kwargs) -> list:
        return []

    monkeypatch.setattr(agent_engine, "run", fake_agent_run)
    monkeypatch.setattr(engine, "_emit", fake_emit)
    monkeypatch.setattr(engine, "_workflow_stage_required_tools", lambda *_args, **_kwargs: set())
    monkeypatch.setattr(engine, "_execute_stage_delegates", no_delegates)

    with pytest.raises(TimeoutError):
        await engine._execute_node(node, run, "test", effort="balanced", assurance="draft", opts={})
    assert (tmp_path / "ideas/ideas.md").read_text(encoding="utf-8").startswith("# Ideas")
    assert not any(name == "node_timeout_artifact_recovered" for name, _ in events)
    trace = json.loads((tmp_path / ".merak/runs" / f"{run.id}.skills.json").read_text(encoding="utf-8"))
    assert not any(item.get("status") == "completed" for item in trace["stages"]["idea"]["invocations"])



@pytest.mark.asyncio
async def test_provider_timeout_without_artifact_change_still_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skill_registry.scan_directory(Path(__file__).parents[2] / "merak-skills")
    engine = WorkflowEngine()
    node = WorkflowNode(id="idea", name="Idea", skill="/idea-discovery")
    run = WorkflowRun(
        id="empty-timeout",
        project_path=str(tmp_path),
        nodes=[node],
        status="running",
    )
    node.artifact_baseline = engine._snapshot_node_artifacts(node, run)

    async def fake_agent_run(**_kwargs) -> str:
        raise asyncio.TimeoutError("Model request timeout before tool response")

    async def no_emit(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(agent_engine, "run", fake_agent_run)
    monkeypatch.setattr(engine, "_emit", no_emit)
    monkeypatch.setattr(engine, "_workflow_stage_required_tools", lambda *_args, **_kwargs: set())

    with pytest.raises(TimeoutError, match="Model request timeout"):
        await engine._execute_node(
            node, run, "test", effort="balanced", assurance="draft", opts={},
        )


@pytest.mark.asyncio
async def test_backend_restart_rehydrates_interrupted_primary_agent_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    node, run, _phase = _timed_out_fixture(tmp_path)
    skill_registry.scan_directory(Path(__file__).parents[2] / "merak-skills")
    transcript_dir = tmp_path / ".merak" / "agent-sessions"
    transcript_dir.mkdir(parents=True, exist_ok=True)
    (transcript_dir / "primary-session.json").write_text(json.dumps({
        "schema": 2,
        "session_id": "primary-session",
        "status": "error",
        "model_role": "executor",
        "context_key": "skill-chain:domain-idea-discovery",
        "iterations": 2,
        "total_tokens": 321,
        "max_iterations": 12,
        "tool_call_limits": {"Write": 4},
        "tool_call_counts": {"Write": 1},
        "tool_policy": "workflow_artifacts",
        "messages": [
            {"role": "system", "content": "old contract", "tool_calls": []},
            {"role": "user", "content": "original node task", "tool_calls": []},
            {"role": "assistant", "content": "partial reasoning", "tool_calls": []},
        ],
    }), encoding="utf-8")
    agent_engine._sessions.pop("primary-session", None)
    engine = WorkflowEngine()
    captured: dict[str, Any] = {}
    events: list[tuple[str, dict[str, Any]]] = []

    async def fake_agent_run(**kwargs) -> str:
        captured.update(kwargs)
        (tmp_path / "ideas" / "ideas.md").write_text(
            "# Candidate ideas\n\nCompleted using the restored transcript.\n",
            encoding="utf-8",
        )
        return "continued from durable transcript"

    async def fake_emit(_run, event_type: str, payload: dict[str, Any]) -> None:
        events.append((event_type, payload))

    async def no_delegates(**_kwargs) -> list:
        return []

    monkeypatch.setattr(agent_engine, "run", fake_agent_run)
    monkeypatch.setattr(engine, "_emit", fake_emit)
    monkeypatch.setattr(
        engine,
        "_workflow_stage_required_tools",
        lambda *_args, **_kwargs: set(),
    )
    monkeypatch.setattr(engine, "_execute_stage_delegates", no_delegates)

    try:
        result = await engine._execute_node(
            node, run, "test", effort="balanced", assurance="draft", opts={},
        )
    finally:
        agent_engine._sessions.pop("primary-session", None)

    assert result == "continued from durable transcript"
    assert captured["session_id"] == "primary-session"
    assert captured["user_message"].startswith(
        "Resume the interrupted workflow-node attempt"
    )
    recovery = next(
        payload for event, payload in events
        if event == "agent_session_rehydrated"
    )
    assert recovery["session_id"] == "primary-session"
    assert recovery["recovery_count"] == 1


@pytest.mark.asyncio
async def test_persisted_same_run_write_revalidates_without_model_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    node, run, _phase = _timed_out_fixture(tmp_path)
    engine = WorkflowEngine()
    engine._runs[run.id] = run
    model_calls: list[str] = []
    revision_args: list[dict[str, Any]] = []

    async def fail_if_model_called(*_args, **_kwargs) -> str:
        model_calls.append("called")
        raise AssertionError("model must not be called for validation-only recovery")

    async def fake_revision_loop(**kwargs):
        revision_args.append(kwargs)
        return ({
            "accepted": True,
            "verdict_id": "idea-recovered",
            "reviewer": "deterministic:test",
            "summary": "accepted after independent validation",
        }, kwargs["initial_result"])

    async def immediate_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(engine, "_execute_node", fail_if_model_called)
    monkeypatch.setattr(engine, "_run_node_revision_loop", fake_revision_loop)
    monkeypatch.setattr("server.workflows.engine.asyncio.sleep", immediate_sleep)
    monkeypatch.setattr(
        "server.services.node_risk_audit.node_risk_audit_service.preflight_node",
        lambda *_args, **_kwargs: [],
    )

    await engine._execute_run(
        run,
        "test",
        opts={
            "human_checkpoint": False,
            "code_review": False,
            "research_quality_mode": "off",
        },
    )

    assert model_calls == []
    assert revision_args[0]["require_fresh"] is False
    phase = (RunState(str(tmp_path), run.id).load() or {})["phases"]["idea"]
    assert phase["status"] == "accepted"
    assert phase["details"]["timeout_artifact_recovery"]["session_id"] == "primary-session"
    execution = skill_orchestrator.execution_gate(str(tmp_path), run.id, "idea")
    assert execution["primary_model_execution_verified"] is True


def test_unrelated_or_wrong_session_write_cannot_recover(tmp_path: Path) -> None:
    engine = WorkflowEngine()
    unrelated = tmp_path / "unrelated"
    node, run, phase = _timed_out_fixture(
        unrelated,
        artifact_relative="misc/notes.md",
    )
    assert engine._persisted_timeout_artifact_evidence(node, run, phase) is None

    wrong_session = tmp_path / "wrong-session"
    node, run, phase = _timed_out_fixture(
        wrong_session,
        event_session_id="delegate-session",
    )
    assert engine._persisted_timeout_artifact_evidence(node, run, phase) is None

    delegated = tmp_path / "delegate-active"
    node, run, phase = _timed_out_fixture(delegated, delegate_active=True)
    assert engine._persisted_timeout_artifact_evidence(node, run, phase) is None


def test_other_run_or_node_write_cannot_recover(tmp_path: Path) -> None:
    engine = WorkflowEngine()
    other_node = tmp_path / "other-node"
    node, run, phase = _timed_out_fixture(other_node, event_node_id="lit")
    assert engine._persisted_timeout_artifact_evidence(node, run, phase) is None

    other_run = tmp_path / "other-run"
    node, run, phase = _timed_out_fixture(other_run, event_run_id="different-run")
    assert engine._persisted_timeout_artifact_evidence(node, run, phase) is None


@pytest.mark.asyncio
async def test_recovered_artifact_is_not_auto_accepted_when_gate_waits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    node, run, _phase = _timed_out_fixture(tmp_path, run_id="recovered-rejected")
    engine = WorkflowEngine()
    engine._runs[run.id] = run

    async def fail_if_model_called(*_args, **_kwargs) -> str:
        raise AssertionError("initial model generation must be skipped")

    async def waiting_gate(**kwargs):
        return ({
            "accepted": False,
            "waiting": True,
            "reason": "independent quality gate rejected the artifact",
        }, kwargs["initial_result"])

    async def immediate_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(engine, "_execute_node", fail_if_model_called)
    monkeypatch.setattr(engine, "_run_node_revision_loop", waiting_gate)
    monkeypatch.setattr("server.workflows.engine.asyncio.sleep", immediate_sleep)
    monkeypatch.setattr(
        "server.services.node_risk_audit.node_risk_audit_service.preflight_node",
        lambda *_args, **_kwargs: [],
    )

    await engine._execute_run(
        run,
        "test",
        opts={
            "human_checkpoint": False,
            "code_review": False,
            "research_quality_mode": "off",
        },
    )

    phase = (RunState(str(tmp_path), run.id).load() or {})["phases"]["idea"]
    assert phase["status"] != "accepted"
    assert run.status == "incomplete"
