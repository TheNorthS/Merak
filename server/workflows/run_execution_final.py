"""Classify run completion and persist cancellation/error recovery information.

An ended attempt with resumable nodes is incomplete, not a completed scientific
study. Notification failures must not rewrite the evidence verdict."""

from __future__ import annotations

import time

from ..services.project_memory import project_memory
from .engine_context import logger
from .models import NodeStatus
from .run_execution_context import (
    RunExecutionContext,
    save_resume_session,
)


async def classify_run(ctx: RunExecutionContext) -> None:
    from .acceptance_manifest import deliver_acceptance_manifests
    deliver_acceptance_manifests(ctx.host, ctx.run)
    ctx.durable_state = ctx.run_state.load() or {}
    ctx.failed = [n for n in ctx.run.nodes if n.status == NodeStatus.FAILED]
    if ctx.opts.get("enable_meta_optimization"):
        meta_targets = ctx.host._meta_optimization_candidates(
            ctx.run, ctx.durable_state
        )
        if meta_targets:
            await ctx.host._observe_meta_optimization(ctx.run, meta_targets)
    ctx.resumable_ids = ctx.host._resumable_phase_ids(ctx.durable_state)
    ctx.run.finished_at = time.time()
    if ctx.failed:
        ctx.run.status = "failed"
        ctx.run_state.set_run_status("failed")
        nodes_status, session_config = save_resume_session(
            ctx, ctx.resumable_ids[0] if ctx.resumable_ids else ctx.failed[0].id
        )
        await ctx.host._emit(
            ctx.run,
            "workflow_failed",
            {
                "run_id": ctx.run.id,
                "failed_nodes": [ctx.node.id for ctx.node in ctx.failed],
                "pending_nodes": ctx.resumable_ids,
                "current_node": ctx.resumable_ids[0]
                if ctx.resumable_ids
                else ctx.failed[0].id,
                "nodes_status": nodes_status,
                "config": session_config,
            },
        )
    elif ctx.resumable_ids:
        ctx.run.status = "incomplete"
        ctx.run_state.set_run_status("incomplete")
        nodes_status, session_config = save_resume_session(ctx, ctx.resumable_ids[0])
        await ctx.host._emit(
            ctx.run,
            "workflow_incomplete",
            {
                "run_id": ctx.run.id,
                "pending_nodes": ctx.resumable_ids,
                "current_node": ctx.resumable_ids[0],
                "nodes_status": nodes_status,
                "config": session_config,
            },
        )
    else:
        ctx.run.status = "completed"
        from ..services.workflow_readiness import workflow_readiness_service

        ctx.run.completion = workflow_readiness_service.assess(
            ctx.run.project_path, ctx.durable_state
        )
        ctx.session_state.clear()
        ctx.run_state.complete(ctx.run.completion)
        await ctx.host._emit(
            ctx.run,
            "workflow_completed",
            {"run_id": ctx.run.id, "failed_nodes": [], **ctx.run.completion},
        )


async def record_run_memory(ctx: RunExecutionContext) -> None:
    ctx.completed_nodes = [
        n.id for n in ctx.run.nodes if n.status == NodeStatus.COMPLETED
    ]
    try:
        project_memory.record_workflow_run(
            ctx.run.project_path,
            {
                "run_id": ctx.run.id,
                "status": ctx.run.status,
                "nodes_completed": ctx.completed_nodes,
                "duration": ctx.run.finished_at - ctx.run.created_at,
                "completion_class": str(
                    ctx.run.completion.get("completion_class") or ""
                ),
                "submission_ready": bool(ctx.run.completion.get("submission_ready")),
            },
        )
        for ctx.node in ctx.run.nodes:
            if ctx.node.status == NodeStatus.COMPLETED and ctx.node.output:
                project_memory.add_entry(
                    ctx.run.project_path,
                    key=f"workflow/{ctx.node.id}",
                    content=ctx.node.output[:300],
                    source="workflow",
                )
    except Exception as exc:
        logger.warning(
            "Workflow completed without updating project memory",
            run_id=ctx.run.id,
            error=str(exc),
        )
        await ctx.host._emit(
            ctx.run,
            "project_memory_update_failed",
            {"run_id": ctx.run.id, "error": ctx.host._exception_summary(exc)},
        )
    try:
        from ..services.notification import notification_service
        from .notification_readiness import notification_ready
        if not await notification_ready(ctx, notification_service):
            return

        duration = ctx.run.finished_at - ctx.run.created_at
        if ctx.failed:
            notification_result = await notification_service.workflow_failed(
                workflow_name=ctx.research_direction or "Unnamed",
                node_name=ctx.failed[0].name,
                error=ctx.failed[0].error or "acceptance gate failed",
            )
        elif ctx.resumable_ids:
            notification_result = await notification_service.workflow_failed(
                workflow_name=ctx.research_direction or "Unnamed",
                node_name=ctx.resumable_ids[0],
                error="Workflow attempt ended with resumable phases remaining.",
            )
        else:
            notification_result = await notification_service.workflow_completed(
                workflow_name=ctx.research_direction or "Unnamed",
                duration_s=duration,
                nodes_completed=len(ctx.completed_nodes),
            )
        await ctx.host._emit(
            ctx.run,
            "notification_delivery",
            {"run_id": ctx.run.id, **notification_result},
        )
    except Exception as exc:
        logger.warning(
            "Workflow notification dispatch failed", run_id=ctx.run.id, error=str(exc)
        )


async def handle_run_cancelled(ctx: RunExecutionContext) -> None:
    interruption_reason = str(ctx.run.interruption_reason or "").strip()
    from .interruption_checkpoint import record_interruption
    active_node = next((node for node in ctx.run.nodes if node.status == NodeStatus.RUNNING), ctx.node)
    record_interruption(ctx.run, active_node, interruption_reason or "cancelled by operator",
                        kind="interrupted" if interruption_reason else "cancelled")
    if ctx.run.checkpoint_future and (not ctx.run.checkpoint_future.done()):
        ctx.run.checkpoint_future.set_result({"feedback": "", "cancelled": True})
    current = next(
        (
            ctx.node.id
            for ctx.node in ctx.run.nodes
            if ctx.node.status == NodeStatus.RUNNING
        ),
        "",
    )
    if interruption_reason:
        ctx.run.status = "incomplete"
        if current:
            ctx.run_state.set_status(current, "pending", error=interruption_reason)
        ctx.run_state.set_run_status("incomplete")
        ctx.run_state.update_state(
            lambda latest: {
                **latest,
                "interruption_reason": interruption_reason,
                "interrupted_at": time.time(),
            }
        )
    else:
        ctx.run.status = "cancelled"
        if current:
            ctx.run_state.set_status(current, "pending", error="cancelled by operator")
        ctx.run_state.set_run_status("cancelled")
    ctx.run.finished_at = time.time()
    for node in ctx.run.nodes:
        if node.status in {NodeStatus.RUNNING, NodeStatus.QUEUED}:
            node.status = NodeStatus.IDLE
            node.finished_at = ctx.run.finished_at
            node.error = interruption_reason or "cancelled by operator"
    ctx.resumable_ids = ctx.run_state.resumable_phase_ids()
    nodes_status, config = save_resume_session(
        ctx, current or (ctx.resumable_ids[0] if ctx.resumable_ids else "")
    )
    await ctx.host._emit(
        ctx.run,
        "workflow_interrupted" if interruption_reason else "workflow_cancelled",
        {
            "run_id": ctx.run.id,
            "current_node": current or (ctx.resumable_ids[0] if ctx.resumable_ids else ""),
            "pending_nodes": ctx.resumable_ids, "nodes_status": nodes_status, "config": config,
            "manual_resume_required": True,
            **(
                {"reason": interruption_reason, "resumable_nodes": ctx.resumable_ids}
                if interruption_reason
                else {}
            ),
        },
    )


async def handle_run_error(ctx: RunExecutionContext, e: Exception) -> None:
    error_summary = ctx.host._exception_summary(e)
    from .interruption_checkpoint import record_interruption
    record_interruption(ctx.run, ctx.node, error_summary, kind="error")
    ctx.run.status = "failed"
    current = next(
        (
            ctx.node
            for ctx.node in ctx.run.nodes
            if ctx.node.status == NodeStatus.RUNNING
        ),
        None,
    )
    if current is not None:
        current.status = NodeStatus.FAILED
        current.error = error_summary
        current.finished_at = time.time()
        ctx.run_state.set_status(current.id, "failed", error=error_summary)
    ctx.run_state.set_run_status("failed")
    ctx.run.finished_at = time.time()
    pending = ctx.run_state.resumable_phase_ids()
    current_id = current.id if current else (pending[0] if pending else "")
    nodes_status, config = save_resume_session(ctx, current_id)
    logger.error("Workflow execution failed", error=error_summary, run_id=ctx.run.id)
    import traceback

    logger.error("Traceback", tb=traceback.format_exc())
    await ctx.host._emit(
        ctx.run, "workflow_error", {"run_id": ctx.run.id, "error": error_summary,
                                   "current_node": current_id, "pending_nodes": pending,
                                   "nodes_status": nodes_status, "config": config,
                                   "manual_resume_required": True}
    )
