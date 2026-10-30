"""Run an explicitly authorized experiment through the durable scheduler."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from ..services.experiment_runner import (
    Experiment,
    GPUBackend,
    JobStatus,
    experiment_scheduler,
)
from ..services.backend_python_command import local_experiment_python
from ..services.run_spec import (
    execution_seeds,
    run_spec_preflight_command,
    run_spec_requires_seeds,
    run_spec_scientific_command,
    unresolved_command_placeholders,
)
from .models import WorkflowRun
from ..services.execution_matrix import compile_execution_cells, matrix_coverage_issues


def _run_contract(
    host: Any,
    run: WorkflowRun,
    opts: dict[str, Any],
) -> tuple[dict[str, Any], str, str, GPUBackend, list[int], dict[str, str], int]:
    from ..services.scientific_execution_readiness import require_scientific_execution_ready
    from ..services.experiment_output_failure import require_no_known_output_failure
    require_no_known_output_failure(Path(run.project_path).resolve())
    from ..services.experiment_aggregation_validation import require_no_failed_aggregation
    require_no_failed_aggregation(Path(run.project_path).resolve(), run.id)
    try:
        require_scientific_execution_ready(run.project_path)
    except ValueError as error:
        from ..contracts.preparation import PreparationContractError
        raise PreparationContractError(
            str(error) + '. Reconcile RUN_SPEC at its design owner: preserve real missing external '
            'inputs, but do not confuse pending runtime authorization/preflight with unavailable '
            'scientific inputs. The scheduler still requires authorization and runs preflight before compute.',
            owner='exp-design', paths=('experiments/RUN_SPEC.json',),
        ) from error
    path = Path(run.project_path).resolve() / "experiments" / "RUN_SPEC.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Invalid experiments/RUN_SPEC.json: {error}") from error
    if not isinstance(value, dict):
        raise RuntimeError("RUN_SPEC root must be a JSON object")
    command = run_spec_scientific_command(value)
    preflight = run_spec_preflight_command(value)
    if not command:
        raise RuntimeError(
            "Experiment run contract has no executable scientific command"
        )
    unresolved = unresolved_command_placeholders(command)
    if unresolved:
        raise RuntimeError(
            "Experiment scientific command contains unresolved placeholder(s): "
            + ", ".join(unresolved),
        )
    target = str(opts.get("gpu_target") or "local")
    backend = {
        "local": GPUBackend.LOCAL,
        "remote": GPUBackend.SSH_REMOTE,
        "vast": GPUBackend.VAST_AI,
        "modal": GPUBackend.MODAL,
    }.get(target)
    if backend is None:
        raise RuntimeError(f"Unsupported workflow GPU target: {target}")
    if backend == GPUBackend.LOCAL:
        interpreter = local_experiment_python()
        command = host._replace_local_python_launcher(command, interpreter)
        preflight = host._replace_local_python_launcher(preflight, interpreter)
    seeds = execution_seeds(value)
    if not seeds and run_spec_requires_seeds(value):
        raise RuntimeError("Experiment run contract has no valid explicit seed list")
    seeds = seeds or [0]
    compile_execution_cells(value, command)
    environment = value.get("environment") or {}
    if not isinstance(environment, dict):
        raise RuntimeError("RUN_SPEC.environment must be an object")
    retry = opts.get("max_retries", value.get("max_retries", 0))
    try:
        retry_limit = max(0, min(20, int(retry or 0)))
    except (TypeError, ValueError):
        retry_limit = 0
    return (
        value,
        command,
        preflight,
        backend,
        seeds,
        {str(key): str(item) for key, item in environment.items()},
        retry_limit,
    )


def _experiment(
    run: WorkflowRun,
    opts: dict[str, Any],
    run_spec: dict[str, Any],
    command: str,
    preflight: str,
    backend: GPUBackend,
    seeds: list[int],
    environment: dict[str, str],
    retries: int,
) -> Experiment:
    root = Path(run.project_path).resolve()
    from ..services.experiment_output_failure import source_bound_experiment_id
    experiment_id = source_bound_experiment_id(root, run.id)
    existing = experiment_scheduler.get_experiment(experiment_id)
    if existing is not None:
        if (existing.command_template != command or existing.seeds != seeds
                or existing.execution_cells != compile_execution_cells(run_spec, command, execution_id=experiment_id)):
            from ..contracts.preparation import PreparationContractError
            raise PreparationContractError("An existing experiment cannot reuse jobs for a changed command or matrix; start a new execution identity")
        existing.max_retries = max(int(existing.max_retries), retries)
        existing.command_template = command
        existing.preflight_command = preflight
        existing.env_vars = environment
        existing.timeout_seconds = max(
            30,
            int(opts.get("experiment_timeout_seconds") or 6 * 3600),
        )
        for job in existing.jobs:
            job.max_retries = max(int(job.max_retries), retries)
            if job.status in {JobStatus.FAILED, JobStatus.READY_TO_RETRY}:
                job.command = command.format(
                    seed=job.seed,
                    batch_size=existing.batch_size or "",
                    work_dir=existing.work_dir,
                )
        return existing
    return Experiment(
        id=experiment_id,
        name=str(run_spec.get("name") or f"MERAK workflow {run.id}"),
        project_id=str(root),
        project_path=str(root),
        command_template=command,
        preflight_command=preflight,
        backend=backend,
        server_id=str(opts.get("ssh_server_id") or "") or None,
        seeds=seeds,
        execution_cells=compile_execution_cells(run_spec, command, execution_id=experiment_id),
        batch_size=int(run_spec["batch_size"])
        if str(run_spec.get("batch_size") or "").isdigit()
        else None,
        env_vars=environment,
        work_dir=str(root),
        wave_size=max(0, int(run_spec.get("wave_size") or 1)),
        timeout_seconds=max(
            30, int(opts.get("experiment_timeout_seconds") or 6 * 3600)
        ),
        include_data=bool(opts.get("sync_project_data", False)),
        auto_stop_on_anomaly=bool(opts.get("auto_stop_on_anomaly", True)),
        gpu_required=bool(run_spec.get("gpu_required", True)),
        gpu_type=str(opts.get("remote_gpu_type") or run_spec.get("gpu_type") or "A100"),
        max_remote_cost_usd=float(opts.get("max_remote_cost_usd") or 10.0),
        vast_max_hourly_usd=float(opts.get("vast_max_hourly_usd") or 2.0),
        auto_destroy=bool(opts.get("auto_destroy_vast", True)),
        max_retries=retries,
    )


async def _validate_outputs(
    host: Any,
    run: WorkflowRun,
    experiment: Experiment,
    root: Path,
    run_spec: dict[str, Any],
) -> None:
    coverage = matrix_coverage_issues(run_spec, experiment.jobs, execution_id=experiment.id)
    if coverage:
        raise RuntimeError("Managed experiment matrix is incomplete: " + "; ".join(coverage))
    failures = []
    for job in experiment.jobs:
        if job.status != JobStatus.COMPLETED:
            continue
        issues = host._managed_experiment_output_issues(root, run_spec, job)
        if issues:
            await experiment_scheduler.mark_job_output_validation_failed(
                experiment.id,
                job.id,
                issues,
            )
            failures.append({"job_id": job.id, "issues": issues})
    if failures:
        await host._emit(
            run,
            "experiment_output_validation_failed",
            {
                "node_id": "exp-run",
                "experiment_id": experiment.id,
                "failures": failures,
            },
        )
        detail = "; ".join(
            f"{item['job_id']}: " + "; ".join(item["issues"]) for item in failures
        )
        from ..contracts.preparation import PreparationContractError
        from ..services.experiment_output_contract import output_provenance_instruction
        from ..services.experiment_output_failure import record_output_failure
        record_output_failure(root, experiment.id, "Managed experiment post-run validation failed: " + detail[:6000])
        raise PreparationContractError(
            "Managed experiment post-run validation failed: " + detail[:6000] + '\n' + output_provenance_instruction(),
            owner='exp-design', paths=('experiments/src/provenance.py', 'experiments/src/evaluation.py'),
        )


async def _retry_or_fail(
    host: Any,
    run: WorkflowRun,
    experiment: Experiment,
    failed: list[Any],
) -> bool:
    retries, assessments = [], {}
    for job in failed:
        if job.status != JobStatus.FAILED:
            continue
        assessment = experiment_scheduler.automatic_retry_assessment(
            experiment.id,
            job.id,
        )
        assessments[job.id] = assessment
        if assessment.get("eligible"):
            retries.append(
                await experiment_scheduler.retry_failed_job_automatically(
                    experiment.id,
                    job.id,
                    assessment=assessment,
                )
            )
    if retries:
        await host._emit(
            run,
            "experiment_automatic_retry",
            {
                "node_id": "exp-run",
                "experiment_id": experiment.id,
                "attempts": retries,
            },
        )
        return True
    detail = "; ".join(
        f"{job.name}: {job.error_message or job.status.value}"
        + (
            f" [retry: {assessments[job.id].get('reason')}]"
            if job.id in assessments
            else ""
        )
        + (f" (diagnosis: {job.diagnosis_path})" if job.diagnosis_path else "")
        for job in failed
    )
    raise RuntimeError(f"Managed experiment did not complete: {detail}")


async def _await_completion(
    host: Any,
    run: WorkflowRun,
    experiment: Experiment,
    root: Path,
    run_spec: dict[str, Any],
) -> None:
    while True:
        while experiment.status not in {
            "completed",
            "partial_failure",
            "cancelled",
            "attention_required",
        }:
            await asyncio.sleep(1)
        failed = [
            job
            for job in experiment.jobs
            if job.status
            in {
                JobStatus.FAILED,
                JobStatus.CANCELLED,
                JobStatus.AWAITING_APPROVAL,
            }
        ]
        if not failed:
            await _validate_outputs(host, run, experiment, root, run_spec)
            return
        if await _retry_or_fail(host, run, experiment, failed):
            continue


def _summary(experiment: Experiment) -> dict[str, Any]:
    return {
        "experiment_id": experiment.id,
        "backend": experiment.backend.value,
        "status": experiment.status,
        "jobs": [
            {
                "job_id": job.id,
                "seed": job.seed,
                "cell": dict(job.cell),
                "status": job.status.value,
                "manifest_path": job.manifest_path,
                "result_path": job.result_path,
                "log_path": job.log_path,
                "metrics": job.metrics,
            }
            for job in experiment.jobs
        ],
    }


async def execute_managed_experiment(
    host: Any,
    run: WorkflowRun,
    opts: dict[str, Any],
) -> str:
    root = Path(run.project_path).resolve()
    contract = _run_contract(host, run, opts)
    run_spec, command, preflight, backend, seeds, environment, retries = contract
    experiment = _experiment(
        run,
        opts,
        run_spec,
        command,
        preflight,
        backend,
        seeds,
        environment,
        retries,
    )
    if experiment_scheduler.get_experiment(experiment.id) is None:
        await experiment_scheduler.submit_experiment(experiment)
    run.options["experiment_id"] = experiment.id

    async def listener(event: str, payload: dict[str, Any]) -> None:
        if payload.get("experiment_id") != experiment.id:
            return
        event_payload = dict(payload)
        runtime_run_id = event_payload.pop("run_id", "")
        await host._emit(
            run,
            event,
            {
                "node_id": "exp-run",
                "experiment_id": experiment.id,
                "experiment_run_id": runtime_run_id,
                **event_payload,
            },
        )

    experiment_scheduler.add_listener(listener)
    try:
        await _await_completion(host, run, experiment, root, run_spec)
        from ..services.accepted_experiment_matrix import aggregate_accepted_matrix
        await aggregate_accepted_matrix(host, run, experiment, run_spec)
        summary = _summary(experiment)
        from ..services.notification import notification_service

        metrics = {
            f"{job.cell.get('cell_id') or f'seed_{job.seed}'}.{key}": value
            for job in experiment.jobs
            for key, value in list(job.metrics.items())[:10]
        }
        delivery = await notification_service.experiment_completed(
            experiment.name,
            metrics,
        )
        await host._emit(
            run,
            "notification_delivery",
            {
                "run_id": run.id,
                "node_id": "exp-run",
                "event": "experiment_completed",
                **delivery,
            },
        )
        return json.dumps(summary, ensure_ascii=False, indent=2)
    finally:
        experiment_scheduler.remove_listener(listener)
