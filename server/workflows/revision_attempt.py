"""Execute one revision attempt and preserve upstream and transport ownership."""

from __future__ import annotations

import time
from typing import Any

from .models import NodeStatus
from .revision_loop_context import (
    RevisionComplete,
    RevisionContinue,
    RevisionLoopContext,
)
from .run_state import RunState


async def _revalidate_owner(
    context: RevisionLoopContext, revised: str, current: str
) -> None:
    owner, run = (context.revision_owner, context.run)
    from .owner_revision_transaction import update_owner_boundary
    update_owner_boundary(context.run_state, owner, "acceptance")
    result = await context.host._prepare_node_for_gate(
        owner, run, revised, context.research_direction, context.assurance, context.opts
    )
    changed = bool(context.host._changed_nonempty_node_artifacts(owner, run))
    state = RunState(run.project_path, run.id)
    state.set_status(
        owner.id,
        "done",
        artifact=context.host._primary_artifact_for_node(run.project_path, owner.id),
        details={"summary": result[:500]},
    )
    gate = context.host._acceptance_gate(
        owner, run, context.assurance, result, require_fresh=False
    )
    if gate.get("accepted"):
        state.accept(
            owner.id,
            str(gate["verdict_id"]),
            str(gate["reviewer"]),
            gate.get("details", {}),
        )
        owner.status = NodeStatus.COMPLETED
    await context.host._emit(
        run,
        "upstream_owner_revalidated",
        {
            "node_id": context.node.id,
            "owner_node_id": owner.id,
            "accepted": bool(gate.get("accepted")),
            "summary": str(gate.get("summary") or gate.get("reason") or ""),
        },
    )
    if not gate.get("accepted"):
        await _stop_on_invalid_owner(context, state, gate)
    def clear_repair(saved: dict) -> None:
        saved.pop("active_owner_revision", None)
    state.update_state(clear_repair)
    await _accepted_owner_followup(context, state, changed, current)


async def _accepted_owner_followup(
    context: RevisionLoopContext, state: RunState, changed: bool, current: str
) -> None:
    context.result = current
    stale = any(
        (
            marker
            in " ".join(
                (str(item) for item in context.diagnostics.get("issues") or [])
            ).casefold()
            for marker in (
                "scientific inputs changed after paper freeze",
                "staged paper state is stale relative to scientific inputs",
                "staged paper state is bound to a different scientific freeze",
            )
        )
    )
    if changed or stale:
        from .reconciliation_budget import request_owner_rebuild
        restart = await request_owner_rebuild(context, state)
        if restart:
            raise RevisionComplete(
                (
                    {
                        "accepted": False,
                        "restart_required": True,
                        "restart_from_node": restart,
                        "revision_owner_id": context.revision_owner.id,
                        "reason": "upstream scientific repair requires downstream rebuild",
                    },
                    context.result,
                )
            )
    findings = [
        item
        for item in context.diagnostics.get("findings", [])
        if isinstance(item, dict)
    ]
    layout_only = (
        (bool(findings) and all(
            str(item.get("category") or "").casefold() == "visual_layout"
            for item in findings
        ))
        or "layout" in str(context.diagnostics.get("reason") or "").casefold()
    )
    if context.node.id in {"review", "audit"} and not layout_only:
        await _require_consumer_refresh(context, state)


async def _stop_on_invalid_owner(
    context: RevisionLoopContext,
    state: RunState,
    gate: dict[str, Any],
) -> None:
    owner = context.revision_owner
    summary = str(
        gate.get("summary") or gate.get("reason") or "upstream owner remains invalid"
    )
    diagnostics = context.host._revision_diagnostics_for_owner(
        context.host._gate_revision_diagnostics(gate),
        owner.id,
        owner.id,
    )
    state.set_status(owner.id, "pending", error=summary[:2000])
    waiting = {
        **diagnostics,
        "reason": "upstream owner revalidation failed",
        "summary": summary,
        "intervention_kind": "platform_repair",
        "requires_human_decision": False,
    }
    state.set_revision_waiting(
        context.node.id,
        round_number=context.round_number,
        cycle=context.cycle,
        gate=waiting,
        artifact_signature=context.host._revision_artifact_signature(
            context.run.project_path,
            owner.id,
            context.opts,
        ),
        artifact_owner_id=owner.id,
        runtime_signature=context.host._revision_runtime_signature(
            context.run.project_path,
            owner.id,
            context.opts,
        ),
        owner_rounds=context.owner_rounds,
    )
    await context.host._emit(
        context.run,
        "node_platform_repair_required",
        {
            "node_id": context.node.id,
            "name": context.node.name,
            "owner_node_id": owner.id,
            "round": context.round_number,
            "cycle": context.cycle,
            "reason": "upstream owner revalidation failed",
            "summary": summary,
            "issues": list(diagnostics.get("issues") or [])[:8],
            "component_statuses": diagnostics.get("component_statuses", {}),
        },
    )
    raise RevisionComplete(
        (
            {
                **gate,
                "accepted": False,
                "waiting": True,
                "revision_owner_id": owner.id,
                "reason": "upstream owner revalidation failed",
                "summary": summary,
            },
            context.result,
        )
    )


async def _require_consumer_refresh(
    context: RevisionLoopContext, state: RunState
) -> None:
    reason = str(
        context.diagnostics.get("summary")
        or context.diagnostics.get("reason")
        or "upstream owner accepted after managed consumer verdict"
    )
    state.require_consumer_refresh(
        context.node.id,
        owner_id=context.revision_owner.id,
        reason=reason,
    )
    context.consumer_refresh_required = True
    context.saved_revision["consumer_refresh_owner_id"] = context.revision_owner.id
    await context.host._emit(
        context.run,
        "consumer_snapshot_refresh_required",
        {
            "node_id": context.node.id,
            "upstream_owner_id": context.revision_owner.id,
            "reason": reason[:1000],
        },
    )


async def _apply_revision(context: RevisionLoopContext) -> None:
    current = context.result
    context.revision_owner.started_at = time.time()
    revised = await context.host._revise_node_from_gate(
        node=context.revision_owner,
        run=context.run,
        diagnostics=context.diagnostics,
        round_number=context.round_number,
        cycle=context.cycle,
        user_feedback=context.pending_feedback,
        research_direction=context.research_direction,
        effort=context.effort,
        assurance=context.assurance,
        opts=context.opts,
    )
    if context.revision_owner.id != context.node.id:
        await _revalidate_owner(context, revised, current)
    else:
        context.result = revised
    context.pending_feedback = ""
    context.transport_failures = 0
    context.last_execution_error = None
    context.last_revision_method = f"agent:{context.revision_owner.id}"
    context.last_revision_execution_succeeded = True








async def run_revision_attempt(context: RevisionLoopContext) -> None:
    """Execution failures propagate to the durable manual interruption boundary."""
    await _apply_revision(context)
