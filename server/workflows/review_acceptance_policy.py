"""Accept durable review evidence through explicit, bounded decision policies."""

from __future__ import annotations

from typing import Any

from ..services.simulation_policy import is_complete_evidence_mode
from .review_audit import BOUNDED_REVIEW_FALLBACK_EVIDENCE_MODES
from .review_acceptance_facts import (
    ReviewAcceptanceContext,
    ReviewAcceptanceHost,
    ReviewOutcome,
    load_acceptance_context,
    persist_derived_outcome,
    review_outcome,
)
from .review_acceptance_findings import review_gate_details


def _missing_rounds(
    host: ReviewAcceptanceHost, context: ReviewAcceptanceContext
) -> dict[str, Any]:
    messages = [
        context.state_error
        or "Persist at least one structured review round with weaknesses and action items.",
        *(
            str(item.get("message") or "")
            for item in context.layout_findings
            if str(item.get("message") or "").strip()
        ),
    ]
    return {
        "accepted": False,
        "reason": "structured review state is missing or has no rounds",
        "summary": "review-stage/REVIEW_STATE.json must contain reviewer findings and actions; a score printed in model output is not review evidence",
        "details": {
            "path": str(context.state_path),
            "managed_review": context.state.get("managed_by")
            == "cross_model_review_loop",
            "issues": list(dict.fromkeys(messages)),
            "review_findings": context.layout_findings,
            "target_files": host._revision_target_files(
                [item.get("target_files") for item in context.layout_findings]
            ),
            "deterministic_layout_findings": context.layout_findings,
        },
    }


def _accept(
    host: ReviewAcceptanceHost,
    context: ReviewAcceptanceContext,
    outcome: ReviewOutcome,
    details: dict[str, Any],
    *,
    advisory: bool = False,
) -> dict[str, Any]:
    artifacts = [
        path for path in (context.state_path, context.paper_path) if path.exists()
    ]
    if advisory:
        details = {**details, "advisory": True, "publication_ready": False}
        reviewer = "cross-model:bounded-advisory"
        summary = (
            f"Bounded review completed without reaching the score threshold. The {details['evidence_mode']} "
            f"workflow may continue with score={outcome.score}, verdict={outcome.verdict or 'unknown'}, "
            "publication_ready=false; unresolved findings remain visible for the downstream audit and researcher."
        )
    else:
        reviewer = context.reviewer
        summary = (
            f"Review gate passed for evidence mode {details['evidence_mode'] or 'unspecified'}: "
            f"score={outcome.score}, verdict={outcome.verdict}, "
            f"publication_ready={details['publication_ready']}, source={outcome.source}."
        )
    return {
        "accepted": True,
        "verdict_id": host._verdict_id("review", artifacts),
        "reviewer": reviewer,
        "summary": summary,
        "details": details,
    }


def _reject(reason: str, summary: str, details: dict[str, Any]) -> dict[str, Any]:
    return {"accepted": False, "reason": reason, "summary": summary, "details": details}


def _decide(
    host: ReviewAcceptanceHost,
    context: ReviewAcceptanceContext,
    outcome: ReviewOutcome,
    details: dict[str, Any],
) -> dict[str, Any]:
    reconciliation = details.get("paper_reconciliation")
    if isinstance(reconciliation, dict) and not reconciliation.get("passed"):
        return _reject(
            "reviewed paper failed deterministic reconciliation",
            "; ".join(str(item) for item in reconciliation.get("issues", [])[:8]),
            {**details, "issues": list(reconciliation.get("issues") or [])},
        )
    if context.state_error:
        return _reject(
            "review state derivation could not be persisted",
            context.state_error,
            details,
        )
    if outcome.threshold_met:
        return _accept(host, context, outcome, details)
    if outcome.active_layout_findings:
        return _reject(
            "deterministic PDF layout findings require source repair",
            "; ".join(
                str(item.get("message") or "")
                for item in outcome.active_layout_findings[:8]
            )[:2000],
            details,
        )
    if (
        details["managed_review"]
        and outcome.visual_evidence.get("verified") is not True
    ):
        return _reject(
            "managed review lacks current native PDF visual evidence",
            "; ".join(
                str(item) for item in outcome.visual_evidence.get("issues") or []
            )[:2000],
            details,
        )
    mode = details["evidence_mode"]
    if (
        details["managed_review"]
        and outcome.bounded_complete
        and mode in BOUNDED_REVIEW_FALLBACK_EVIDENCE_MODES
        and not is_complete_evidence_mode(mode)
    ):
        return _accept(host, context, outcome, details, advisory=True)
    return _reject(
        "review gate did not reach score>=6 with verdict ready/almost",
        f"score={outcome.score}, verdict={outcome.verdict or 'unknown'}, source={outcome.source}",
        details,
    )


def review_acceptance_gate(
    host: ReviewAcceptanceHost,
    project_path: str,
    *,
    review_started_at: float | None = None,
    delivery_goal: str = "submission_candidate",
) -> dict[str, Any]:
    context = load_acceptance_context(project_path)
    if (
        review_started_at is not None
        and context.state_path.is_file()
        and context.state_path.stat().st_mtime + 1.0 < float(review_started_at)
    ):
        return _reject(
            "structured review state is stale",
            "REVIEW_STATE.json predates the current review attempt; a previous run cannot certify the current paper",
            {
                "path": str(context.state_path),
                "issues": [
                    "Write a fresh structured review state for the current attempt."
                ],
            },
        )
    context.layout_findings = host._review_layout_revision_findings(
        project_path, context.state
    )
    if not context.rounds:
        return _missing_rounds(host, context)
    outcome = review_outcome(host, context)
    persist_derived_outcome(context, outcome)
    details = review_gate_details(host, context, outcome)
    from .draft_delivery import DRAFT, draft_blockers
    if delivery_goal == DRAFT:
        from .draft_review_evidence import draft_response_matches
        from pathlib import Path
        blockers = draft_blockers(context.rounds[-1].get("draft_blockers"))
        details.update(delivery_goal=DRAFT, publication_ready=False,
            unresolved_scientific_findings={"score": outcome.score, "verdict": outcome.verdict,
                "weaknesses": context.rounds[-1].get("weaknesses", []), "action_items": context.rounds[-1].get("action_items", [])})
        if (context.state.get("delivery_goal") != DRAFT or blockers is None
                or not draft_response_matches(Path(project_path).resolve(), context.rounds[-1], review=True)):
            return _reject("independent draft review required", "The current report lacks an explicit draft integrity verdict", details)
        if blockers:
            return _reject("draft integrity review requires repair", "; ".join(blockers), {**details, "issues": blockers})
        if (context.state_error or not details.get("managed_review") or not outcome.bounded_complete or outcome.visual_evidence.get("verified") is not True
                or outcome.active_layout_findings or not (details.get("paper_reconciliation") or {}).get("passed")):
            return _reject("draft review evidence incomplete", "Current PDF, manuscript and review provenance must pass validation", details)
        return _accept(host, context, outcome, details, advisory=True)
    return _decide(host, context, outcome, details)
