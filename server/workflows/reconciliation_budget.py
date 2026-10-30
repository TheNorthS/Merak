"""Stop stale-consumer work when a bounded upstream rebuild cannot be scheduled."""

from typing import Any

from .revision_loop_context import RevisionComplete


class ReconciliationBudgetExhausted(RuntimeError):
    """A repaired owner remains valid, but its consumers require a later rebuild."""


async def request_owner_rebuild(context: Any, state: Any) -> str:
    """Persist the waiting boundary without expanding limits or refreshing consumers."""
    owner = context.revision_owner.id
    try:
        return await context.host._prepare_research_loop_restart(
            run=context.run, run_state=state, owner_id=owner,
            reason=str(context.diagnostics.get("summary") or context.diagnostics.get("reason")
                       or "upstream scientific artifact changed"),
            opts=context.opts, consumer_id=context.node.id,
        )
    except ReconciliationBudgetExhausted as error:
        gate = {"accepted": False, "waiting": True, "hard_limit": True,
            "reason": "upstream rebuild budget exhausted", "summary": str(error),
            "revision_owner_id": owner, "requires_human_decision": True,
            "issues": [str(error)]}
        state.set_revision_waiting(context.node.id, round_number=context.round_number,
            cycle=context.cycle, gate=gate, artifact_owner_id=owner,
            artifact_signature=context.host._revision_artifact_signature(context.run.project_path, owner, context.opts),
            runtime_signature=context.host._revision_runtime_signature(context.run.project_path, owner, context.opts),
            owner_rounds=context.owner_rounds)
        await context.host._emit(context.run, "node_revision_waiting", {
            "node_id": context.node.id, "owner_node_id": owner, **gate})
        raise RevisionComplete((gate, context.result)) from error
