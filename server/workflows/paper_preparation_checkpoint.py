"""Stop before manuscript authoring on deterministic preparation defects.

The checkpoint preserves upstream acceptance and section outputs. An unchanged
producer defect cannot spend a model revision budget or advance later nodes.
"""

from __future__ import annotations

import time

from ..services.paper_preparation_errors import PaperPreparationError
from .models import NodeStatus
from .run_execution_context import RunExecutionContext


async def persist_paper_preparation_checkpoint(
    context: RunExecutionContext, error: PaperPreparationError,
) -> None:
    node, run, state = context.node, context.run, context.run_state
    diagnostics = {"accepted": False, "reason": "deterministic paper preparation failed",
                   "summary": str(error), "stopped_for_deterministic_stage": True,
                   "intervention_kind": "platform_repair", "requires_human_decision": False,
                   **error.gate_details()}
    revision = state.revision_state(node.id)
    round_number, cycle = int(revision.get("round") or 0), max(1, int(revision.get("cycle") or 1))
    state.record_revision_gate(node.id, round_number=round_number, cycle=cycle,
                               gate=diagnostics, owner_id=node.id)
    state.set_revision_waiting(
        node.id, round_number=round_number, cycle=cycle, gate=diagnostics,
        artifact_signature=context.host._revision_artifact_signature(run.project_path, node.id, context.opts),
        artifact_owner_id=node.id,
        runtime_signature=context.host._revision_runtime_signature(run.project_path, node.id, context.opts),
    )
    state.update_state(lambda latest: latest["phases"][node.id]["details"].update(
        {"preparation_failure": diagnostics}
    ))
    node.status, node.error, node.finished_at = NodeStatus.IDLE, None, time.time()
    context.result = str(error)
    for event in ("paper_preparation_failed", "node_platform_repair_required", "node_revision_waiting"):
        await context.host._emit(run, event, {"node_id": node.id, "name": node.name,
                                            "round": round_number, "cycle": cycle, **diagnostics})
