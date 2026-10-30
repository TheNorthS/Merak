"""Recheck draft integrity at delivery; completed phase flags cannot certify changed files."""

from pathlib import Path
from typing import Any

from .review_readiness import review_readiness_issues


def draft_review_issues(root: Path, state: dict[str, Any], *, run_id: str, mode: str) -> list[str]:
    from ..workflows.draft_delivery import DRAFT, draft_blockers
    from ..workflows.draft_review_evidence import draft_response_matches
    from ..workflows.review_visual_evidence import review_visual_evidence_gate

    issues, _ = review_readiness_issues(root, state, run_id=run_id,
        evidence_mode=mode, require_threshold=False)
    rounds = [item for item in state.get("rounds", []) if isinstance(item, dict)]
    final = rounds[-1] if rounds else {}
    try:
        blockers = draft_blockers(final.get("draft_blockers"))
    except ValueError:
        blockers = None
    if state.get("delivery_goal") != DRAFT or blockers is None or not draft_response_matches(root, final, review=True):
        issues.append("Current independent draft integrity response is missing or invalid")
    issues.extend(blockers or [])
    if (state.get("paper_reconciliation") or {}).get("passed") is not True:
        issues.append("Reviewed manuscript reconciliation did not pass")
    visual = review_visual_evidence_gate(str(root), state, rounds)
    if not visual.get("verified"):
        issues.extend(visual.get("issues") or ["Native visual review is invalid"])
    return list(dict.fromkeys(issues))


def draft_delivery_integrity(root: Path, state: dict[str, Any], context: dict[str, Any],
    attestations: dict[str, Any], simulation: dict[str, Any], review_state: dict[str, Any]) -> dict[str, Any]:
    from ..workflows.draft_delivery import draft_audit_findings
    from ..workflows.review_audit import validate_audit_bundle
    from .node_risk_audit import node_risk_audit_service
    from .risk_stage_ppt import audit as audit_slides

    issues = [f"Current {name} artifact validation failed" for name in ("figures", "paper")
        if attestations.get(name, {}).get("valid") is not True]
    if simulation.get("valid") is not True:
        issues.append("Current simulation package failed source validation")
    run_id, mode = str(state.get("run_id") or ""), context["evidence_mode"]
    issues.extend(draft_review_issues(root, review_state, run_id=run_id, mode=mode))
    bundle = validate_audit_bundle(root, run_id=run_id, evidence_mode=mode,
        executor_model=str(review_state.get("executor_model") or ""))
    if bundle.get("valid") is not True:
        issues.extend(bundle.get("issues") or ["Current audit source binding is invalid"])
    else:
        issues.extend(draft_audit_findings(root, bundle))
    issues.extend(str(item.get("message") or item.get("id") or "Slide validation failed")
        for item in audit_slides(node_risk_audit_service, root, context["options"])
        if item.get("severity") == "blocker")
    return {"applicable": True, "valid": not issues, "issues": list(dict.fromkeys(issues))}
