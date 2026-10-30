"""Collect immutable runtime failures and invoke one bounded source repair."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from ..agent.tools import invoke_skill
from ..services.experiment_runner import JobStatus, experiment_scheduler
from ..services.remote_experiment_runtime import RunManifestStore
from ..services.skill_orchestrator import skill_orchestrator
from .models import WorkflowRun


def _run_spec(root: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            (root / "experiments" / "RUN_SPEC.json").read_text(
                encoding="utf-8-sig",
                errors="strict",
            ),
        )
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _current_attempt(manifest: dict[str, Any]) -> dict[str, Any]:
    attempts = [
        item for item in manifest.get("attempts") or [] if isinstance(item, dict)
    ]
    current = int(manifest.get("current_attempt") or 0)
    return next(
        (item for item in attempts if int(item.get("attempt") or 0) == current),
        attempts[-1] if attempts else {},
    )


def _failure_record(
    host: Any,
    root: Path,
    run_spec: dict[str, Any],
    job_id: str,
    manifest: dict[str, Any],
    job: Any,
    completed_output_failure: bool,
) -> dict[str, Any] | None:
    from ..services.experiment_output_failure import attempt_uses_current_sources
    if not attempt_uses_current_sources(root, job_id):
        return None
    attempt = _current_attempt(manifest)
    status = str(attempt.get("status") or manifest.get("status") or "").casefold()
    validation = [
        str(item)
        for item in attempt.get("validation_issues") or []
        if str(item).strip()
    ]
    eligibility_only = (
        bool(validation)
        and all(
            "explicitly ineligible as evidence" in item.casefold()
            for item in validation
        )
        and Path(str(attempt.get("diagnosis_path") or "")).name.casefold()
        == "post-run-validation.json"
    )
    if status == "failed_validation" and eligibility_only:
        return None
    if status not in {"failed", "failed_validation"}:
        if status != "completed" or not completed_output_failure or not run_spec:
            return None
        path = root / ".merak" / "experiments" / job_id / "run.json"
        if not host._managed_experiment_output_issues(root, run_spec, path):
            return None
    if any(
        isinstance(item, dict)
        and str(item.get("severity") or "").casefold() == "critical"
        for item in attempt.get("anomalies") or []
    ):
        return None
    log_path = Path(
        str(attempt.get("local_log_path") or getattr(job, "log_path", "") or "")
    )
    diagnosis_path = Path(
        str(
            attempt.get("diagnosis_path") or getattr(job, "diagnosis_path", "") or "",
        )
    )
    return {
        "job_id": job_id,
        "attempt": int(attempt.get("attempt") or 0),
        "exit_code": attempt.get("exit_code", getattr(job, "exit_code", None)),
        "command": str(attempt.get("command") or getattr(job, "command", "") or ""),
        "error": str(
            attempt.get("error")
            or getattr(job, "error_message", "")
            or "; ".join(validation)
        ),
        "validation_issues": validation,
        "log_path": "" if str(log_path) == "." else str(log_path),
        "diagnosis_path": "" if str(diagnosis_path) == "." else str(diagnosis_path),
        "log_tail": _tail(log_path, 16000),
        "diagnosis": _tail(diagnosis_path, 8000),
    }


def _tail(path: Path, limit: int) -> str:
    try:
        return path.read_text(encoding="utf-8-sig", errors="replace")[-limit:]
    except OSError:
        return ""


async def _failure_inventory(
    host: Any,
    run: WorkflowRun,
    diagnostics: dict[str, Any],
) -> tuple[str, list[dict[str, Any]]]:
    from ..services.experiment_output_failure import source_bound_experiment_id
    experiment_id = source_bound_experiment_id(Path(run.project_path).resolve(), run.id)
    experiment = experiment_scheduler.get_experiment(experiment_id)
    root = Path(run.project_path).resolve()
    run_spec = _run_spec(root)
    text = " ".join(
        [
            str(diagnostics.get("reason") or ""),
            str(diagnostics.get("summary") or ""),
            *(str(item) for item in diagnostics.get("issues", [])),
        ]
    ).casefold()
    completed_failure = any(
        marker in text
        for marker in (
            "managed experiment evidence contract failed",
            "managed experiment post-run validation failed",
            "declared output",
            "no data rows",
            "not hash-owned",
        )
    )
    records, seen = [], set()
    if experiment is not None:
        for job in experiment.jobs:
            store = RunManifestStore(experiment.project_path, job.id)
            manifest = store.load()
            if job.status == JobStatus.COMPLETED and completed_failure:
                issues = host._managed_experiment_output_issues(
                    root, run_spec, store.path
                )
                if issues:
                    await experiment_scheduler.mark_job_output_validation_failed(
                        experiment.id,
                        job.id,
                        issues,
                    )
                    manifest = store.load()
            record = _failure_record(
                host,
                root,
                run_spec,
                job.id,
                manifest,
                job,
                completed_failure,
            )
            if record:
                records.append(record)
                seen.add(job.id)
    runtime_root = root / ".merak" / "experiments"
    for path in (
        sorted(runtime_root.glob(f"{experiment_id[:56]}-seed-*/run.json"))
        if runtime_root.is_dir()
        else []
    ):
        if path.parent.name in seen:
            continue
        manifest = _read_manifest(path)
        record = _failure_record(
            host,
            root,
            run_spec,
            path.parent.name,
            manifest,
            None,
            completed_failure,
        )
        if record:
            records.append(record)
    return experiment_id, records


def _read_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _repair_prompt(
    run: WorkflowRun,
    diagnostics: dict[str, Any],
    failures: list[dict[str, Any]],
    round_number: int,
    cycle: int,
) -> str:
    gate = {
        "reason": diagnostics.get("reason"),
        "summary": diagnostics.get("summary"),
        "issues": list(diagnostics.get("issues") or [])[:8],
    }
    return (
        "Repair one deterministic experiment execution failure in place.\n\n"
        f"Project: {run.project_path}\nWorkflow run: {run.id}\n"
        f"Revision round/cycle: {round_number}/{cycle}\n"
        f"Failed immutable attempt evidence:\n{json.dumps(failures, ensure_ascii=False, indent=2)}\n\n"
        f"Gate context:\n{json.dumps(gate, ensure_ascii=False, indent=2)}\n\n"
        "Read the exact traceback, diagnosis, command, source, configuration, "
        "RUN_SPEC, METHOD_CONTRACT, and experiment plan before editing. Fix only "
        "the minimal deterministic implementation or runtime bug. Preserve the "
        "frozen scientific design. Do not fabricate results, delete failed evidence, "
        "edit runtime manifests, weaken a gate, or run the experiment."
    )


async def repair_failed_experiment_source(
    host: Any,
    run: WorkflowRun,
    diagnostics: dict[str, Any],
    round_number: int,
    cycle: int,
) -> str:
    experiment_id, failures = await _failure_inventory(host, run, diagnostics)
    if not failures:
        return ""
    before = host._revision_artifact_signature(
        run.project_path, "exp-design", run.options
    )
    started = time.time()
    skill_orchestrator.mark_execution(
        run.project_path,
        run.id,
        "exp-run",
        "experiment-bridge",
        "running",
        role="runtime_repair",
        policy_loaded=True,
        execution_kind="model_owned",
    )
    try:
        output = await invoke_skill(
            "experiment-bridge",
            _repair_prompt(run, diagnostics, failures, round_number, cycle),
            project_path=run.project_path,
            parent_context="skill-chain:workflow>exp-run-repair",
            allowed_tools_override=["Read", "Write", "Edit", "Glob", "Grep"],
            invocation_contract="Repair one preserved deterministic experiment failure. Runtime owns execution, monitoring, and evidence.",
            max_iterations=12,
        )
    except Exception as error:
        _record_repair(
            host, run, started, "failed", error=host._exception_summary(error)
        )
        raise
    return await _finish_repair(
        host, run, experiment_id, failures, before, started, output
    )


async def _finish_repair(
    host: Any,
    run: WorkflowRun,
    experiment_id: str,
    failures: list[dict[str, Any]],
    before: str,
    started: float,
    output: str,
) -> str:
    changed = before != host._revision_artifact_signature(
        run.project_path, "exp-design", run.options
    )
    _record_repair(
        host,
        run,
        started,
        "completed" if changed else "failed",
        output=output,
        error="" if changed else "No execution input changed",
    )
    await host._emit(
        run,
        "experiment_source_repair_completed",
        {
            "node_id": "exp-run",
            "experiment_id": experiment_id,
            "changed": changed,
            "failed_attempts": [
                {
                    key: item[key]
                    for key in (
                        "job_id",
                        "attempt",
                        "exit_code",
                        "diagnosis_path",
                        "log_path",
                    )
                }
                for item in failures
            ],
        },
    )
    if not changed:
        raise RuntimeError(
            "Experiment debugger returned without changing executable inputs; the preserved failure was not retried."
        )
    return str(output or "")


def _record_repair(
    host: Any,
    run: WorkflowRun,
    started: float,
    status: str,
    *,
    output: str = "",
    error: str = "",
) -> None:
    traces = host._skill_invocation_traces(
        run.project_path,
        "experiment-bridge",
        started,
    )
    trace = traces[-1] if traces else {}
    skill_orchestrator.mark_execution(
        run.project_path,
        run.id,
        "exp-run",
        "experiment-bridge",
        status,
        role="runtime_repair",
        session_id=str(trace.get("session_id") or ""),
        output=output,
        error=error,
        policy_loaded=True,
        execution_kind="model_owned",
    )
