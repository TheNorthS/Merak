"""Bind figure execution declarations and recheck the complete node gate.

Selecting a producer is not execution evidence. Runtime completion is recorded
only after artifact preparation and a real acceptance evaluation; a missing
runtime record must then be revalidated, never converted directly to success.
"""

from __future__ import annotations

from ..services.skill_orchestrator import resolve_execution_contract, skill_orchestrator
from .revision_loop_context import RevisionLoopContext


def refresh_figure_execution_contract(context: RevisionLoopContext) -> None:
    """Use the prepared canonical portfolio instead of a stale resumed skill plan."""
    if context.node.id != "figure" or context.preparation_error:
        return
    plan = skill_orchestrator.select(
        context.node.id, context.node.skill, context.run.project_path, context.opts,
    )
    skill_orchestrator.record(context.run.project_path, context.run.id, plan)
    context.execution_contract = resolve_execution_contract(
        context.node.id, context.opts, project_path=context.run.project_path,
    )
    context.gate_runtime_service = context.execution_contract.runtime_service
    context.node.execution_kind = plan.execution_kind
    context.node.runtime_service = plan.runtime_service
    context.node.policy_required = plan.policy_required


def revalidate_figure_after_runtime(context: RevisionLoopContext) -> None:
    """A newly recorded runtime operation requires a fresh full gate, not a waiver."""
    if (
        context.node.id != "figure" or context.preparation_error
        or not context.execution_gate_applied or not context.gate_runtime_service
        or context.consumer_refresh_upstream_gate is not None
        or context.gate.get("reason") != "declared node execution was not verified"
    ):
        return
    context.gate = context.host._acceptance_gate(
        context.node, context.run, context.assurance, context.result,
        require_fresh=context.require_fresh,
    )
