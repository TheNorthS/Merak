"""Runtime-owned paper refresh is separate from bounded semantic authoring.

Scientific hashes, contracts and generated projections cannot be write targets
of a model session. Current upstream prerequisites must pass before the normal
preparation producer may establish a new draft/freeze identity.
"""

from __future__ import annotations

from typing import Any

from ..services.paper_preparation_errors import guard_paper_preparation, prepare_paper_evidence
from .models import WorkflowNode, WorkflowRun


PAPER_RUNTIME_TARGETS = frozenset({
    "paper/scientific_freeze.json", "paper/draft_state.json", "paper/section_contracts.json",
    "paper/section_reviews.json", "paper/authoring_asset_manifest.json",
    "paper/tables/table_manifest.json", "paper/paper_style_profile.json", "paper/paper_profile.json",
    "paper/tables/synthetic_preview_results.tex",
})
STALE_PAPER_MESSAGES = (
    "scientific inputs changed after paper freeze", "staged paper state is stale relative to scientific inputs",
    "authoritative paper-input hashes changed after the manuscript scientific freeze",
    "staged paper state is bound to a different scientific freeze",
)


def paper_refresh_required(diagnostics: dict[str, Any]) -> bool:
    findings = diagnostics.get("findings") or []
    return any(str(item.get("id") or "") == "PAPER-STALE-001"
               for item in findings if isinstance(item, dict)) or any(
        marker in " ".join(str(item) for item in diagnostics.get("issues") or []).casefold()
        for marker in STALE_PAPER_MESSAGES
    )


def remaining_paper_findings(diagnostics: dict[str, Any]) -> dict[str, Any]:
    """Only a freshly verified runtime refresh resolves its prior identity findings."""
    runtime_findings = {"PAPER-STALE-001"}
    resolved_messages = {str(item.get("message") or "") for item in diagnostics.get("findings") or []
                         if isinstance(item, dict) and (str(item.get("id") or "") in runtime_findings
                                                       or item.get("runtime_operation") == "refresh_paper_runtime_inputs")}
    findings = [item for item in diagnostics.get("findings") or [] if not (
        isinstance(item, dict) and (str(item.get("id") or "") in runtime_findings
                                  or item.get("runtime_operation") == "refresh_paper_runtime_inputs")
    )]
    issues = [item for item in diagnostics.get("issues") or [] if str(item) not in resolved_messages
              if not any(marker in str(item).casefold() for marker in STALE_PAPER_MESSAGES)]
    return {**diagnostics, "findings": findings, "issues": issues}


async def refresh_paper_runtime_inputs(
    host: Any, node: WorkflowNode, run: WorkflowRun, direction: str, options: dict[str, Any],
) -> dict[str, Any]:
    """Rebuild through the real producer only after fresh upstream validation.

    This operation neither grants acceptance nor edits research decisions. The
    draft service preserves/archive-binds prior sections under its normal source
    change contract; model work remains scoped to the affected author outputs.
    """
    from ..services.node_risk_audit import node_risk_audit_service
    from ..services.paper_drafting import paper_drafting_service

    findings = [*node_risk_audit_service.preflight_node(run.project_path, "paper", options),
                *node_risk_audit_service.protected_upstream_findings(run.project_path, "paper", options)]
    blockers = [item for item in findings if item.get("severity") == "blocker"
                and str(item.get("upstream_node") or "") not in {"", "paper"}]
    if blockers:
        return {"passed": False, "findings": blockers,
                "issues": [str(item.get("plain_message") or item.get("message") or "") for item in blockers]}
    before = paper_drafting_service.validate_scientific_freeze(run.project_path, options)
    from .paper_method_presentation import refresh_method_presentation
    await refresh_method_presentation(run)
    prepare_paper_evidence(run.project_path, direction)
    state = guard_paper_preparation(
        "draft_contracts", lambda: paper_drafting_service.prepare(run.project_path, options),
    )
    after = paper_drafting_service.validate_scientific_freeze(run.project_path, options)
    await host._emit(run, "paper_runtime_inputs_refreshed", {
        "node_id": node.id, "changed_inputs": before.get("changed_inputs") or [],
        "passed": bool(after.get("passed")), "freeze_id": state.get("scientific_freeze_id") or "",
        "model_invoked": False,
    })
    return {"passed": bool(after.get("passed")), "issues": list(after.get("issues") or []),
            "changed_inputs": before.get("changed_inputs") or []}
