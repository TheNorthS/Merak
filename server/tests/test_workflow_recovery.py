from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from server.services.workflow_recovery import WorkflowRecoveryWatchdog
from server.workflows.run_state import RunState


class FakeWorkflowEngine:
    def __init__(
        self,
        runtime_signature: str = "runtime:unchanged",
        artifact_signature: str = "artifact:unchanged",
        fail_resume: bool = False,
        active_run_id: str = "",
    ) -> None:
        self.runtime_signature = runtime_signature
        self.artifact_signature = artifact_signature
        self.fail_resume = fail_resume
        self.active_run_id = active_run_id
        self.resumed: list[dict[str, Any]] = []
        self.artifact_options: list[dict[str, Any]] = []

    def _active_run_for_project(self, _project_path: str) -> str | None:
        return self.active_run_id or None

    @staticmethod
    def _is_platform_repair_revision_checkpoint(revision: dict[str, Any]) -> bool:
        return (
            revision.get("intervention_kind") == "platform_repair"
            and revision.get("requires_human_decision") is not True
        )

    @staticmethod
    def _is_transport_revision_checkpoint(revision: dict[str, Any]) -> bool:
        return revision.get("transport_exhausted") is True

    @classmethod
    def _platform_checkpoint_is_auto_recoverable(
        cls,
        revision: dict[str, Any],
    ) -> bool:
        return bool(
            cls._is_platform_repair_revision_checkpoint(revision)
            and not cls._is_transport_revision_checkpoint(revision)
            and not any(
                revision.get(flag)
                or (
                    isinstance(revision.get("last_gate"), dict)
                    and revision["last_gate"].get(flag)
                )
                for flag in (
                    "hard_limit",
                    "stopped_for_no_progress",
                    "stopped_for_deterministic_stage",
                    "stopped_for_managed_stage",
                )
            )
        )

    def _revision_artifact_signature(
        self,
        _project_path: str,
        _phase_id: str,
        _options: dict[str, Any] | None = None,
    ) -> str:
        self.artifact_options.append(dict(_options or {}))
        return self.artifact_signature

    def _revision_runtime_signature(
        self,
        _project_path: str,
        _phase_id: str,
        _options: dict[str, Any],
    ) -> str:
        return self.runtime_signature

    async def resume_persisted_run(self, **kwargs: Any) -> str:
        self.resumed.append(kwargs)
        if self.fail_resume:
            raise RuntimeError("simulated resume failure")
        return str(kwargs["run_id"])


def write_run(
    project: Path,
    *,
    run_id: str,
    revision: dict[str, Any],
    options: dict[str, Any] | None = None,
) -> None:
    path = project / ".merak" / "runs" / f"{run_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema": 1,
        "run_id": run_id,
        "status": "incomplete",
        "config": {
            "direction": "test",
            "options": {
                "auto_proceed": True,
                "platform_auto_recovery": True,
                **(options or {}),
            },
        },
        "phases": {
            "results": {
                "id": "results",
                "status": "awaiting_revision",
                "details": {"revision": revision},
            },
        },
    }), encoding="utf-8")


@pytest.mark.asyncio
async def test_watchdog_waits_for_transport_backoff_then_resumes(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    run_id = "transport-due"
    future = time.time() + 300
    revision = {
        "intervention_kind": "platform_repair",
        "requires_human_decision": False,
        "transport_exhausted": True,
        "transport_retry_count": 1,
        "max_transport_checkpoint_retries": 4,
        "next_retry_at": future,
    }
    write_run(project, run_id=run_id, revision=revision)
    watchdog = WorkflowRecoveryWatchdog(
        registry_path=tmp_path / "registry.json",
    )
    watchdog.observe_project(project)
    engine = FakeWorkflowEngine()

    assert await watchdog.scan_once(engine) == []
    assert engine.resumed == []

    revision["next_retry_at"] = time.time() - 1
    write_run(project, run_id=run_id, revision=revision)
    started = await watchdog.scan_once(engine)

    assert started == []
    assert engine.resumed == []



@pytest.mark.asyncio
async def test_watchdog_does_not_loop_after_transport_retry_limit(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    write_run(
        project,
        run_id="transport-limit",
        revision={
            "intervention_kind": "platform_repair",
            "requires_human_decision": False,
            "transport_exhausted": True,
            "transport_retry_count": 4,
            "max_transport_checkpoint_retries": 4,
            "next_retry_at": time.time() - 1,
        },
    )
    watchdog = WorkflowRecoveryWatchdog(
        registry_path=tmp_path / "registry.json",
    )
    watchdog.observe_project(project)
    engine = FakeWorkflowEngine()

    assert await watchdog.scan_once(engine) == []
    assert engine.resumed == []


@pytest.mark.asyncio
async def test_watchdog_keeps_exhausted_gate_stopped_after_runtime_change(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    write_run(
        project,
        run_id="runtime-upgraded",
        revision={
            "intervention_kind": "platform_repair",
            "requires_human_decision": False,
            "platform_auto_recovery_count": 3,
            "runtime_signature": "runtime:old",
            "artifact_signature": "artifact:unchanged",
            "artifact_owner_id": "results",
            "stopped_for_no_progress": True,
        },
        options={"max_research_loop_cycles": 3},
    )
    watchdog = WorkflowRecoveryWatchdog(
        registry_path=tmp_path / "registry.json",
    )
    watchdog.observe_project(project)
    engine = FakeWorkflowEngine(runtime_signature="runtime:new")

    started = await watchdog.scan_once(engine)

    assert started == []
    assert engine.resumed == []


@pytest.mark.parametrize(
    "stop_flag",
    [
        "stopped_for_no_progress",
        "stopped_for_deterministic_stage",
    ],
)
@pytest.mark.asyncio
async def test_watchdog_does_not_reopen_unchanged_terminal_checkpoint(
    tmp_path: Path,
    stop_flag: str,
) -> None:
    project = tmp_path / "project"
    write_run(
        project,
        run_id=f"terminal-unchanged-{stop_flag}",
        revision={
            "intervention_kind": "platform_repair",
            "requires_human_decision": False,
            stop_flag: True,
            "platform_auto_recovery_count": 0,
            "runtime_signature": "runtime:unchanged",
            "artifact_signature": "artifact:unchanged",
            "artifact_owner_id": "results",
        },
    )
    watchdog = WorkflowRecoveryWatchdog(
        registry_path=tmp_path / "registry.json",
    )
    watchdog.observe_project(project)
    engine = FakeWorkflowEngine()

    assert await watchdog.scan_once(engine) == []
    assert engine.resumed == []


@pytest.mark.asyncio
async def test_watchdog_keeps_terminal_checkpoint_stopped_after_artifact_change(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    write_run(
        project,
        run_id="terminal-artifact-edited",
        revision={
            "intervention_kind": "platform_repair",
            "requires_human_decision": False,
            "stopped_for_no_progress": True,
            "runtime_signature": "runtime:unchanged",
            "artifact_signature": "artifact:old",
            "artifact_owner_id": "results",
        },
        options={
            "run_experiment": False,
            "literature_sources": ["zotero"],
        },
    )
    watchdog = WorkflowRecoveryWatchdog(
        registry_path=tmp_path / "registry.json",
    )
    watchdog.observe_project(project)
    engine = FakeWorkflowEngine(artifact_signature="artifact:new")

    started = await watchdog.scan_once(engine)

    assert started == []
    assert engine.resumed == []
    assert engine.artifact_options == []


@pytest.mark.asyncio
async def test_watchdog_never_resumes_researcher_decision(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    write_run(
        project,
        run_id="researcher-decision",
        revision={
            "intervention_kind": "researcher_decision",
            "requires_human_decision": True,
        },
    )
    watchdog = WorkflowRecoveryWatchdog(
        registry_path=tmp_path / "registry.json",
    )
    watchdog.observe_project(project)
    engine = FakeWorkflowEngine()

    assert await watchdog.scan_once(engine) == []
    assert engine.resumed == []


@pytest.mark.asyncio
async def test_watchdog_resumes_hash_invalidated_submission_rebuild(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    run_id = "submission-rebuild"
    path = project / ".merak" / "runs" / f"{run_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema": 1,
        "run_id": run_id,
        "status": "running",
        "auto_rebuild_required": {
            "reason": "review source hash changed",
        },
        "config": {
            "direction": "test",
            "options": {
                "auto_proceed": True,
                "platform_auto_recovery": True,
            },
        },
        "phases": {
            "paper": {
                "id": "paper",
                "status": "done",
                "details": {"acceptance_invalidations": [{}]},
            },
            "review": {"id": "review", "status": "done", "details": {}},
        },
    }), encoding="utf-8")
    watchdog = WorkflowRecoveryWatchdog(
        registry_path=tmp_path / "registry.json",
    )
    watchdog.observe_project(project)
    engine = FakeWorkflowEngine()

    started = await watchdog.scan_once(engine)

    assert started == [{
        "project_path": str(project.resolve()),
        "run_id": run_id,
        "phase_id": "paper",
    }]
    assert engine.resumed[0]["run_id"] == run_id


@pytest.mark.asyncio
async def test_watchdog_preserves_completed_run_even_with_durable_rebuild_marker(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    run_id = "completed-submission-rebuild"
    path = project / ".merak" / "runs" / f"{run_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema": 1,
        "run_id": run_id,
        "status": "completed",
        "auto_rebuild_required": {"reason": "bound paper source changed"},
        "config": {
            "direction": "test",
            "options": {
                "auto_proceed": True,
                "platform_auto_recovery": True,
            },
        },
        "phases": {
            "paper": {"id": "paper", "status": "done", "details": {}},
            "review": {"id": "review", "status": "done", "details": {}},
        },
    }), encoding="utf-8")
    watchdog = WorkflowRecoveryWatchdog(registry_path=tmp_path / "registry.json")
    watchdog.observe_project(project)
    engine = FakeWorkflowEngine()

    before = path.read_bytes()
    started = await watchdog.scan_once(engine)

    assert started == []
    assert engine.resumed == []
    assert path.read_bytes() == before


def test_non_transport_gate_clears_stale_transport_retry_state(
    tmp_path: Path,
) -> None:
    run_state = RunState(str(tmp_path), "transport-transition")
    run_state.start(
        [{"id": "results", "name": "Results", "skill": "results"}],
        {"options": {}},
    )
    run_state.set_revision_waiting(
        "results",
        round_number=1,
        cycle=1,
        gate={
            "summary": "provider timed out",
            "issues": ["provider timed out"],
            "transport_exhausted": True,
            "error_category": "transport",
            "retryable": True,
            "transport_retry_count": 2,
            "next_retry_at": time.time() + 30,
            "max_transport_checkpoint_retries": 4,
        },
    )

    run_state.set_revision_waiting(
        "results",
        round_number=2,
        cycle=1,
        gate={
            "summary": "quality evidence is incomplete",
            "issues": ["missing uncertainty evidence"],
            "intervention_kind": "platform_repair",
            "stopped_for_no_progress": True,
        },
    )

    revision = run_state.revision_state("results")
    for key in (
        "transport_exhausted",
        "error_category",
        "retryable",
        "transport_retry_count",
        "next_retry_at",
        "max_transport_checkpoint_retries",
    ):
        assert key not in revision
    assert revision["last_gate"]["error_category"] == ""
    assert revision["stopped_for_no_progress"] is True


def test_save_state_preserves_same_rebuild_failure_budget(tmp_path: Path) -> None:
    run_state = RunState(str(tmp_path), "rebuild-budget")
    run_state.start(
        [{"id": "paper", "name": "Paper", "skill": "paper"}],
        {"options": {}},
    )
    state = run_state.load()
    assert state is not None
    state["auto_rebuild_required"] = {
        "reason": "submission attestation changed or became stale",
        "recovery_attempt_count": 2,
        "recovery_max_attempts": 4,
        "recovery_last_attempt_at": 1200.0,
        "recovery_last_phase_id": "paper",
        "recovery_next_retry_at": 1234.0,
        "recovery_exhausted": True,
        "recovery_exhausted_at": 1250.0,
    }
    run_state.save_state(state)

    refreshed = run_state.load()
    assert refreshed is not None
    refreshed["auto_rebuild_required"] = {
        "reason": "submission attestation changed or became stale",
        "detected_at": time.time(),
    }
    run_state.save_state(refreshed)

    marker = (run_state.load() or {})["auto_rebuild_required"]
    assert marker["recovery_attempt_count"] == 2
    assert marker["recovery_max_attempts"] == 4
    assert marker["recovery_last_attempt_at"] == 1200.0
    assert marker["recovery_last_phase_id"] == "paper"
    assert marker["recovery_next_retry_at"] == 1234.0
    assert marker["recovery_exhausted"] is True
    assert marker["recovery_exhausted_at"] == 1250.0


@pytest.mark.asyncio
async def test_watchdog_does_not_schedule_legacy_runtime_only_checkpoint(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    write_run(
        project,
        run_id="runtime-only",
        revision={
            "intervention_kind": "platform_repair",
            "requires_human_decision": False,
            "runtime_signature": "runtime:old",
        },
    )
    watchdog = WorkflowRecoveryWatchdog(registry_path=tmp_path / "registry.json")
    watchdog.observe_project(project)
    engine = FakeWorkflowEngine(runtime_signature="runtime:new")

    assert await watchdog.scan_once(engine) == []
    assert engine.resumed == []


@pytest.mark.asyncio
async def test_watchdog_never_walks_back_to_older_unfinished_run(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    write_run(
        project,
        run_id="old-due",
        revision={
            "intervention_kind": "platform_repair",
            "requires_human_decision": False,
        },
    )
    write_run(
        project,
        run_id="new-researcher-decision",
        revision={
            "intervention_kind": "researcher_decision",
            "requires_human_decision": True,
        },
    )
    old_path = project / ".merak" / "runs" / "old-due.json"
    old_time = time.time() - 30
    os.utime(old_path, (old_time, old_time))
    watchdog = WorkflowRecoveryWatchdog(registry_path=tmp_path / "registry.json")
    watchdog.observe_project(project)
    engine = FakeWorkflowEngine()

    assert await watchdog.scan_once(engine) == []
    assert engine.resumed == []


@pytest.mark.asyncio
async def test_newer_run_sidecar_does_not_hide_canonical_recovery_state(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    run_id = "sidecar-recovery"
    write_run(
        project,
        run_id=run_id,
        revision={
            "intervention_kind": "platform_repair",
            "requires_human_decision": False,
        },
    )
    sidecar = project / ".merak" / "runs" / f"{run_id}.skills.json"
    sidecar.write_text(
        json.dumps({"schema": 2, "run_id": run_id, "stages": {}}),
        encoding="utf-8",
    )
    future = time.time() + 5
    os.utime(sidecar, (future, future))
    watchdog = WorkflowRecoveryWatchdog(registry_path=tmp_path / "registry.json")
    watchdog.observe_project(project)
    engine = FakeWorkflowEngine()

    started = await watchdog.scan_once(engine)

    assert started == [{
        "project_path": str(project.resolve()),
        "run_id": run_id,
        "phase_id": "results",
    }]
    assert engine.resumed[0]["run_id"] == run_id


@pytest.mark.asyncio
async def test_newer_session_marker_cannot_revive_an_older_run(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    write_run(
        project,
        run_id="explicit-active",
        revision={
            "intervention_kind": "platform_repair",
            "requires_human_decision": False,
        },
    )
    write_run(
        project,
        run_id="newer-but-dormant",
        revision={
            "intervention_kind": "researcher_decision",
            "requires_human_decision": True,
        },
    )
    runs = project / ".merak" / "runs"
    older = 1_700_000_000_000_000_000
    os.utime(runs / "explicit-active.json", ns=(older, older))
    os.utime(runs / "newer-but-dormant.json", ns=(older + 2_000_000_000, older + 2_000_000_000))
    session_path = project / ".merak" / "state.json"
    session_path.write_text(json.dumps({
        "run_id": "explicit-active",
        "resumable": True,
        "saved_at": time.time() + 60,
    }), encoding="utf-8")
    watchdog = WorkflowRecoveryWatchdog(registry_path=tmp_path / "registry.json")
    watchdog.observe_project(project)
    engine = FakeWorkflowEngine()

    assert await watchdog.scan_once(engine) == []
    assert engine.resumed == []


@pytest.mark.asyncio
async def test_cross_process_lease_allows_only_one_watchdog_resume(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    write_run(
        project,
        run_id="leased-run",
        revision={
            "intervention_kind": "platform_repair",
            "requires_human_decision": False,
        },
    )
    first = WorkflowRecoveryWatchdog(registry_path=tmp_path / "first.json")
    second = WorkflowRecoveryWatchdog(registry_path=tmp_path / "second.json")
    first.observe_project(project)
    second.observe_project(project)
    first_engine = FakeWorkflowEngine()
    second_engine = FakeWorkflowEngine()

    assert len(await first.scan_once(first_engine)) == 1
    assert await second.scan_once(second_engine) == []
    assert len(first_engine.resumed) == 1
    assert second_engine.resumed == []
    for key in list(first._held_leases):
        first._release_recovery_lease(key)


def test_atomic_lease_has_one_winner_under_simultaneous_contention(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    first = WorkflowRecoveryWatchdog(registry_path=tmp_path / "first.json")
    second = WorkflowRecoveryWatchdog(registry_path=tmp_path / "second.json")
    barrier = threading.Barrier(2)

    def contend(watchdog: WorkflowRecoveryWatchdog) -> bool:
        barrier.wait(timeout=5)
        return watchdog._acquire_recovery_lease(
            str(project),
            "contended-run",
            now=time.time(),
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(contend, (first, second)))

    assert sum(outcomes) == 1
    for watchdog in (first, second):
        for key in list(watchdog._held_leases):
            watchdog._release_recovery_lease(key)


def test_released_canonical_lease_is_reclaimed(tmp_path: Path) -> None:
    project = tmp_path / "project"
    first = WorkflowRecoveryWatchdog(registry_path=tmp_path / "first.json")
    second = WorkflowRecoveryWatchdog(registry_path=tmp_path / "second.json")
    now = time.time()
    assert first._acquire_recovery_lease(str(project), "stale-run", now=now)
    key = (first._project_key(project), "stale-run")
    first._release_recovery_lease(key)

    assert second._acquire_recovery_lease(
        str(project),
        "stale-run",
        now=now + 1,
    )
    for key in list(second._held_leases):
        second._release_recovery_lease(key)


@pytest.mark.asyncio
async def test_auto_rebuild_budget_persists_and_becomes_terminal(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    run_id = "bounded-rebuild"
    state_path = project / ".merak" / "runs" / f"{run_id}.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({
        "schema": 1,
        "run_id": run_id,
        "status": "running",
        "auto_rebuild_required": {"reason": "stale submission"},
        "config": {"options": {
            "auto_proceed": True,
            "platform_auto_recovery": True,
            "auto_rebuild_max_attempts": 3,
            "auto_rebuild_retry_delay_seconds": 5,
        }},
        "phases": {"paper": {"id": "paper", "status": "done", "details": {}}},
    }), encoding="utf-8")

    for attempt in range(1, 4):
        watchdog = WorkflowRecoveryWatchdog(
            registry_path=tmp_path / f"registry-{attempt}.json",
        )
        watchdog.observe_project(project)
        engine = FakeWorkflowEngine(fail_resume=True)
        assert await watchdog.scan_once(engine) == []
        assert len(engine.resumed) == 1
        state = json.loads(state_path.read_text(encoding="utf-8"))
        rebuild = state["auto_rebuild_required"]
        assert rebuild["recovery_attempt_count"] == attempt
        if attempt < 3:
            rebuild["recovery_next_retry_at"] = time.time() - 1
            state_path.write_text(json.dumps(state), encoding="utf-8")

    final_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert final_state["auto_rebuild_required"]["recovery_exhausted"] is True
    final_watchdog = WorkflowRecoveryWatchdog(
        registry_path=tmp_path / "registry-final.json",
    )
    final_watchdog.observe_project(project)
    final_engine = FakeWorkflowEngine()
    assert await final_watchdog.scan_once(final_engine) == []
    assert final_engine.resumed == []


@pytest.mark.asyncio
async def test_registry_prunes_missing_projects_loaded_from_disk(
    tmp_path: Path,
) -> None:
    registry = tmp_path / "registry.json"
    missing = tmp_path / "deleted-project"
    registry.write_text(json.dumps({
        "schema": 1,
        "projects": [str(missing)],
    }), encoding="utf-8")
    watchdog = WorkflowRecoveryWatchdog(registry_path=registry)
    watchdog._load_registry()

    await watchdog.scan_once(FakeWorkflowEngine())

    payload = json.loads(registry.read_text(encoding="utf-8"))
    assert payload["projects"] == []


@pytest.mark.asyncio
async def test_registry_keeps_fresh_project_until_run_directory_is_created(
    tmp_path: Path,
) -> None:
    registry = tmp_path / "registry.json"
    project = tmp_path / "new-project"
    watchdog = WorkflowRecoveryWatchdog(registry_path=registry)
    watchdog.observe_project(project)

    await watchdog.scan_once(FakeWorkflowEngine())

    payload = json.loads(registry.read_text(encoding="utf-8"))
    assert payload["projects"] == [str(project.resolve())]
