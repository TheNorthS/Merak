import ast
import asyncio
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from server.services import remote_experiment_runtime as runtime_module
from server.services.experiment_health import ExperimentHealthMonitor, HealthPolicy
from server.services.remote_experiment_runtime import (
    ExperimentRuntime,
    ProjectSnapshot,
    RunManifestStore,
    RuntimeSpec,
)
from server.services.experiment_runner import (
    Experiment,
    ExperimentJob,
    ExperimentScheduler,
    GPUBackend,
    JobStatus,
)
from server.workflows.engine import WorkflowEngine, WorkflowRun


def test_health_monitor_detects_non_finite_and_zero_loss_once():
    monitor = ExperimentHealthMonitor(HealthPolicy(zero_loss_min_points=5))

    findings = monitor.ingest('{"step": 1, "train/loss": "NaN"}\n')
    assert [item.kind for item in findings] == ["non_finite_loss"]

    zero_findings = []
    for step in range(2, 8):
        zero_findings.extend(monitor.ingest(json.dumps({"step": step, "train/loss": 0.0}) + "\n"))
    assert [item.kind for item in zero_findings].count("loss_collapse") == 1
    assert monitor.should_stop(findings + zero_findings) is True


def test_health_monitor_requires_stall_and_repeated_gpu_idle_for_critical_stop():
    policy = HealthPolicy(
        startup_grace_seconds=10,
        stall_timeout_seconds=20,
        gpu_idle_consecutive_checks=3,
    )
    monitor = ExperimentHealthMonitor(policy, started_at=100)

    first = monitor.heartbeat(running=True, gpu_utilization=[0], now=140)
    second = monitor.heartbeat(running=True, gpu_utilization=[0], now=141)
    third = monitor.heartbeat(running=True, gpu_utilization=[0], now=142)

    assert first[0].kind == "log_stalled"
    assert second == []  # warning is de-duplicated
    assert third[0].kind == "stalled_and_gpu_idle"
    assert monitor.should_stop(third) is True


@pytest.mark.asyncio
async def test_runtime_heartbeat_reports_current_phase():
    events = []

    async def on_event(event, payload):
        events.append((event, payload))

    runtime = ExperimentRuntime()
    spec = RuntimeSpec(run_id="heartbeat-phase", project_path=".", command="echo ok")
    emitted_at = await runtime._maybe_emit_runtime_heartbeat(
        on_event,
        spec=spec,
        attempt_number=1,
        backend="local",
        started_at=0,
        last_visible_event=0,
        health=ExperimentHealthMonitor(HealthPolicy()),
        phase="preflight",
    )

    assert emitted_at > 0
    assert events[0][0] == "experiment_heartbeat"
    assert events[0][1]["phase"] == "preflight"


def test_snapshot_excludes_secrets_generated_outputs_and_datasets(tmp_path):
    (tmp_path / "experiments" / "src").mkdir(parents=True)
    (tmp_path / "experiments" / "src" / "train.py").write_text("print('ok')\n", encoding="utf-8")
    (tmp_path / "experiments" / "results").mkdir(parents=True)
    (tmp_path / "experiments" / "results" / "old.json").write_text("{}", encoding="utf-8")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "large.csv").write_text("secret data", encoding="utf-8")
    (tmp_path / ".env").write_text("TOKEN=secret", encoding="utf-8")

    spec = RuntimeSpec(run_id="snapshot-test", project_path=str(tmp_path), command="echo ok")
    store = RunManifestStore(tmp_path, spec.run_id)
    snapshot = ProjectSnapshot(spec, store).build()
    included = {item["path"] for item in snapshot["files"]}
    excluded = {item["path"]: item["reason"] for item in snapshot["excluded"]}

    assert "experiments/src/train.py" in included
    assert excluded["experiments/results/old.json"] == "previous_experiment_artifact"
    assert excluded["data/large.csv"] == "dataset_sync_disabled"
    assert excluded[".env"] == "sensitive_local_file"
    assert len(snapshot["snapshot_hash"]) == 64


@pytest.mark.asyncio
async def test_local_runtime_persists_manifest_logs_and_results(tmp_path):
    script = tmp_path / "train_test.py"
    script.write_text(
        "from pathlib import Path\n"
        "import json\n"
        "out = Path('experiments/results')\n"
        "out.mkdir(parents=True, exist_ok=True)\n"
        "print(json.dumps({'step': 1, 'train/loss': 1.0}), flush=True)\n"
        "(out / 'metrics.json').write_text(json.dumps({'accuracy': 0.5}), encoding='utf-8')\n",
        encoding="utf-8",
    )
    command = subprocess.list2cmdline([sys.executable, "-u", script.name])
    runtime = ExperimentRuntime()

    outcome = await runtime.run(RuntimeSpec(
        run_id="local-success",
        project_path=str(tmp_path),
        command=command,
        backend="local",
        gpu_required=False,
        timeout_seconds=30,
        poll_interval_seconds=0.5,
    ))

    assert outcome.status == "completed"
    assert Path(outcome.manifest_path).is_file()
    assert Path(outcome.log_path).read_text(encoding="utf-8").strip()
    manifest = json.loads(Path(outcome.manifest_path).read_text(encoding="utf-8"))
    published_log = Path(manifest["published_log_path"])
    assert published_log.is_file()
    assert published_log.relative_to(tmp_path).as_posix().startswith(
        "experiments/logs/managed/local-success/"
    )
    assert published_log.relative_to(tmp_path).as_posix() in manifest["result_artifacts"]
    manifest_copy = tmp_path / "experiments" / "results" / "remote" / "local-success" / "run_manifest.json"
    assert manifest_copy.is_file()
    assert json.loads(manifest_copy.read_text(encoding="utf-8"))["status"] == "completed"


@pytest.mark.asyncio
async def test_local_runtime_stops_suspicious_zero_loss_and_writes_diagnosis(tmp_path):
    script = tmp_path / "collapse.py"
    script.write_text(
        "import json, time\n"
        "for step in range(8):\n"
        "    print(json.dumps({'step': step, 'train/loss': 0.0}), flush=True)\n"
        "    time.sleep(0.05)\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )
    command = subprocess.list2cmdline([sys.executable, "-u", script.name])
    runtime = ExperimentRuntime()

    outcome = await runtime.run(RuntimeSpec(
        run_id="local-collapse",
        project_path=str(tmp_path),
        command=command,
        backend="local",
        gpu_required=False,
        timeout_seconds=30,
        poll_interval_seconds=0.5,
        health_policy=HealthPolicy(zero_loss_min_points=5),
    ))

    assert outcome.status == "anomaly_stopped"
    assert any(item["kind"] == "loss_collapse" for item in outcome.anomalies)
    assert outcome.metrics["train/loss"] == 0.0
    diagnosis = Path(outcome.diagnosis_path)
    assert diagnosis.is_file()
    payload = json.loads(diagnosis.read_text(encoding="utf-8"))
    assert payload["retry_contract"]["automatic_code_edits"] is False
    assert (diagnosis.parent / "DIAGNOSIS.md").is_file()


def test_remote_wrapper_preserves_training_exit_code(tmp_path):
    spec = RuntimeSpec(
        run_id="wrapper-test",
        project_path=str(tmp_path),
        command="python experiments/src/train.py",
        env_vars={"MERAK_SEED": "42"},
    )
    wrapper = ExperimentRuntime._build_remote_wrapper(
        spec,
        "/workspace/run",
        "/workspace/meta/train.log",
        "/workspace/meta/status.json",
    )

    assert "set -uo pipefail" in wrapper
    assert "PIPESTATUS[0]" in wrapper
    assert "export MERAK_SEED=42" in wrapper
    assert "status.json" in wrapper


def test_modal_launcher_mounts_snapshot_persists_logs_and_status(tmp_path):
    spec = RuntimeSpec(
        run_id="modal-test",
        project_path=str(tmp_path),
        command="python train.py",
        preflight_command="python train.py --dry-run",
        backend="modal",
    )
    launcher = ExperimentRuntime()._build_modal_launcher(
        spec, tmp_path, "merak-modal-test", 1
    )

    ast.parse(launcher)
    assert ".add_local_dir(" in launcher
    assert "modal.Volume.from_name" in launcher
    assert "status.json" in launcher
    assert "volume.commit()" in launcher
    assert "train.log" in launcher
    assert "MERAK_GPU:" in launcher
    assert "nvidia-smi" in launcher


def test_managed_output_contract_rejects_empty_declared_table(tmp_path):
    result_dir = tmp_path / "experiments" / "results" / "run-1"
    result_dir.mkdir(parents=True)
    paired = result_dir / "paired_differences.csv"
    paired.write_text("\r\n", encoding="utf-8")
    provenance = result_dir / "provenance.json"
    provenance.write_text(
        json.dumps({"result_file_sha256": {"paired_differences": "paired-hash"}}),
        encoding="utf-8",
    )
    manifest = tmp_path / ".merak" / "experiments" / "job-1" / "run.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({
        "status": "completed",
        "current_attempt": 1,
        "attempts": [{
            "attempt": 1,
            "status": "completed",
            "result_artifacts": {
                paired.relative_to(tmp_path).as_posix(): {
                    "sha256": "paired-hash",
                    "mtime": paired.stat().st_mtime,
                    "bytes": paired.stat().st_size,
                },
                provenance.relative_to(tmp_path).as_posix(): {
                    "sha256": "provenance-hash",
                    "mtime": provenance.stat().st_mtime,
                    "bytes": provenance.stat().st_size,
                },
            },
        }],
    }), encoding="utf-8")

    issues = WorkflowEngine._managed_experiment_output_issues(
        tmp_path,
        {"outputs": {"per_run_files": [
            "paired_differences.csv",
            "provenance.json",
        ]}},
        SimpleNamespace(manifest_path=str(manifest)),
    )

    assert any("no header" in item for item in issues)
    assert any("no data rows" in item for item in issues)


def test_exp_run_resume_revalidates_persisted_managed_outputs(tmp_path):
    run_id = "durable-output-check"
    result_dir = tmp_path / "experiments" / "results" / "run-1"
    result_dir.mkdir(parents=True)
    paired = result_dir / "paired_differences.csv"
    paired.write_text("\r\n", encoding="utf-8")
    provenance = result_dir / "provenance.json"
    run_spec = tmp_path / "experiments" / "RUN_SPEC.json"
    run_spec.write_text(json.dumps({
        "outputs": {
            "per_run_files": ["paired_differences.csv", "provenance.json"],
        },
    }), encoding="utf-8")
    from server.services.experiment_output_failure import source_bound_experiment_id
    experiment_id = source_bound_experiment_id(tmp_path, run_id)
    manifest = (
        tmp_path
        / ".merak"
        / "experiments"
        / f"{experiment_id}-seed-42-0"
        / "run.json"
    )
    manifest.parent.mkdir(parents=True)

    def write_manifest() -> None:
        provenance.write_text(
            json.dumps({
                "result_file_sha256": {
                    "paired_differences": hashlib.sha256(
                        paired.read_bytes()
                    ).hexdigest(),
                },
            }),
            encoding="utf-8",
        )
        manifest.write_text(json.dumps({
            "status": "completed",
            "current_attempt": 1,
            "attempts": [{
                "attempt": 1,
                "status": "completed",
                "result_artifacts": {
                    paired.relative_to(tmp_path).as_posix(): {
                        "sha256": hashlib.sha256(paired.read_bytes()).hexdigest(),
                        "mtime": paired.stat().st_mtime,
                        "bytes": paired.stat().st_size,
                    },
                    provenance.relative_to(tmp_path).as_posix(): {
                        "sha256": hashlib.sha256(provenance.read_bytes()).hexdigest(),
                        "mtime": provenance.stat().st_mtime,
                        "bytes": provenance.stat().st_size,
                    },
                },
            }],
        }), encoding="utf-8")

    write_manifest()
    run = WorkflowRun(id=run_id, project_path=str(tmp_path), options={})
    engine = WorkflowEngine()

    rejected = engine._managed_experiment_acceptance_gate(
        run,
        {"run_experiment": True},
    )

    assert rejected["accepted"] is False
    assert rejected["details"]["jobs_checked"] == 1
    assert any("no data rows" in item for item in rejected["details"]["issues"])

    paired.write_text("method_a,method_b,difference\na,b,0.1\n", encoding="utf-8")
    write_manifest()
    accepted = engine._managed_experiment_acceptance_gate(
        run,
        {"run_experiment": True, "experiment_id": f"workflow-{run_id}"},
    )

    assert accepted["accepted"] is True
    assert accepted["details"]["experiment_id"] == experiment_id
    assert accepted["reviewer"] == "deterministic:managed-experiment-output-contract"


@pytest.mark.asyncio
async def test_exp_run_repair_discovers_persisted_validation_failure_after_restart(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    run_id = "persisted-runtime-repair"
    experiments = tmp_path / "experiments"
    experiments.mkdir()
    (experiments / "RUN_SPEC.json").write_text(
        json.dumps({"outputs": {"per_run_files": ["paired_differences.csv"]}}), encoding="utf-8")
    from server.services.experiment_output_failure import source_bound_experiment_id
    job_id = f"{source_bound_experiment_id(tmp_path, run_id)}-seed-101-0"
    attempt_dir = tmp_path / ".merak" / "experiments" / job_id / "attempt-01"
    attempt_dir.mkdir(parents=True)
    log_path = attempt_dir / "train.log"
    log_path.write_text("analysis completed\n", encoding="utf-8")
    diagnosis_path = attempt_dir / "post-run-validation.json"
    diagnosis_path.write_text(
        json.dumps({"issues": ["paired_differences.csv has no data rows"]}),
        encoding="utf-8",
    )
    manifest_path = attempt_dir.parent / "run.json"
    manifest_path.write_text(json.dumps({
        "run_id": job_id,
        "status": "failed_validation",
        "current_attempt": 1,
        "attempts": [{
            "attempt": 1,
            "status": "failed_validation",
            "exit_code": 0,
            "command": "python experiments/src/train.py --stage decisive",
            "local_log_path": str(log_path),
            "diagnosis_path": str(diagnosis_path),
            "validation_issues": ["paired_differences.csv has no data rows"],
            "anomalies": [],
        }],
    }), encoding="utf-8")
    experiments = tmp_path / "experiments"
    experiments.mkdir(exist_ok=True)
    (experiments / "RUN_SPEC.json").write_text(
        json.dumps({"outputs": {"per_run_files": ["paired_differences.csv"]}}),
        encoding="utf-8",
    )
    run = WorkflowRun(
        id=run_id,
        project_path=str(tmp_path),
        options={"run_experiment": True},
    )
    engine = WorkflowEngine()
    signatures = iter(["before", "after"])
    monkeypatch.setattr(
        engine,
        "_revision_artifact_signature",
        lambda *_args, **_kwargs: next(signatures),
    )
    monkeypatch.setattr(
        engine,
        "_skill_invocation_traces",
        lambda *_args, **_kwargs: [{"session_id": "repair-session"}],
    )
    captured: dict[str, str] = {}

    async def fake_invoke_skill(skill: str, prompt: str, **_kwargs):
        captured["skill"] = skill
        captured["prompt"] = prompt
        return "repaired persisted failure"

    monkeypatch.setattr(
        "server.agent.tools.invoke_skill",
        fake_invoke_skill,
    )

    output = await engine._repair_failed_experiment_source(
        run=run,
        diagnostics={
            "reason": "managed experiment evidence contract failed",
            "issues": ["paired_differences.csv has no data rows"],
        },
        round_number=1,
        cycle=1,
    )

    assert output == "repaired persisted failure"
    assert captured["skill"] == "experiment-bridge"
    assert "paired_differences.csv has no data rows" in captured["prompt"]
    assert "post-run-validation.json" in captured["prompt"]


@pytest.mark.asyncio
async def test_exp_run_repair_skips_manifest_eligibility_state_failure(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    run_id = "eligibility-state-retry"
    job_id = f"workflow-{run_id}-seed-101-0"
    attempt_dir = tmp_path / ".merak" / "experiments" / job_id / "attempt-01"
    attempt_dir.mkdir(parents=True)
    diagnosis_path = attempt_dir / "post-run-validation.json"
    diagnosis_path.write_text("{}\n", encoding="utf-8")
    (attempt_dir.parent / "run.json").write_text(json.dumps({
        "run_id": job_id,
        "status": "failed_validation",
        "current_attempt": 1,
        "attempts": [{
            "attempt": 1,
            "status": "failed_validation",
            "exit_code": 0,
            "diagnosis_path": str(diagnosis_path),
            "validation_issues": [
                "current managed attempt is explicitly ineligible as evidence"
            ],
            "anomalies": [],
        }],
    }), encoding="utf-8")
    experiments = tmp_path / "experiments"
    experiments.mkdir(exist_ok=True)
    (experiments / "RUN_SPEC.json").write_text("{}\n", encoding="utf-8")

    async def unexpected_skill(*_args, **_kwargs):
        raise AssertionError("manifest eligibility repair must not invoke a model")

    monkeypatch.setattr("server.agent.tools.invoke_skill", unexpected_skill)
    output = await WorkflowEngine()._repair_failed_experiment_source(
        run=WorkflowRun(
            id=run_id,
            project_path=str(tmp_path),
            options={"run_experiment": True},
        ),
        diagnostics={"reason": "managed experiment evidence contract failed"},
        round_number=1,
        cycle=1,
    )

    assert output == ""


@pytest.mark.asyncio
async def test_local_runtime_cooperative_stop_preserves_diagnosis(tmp_path):
    script = tmp_path / "long_train.py"
    script.write_text(
        "import json, time\n"
        "print(json.dumps({'step': 1, 'train/loss': 1.0}), flush=True)\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )
    runtime = ExperimentRuntime()
    spec = RuntimeSpec(
        run_id="operator-stop",
        project_path=str(tmp_path),
        command=subprocess.list2cmdline([sys.executable, "-u", script.name]),
        backend="local",
        gpu_required=False,
        timeout_seconds=60,
        poll_interval_seconds=0.5,
    )

    launched = asyncio.Event()

    async def on_event(event, payload):
        if event == "experiment_phase" and payload.get("phase") == "launch":
            launched.set()

    task = asyncio.create_task(runtime.run(spec, on_event))
    try:
        await asyncio.wait_for(launched.wait(), timeout=20)
        assert await runtime.cancel(spec.run_id, "Stopped after operator review") is True
        outcome = await asyncio.wait_for(task, timeout=10)
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    assert outcome.status == "cancelled"
    assert Path(outcome.log_path).is_file()
    diagnosis = json.loads(Path(outcome.diagnosis_path).read_text(encoding="utf-8"))
    assert diagnosis["state"] == "cancelled"
    assert "operator review" in diagnosis["error"]


@pytest.mark.asyncio
async def test_local_preflight_emits_phase_and_honors_cooperative_stop(tmp_path):
    script = tmp_path / "long_preflight.py"
    script.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    runtime = ExperimentRuntime()
    spec = RuntimeSpec(
        run_id="operator-stop-preflight",
        project_path=str(tmp_path),
        command="echo should-not-launch",
        preflight_command=subprocess.list2cmdline([sys.executable, script.name]),
        backend="local",
        gpu_required=False,
        timeout_seconds=60,
    )
    preflight_started = asyncio.Event()

    async def on_event(event, payload):
        if event == "experiment_phase" and payload.get("phase") == "preflight":
            preflight_started.set()

    task = asyncio.create_task(runtime.run(spec, on_event))
    try:
        await asyncio.wait_for(preflight_started.wait(), timeout=20)
        assert await runtime.cancel(spec.run_id, "Stopped during preflight") is True
        outcome = await asyncio.wait_for(task, timeout=5)
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    assert outcome.status == "cancelled"
    assert Path(outcome.log_path).is_file()
    assert "Stopped during preflight" in Path(outcome.diagnosis_path).read_text(
        encoding="utf-8"
    )


@pytest.mark.asyncio
async def test_scheduler_reserves_one_slot_start_is_idempotent_and_stop_finalizes_local_job(
    tmp_path,
    monkeypatch,
):
    scheduler = ExperimentScheduler()
    scheduler._max_concurrent = 1
    first_started = asyncio.Event()

    async def blocked_run(job):
        first_started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(scheduler, "_run_managed_job", blocked_run)
    experiment = Experiment(
        id="scheduler-lifecycle",
        name="scheduler lifecycle",
        project_id="project",
        project_path=str(tmp_path),
        command_template="echo {seed}",
        backend=GPUBackend.LOCAL,
        work_dir=str(tmp_path),
        seeds=[1, 2],
        gpu_required=False,
    )
    await scheduler.submit_experiment(experiment)
    await scheduler.start()
    scheduler_task = scheduler._scheduler_task
    await scheduler.start()

    assert scheduler._scheduler_task is scheduler_task
    await asyncio.wait_for(first_started.wait(), timeout=5)
    await asyncio.sleep(0)
    assert len(scheduler._running_jobs) == 1
    assert sum(job.status == JobStatus.RUNNING for job in experiment.jobs) == 1

    await scheduler.stop()

    assert scheduler._scheduler_task is None
    assert not scheduler._job_tasks
    assert not scheduler._running_jobs
    assert all(
        job.status not in {JobStatus.RUNNING, JobStatus.STOPPING}
        for job in experiment.jobs
    )
    cancelled = [job for job in experiment.jobs if job.status == JobStatus.CANCELLED]
    assert len(cancelled) == 1
    assert cancelled[0].finished_at is not None


@pytest.mark.asyncio
async def test_local_runtime_falls_back_when_async_subprocess_is_unavailable(
    tmp_path,
    monkeypatch,
):
    script = tmp_path / "fallback.py"
    script.write_text("print('threaded-fallback-ok')\n", encoding="utf-8")

    async def unavailable(*args, **kwargs):
        raise NotImplementedError()

    monkeypatch.setattr(asyncio, "create_subprocess_shell", unavailable)
    runtime = ExperimentRuntime()
    command = subprocess.list2cmdline([sys.executable, "-u", script.name])
    outcome = await runtime.run(RuntimeSpec(
        run_id="selector-loop-fallback",
        project_path=str(tmp_path),
        command=command,
        preflight_command=command,
        backend="local",
        gpu_required=False,
        timeout_seconds=30,
        poll_interval_seconds=0.5,
    ))

    assert outcome.status == "completed"
    assert "threaded-fallback-ok" in Path(outcome.log_path).read_text(encoding="utf-8")
    manifest = json.loads(Path(outcome.manifest_path).read_text(encoding="utf-8"))
    assert manifest["attempts"][0]["status"] == "completed"
    assert manifest["evidence_eligible"] is True
    assert manifest["attempts"][0]["evidence_eligible"] is True


@pytest.mark.asyncio
async def test_successful_retry_resets_failed_validation_evidence_flag(tmp_path):
    script = tmp_path / "retry_success.py"
    script.write_text("print('retry-ok')\n", encoding="utf-8")
    spec = RuntimeSpec(
        run_id="eligibility-reset",
        project_path=str(tmp_path),
        command=subprocess.list2cmdline([sys.executable, "-u", script.name]),
        backend="local",
        gpu_required=False,
        timeout_seconds=30,
        poll_interval_seconds=0.5,
    )
    store = RunManifestStore(tmp_path, spec.run_id)
    store.initialize(spec)
    store.begin_attempt(spec, "old-snapshot")
    store.update_attempt(
        1,
        status="failed_validation",
        evidence_eligible=False,
        finished_at="2026-01-01T00:00:00+00:00",
    )
    store.update(status="failed_validation", evidence_eligible=False)

    outcome = await ExperimentRuntime().run(spec)

    assert outcome.status == "completed"
    manifest = store.load()
    assert manifest["current_attempt"] == 2
    assert manifest["status"] == "completed"
    assert manifest["evidence_eligible"] is True
    assert manifest["attempts"][0]["evidence_eligible"] is False
    assert manifest["attempts"][1]["evidence_eligible"] is True


@pytest.mark.asyncio
async def test_runtime_persists_exception_type_and_traceback_for_empty_error(
    tmp_path,
    monkeypatch,
):
    async def broken_launcher(*args, **kwargs):
        raise AssertionError()

    monkeypatch.setattr(runtime_module, "_create_local_subprocess_shell", broken_launcher)
    outcome = await ExperimentRuntime().run(RuntimeSpec(
        run_id="empty-launch-error",
        project_path=str(tmp_path),
        command="python missing.py",
        backend="local",
        gpu_required=False,
        timeout_seconds=30,
    ))

    assert outcome.status == "failed"
    assert outcome.error == "AssertionError"
    assert Path(outcome.log_path).name == "runtime-error.log"
    assert "AssertionError" in Path(outcome.log_path).read_text(encoding="utf-8")
    diagnosis = json.loads(Path(outcome.diagnosis_path).read_text(encoding="utf-8"))
    assert diagnosis["error"] == "AssertionError"
    assert diagnosis["log_path"] == outcome.log_path


@pytest.mark.asyncio
async def test_adjustment_requires_approval_and_is_consumed_once(tmp_path):
    scheduler = ExperimentScheduler()
    experiment = Experiment(
        id="exp-approval",
        name="approval test",
        project_id="project",
        project_path=str(tmp_path),
        command_template="python train.py --seed {seed} --batch-size {batch_size}",
        backend=GPUBackend.LOCAL,
        work_dir=str(tmp_path),
        batch_size=32,
        max_retries=2,
    )
    job = ExperimentJob(
        id="approval-job",
        experiment_id=experiment.id,
        name="approval-job",
        command="python train.py --seed 42 --batch-size 32",
        backend=GPUBackend.LOCAL,
        seed=42,
        status=JobStatus.FAILED,
        batch_size=32,
        original_batch_size=32,
        max_retries=2,
    )
    experiment.jobs = [job]
    scheduler._experiments[experiment.id] = experiment
    store = RunManifestStore(tmp_path, job.id)
    spec = RuntimeSpec(run_id=job.id, project_path=str(tmp_path), command=job.command)
    store.initialize(spec)
    store.begin_attempt(spec, "a" * 64)
    store.update_attempt(1, status="failed")
    store.update(status="failed", snapshot_hash="a" * 64)

    proposal = await scheduler.create_adjustment_proposal(
        experiment.id,
        job.id,
        summary="Reduce batch size after OOM",
        rationale="The preserved log contains a deterministic CUDA OOM finding.",
        batch_size=16,
    )
    assert job.batch_size == 32
    assert job.status == JobStatus.AWAITING_APPROVAL
    assert proposal["decision_brief"]["trigger"] == "researcher_proposed_adjustment"
    assert "research claim" in proposal["decision_brief"]["approval_question"]
    assert proposal["decision_brief"]["proposed_action"]
    assert proposal["decision_brief"]["research_impact"]
    assert proposal["decision_brief"]["risks"]

    await scheduler.resolve_adjustment_proposal(
        experiment.id, job.id, proposal["proposal_id"], approved=True
    )
    assert job.batch_size == 16
    assert job.status == JobStatus.READY_TO_RETRY
    assert "--batch-size 16" in job.command

    unexpected = tmp_path / "unexpected_change.py"
    unexpected.write_text("print('changed after approval')\n", encoding="utf-8")
    with pytest.raises(ValueError, match="source changed after approval"):
        await scheduler.retry_job(experiment.id, job.id, proposal["proposal_id"])
    unexpected.unlink()

    queued = await scheduler.retry_job(experiment.id, job.id, proposal["proposal_id"])
    assert queued["next_attempt"] == 2
    assert job.status == JobStatus.QUEUED
    assert job.retry_count == 1
    with pytest.raises(ValueError, match="already active|already been used"):
        await scheduler.retry_job(experiment.id, job.id, proposal["proposal_id"])


@pytest.mark.asyncio
async def test_platform_failure_queues_one_automatic_immutable_attempt(tmp_path):
    source = tmp_path / "train.py"
    source.write_text("print('ok')\n", encoding="utf-8")
    scheduler = ExperimentScheduler()
    experiment = Experiment(
        id="exp-platform-retry",
        name="platform retry",
        project_id="project",
        project_path=str(tmp_path),
        command_template="python train.py",
        backend=GPUBackend.LOCAL,
        work_dir=str(tmp_path),
        max_retries=2,
    )
    job = ExperimentJob(
        id="platform-retry-job",
        experiment_id=experiment.id,
        name="platform-retry-job",
        command="python train.py",
        backend=GPUBackend.LOCAL,
        status=JobStatus.FAILED,
        max_retries=2,
        error_message="NotImplementedError",
    )
    experiment.jobs = [job]
    scheduler._experiments[experiment.id] = experiment
    store = RunManifestStore(tmp_path, job.id)
    spec = RuntimeSpec(
        run_id=job.id,
        project_path=str(tmp_path),
        command=job.command,
        gpu_required=False,
    )
    snapshot = ProjectSnapshot(spec, store).build()
    store.initialize(spec)
    store.begin_attempt(spec, snapshot["snapshot_hash"])
    store.update_attempt(
        1,
        status="failed",
        finished_at="2026-01-01T00:00:00+00:00",
        exit_code=None,
        error="NotImplementedError",
        anomalies=[],
    )
    store.update(status="failed", error="NotImplementedError")

    assessment = scheduler.automatic_retry_assessment(experiment.id, job.id)
    assert assessment["eligible"] is True
    assert assessment["platform_launch_failure"] is True
    queued = await scheduler.retry_failed_job_automatically(
        experiment.id,
        job.id,
        assessment=assessment,
    )

    assert queued["next_attempt"] == 2
    assert job.status == JobStatus.QUEUED
    assert job.retry_count == 1
    preserved = store.load()
    assert preserved["current_attempt"] == 1
    assert preserved["attempts"][0]["status"] == "failed"
    assert "automatic_retry_queued" in store.events_path.read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="Only a preserved failed job|not eligible"):
        await scheduler.retry_failed_job_automatically(experiment.id, job.id)


@pytest.mark.asyncio
async def test_completed_job_with_invalid_outputs_is_quarantined(tmp_path):
    scheduler = ExperimentScheduler()
    experiment = Experiment(
        id="exp-invalid-output",
        name="invalid output",
        project_id="project",
        project_path=str(tmp_path),
        command_template="python train.py",
        backend=GPUBackend.LOCAL,
        work_dir=str(tmp_path),
        max_retries=2,
    )
    job = ExperimentJob(
        id="invalid-output-job",
        experiment_id=experiment.id,
        name="invalid-output-job",
        command="python train.py",
        backend=GPUBackend.LOCAL,
        status=JobStatus.COMPLETED,
        max_retries=2,
        exit_code=0,
    )
    experiment.jobs = [job]
    scheduler._experiments[experiment.id] = experiment
    store = RunManifestStore(tmp_path, job.id)
    spec = RuntimeSpec(
        run_id=job.id,
        project_path=str(tmp_path),
        command=job.command,
        gpu_required=False,
    )
    store.initialize(spec)
    store.begin_attempt(spec, "a" * 64)
    store.update_attempt(1, status="completed", exit_code=0)
    store.update(status="completed", current_attempt=1, exit_code=0)

    diagnosis = await scheduler.mark_job_output_validation_failed(
        experiment.id,
        job.id,
        ["paired_differences.csv has no data rows"],
    )

    assert diagnosis["state"] == "failed_validation"
    assert job.status == JobStatus.FAILED
    assert job.exit_code == 0
    quarantined = store.load()
    assert quarantined["status"] == "failed_validation"
    assert quarantined["evidence_eligible"] is False
    assert quarantined["attempts"][0]["status"] == "failed_validation"


@pytest.mark.asyncio
async def test_oom_creates_proposal_without_automatic_retry(tmp_path):
    scheduler = ExperimentScheduler()
    experiment = Experiment(
        id="oom-approval",
        name="oom",
        project_id="project",
        project_path=str(tmp_path),
        command_template="python train.py --seed {seed} --batch-size {batch_size}",
        backend=GPUBackend.LOCAL,
        work_dir=str(tmp_path),
        batch_size=32,
        max_retries=2,
    )
    job = ExperimentJob(
        id="oom-job",
        experiment_id=experiment.id,
        name="oom-job",
        command="python train.py --seed 42 --batch-size 32",
        backend=GPUBackend.LOCAL,
        status=JobStatus.RUNNING,
        batch_size=32,
        max_retries=2,
    )
    experiment.jobs = [job]
    scheduler._experiments[experiment.id] = experiment

    await scheduler._handle_oom(job)

    assert job.status == JobStatus.AWAITING_APPROVAL
    assert job.batch_size == 32
    assert scheduler._queue.qsize() == 0
    proposals = scheduler.list_adjustment_proposals(experiment.id, job.id)
    assert proposals[0]["changes"]["batch_size"] == 16
    assert proposals[0]["status"] == "pending"
