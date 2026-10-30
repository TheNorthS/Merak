"""Create durable run state and own background lifecycle claims."""

from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path
from typing import Any

from .engine_context import ProjectRunLease, logger
from .models import NodeStatus, WorkflowRun
from .run_start_preparation import RunStartPlan
from .run_state import RunState


def _bind_execution_contracts(plan: RunStartPlan, project_path: str) -> None:
    from ..services.skill_orchestrator import resolve_execution_contract

    phase_ids = list((plan.existing_state or {}).get("phases", {}).keys())
    plan.options["selected_node_ids"] = phase_ids or [node.id for node in plan.nodes]
    for node in plan.nodes:
        contract = resolve_execution_contract(node.id, plan.options, project_path=project_path)
        node.execution_kind = contract.kind
        node.runtime_service = contract.runtime_service
        node.policy_required = contract.policy_required


def create_run(
    host: Any,
    plan: RunStartPlan,
    project_path: str,
    research_direction: str,
    effort: str,
    on_event: Any,
) -> tuple[WorkflowRun, RunState]:
    _bind_execution_contracts(plan, project_path)
    run = WorkflowRun(
        id=plan.requested_run_id or plan.project_claim_run_id or uuid.uuid4().hex[:12],
        project_path=project_path,
        nodes=plan.nodes,
        status="running",
        created_at=float((plan.existing_state or {}).get("created_at") or time.time()),
        on_event=on_event,
        options=plan.options,
        input_baseline=plan.input_baseline,
        resume_claim_token=plan.resume_claim_token,
        project_claim_token=plan.project_claim_token,
    )
    if run.input_baseline.get("run_id") == "pending":
        run.input_baseline["run_id"] = run.id
    _bind_imported_evidence(run)
    if plan.resume_feedback and plan.nodes:
        run.checkpoint_feedback = plan.resume_feedback
        run.checkpoint_node_id = plan.nodes[0].id
    host._runs[run.id] = run
    state = RunState(project_path, run.id)
    _prepare_research_strategy(host, run)
    _prepare_specialists(run, research_direction)
    state.start(
        [
            {
                "id": node.id,
                "name": node.name,
                "skill": node.skill,
                "execution_kind": node.execution_kind,
                "runtime_service": node.runtime_service,
                "policy_required": node.policy_required,
            }
            for node in plan.nodes
        ],
        {
            "effort": effort,
            "assurance": plan.assurance,
            "direction": research_direction,
            "options": plan.options,
        },
        input_baseline=run.input_baseline,
    )
    if plan.resume_feedback and plan.nodes:
        from .operator_feedback import record_operator_feedback
        record_operator_feedback(state, plan.nodes[0].id, plan.resume_feedback)
    return run, state


def _bind_imported_evidence(run: WorkflowRun) -> None:
    mode = str(
        run.options.get("non_experiment_evidence_mode") or "design_only"
    ).casefold()
    if run.options.get("run_experiment") is True or mode not in {
        "existing_results",
        "secondary_analysis",
    }:
        return
    from ..services.execution_provenance import execution_provenance_service

    sources = execution_provenance_service.proven_result_sources(
        run.project_path,
        suffixes={".csv", ".tsv", ".json", ".npz"},
    )
    manifest = execution_provenance_service.record_import(
        run.project_path,
        run_id=run.id,
        evidence_mode=mode,
        input_baseline=run.input_baseline,
    )
    if not manifest.get("artifacts") and not sources:
        relative = str(manifest.get("manifest_path") or "")
        if relative:
            try:
                (Path(run.project_path).resolve() / relative).unlink(missing_ok=True)
            except OSError:
                pass
        raise ValueError(
            f"{mode} requires at least one explicitly selected CSV/JSON/TSV/NPZ file "
            "under experiments/results or experiments/logs, or a previously verified runtime result",
        )
    run.options["evidence_import_manifest"] = str(manifest.get("manifest_path") or "")


def _prepare_research_strategy(host: Any, run: WorkflowRun) -> None:
    strategy = host._normalize_research_strategy(
        run.options.get("research_strategy", {})
    )
    if not strategy:
        return
    run.options["research_strategy"] = strategy
    if any(node.id in {"lit", "novelty"} for node in run.nodes):
        host._save_research_strategy(run.project_path, run.id, strategy)
        return
    reused = host._restore_search_strategy_provenance(run.project_path, strategy)
    if reused:
        run.options["reused_search_evidence_run_id"] = reused


def _prepare_specialists(run: WorkflowRun, direction: str) -> None:
    from .report_revision_recovery import active_report_consumer
    if active_report_consumer(RunState(run.project_path, run.id).load() or {}):
        return
    try:
        from ..services.research_specialists import research_specialist_service

        plan = research_specialist_service.prepare(
            run.project_path,
            run.id,
            direction,
            run.options,
            [node.id for node in run.nodes],
        )
        run.options["specialist_plan_path"] = str(
            research_specialist_service.plan_path(run.project_path, run.id),
        )
        run.options["research_profile"] = dict(plan.get("profile") or {})
    except Exception as error:
        logger.warning(
            "Research specialist plan could not be prepared", error=str(error)
        )


async def _cleanup_lifecycle(
    host: Any, run: WorkflowRun, task: asyncio.Task[Any]
) -> None:
    heartbeat_tasks = []
    for registry in (host._resume_claim_heartbeats, host._project_claim_heartbeats):
        heartbeat = registry.pop(run.id, None)
        if heartbeat is not None and not heartbeat.done():
            heartbeat.cancel()
            heartbeat_tasks.append(heartbeat)
    if heartbeat_tasks:
        await asyncio.gather(*heartbeat_tasks, return_exceptions=True)
    try:
        if run.resume_claim_token:
            await asyncio.to_thread(
                RunState(run.project_path, run.id).release_resume_claim,
                run.resume_claim_token,
            )
        if run.project_claim_token:
            await asyncio.to_thread(
                ProjectRunLease(run.project_path).release,
                run.project_claim_token,
                run_id=run.id,
            )
    except Exception as error:
        logger.warning(
            "Workflow lifecycle claim cleanup failed",
            run_id=run.id,
            error=str(error),
        )
    if task.done() and not task.cancelled() and task.exception():
        logger.error("Workflow task crashed", error=str(task.exception()))


async def execute_with_lifecycle_cleanup(
    host: Any, run: WorkflowRun, direction: str, effort: str, assurance: str,
) -> None:
    """A worker is not finished until its heartbeat and durable leases are released."""
    try:
        await host._execute_run(run, direction, effort, assurance, run.options)
    finally:
        cleanup = asyncio.create_task(_cleanup_lifecycle(host, run, asyncio.current_task()))
        while not cleanup.done():
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                # A second stop must not interrupt the cleanup owned by the first.
                continue
        cleanup.result()


def launch_run(
    host: Any,
    run: WorkflowRun,
    state: RunState,
    direction: str,
    effort: str,
    assurance: str,
) -> str:
    try:
        from ..services.research_workflow_contract import (
            research_workflow_contract_service,
        )

        research_workflow_contract_service.prepare(
            run.project_path, direction, run.options
        )
    except Exception as error:
        logger.warning(
            "Research workflow contract could not be persisted", error=str(error)
        )
    from .report_revision_recovery import protect_report_recovery
    repairing = protect_report_recovery(host, run, state)
    accepted = set() if repairing else set(host._validated_accepted_phase_ids(run, state))
    from .resume_node_closure import include_reopened_dependencies
    if not repairing:
        include_reopened_dependencies(host, run, state)
    for node in run.nodes:
        if node.id in accepted:
            node.status = NodeStatus.COMPLETED
    task = asyncio.create_task(
        execute_with_lifecycle_cleanup(host, run, direction, effort, assurance),
    )
    host._running_tasks[run.id] = task
    if run.resume_claim_token:
        host._resume_claim_heartbeats[run.id] = asyncio.create_task(
            host._heartbeat_resume_claim(run),
        )
    if run.project_claim_token:
        host._project_claim_heartbeats[run.id] = asyncio.create_task(
            host._heartbeat_project_claim(run),
        )

    def done(completed: asyncio.Task[Any]) -> None:
        if host._running_tasks.get(run.id) is completed:
            host._running_tasks.pop(run.id, None)

    task.add_done_callback(done)
    return run.id
