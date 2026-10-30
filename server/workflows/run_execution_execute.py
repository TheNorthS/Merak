"""Coordinate node revision, durable acceptance, and acceptance notifications.

Executor completion is not acceptance. Only a fresh passing gate permits the
durable accepted transition; bounded repair stops retain resumable state."""

from __future__ import annotations

import time

from .engine_context import logger
from .models import NodeStatus
from .run_execution_context import (
    CompleteRun,
    RestartRun,
    RunExecutionContext,
    StopRunNodes,
    save_resume_session,
)


async def run_acceptance_loop(ctx: RunExecutionContext) -> None:
    from .interruption_checkpoint import mark_boundary
    if ((not ctx.revalidate_done or ctx.resume_stage == "specialists")
            and not ctx.upstream_preflight and ctx.resume_stage != "acceptance"):
        mark_boundary(ctx.run, ctx.node, "specialists", result=str(ctx.result or ""))
        await ctx.host._execute_profile_specialists(
            node=ctx.node, run=ctx.run, direction=ctx.research_direction, opts=ctx.opts
        )
    mark_boundary(ctx.run, ctx.node, "acceptance", result=str(ctx.result or ""))
    ctx.gate, ctx.result = await ctx.host._run_node_revision_loop(
        node=ctx.node,
        run=ctx.run,
        initial_result=ctx.result,
        research_direction=ctx.research_direction,
        effort=ctx.effort,
        assurance=ctx.assurance,
        opts=ctx.opts,
        require_fresh=not ctx.revalidate_done,
        checkpoint_timeout=ctx.checkpoint_timeout,
        max_revision_rounds=ctx.max_revision_rounds,
    )
    if ctx.run.status == "cancelled":
        raise CompleteRun()
    if ctx.gate.get("restart_required"):
        ctx.host._mark_run_running(ctx.run)
        save_resume_session(ctx, str(ctx.gate.get("restart_from_node") or ctx.node.id))
        raise RestartRun()
    if ctx.gate.get("waiting"):
        ctx.node.status = NodeStatus.IDLE
        ctx.node.error = None
        raise StopRunNodes()



async def persist_node_acceptance(ctx: RunExecutionContext) -> None:
    if ctx.node.id == "compile" and ctx.opts.get("enable_overleaf_sync"):
        await ctx.host._finish_overleaf_compile(ctx.run, ctx.opts)
    ctx.node.output = ctx.result
    ctx.node.status = NodeStatus.COMPLETED
    ctx.node.error = None
    ctx.persisted_phase = (ctx.run_state.load() or {}).get("phases", {}).get(
        ctx.node.id
    ) or {}
    if str(ctx.persisted_phase.get("status") or "") != "done":
        ctx.run_state.set_status(
            ctx.node.id,
            "done",
            artifact=ctx.host._primary_artifact_for_node(
                ctx.run.project_path, ctx.node.id
            ),
            details={"summary": ctx.result[:500]},
        )


async def refresh_node_audits(ctx: RunExecutionContext) -> None:
    from .acceptance_manifest import acceptance_details, deliver_acceptance_manifests
    ctx.run_state.accept(
        ctx.node.id,
        ctx.gate["verdict_id"],
        ctx.gate["reviewer"],
        acceptance_details(ctx.gate, ctx.node.id),
    )
    def clear_checkpoint(state: dict) -> None:
        details = state.get("phases", {}).get(ctx.node.id, {}).get("details", {})
        details.pop("interruption", None)
        details.pop("execution_checkpoint", None)
    ctx.run_state.update_state(clear_checkpoint)
    delivery_failures = deliver_acceptance_manifests(ctx.host, ctx.run)
    if delivery_failures:
        await ctx.host._emit(ctx.run, "acceptance_manifest_pending", {"node_id": ctx.node.id, "deliveries": delivery_failures})
    try:
        from ..services.research_workflow_contract import (
            research_workflow_contract_service,
        )

        research_workflow_contract_service.prepare(
            ctx.run.project_path, ctx.research_direction, ctx.opts
        )
    except Exception as exc:
        logger.warning(
            "Research workflow contract refresh failed",
            node=ctx.node.id,
            error=str(exc),
        )
    try:
        from ..services.node_risk_audit import node_risk_audit_service

        risk_snapshot = node_risk_audit_service.audit_workflow(
            ctx.run.project_path,
            ctx.run.options,
            through_node=ctx.node.id,
            persist=True,
        )
        risk_delta = ctx.host._new_workflow_risk_findings(
            ctx.run, risk_snapshot, ctx.node.id
        )
        if risk_delta["new_findings"] or risk_delta["latent_blockers"]:
            await ctx.host._emit(
                ctx.run,
                "workflow_risk_snapshot",
                {
                    "node_id": ctx.node.id,
                    "status": risk_snapshot.get("status", "clear"),
                    "counts": risk_snapshot.get("counts", {}),
                    "new_findings": risk_delta["new_findings"][:12],
                    "latent_blockers": risk_delta["latent_blockers"][:8],
                    "report_path": risk_snapshot.get("report_path", ""),
                },
            )
    except Exception as exc:
        logger.warning(
            "Workflow risk snapshot could not be persisted",
            node=ctx.node.id,
            error=str(exc),
        )


async def emit_node_acceptance(ctx: RunExecutionContext) -> None:
    for warning in ctx.gate.get("warnings", []):
        if not isinstance(warning, dict):
            continue
        await ctx.host._emit(
            ctx.run, "node_quality_advisory", {"node_id": ctx.node.id, **warning}
        )
    await ctx.host._emit(
        ctx.run,
        "node_accepted",
        {
            "node_id": ctx.node.id,
            "verdict_id": ctx.gate["verdict_id"],
            "reviewer": ctx.gate["reviewer"],
            "revision_round": ctx.gate.get("revision_round", 0),
        },
    )


async def handle_node_error(ctx: RunExecutionContext, e: Exception) -> None:
    from ..services.paper_preparation_errors import PaperPreparationError
    from .paper_preparation_checkpoint import persist_paper_preparation_checkpoint
    from .interruption_checkpoint import record_interruption

    record_interruption(ctx.run, ctx.node, ctx.host._exception_summary(e), kind="error")

    if ctx.node.id == "paper" and isinstance(e, PaperPreparationError):
        await persist_paper_preparation_checkpoint(ctx, e)
        raise StopRunNodes()
    error_summary = ctx.host._exception_summary(e)
    if ctx.host._is_transport_research_error(e):
        await ctx.host._persist_model_transport_checkpoint(
            node=ctx.node,
            run=ctx.run,
            error=e,
            opts=ctx.opts,
            max_revision_rounds=ctx.max_revision_rounds,
        )
        logger.warning(
            "Workflow node paused after model transport exhaustion",
            node=ctx.node.id,
            error=error_summary,
        )
        raise StopRunNodes()
    ctx.node.status = NodeStatus.FAILED
    ctx.node.error = error_summary
    ctx.node.finished_at = time.time()
    ctx.run_state.set_status(ctx.node.id, "failed", error=error_summary)
    await ctx.host._emit(
        ctx.run, "node_failed", {"node_id": ctx.node.id, "error": error_summary}
    )
    logger.error("Workflow node failed", node=ctx.node.id, error=error_summary)
    raise StopRunNodes()
