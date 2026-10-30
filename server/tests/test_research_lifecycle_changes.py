"""Real state transitions for reviewed edits and experiment reattachment."""

import asyncio
import json
import hashlib
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from server.agent import Message, ModelRouter, ToolCall
from server.agent.engine import AgentEngine
from server.agent.session_models import AgentSession, PendingChange
from server.agent.session_persistence import persist_session_transcript, restore_session
from server.services.experiment_runtime_identity import ActiveExperimentConflict
from server.services.experiment_runtime_state import ProjectSnapshot, RunManifestStore, RuntimeSpec
from server.services.remote_experiment_runtime import ExperimentRuntime
from server.services.research_change_application import affected_phases, apply_research_change
from server.utils.atomic_write import atomic_write_json
from server.workflows.workflow_lease import ProjectRunLease


def proposal(root, *, action="edit", before="old", after="new", path="paper/sections/intro.tex"):
    target = root / path
    if action != "create":
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(before, encoding="utf-8")
    return PendingChange("a" * 12, "b" * 12, action, str(target), before, after, "diff")


def test_chat_edit_rejects_concurrent_changes_and_deleted_file(tmp_path):
    change = proposal(tmp_path)
    target = Path(change.path)
    target.write_text("another editor", encoding="utf-8")
    with pytest.raises(ValueError, match="conflict"):
        apply_research_change(tmp_path, change)
    assert target.read_text() == "another editor"
    target.unlink()
    with pytest.raises(ValueError, match="conflict"):
        apply_research_change(tmp_path, change)
    assert not target.exists()


def test_chat_create_rejects_concurrently_created_empty_file(tmp_path):
    change = proposal(tmp_path, action="create", before="")
    target = Path(change.path)
    target.parent.mkdir(parents=True)
    target.touch()
    with pytest.raises(ValueError, match="conflict"):
        apply_research_change(tmp_path, change)
    assert target.read_text() == ""


def test_chat_edit_preserves_completed_run_and_records_separate_local_revision(tmp_path):
    change = proposal(tmp_path)
    run_file = tmp_path / ".merak/runs/run1.json"
    nodes = ("lit", "exp-design", "exp-run", "paper", "review", "audit", "compile", "ppt")
    atomic_write_json(run_file, {"run_id": "run1", "status": "completed",
        "submission_ready": True, "execution_completed": True,
        "completion": {"submission_ready": True, "execution_completed": True}, "phases": {
            node: {"status": "accepted", "verdict_id": "verified", "reviewer": "reviewer",
                   "accepted_at": 1, "details": {}} for node in nodes}})
    completed_bytes = run_file.read_bytes()
    receipt = apply_research_change(tmp_path, change)
    state = json.loads(run_file.read_text())
    assert Path(change.path).read_text() == "new"
    assert receipt["affected_phases"] == ["paper", "review", "audit", "compile", "ppt"]
    assert state["status"] == "completed"
    assert run_file.read_bytes() == completed_bytes
    assert receipt['affected_runs'] == [] and receipt['completed_runs'] == ['run1']
    assert receipt['workflow_restart_required'] is False
    assert receipt['revision_mode'] == 'local'
    from server.services.workflow_recovery_policy import due_phase
    assert due_phase(engine=None, project_path=str(tmp_path), state=state, now=1) == ""
    assert state["phases"]["exp-run"]["status"] == "accepted"
    assert state["phases"]["lit"]["status"] == "accepted"
    assert state["phases"]["paper"]["status"] == "accepted"
    assert state["phases"]["review"]["status"] == "accepted"
    assert state["phases"]["compile"]["accepted_at"] == 1
    assert state['completion']['execution_completed'] is True
    revision = json.loads(next((tmp_path/'.merak/local-revisions').glob('*.json')).read_bytes())
    assert revision['scheduled_nodes'] == [] and revision['validation'] == 'not_independently_reviewed'
    assert (tmp_path/'.merak/research-edits'/f'{change.id}.before').read_text() == 'old'
    assert apply_research_change(tmp_path, change) == receipt
    assert json.loads(run_file.read_text()) == state
    from server.services.research_edit_context import research_edit_context
    prompt = research_edit_context(str(tmp_path), "paper")
    assert "paper/sections/intro.tex" in prompt and "approved" in prompt
    assert research_edit_context(str(tmp_path), "exp-run") == ""


def test_completed_run_ignores_stale_automatic_recovery_fields():
    from server.services.workflow_recovery_policy import due_phase
    state = {"status": "completed", "auto_rebuild_required": {"recovery_next_retry_at": 0},
        "phases": {"paper": {"status": "awaiting_revision", "details": {"revision": {}}}}}
    assert due_phase(engine=None, project_path="unused", state=state, now=100) == ""
    state["phases"]["paper"]["status"] = "pending"
    assert due_phase(engine=None, project_path="unused", state=state, now=100) == ""


def test_config_changes_invalidate_experiment_and_results(tmp_path):
    assert affected_phases("experiments/configs/main.yaml")[:3] == ["exp-design", "exp-run", "results"]
    assert affected_phases("slides/slides.tex") == ["ppt"]
    assert affected_phases("ideas/SELECTED_IDEA.json")[0] == "novelty"


def test_edit_of_failed_owner_clears_stale_execution_checkpoint(tmp_path):
    change = proposal(tmp_path, path="experiments/configs/main.yaml")
    state = tmp_path / ".merak/runs/interrupted.json"
    atomic_write_json(state, {"run_id": "interrupted", "status": "incomplete",
        "interruption": {"node_id": "exp-design", "stage": "acceptance"},
        "phases": {"exp-design": {"status": "awaiting_revision", "details": {
            "interruption": {"stage": "acceptance"}, "execution_checkpoint": {"stage": "acceptance"}}},
            "exp-run": {"status": "pending", "details": {}}}})
    apply_research_change(tmp_path, change)
    saved = json.loads(state.read_text())
    phase = saved["phases"]["exp-design"]
    assert phase["status"] == "done"
    assert "execution_checkpoint" not in phase["details"]
    assert "interruption" not in phase["details"] and "interruption" not in saved
    assert saved["research_edit"]["previous_interruption"]["stage"] == "acceptance"


def test_active_workflow_prevents_chat_file_mutation(tmp_path, monkeypatch):
    change = proposal(tmp_path)
    monkeypatch.setattr(ProjectRunLease, "active_claim", lambda _: {"run_id": "active"})
    with pytest.raises(RuntimeError, match="workflow is active"):
        apply_research_change(tmp_path, change)
    assert Path(change.path).read_text() == "old"


def test_change_proposal_survives_session_restart(tmp_path):
    change = proposal(tmp_path)
    session = AgentSession(id=change.session_id, project_path=str(tmp_path),
        messages=[Message(role="user", content="revise the introduction")],
        pending_changes={change.id: change}, tool_policy="research_artifacts")
    assert persist_session_transcript(session)
    restored = restore_session({}, session.id, str(tmp_path))
    assert restored.pending_changes[change.id] == change


@pytest.mark.asyncio
async def test_chat_ambiguous_edit_does_not_create_proposal(tmp_path):
    change = proposal(tmp_path, before="repeat repeat")
    engine = AgentEngine(ModelRouter())
    session = AgentSession(project_path=str(tmp_path), tool_policy="research_artifacts")
    call = ToolCall(id="edit", name="Edit", arguments={
        "path": change.path, "old_text": "repeat", "new_text": "new"})
    result = await engine._stage_file_change(session, call, None)
    assert not result.success
    assert "ambiguous" in result.output
    assert not session.pending_changes
    assert Path(change.path).read_text() == "repeat repeat"


def active_experiment(root):
    (root / "train.py").write_text("print('original')", encoding="utf-8")
    spec = RuntimeSpec(run_id="durable", project_path=str(root), command="python train.py",
                       backend="ssh_remote", server_id="gpu-a")
    store = RunManifestStore(root, spec.run_id)
    snapshot = ProjectSnapshot(spec, store).build()
    store.begin_attempt(spec, snapshot["snapshot_hash"])
    store.update(snapshot_hash=snapshot["snapshot_hash"])
    store.update_attempt(1, status="monitor", pid=123)
    return spec, store


@pytest.mark.asyncio
async def test_active_source_change_preserves_snapshot_and_does_not_launch(tmp_path, monkeypatch):
    spec, store = active_experiment(tmp_path)
    original = (store.root / "snapshot.json").read_bytes()
    before = store.path.read_bytes()
    (tmp_path / "train.py").write_text("print('changed')", encoding="utf-8")
    runtime = ExperimentRuntime()
    launch = AsyncMock()
    monkeypatch.setattr(runtime, "_execute_backend", launch)
    with pytest.raises(ActiveExperimentConflict, match="still active"):
        await runtime.run(spec)
    launch.assert_not_called()
    assert store.path.read_bytes() == before
    assert (store.root / "snapshot.json").read_bytes() == original


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"command": "python train.py --changed"}, {"env_vars": {"SEED": "2"}},
    {"server_id": "gpu-b"}, {"preflight_command": "check-data"},
])
async def test_active_execution_change_cannot_reattach_or_duplicate(tmp_path, changes):
    spec, store = active_experiment(tmp_path)
    before = store.path.read_bytes()
    with pytest.raises(ActiveExperimentConflict):
        await ExperimentRuntime().run(replace(spec, **changes))
    assert store.path.read_bytes() == before


def test_completed_cache_requires_execution_identity(tmp_path):
    spec, store = active_experiment(tmp_path)
    store.update_attempt(1, status="completed")
    store.update(status="completed")
    result = tmp_path / "experiments/results/metrics.json"
    result.parent.mkdir(parents=True)
    result.write_text('{"score": 0.5}', encoding="utf-8")
    store.update(evidence_eligible=True, result_artifacts={"experiments/results/metrics.json": {
        "sha256": hashlib.sha256(result.read_bytes()).hexdigest()}})
    snapshot = ProjectSnapshot(spec, store).build(persist=False)
    runtime = ExperimentRuntime()
    assert runtime._cached_outcome(spec, store, snapshot, store.load()) is not None
    before = store.path.read_bytes()
    with pytest.raises(ValueError, match="implicit re-execution is prohibited"):
        runtime._cached_outcome(replace(spec, env_vars={"SEED": "2"}), store, snapshot, store.load())
    with pytest.raises(ValueError, match="implicit re-execution is prohibited"):
        runtime._cached_outcome(spec, store, {**snapshot, "snapshot_hash": "changed"}, store.load())
    assert store.path.read_bytes() == before
    result.write_text('{"score": 1.0}', encoding="utf-8")
    with pytest.raises(ValueError, match="artifact changed"):
        runtime._cached_outcome(spec, store, snapshot, store.load())


def test_snapshot_materialization_rejects_changed_source(tmp_path):
    spec, store = active_experiment(tmp_path)
    snapshot = ProjectSnapshot(spec, store).build(persist=False)
    (tmp_path / "train.py").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="Source changed"):
        ProjectSnapshot(spec, store).materialize(snapshot, store.root / "staging")


def test_unreconciled_remote_attempt_is_not_a_retryable_platform_failure():
    from types import SimpleNamespace
    from server.services.experiment_models import JobStatus
    from server.services.experiment_retries import _retry_reason

    context = {"previous": {"status": "recovery_required", "exit_code": None},
               "critical": [], "source_changed": False, "command_changed": False}
    reason, eligible = _retry_reason(SimpleNamespace(status=JobStatus.FAILED), context, 3)
    assert not eligible and "reconciliation" in reason


@pytest.mark.asyncio
async def test_chat_controller_recovers_and_resolves_proposal_after_restart(tmp_path, monkeypatch):
    from server.api import chat_socket_controller
    from server.tests.test_chat_socket_controller import FakeSocket

    change = proposal(tmp_path)
    session = AgentSession(id=change.session_id, project_path=str(tmp_path),
        messages=[Message(role="user", content="revise")],
        pending_changes={change.id: change}, tool_policy="research_artifacts")
    persist_session_transcript(session)
    engine = AgentEngine(ModelRouter())
    monkeypatch.setattr(chat_socket_controller, "agent_engine", engine)
    socket = FakeSocket()
    controller = chat_socket_controller.ChatSocketController(socket)
    controller.project_path = str(tmp_path)
    await controller._resolve_change({"session_id": session.id, "change_id": change.id, "approved": True})
    assert socket.sent[-1]["type"] == "change_applied"
    assert Path(change.path).read_text() == "new"
    await controller._resolve_change({"session_id": session.id, "change_id": change.id, "approved": False})
    assert socket.sent[-1]["type"] == "change_applied"
    assert Path(change.path).read_text() == "new"


@pytest.mark.asyncio
async def test_chat_figure_runtime_reserves_project_and_preserves_completed_run_on_failure(tmp_path):
    from server.services.chat_runtime_revision import chat_runtime_revision

    state = tmp_path / ".merak/runs/figure-run.json"
    atomic_write_json(state, {"run_id": "figure-run", "status": "completed", "phases": {
        node: {"status": "accepted", "details": {}, "verdict_id": "prior"}
        for node in ("exp-run", "figure", "paper", "compile")}})
    session = AgentSession(project_path=str(tmp_path), tool_policy="research_artifacts")
    with pytest.raises(OSError, match="render failed"):
        async with chat_runtime_revision(session, "generate_figure"):
            assert ProjectRunLease(str(tmp_path)).active_claim()
            saved = json.loads(state.read_text())
            assert saved["phases"]["figure"]["status"] == "accepted"
            assert saved["phases"]["paper"]["status"] == "accepted"
            assert saved['status'] == 'completed'
            assert saved["phases"]["exp-run"]["status"] == "accepted"
            raise OSError("render failed")
    assert not ProjectRunLease(str(tmp_path)).active_claim()


@pytest.mark.asyncio
async def test_duplicate_live_monitor_is_rejected(tmp_path):
    runtime = ExperimentRuntime()
    spec = RuntimeSpec(run_id="live", project_path=str(tmp_path), command="python train.py")
    runtime._active[spec.run_id] = asyncio.current_task()
    with pytest.raises(ActiveExperimentConflict, match="active monitor"):
        await runtime.run(spec)


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_worker_awaits_lease_cleanup_before_reporting_completion(tmp_path, cancel):
    from types import SimpleNamespace
    from server.workflows.models import WorkflowRun
    from server.workflows.run_start_lifecycle import execute_with_lifecycle_cleanup

    entered = asyncio.Event()
    async def work(*args):
        entered.set()
        if cancel:
            await asyncio.Event().wait()
    lease = ProjectRunLease(str(tmp_path))
    token = lease.claim(run_id="cleanup-run", owner_id="test")
    run = WorkflowRun(id="cleanup-run", project_path=str(tmp_path), project_claim_token=token)
    host = SimpleNamespace(_execute_run=work, _resume_claim_heartbeats={}, _project_claim_heartbeats={})
    task = asyncio.create_task(execute_with_lifecycle_cleanup(host, run, "topic", "balanced", "draft"))
    await entered.wait()
    if cancel:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        await task
    assert not lease.active_claim()
    assert lease.claim(run_id="next", owner_id="new-process")


@pytest.mark.asyncio
async def test_duplicate_monitor_is_blocked_during_initial_event_delivery(tmp_path, monkeypatch):
    from server.services.experiment_runtime_state import RuntimeOutcome

    runtime = ExperimentRuntime()
    spec = RuntimeSpec(run_id="initial-event", project_path=str(tmp_path), command="python train.py")
    async def emit(event, payload):
        with pytest.raises(ActiveExperimentConflict, match="active monitor"):
            await runtime.run(spec)
    monkeypatch.setattr(runtime, "_execute_backend", AsyncMock(return_value=RuntimeOutcome(
        run_id=spec.run_id, backend="local", status="completed")))
    await runtime.run(spec, emit)


def test_ssh_reattach_keeps_original_deadline_and_log_position(tmp_path):
    import time
    from datetime import datetime, timezone
    from server.services.experiment_runtime_ssh import _MonitorState

    spec, store = active_experiment(tmp_path)
    original = time.time() - 300
    store.update_attempt(1, started_at=datetime.fromtimestamp(original, timezone.utc).isoformat(),
                         log_offset=1234, health={"latest_metrics": {"loss": 0.3}})
    monitor = _MonitorState(store, spec, 1)
    assert abs(monitor.started - original) < 1
    assert monitor.log_offset == 1234
    assert monitor.health.latest_metrics == {"loss": 0.3}


def test_durable_attempt_creation_rejects_second_scheduler(tmp_path):
    spec, store = active_experiment(tmp_path)
    other = RunManifestStore(tmp_path, spec.run_id)
    before = store.path.read_bytes()
    with pytest.raises(ActiveExperimentConflict, match="already owns"):
        other.begin_attempt(spec, "new-source")
    assert store.path.read_bytes() == before


def test_stage_input_identity_ignores_only_structural_formatting(tmp_path):
    from server.services.implementation_dependencies import stage_input_fingerprint

    path = tmp_path / "config.yaml"
    path.write_text("training:\n  seed: 13\n  lr: 0.001\n", encoding="utf-8")
    first = stage_input_fingerprint(path)
    path.write_text("# Formatting only\ntraining: {lr: 0.001, seed: 13}\n", encoding="utf-8")
    assert stage_input_fingerprint(path) == first
    path.write_text("training: {lr: 0.002, seed: 13}\n", encoding="utf-8")
    assert stage_input_fingerprint(path) != first
