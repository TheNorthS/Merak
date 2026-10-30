"""Public acceptance coordinator over deterministic prerequisites and node gates."""

from __future__ import annotations

from typing import Any

from .acceptance_context import (
    AcceptanceGateHost,
    artifact_failure,
    build_context,
    prerequisite_failure,
    specialist_failure,
)
from .acceptance_node_gates import (
    generic_artifact_gate,
    method_alignment_gate,
    node_specific_gate,
    novelty_contract_gate,
)
from .acceptance_pipeline import finalize_gate
from .models import WorkflowNode, WorkflowRun


def acceptance_gate(
    host: AcceptanceGateHost,
    node: WorkflowNode,
    run: WorkflowRun,
    assurance: str,
    result: str,
    require_fresh: bool = True,
) -> dict[str, Any]:
    context = build_context(host, node, run, assurance, result, require_fresh)
    failure = prerequisite_failure(context)
    if failure is not None:
        # A blocked stage is a failed prerequisite, not a partially accepted
        # design. Downstream risk/preview/provenance checks run after its owner
        # is valid; otherwise expected missing outputs can hide the real cause.
        return failure
    failure = artifact_failure(context)
    if failure is not None:
        return finalize_gate(context, failure)
    failure = specialist_failure(context)
    if failure is not None:
        return finalize_gate(context, failure)
    gate = node_specific_gate(context)
    if gate is None:
        gate = generic_artifact_gate(context)
    gate = finalize_gate(context, gate)
    gate = method_alignment_gate(context, gate)
    if node.id == "exp-design" and not gate.get("accepted"):
        gate = finalize_gate(context, gate)
    gate = novelty_contract_gate(context, gate)
    return gate
