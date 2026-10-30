"""Initialize durable execution state and resolve the run's research inputs.

Startup prepares the current attempt; it cannot promote unvalidated artifacts
or infer permission to execute a scientific experiment."""

from __future__ import annotations

import asyncio

from ..services.project_memory import project_memory
from .engine_context import DEFAULT_HUMAN_CHECKPOINT_NODES, logger, normalize_revision_rounds
from .run_execution_context import (
    CompleteRun,
    RunExecutionContext,
)
from .run_state import RunState
from .session_state import SessionState


async def startup_wait(ctx: RunExecutionContext) -> None:
    logger.info(
        "Workflow _execute_run started", run_id=ctx.run.id, project=ctx.run.project_path
    )
    try:
        await asyncio.sleep(1.5)
    except asyncio.CancelledError:
        status = "cancelled" if ctx.run.status == "cancelled" else "incomplete"
        ctx.run.status = status
        RunState(ctx.run.project_path, ctx.run.id).set_run_status(status)
        logger.warning(
            "Workflow startup wait cancelled", run_id=ctx.run.id, status=status
        )
        raise CompleteRun()


async def initialize_run(ctx: RunExecutionContext) -> None:
    ctx.opts = dict(ctx.opts or {})
    ctx.run.options = dict(ctx.opts)
    ctx.session_state = SessionState(ctx.run.project_path)
    ctx.run_state = RunState(ctx.run.project_path, ctx.run.id)
    from .notification_readiness import notification_ready
    from ..services.notification import notification_service
    await notification_ready(ctx, notification_service)
    try:
        from ..services.research_specialists import research_specialist_service

        specialist_plan = research_specialist_service.load(
            ctx.run.project_path, ctx.run.id
        )
        if specialist_plan:
            await ctx.host._emit(
                ctx.run,
                "specialist_plan_ready",
                {
                    "run_id": ctx.run.id,
                    "profile": specialist_plan.get("profile", {}),
                    "subnodes": specialist_plan.get("subnodes", []),
                    "plan_path": str(
                        research_specialist_service.plan_path(
                            ctx.run.project_path, ctx.run.id
                        )
                    ),
                },
            )
    except Exception as exc:
        logger.warning("Research specialist plan event failed", error=str(exc))
    ctx.auto_proceed = ctx.opts.get("auto_proceed", True)
    ctx.human_checkpoint = ctx.opts.get("human_checkpoint", False)
    ctx.checkpoint_timeout = max(
        30, min(7200, int(ctx.opts.get("checkpoint_timeout_seconds", 300) or 300))
    )
    ctx.max_revision_rounds = normalize_revision_rounds(
        ctx.opts.get("max_revision_rounds")
    )
    if not ctx.auto_proceed:
        ctx.human_checkpoint = True
    ctx.raw_checkpoint_nodes = ctx.opts.get("human_checkpoint_nodes")
    if isinstance(ctx.raw_checkpoint_nodes, list):
        ctx.human_checkpoint_nodes = {
            str(item) for item in ctx.raw_checkpoint_nodes if str(item).strip()
        }
    else:
        ctx.human_checkpoint_nodes = set(DEFAULT_HUMAN_CHECKPOINT_NODES)
    if ctx.opts.get("run_experiment") is not True:
        ctx.human_checkpoint_nodes.discard("exp-run")
    ctx.code_review_enabled = ctx.opts.get("code_review", True)
    ctx.wandb_enabled = ctx.opts.get("wandb", False)
    ctx.compact_mode = ctx.opts.get("compact", False)


async def prepare_direction(ctx: RunExecutionContext) -> None:
    if ctx.research_direction:
        try:
            project_memory.set_research_direction(
                ctx.run.project_path, ctx.research_direction
            )
        except Exception as e:
            logger.warning("Failed to save research direction", error=str(e))
    logger.info(
        "Workflow starting node loop",
        nodes=len(ctx.run.nodes),
        project=ctx.run.project_path,
    )
