"""Coordinate one workflow node's authorized model session and deterministic traces."""

from __future__ import annotations

from typing import Any

from .models import WorkflowNode, WorkflowRun
from .node_execution_context import NodeExecutionContext
from .node_execution_invocation import run_primary_session
from .node_execution_completion import ensure_primary_output_delivery
from .node_execution_phases import (
    NodeExecutionComplete,
    apply_research_options,
    apply_runtime_options,
    append_project_contract,
    attach_observer,
    finalize_primary,
    configure_reviewer_session,
    open_primary_session,
    prepare_primary_message,
    prepare_skill,
    resolve_tools,
)
from .figure_asset_delegates import run_figure_asset_delegates


async def execute_node(
    host: Any,
    node: WorkflowNode,
    run: WorkflowRun,
    direction: str,
    effort: str,
    assurance: str,
    wandb: bool = False,
    compact: bool = False,
    gpu_target: str = "none",
    ssh_server_id: str = "",
    opts: dict[str, Any] | None = None,
    revision_context: str = "",
) -> str:
    context = NodeExecutionContext(
        host,
        node,
        run,
        direction,
        effort,
        assurance,
        wandb,
        compact,
        gpu_target,
        ssh_server_id,
        revision_context,
        opts=dict(opts or {}),
    )
    try:
        await prepare_skill(context)
        await apply_runtime_options(context)
        await apply_research_options(context)
        await append_project_contract(context)
        delegated = await run_figure_asset_delegates(context)
        if delegated:
            raise NodeExecutionComplete(delegated)
        await open_primary_session(context)
        await prepare_primary_message(context)
        await configure_reviewer_session(context)
        await attach_observer(context)
        await resolve_tools(context)
        context.result = await run_primary_session(context)
        await ensure_primary_output_delivery(context)
        await finalize_primary(context)
    except NodeExecutionComplete as completed:
        return completed.result
    return context.result
