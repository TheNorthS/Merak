from __future__ import annotations

import asyncio
import io
import json
import multiprocessing
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from PIL import Image

from server.services.workflow_event_journal import WorkflowEventJournal
from server.services.remote_experiment_runtime import RunManifestStore
from server.services.node_risk_audit import node_risk_audit_service
from server.services.figure_engine import _append_visual_review
from server.services.gemini_figure_generator import (
    _atomic_json as write_gemini_json,
    _atomic_text as write_gemini_text,
    _save_canonical_png,
)
from server.utils import atomic_write as atomic_files
from server.utils.atomic_write import atomic_replace_file, path_lock
from server.workflows import run_state as run_state_module
from server.workflows.engine import WorkflowEngine, WorkflowRun
from server.workflows.run_state import ProjectRunLease, RunState


def test_experiment_manifest_refuses_to_overwrite_corrupt_state(
    tmp_path: Path,
) -> None:
    store = RunManifestStore(tmp_path, "corrupt-manifest")
    store.path.write_text("{broken", encoding="utf-8")

    with pytest.raises(RuntimeError, match="manifest is unreadable"):
        store.load()
    with pytest.raises(RuntimeError, match="manifest is unreadable"):
        store.update(status="completed")
    assert store.path.read_text(encoding="utf-8") == "{broken"


def _hold_process_lock(
    path: str,
    ready: multiprocessing.synchronize.Event,
    release: multiprocessing.synchronize.Event,
) -> None:
    with path_lock(path):
        ready.set()
        if not release.wait(10):
            raise TimeoutError("test process was not released")


def _claim_resume_process(
    project_path: str,
    run_id: str,
    start: multiprocessing.synchronize.Event,
    results: multiprocessing.queues.Queue,
) -> None:
    if not start.wait(10):
        raise TimeoutError("claim test did not start")
    token = RunState(project_path, run_id).claim_resume(
        owner_id=f"process-{multiprocessing.current_process().pid}",
        expected_status="failed",
        lease_seconds=120,
    )
    results.put(token)


def _claim_project_process(
    project_path: str,
    run_id: str,
    start: multiprocessing.synchronize.Event,
    results: multiprocessing.queues.Queue,
) -> None:
    if not start.wait(10):
        raise TimeoutError("project claim test did not start")
    token = ProjectRunLease(project_path).claim(
        run_id=run_id,
        owner_id=f"process-{multiprocessing.current_process().pid}",
        lease_seconds=120,
    )
    results.put((run_id, token))


def _update_node_risk_process(
    project_path: str,
    node_id: str,
    start: multiprocessing.synchronize.Event,
) -> None:
    if not start.wait(10):
        raise TimeoutError("node-risk update test did not start")
    root = Path(project_path)
    node_risk_audit_service._update_index(
        root,
        {
            "node_id": node_id,
            "status": "clear",
            "blocking": False,
            "counts": {"blocker": 0, "warning": 0, "info": 0},
            "checks_executed": [f"{node_id}-check"],
            "report_path": str(
                root / ".merak" / "quality" / f"{node_id}-risk.json"
            ),
            "generated_at": time.time(),
        },
    )


def test_atomic_json_retries_permission_error_and_uses_unique_temp(
    tmp_path: Path,
    monkeypatch,
) -> None:
    target = tmp_path / "state.json"
    real_replace = atomic_files.os.replace
    sources: list[Path] = []
    failures = 2

    def flaky_replace(source, destination):
        nonlocal failures
        sources.append(Path(source))
        if failures:
            failures -= 1
            raise PermissionError(5, "temporarily locked", str(destination))
        return real_replace(source, destination)

    monkeypatch.setattr(atomic_files.os, "replace", flaky_replace)
    atomic_files.atomic_write_json(target, {"round": 1})
    first_temp = sources[-1]
    atomic_files.atomic_write_json(target, {"round": 2})

    assert len(sources) == 4
    assert sources[0] == sources[1] == sources[2]
    assert sources[3] != first_temp
    assert json.loads(target.read_text(encoding="utf-8")) == {"round": 2}
    assert not any(tmp_path.glob(".*.tmp"))
    assert {path.name for path in tmp_path.iterdir()} == {"state.json"}


def test_atomic_replace_file_retries_windows_sharing_violation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "download.unique.merak-part"
    target = tmp_path / "download.bin"
    source.write_bytes(b"verified transfer")
    real_replace = atomic_files.os.replace
    attempts = 0

    def flaky_replace(source_path, destination_path):
        nonlocal attempts
        attempts += 1
        if attempts <= 2:
            failure = OSError("simulated Windows sharing violation")
            failure.winerror = 32
            raise failure
        return real_replace(source_path, destination_path)

    monkeypatch.setattr(atomic_files.os, "replace", flaky_replace)
    atomic_replace_file(source, target)

    assert attempts == 3
    assert target.read_bytes() == b"verified transfer"
    assert not source.exists()


def test_gemini_image_writers_reuse_winerror_retry(
    tmp_path: Path,
    monkeypatch,
) -> None:
    real_replace = atomic_files.os.replace
    attempts: dict[Path, int] = {}

    def flaky_replace(source, destination):
        target = Path(destination)
        attempts[target] = attempts.get(target, 0) + 1
        if attempts[target] <= 2:
            failure = OSError("simulated Windows sharing violation")
            failure.winerror = 32
            raise failure
        return real_replace(source, destination)

    monkeypatch.setattr(atomic_files.os, "replace", flaky_replace)
    gemini_json = tmp_path / "gemini.json"
    gemini_text = tmp_path / "gemini.txt"
    gemini_png = tmp_path / "gemini.png"
    write_gemini_json(gemini_json, {"writer": "gemini"})
    write_gemini_text(gemini_text, "gemini protocol")
    png_buffer = io.BytesIO()
    Image.new("RGBA", (64, 64), (10, 20, 30, 255)).save(
        png_buffer,
        format="PNG",
    )
    assert _save_canonical_png(png_buffer.getvalue(), gemini_png) == (64, 64)

    assert json.loads(gemini_json.read_text(encoding="utf-8"))["writer"] == "gemini"
    assert gemini_text.read_text(encoding="utf-8") == "gemini protocol"
    with Image.open(gemini_png) as opened:
        assert opened.size == (64, 64)
    assert all(count == 3 for count in attempts.values())
    assert not list(tmp_path.glob(".*.tmp"))
def test_visual_review_history_preserves_concurrent_appends(tmp_path: Path) -> None:
    path = tmp_path / "figure-review.json"
    barrier = threading.Barrier(2)

    def append(marker: str) -> None:
        barrier.wait()
        _append_visual_review(
            path,
            {
                "status": "failed",
                "issues": [marker],
                "content_sha256": marker,
            },
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(append, marker) for marker in ("figurespec", "excalidraw")]
        for future in futures:
            future.result(timeout=10)

    rounds = json.loads(path.read_text(encoding="utf-8"))
    assert {item["content_sha256"] for item in rounds} == {
        "figurespec",
        "excalidraw",
    }
    assert {item["round"] for item in rounds} == {1, 2}
    for index in range(3, 11):
        rounds = _append_visual_review(
            path,
            {
                "status": "passed",
                "issues": [],
                "content_sha256": f"round-{index}",
            },
        )
    assert len(rounds) == 8
    assert rounds[-1]["round"] == 10
    assert not list(tmp_path.glob("*.tmp"))
    assert not list(tmp_path.glob("*.lock"))


def test_node_risk_index_preserves_concurrent_node_updates(tmp_path: Path) -> None:
    node_ids = ("paper", "figure")
    replace_wait = sum(min(atomic_files.MAX_DELAY_SECONDS, atomic_files.REPLACE_DELAY_SECONDS * 2 ** index)
                       for index in range(atomic_files.REPLACE_ATTEMPTS - 1))
    round_wait = len(node_ids) * (2 * atomic_files.LOCK_TIMEOUT_SECONDS + replace_wait)
    # Correctness waiting must cover both serialized updates' thread/OS lock and
    # replace-retry budgets. This is not an end-to-end performance or termination
    # guarantee: the existing outer RLock/fsync and Executor shutdown still wait.
    completed_rounds = []
    for round_number in range(100):
        round_root = tmp_path / f"round-{round_number}"
        barrier = threading.Barrier(2)
        reports = {
            node_id: {
                "node_id": node_id,
                "status": "clear",
                "blocking": False,
                "counts": {"blocker": 0, "warning": 0, "info": 0},
                "checks_executed": [f"{node_id}-check"],
                "report_path": str(round_root / ".merak" / "risk" / f"{node_id}-risk.json"),
                "generated_at": time.time(),
            }
            for node_id in node_ids
        }

        def update(node_id: str) -> None:
            barrier.wait()
            node_risk_audit_service._update_index(round_root, reports[node_id])

        with ThreadPoolExecutor(max_workers=2) as pool:
            deadline = time.monotonic() + round_wait
            futures = [pool.submit(update, node_id) for node_id in node_ids]
            for future in futures:
                future.result(timeout=max(0.0, deadline - time.monotonic()))

        payload = json.loads(
            (round_root / ".merak" / "NODE_RISK_AUDIT.json").read_text(
                encoding="utf-8"
            )
        )
        assert payload["schema"] == 1 and set(payload["nodes"]) == set(node_ids)
        for node_id, report in reports.items():
            assert payload["nodes"][node_id] == {
                "status": report["status"], "blocking": report["blocking"],
                "counts": report["counts"], "checks_executed": report["checks_executed"],
                "report_path": f".merak/risk/{node_id}-risk.json", "updated_at": report["generated_at"],
            }
        assert payload["generated_at"] >= max(report["generated_at"] for report in reports.values())
        completed_rounds.append(round_number)
    assert completed_rounds == list(range(100))
    assert not list(tmp_path.rglob("*.tmp"))


def test_node_risk_index_preserves_cross_process_node_updates(
    tmp_path: Path,
) -> None:
    context = multiprocessing.get_context("spawn")
    start = context.Event()
    node_ids = ("results", "figure", "paper", "review")
    processes = [
        context.Process(
            target=_update_node_risk_process,
            args=(str(tmp_path), node_id, start),
        )
        for node_id in node_ids
    ]
    for process in processes:
        process.start()
    start.set()
    for process in processes:
        process.join(timeout=15)
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
        assert process.exitcode == 0

    payload = json.loads(
        (tmp_path / ".merak" / "NODE_RISK_AUDIT.json").read_text(
            encoding="utf-8"
        )
    )
    assert set(payload["nodes"]) == set(node_ids)
    assert not list((tmp_path / ".merak").glob(".*.tmp"))


def test_run_state_serializes_concurrent_read_modify_write(
    tmp_path: Path,
    monkeypatch,
) -> None:
    state = RunState(str(tmp_path), "thread-contention")
    state.start(
        [
            {"id": "paper", "name": "Paper", "skill": "paper"},
            {"id": "review", "name": "Review", "skill": "review"},
        ],
        {"options": {}},
    )
    original_load = RunState._load_disk
    counter_lock = threading.Lock()
    active = 0
    maximum_active = 0

    def slow_load(instance):
        nonlocal active, maximum_active
        with counter_lock:
            active += 1
            maximum_active = max(maximum_active, active)
        try:
            time.sleep(0.03)
            return original_load(instance)
        finally:
            with counter_lock:
                active -= 1

    monkeypatch.setattr(RunState, "_load_disk", slow_load)
    barrier = threading.Barrier(2)

    def finish(phase_id: str) -> None:
        barrier.wait()
        RunState(str(tmp_path), "thread-contention").set_status(phase_id, "done")

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(finish, phase) for phase in ("paper", "review")]
        for future in futures:
            future.result(timeout=10)

    persisted = state.load()
    assert persisted is not None
    assert persisted["phases"]["paper"]["status"] == "done"
    assert persisted["phases"]["review"]["status"] == "done"
    assert maximum_active == 1


def test_run_state_transaction_preserves_concurrent_list_appends(
    tmp_path: Path,
) -> None:
    state = RunState(str(tmp_path), "append-contention")
    state.start(
        [{"id": "paper", "name": "Paper", "skill": "paper"}],
        {"options": {}},
    )
    barrier = threading.Barrier(2)

    def append(marker: str) -> None:
        barrier.wait()

        def mutate(payload: dict) -> None:
            history = payload["phases"]["paper"]["details"].setdefault(
                "platform_resumes",
                [],
            )
            history.append(marker)
            time.sleep(0.03)

        RunState(str(tmp_path), "append-contention").update_state(mutate)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(append, marker) for marker in ("first", "second")]
        for future in futures:
            future.result(timeout=10)

    persisted = state.load()
    history = persisted["phases"]["paper"]["details"]["platform_resumes"]
    assert sorted(history) == ["first", "second"]


def test_path_lock_blocks_another_process(tmp_path: Path) -> None:
    target = tmp_path / "cross-process.json"
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    release = context.Event()
    process = context.Process(
        target=_hold_process_lock,
        args=(str(target), ready, release),
    )
    process.start()
    try:
        assert ready.wait(10)
        timer = threading.Timer(0.2, release.set)
        timer.start()
        started = time.monotonic()
        with path_lock(target, timeout_seconds=5):
            elapsed = time.monotonic() - started
        timer.join(timeout=2)
        assert elapsed >= 0.15
    finally:
        release.set()
        process.join(timeout=10)
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
    assert process.exitcode == 0


def test_resume_claim_has_one_cross_process_winner(tmp_path: Path) -> None:
    state = RunState(str(tmp_path), "resume-claim-race")
    state.start(
        [{"id": "paper", "name": "Paper", "skill": "paper"}],
        {"options": {}},
    )
    state.set_run_status("failed")
    context = multiprocessing.get_context("spawn")
    start = context.Event()
    results = context.Queue()
    processes = [
        context.Process(
            target=_claim_resume_process,
            args=(str(tmp_path), "resume-claim-race", start, results),
        )
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    start.set()
    for process in processes:
        process.join(timeout=10)
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
        assert process.exitcode == 0
    tokens = [results.get(timeout=2) for _ in processes]
    winners = [token for token in tokens if token]
    assert len(winners) == 1
    assert state.release_resume_claim("wrong-owner-token") is False
    assert state.release_resume_claim(winners[0]) is True


def test_resume_claim_renewal_and_expired_takeover(
    tmp_path: Path,
    monkeypatch,
) -> None:
    clock = [1000.0]
    monkeypatch.setattr(run_state_module.time, "time", lambda: clock[0])
    state = RunState(str(tmp_path), "resume-claim-expiry")
    state.start(
        [{"id": "paper", "name": "Paper", "skill": "paper"}],
        {"options": {}},
    )
    state.set_run_status("failed")
    first = state.claim_resume(
        owner_id="first",
        expected_status="failed",
        lease_seconds=60,
    )
    assert first

    clock[0] = 1050.0
    assert state.renew_resume_claim(first, lease_seconds=60) is True
    clock[0] = 1105.0
    assert state.claim_resume(
        owner_id="second",
        expected_status="failed",
        lease_seconds=60,
    ) == ""

    clock[0] = 1111.0
    second = state.claim_resume(
        owner_id="second",
        expected_status="failed",
        lease_seconds=60,
    )
    assert second and second != first


def test_project_claim_allows_only_one_run_id_across_processes(
    tmp_path: Path,
) -> None:
    context = multiprocessing.get_context("spawn")
    for round_number in range(5):
        round_path = tmp_path / f"round-{round_number}"
        round_path.mkdir()
        start = context.Event()
        results = context.Queue()
        processes = [
            context.Process(
                target=_claim_project_process,
                args=(str(round_path), run_id, start, results),
            )
            for run_id in (
                "fresh-run-a", "fresh-run-b", "fresh-run-c", "fresh-run-d",
            )
        ]
        for process in processes:
            process.start()
        start.set()
        for process in processes:
            process.join(timeout=15)
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
            assert process.exitcode == 0

        claims = [results.get(timeout=2) for _ in processes]
        winners = [(run_id, token) for run_id, token in claims if token]
        assert len(winners) == 1
        active = ProjectRunLease(str(round_path)).active_claim()
        assert active["run_id"] == winners[0][0]
        assert active["token"] == winners[0][1]
        winner_run_id, winner_token = winners[0]
        lease = ProjectRunLease(str(round_path))
        assert lease.release("wrong-token", run_id=winner_run_id) is False
        assert lease.release(winner_token, run_id=winner_run_id) is True
        assert lease.active_claim() == {}


def test_project_claim_retries_transient_read_error_without_overwrite(
    tmp_path: Path,
    monkeypatch,
) -> None:
    lease = ProjectRunLease(str(tmp_path))
    first = lease.claim(run_id="first-run", owner_id="first")
    assert first

    real_read_text = Path.read_text
    failures = 2

    def flaky_read_text(path: Path, *args, **kwargs):
        nonlocal failures
        if path == lease.path and failures:
            failures -= 1
            error = PermissionError("lease temporarily busy")
            error.winerror = 32
            raise error
        return real_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", flaky_read_text)
    assert lease.claim(run_id="second-run", owner_id="second") == ""
    assert failures == 0
    active = lease.active_claim()
    assert active["run_id"] == "first-run"
    assert active["token"] == first


def test_project_claim_fails_closed_and_releases_marker_when_write_is_denied(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import server.workflows.workflow_lease as lease_module

    lease = ProjectRunLease(str(tmp_path))
    real_write = lease_module.atomic_write_json
    def deny_project_write(path, payload, *args, **kwargs):
        if Path(path).resolve() == lease.path:
            raise PermissionError("project lease path temporarily denied")
        return real_write(path, payload, *args, **kwargs)

    monkeypatch.setattr(lease_module, "atomic_write_json", deny_project_write)
    with pytest.raises(PermissionError, match="temporarily denied"):
        lease.claim(run_id="denied-run", owner_id="denied")
    assert not lease.marker_path.exists()
    assert lease.active_claim() == {}
    monkeypatch.setattr(lease_module, "atomic_write_json", real_write)
    token = lease.claim(run_id="recovered-run", owner_id="recovered")
    assert token
    assert lease.active_claim()["run_id"] == "recovered-run"
    assert lease.release(token, run_id="recovered-run")
    assert lease.active_claim() == {}


def test_project_claim_fails_closed_for_corrupt_existing_lease(
    tmp_path: Path,
) -> None:
    lease = ProjectRunLease(str(tmp_path))
    lease.path.parent.mkdir(parents=True)
    lease.path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(RuntimeError, match="lease is corrupt"):
        lease.claim(run_id="replacement-run", owner_id="replacement")
    assert lease.path.read_text(encoding="utf-8") == "{not-json"


def test_project_claim_renewal_and_expired_takeover(
    tmp_path: Path,
    monkeypatch,
) -> None:
    clock = [2000.0]
    monkeypatch.setattr(run_state_module.time, "time", lambda: clock[0])
    lease = ProjectRunLease(str(tmp_path))
    first = lease.claim(
        run_id="first-run",
        owner_id="first",
        lease_seconds=60,
    )
    assert first

    clock[0] = 2050.0
    assert lease.renew(first, run_id="first-run", lease_seconds=60) is True
    clock[0] = 2105.0
    assert lease.claim(
        run_id="second-run",
        owner_id="second",
        lease_seconds=60,
    ) == ""

    clock[0] = 2111.0
    second = lease.claim(
        run_id="second-run",
        owner_id="second",
        lease_seconds=60,
    )
    assert second and second != first


def test_project_claim_orphan_is_recoverable_after_missed_heartbeats(
    tmp_path: Path,
    monkeypatch,
) -> None:
    clock = [3000.0]
    monkeypatch.setattr(run_state_module.time, "time", lambda: clock[0])
    lease = ProjectRunLease(str(tmp_path))
    first = lease.claim(
        run_id="crashed-run",
        owner_id="dead-backend",
        lease_seconds=3600,
    )
    assert first

    clock[0] = 3089.0
    assert lease.claim(
        run_id="recovered-run",
        owner_id="new-backend",
        lease_seconds=120,
    ) == ""

    clock[0] = 3091.0
    recovered = lease.claim(
        run_id="recovered-run",
        owner_id="new-backend",
        lease_seconds=120,
    )
    assert recovered and recovered != first
    assert lease.active_claim()["run_id"] == "recovered-run"


def test_resume_claim_orphan_is_recoverable_after_missed_heartbeats(
    tmp_path: Path,
    monkeypatch,
) -> None:
    clock = [4000.0]
    monkeypatch.setattr(run_state_module.time, "time", lambda: clock[0])
    state = RunState(str(tmp_path), "crashed-resume")
    state.start(
        [{"id": "paper", "name": "Paper", "skill": "paper"}],
        {"options": {}},
    )
    first = state.claim_resume(owner_id="dead-backend", lease_seconds=3600)
    assert first

    clock[0] = 4089.0
    assert state.claim_resume(owner_id="new-backend", lease_seconds=120) == ""
    clock[0] = 4091.0
    recovered = state.claim_resume(owner_id="new-backend", lease_seconds=120)
    assert recovered and recovered != first


def test_engine_heartbeats_renew_resume_and_project_claims(tmp_path: Path) -> None:
    run_id = "heartbeat-run"
    state = RunState(str(tmp_path), run_id)
    state.start(
        [{"id": "paper", "name": "Paper", "skill": "paper"}],
        {"options": {}},
    )
    resume_token = state.claim_resume(
        owner_id="heartbeat-test",
        lease_seconds=60,
    )
    lease = ProjectRunLease(str(tmp_path))
    project_token = lease.claim(
        run_id=run_id,
        owner_id="heartbeat-test",
        lease_seconds=60,
    )
    assert resume_token and project_token
    resume_before = state.load()["resume_claim"]["renewed_at"]
    project_before = lease.active_claim()["renewed_at"]
    engine = WorkflowEngine()
    engine.RESUME_CLAIM_HEARTBEAT_SECONDS = 0.01
    engine.PROJECT_CLAIM_HEARTBEAT_SECONDS = 0.01
    run = WorkflowRun(
        id=run_id,
        project_path=str(tmp_path),
        resume_claim_token=resume_token,
        project_claim_token=project_token,
    )

    async def exercise_heartbeats() -> None:
        tasks = [
            asyncio.create_task(engine._heartbeat_resume_claim(run)),
            asyncio.create_task(engine._heartbeat_project_claim(run)),
        ]
        await asyncio.sleep(0.08)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks)

    asyncio.run(exercise_heartbeats())

    assert state.load()["resume_claim"]["renewed_at"] > resume_before
    assert lease.active_claim()["renewed_at"] > project_before
    assert state.release_resume_claim(resume_token) is True
    assert lease.release(project_token, run_id=run_id) is True


def test_resume_heartbeat_cancels_task_after_claim_is_replaced(
    tmp_path: Path,
) -> None:
    run_id = "lost-resume-claim"
    state = RunState(str(tmp_path), run_id)
    state.start(
        [{"id": "paper", "name": "Paper", "skill": "paper"}],
        {"options": {}},
    )
    resume_token = state.claim_resume(
        owner_id="original-owner",
        lease_seconds=60,
    )
    assert resume_token

    replacement_token = "replacement-token"

    def replace_claim(payload: dict) -> None:
        payload["resume_claim"]["token"] = replacement_token
        payload["resume_claim"]["owner_id"] = "replacement-owner"

    state.update_state(replace_claim)
    engine = WorkflowEngine()
    engine.RESUME_CLAIM_HEARTBEAT_SECONDS = 0.01
    run = WorkflowRun(
        id=run_id,
        project_path=str(tmp_path),
        resume_claim_token=resume_token,
    )

    async def lose_claim() -> bool:
        running = asyncio.create_task(asyncio.sleep(60))
        engine._running_tasks[run_id] = running
        heartbeat = asyncio.create_task(engine._heartbeat_resume_claim(run))
        await asyncio.sleep(0.08)
        await asyncio.gather(running, heartbeat, return_exceptions=True)
        return running.cancelled()

    assert asyncio.run(lose_claim()) is True
    assert "resume ownership" in run.interruption_reason
    assert state.release_resume_claim(replacement_token) is True


def test_engine_shutdown_joins_workers_and_releases_workflow_ownership(
    tmp_path: Path,
) -> None:
    run_id = "backend-restart"
    state = RunState(str(tmp_path), run_id)
    state.start(
        [{"id": "paper", "name": "Paper", "skill": "paper"}],
        {"options": {}},
    )
    resume_token = state.claim_resume(owner_id="desktop", lease_seconds=60)
    lease = ProjectRunLease(str(tmp_path))
    project_token = lease.claim(
        run_id=run_id,
        owner_id="desktop",
        lease_seconds=60,
    )
    assert resume_token and project_token
    engine = WorkflowEngine()
    run = WorkflowRun(
        id=run_id,
        project_path=str(tmp_path),
        resume_claim_token=resume_token,
        project_claim_token=project_token,
    )

    async def exercise_shutdown() -> tuple[bool, str]:
        worker = asyncio.create_task(asyncio.sleep(60))
        engine._runs[run_id] = run
        engine._running_tasks[run_id] = worker
        await engine.shutdown()
        return worker.cancelled(), run.interruption_reason

    cancelled, reason = asyncio.run(exercise_shutdown())

    assert cancelled is True
    assert "backend stopped or restarted" in reason
    assert state.load().get("resume_claim") is None
    assert lease.active_claim() == {}


def test_workflow_display_log_keeps_concurrent_entries(tmp_path: Path) -> None:
    first = WorkflowEventJournal()
    second = WorkflowEventJournal()
    barrier = threading.Barrier(2)

    def record(journal: WorkflowEventJournal, prefix: str) -> None:
        barrier.wait()
        for index in range(5):
            journal.record(
                tmp_path,
                "journal-contention",
                "agent_output",
                {"text": f"{prefix}-{index}"},
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(record, first, "first"),
            pool.submit(record, second, "second"),
        ]
        for future in futures:
            future.result(timeout=10)

    entries = json.loads(
        (tmp_path / ".merak" / "workflow_logs.json").read_text(encoding="utf-8")
    )
    assert {entry["message"] for entry in entries} == {
        *(f"first-{index}" for index in range(5)),
        *(f"second-{index}" for index in range(5)),
    }


def test_experiment_manifest_preserves_concurrent_updates(tmp_path: Path) -> None:
    store = RunManifestStore(tmp_path, "manifest-contention")
    store.write({"run_id": "manifest-contention", "status": "pending"})
    barrier = threading.Barrier(2)

    def update(name: str) -> None:
        barrier.wait()
        store.update(**{name: True})

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(update, name) for name in ("worker_a", "worker_b")]
        for future in futures:
            future.result(timeout=10)

    payload = store.load()
    assert payload["worker_a"] is True
    assert payload["worker_b"] is True
    assert not list(store.root.glob("*.tmp"))
    assert not list(store.root.glob("*.lock"))
