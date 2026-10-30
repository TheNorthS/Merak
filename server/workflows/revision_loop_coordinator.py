"""Coordinate a bounded generate-diagnose-repair-revalidate state machine."""

from __future__ import annotations

from typing import Any

from .models import WorkflowNode, WorkflowRun
from .revision_attempt import run_revision_attempt
from .revision_loop_context import (
    RevisionComplete,
    RevisionContinue,
    RevisionLoopContext,
)
from .revision_loop_phases import (
    collect_upstream_blockers,
    hold_refresh_for_upstream,
    initialize_progress,
    initialize_revision,
    load_consumer_refresh,
    persist_consumer_refresh,
    prepare_consumer_state,
    prepare_scientific_stage,
    restore_progress,
)
from .revision_gate_phases import (
    advance_revision_round,
    apply_execution_error,
    build_current_gate,
    classify_guided_revision,
    classify_managed_stop,
    classify_stop_policy,
    complete_accepted_gate,
    emit_revision_stop,
    finalize_revision,
    measure_revision_change,
    normalize_gate_outcome,
    persist_gate_inputs,
    prepare_revision_stop,
    record_no_progress_stop,
    record_progress,
    record_runtime_gate,
    select_revision_owner,
    start_revision,
    verify_runtime_execution,
)


async def run_node_revision_loop(
    host: Any,
    *,
    node: WorkflowNode,
    run: WorkflowRun,
    initial_result: str,
    research_direction: str,
    effort: str,
    assurance: str,
    opts: dict[str, Any],
    require_fresh: bool,
    checkpoint_timeout: int,
    max_revision_rounds: int,
) -> tuple[dict[str, Any], str]:
    context = RevisionLoopContext(
        host=host,
        node=node,
        run=run,
        assurance=assurance,
        research_direction=research_direction,
        effort=effort,
        opts=opts,
        max_revision_rounds=max_revision_rounds,
        checkpoint_timeout=checkpoint_timeout,
        initial_result=initial_result,
        require_fresh=require_fresh,
        no_progress_limit=2,
    )
    try:
        await initialize_revision(context)
        await initialize_progress(context)
        await restore_progress(context)
        from .report_revision_coordinator import resume_report_revision, handle_report_revision
        await resume_report_revision(context)
        while True:
            try:
                await prepare_consumer_state(context)
                await load_consumer_refresh(context)
                await persist_consumer_refresh(context)
                await collect_upstream_blockers(context)
                await hold_refresh_for_upstream(context)
                await prepare_scientific_stage(context)
                await persist_gate_inputs(context)
                await measure_revision_change(context)
                await build_current_gate(context)
                await record_runtime_gate(context)
                await verify_runtime_execution(context)
                await normalize_gate_outcome(context)
                await complete_accepted_gate(context)
                await handle_report_revision(context)
                await apply_execution_error(context)
                await select_revision_owner(context)
                await record_progress(context)
                await classify_stop_policy(context)
                await classify_managed_stop(context)
                await record_no_progress_stop(context)
                await prepare_revision_stop(context)
                await emit_revision_stop(context)
                await classify_guided_revision(context)
                await advance_revision_round(context)
                await start_revision(context)
                await run_revision_attempt(context)
                await finalize_revision(context)
            except RevisionContinue:
                continue
    except RevisionComplete as completed:
        return completed.gate_and_result
