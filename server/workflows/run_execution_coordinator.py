"""Coordinate workflow execution without embedding node or gate policies."""

from __future__ import annotations

from typing import Any
from ..contracts.preparation import PreparationContractError

from .models import WorkflowRun
from .run_execution_context import (
    CompleteRun,
    RestartRun,
    RunExecutionContext,
    SkipRunNode,
    StopRunNodes,
)
from .run_execution_execute import (
    emit_node_acceptance,
    handle_node_error,
    persist_node_acceptance,
    refresh_node_audits,
    run_acceptance_loop,
)
from .run_execution_final import (
    classify_run,
    handle_run_cancelled,
    handle_run_error,
    record_run_memory,
)
from .run_execution_node import (
    initialize_preflight,
    load_node_preflight,
    prepare_node,
    prepare_node_inputs,
    consume_checkpoint,
    load_resume_state,
    prepare_revalidation,
    run_code_review,
    run_primary_execution,
)
from .run_execution_startup import initialize_run, prepare_direction, startup_wait


async def _execute_one_node(context: RunExecutionContext) -> None:
    from .interruption_checkpoint import mark_boundary
    from ..agent.skill_resume import workflow_scope
    token = workflow_scope.set((context.run.id, context.node.id))
    try:
        from .report_revision_recovery import active_report_consumer
        if active_report_consumer(context.run_state.load() or {}) == context.node.id:
            context.result, context.upstream_preflight = "Resume targeted report repair", []
            context.revalidate_done, context.resume_stage = True, "acceptance"
            await run_acceptance_loop(context)
            raise RuntimeError("Report recovery ended without a verification or waiting boundary")
        await prepare_node(context)
        await load_resume_state(context)
        await consume_checkpoint(context)
        await prepare_revalidation(context)
        await initialize_preflight(context)
        await load_node_preflight(context)
        try:
            if not context.resume_stage:
                mark_boundary(context.run, context.node, "preparation")
            await prepare_node_inputs(context)
            await run_code_review(context)
            if context.resume_stage not in {"specialists", "acceptance"}:
                mark_boundary(context.run, context.node, "primary")
            await run_primary_execution(context)
        except PreparationContractError as error:
            # Enter the existing bounded owner repair loop even before the
            # consumer has produced an artifact. Revalidate the source each lap.
            context.result = str(error)
            context.upstream_preflight = [error.finding()]
            await context.host._emit(context.run, "node_preparation_deferred", {
                "node_id": context.node.id, **error.details(),
            })
        await run_acceptance_loop(context)
        await persist_node_acceptance(context)
        await refresh_node_audits(context)
        await emit_node_acceptance(context)
    except SkipRunNode:
        return
    except (StopRunNodes, RestartRun, CompleteRun):
        raise
    except Exception as error:
        await handle_node_error(context, error)
    finally:
        workflow_scope.reset(token)


async def _execute_nodes(context: RunExecutionContext) -> None:
    for node in context.run.nodes:
        context.node = node
        try:
            await _execute_one_node(context)
        except StopRunNodes:
            return


async def _execute_attempt(context: RunExecutionContext) -> None:
    try:
        await prepare_direction(context)
        await _execute_nodes(context)
        await classify_run(context)
        await record_run_memory(context)
    except (RestartRun, CompleteRun):
        raise
    except BaseException as error:
        import asyncio

        if isinstance(error, asyncio.CancelledError):
            await handle_run_cancelled(context)
            return
        if isinstance(error, Exception):
            await handle_run_error(context, error)
            return
        raise


async def execute_run(
    host: Any,
    run: WorkflowRun,
    research_direction: str,
    effort: str = "balanced",
    assurance: str = "draft",
    opts: dict[str, Any] | None = None,
) -> None:
    context = RunExecutionContext(
        host,
        run,
        research_direction,
        effort,
        assurance,
        dict(opts or {}),
    )
    try:
        await startup_wait(context)
        await initialize_run(context)
        while True:
            try:
                await _execute_attempt(context)
            except RestartRun:
                continue
            break
    except CompleteRun:
        return
