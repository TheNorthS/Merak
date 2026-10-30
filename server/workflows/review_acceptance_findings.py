"""Normalize reviewer objections and merge active deterministic layout findings."""

from __future__ import annotations

import re
from typing import Any

from .review_acceptance_facts import (
    ReviewAcceptanceContext,
    ReviewAcceptanceHost,
    ReviewOutcome,
)


def review_revision_findings(
    host: ReviewAcceptanceHost,
    context: ReviewAcceptanceContext,
    outcome: ReviewOutcome,
) -> list[dict[str, Any]]:
    last_round = context.rounds[-1]
    raw_issues = [
        *list(last_round.get("weaknesses") or []),
        *list(last_round.get("action_items") or []),
    ]
    if context.state.get("delivery_goal") == "reviewable_draft":
        raw_issues = list(last_round.get("draft_blockers") or [])
    findings: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_issues, 1):
        issue = " ".join(str(raw or "").split())
        if not issue or issue.casefold() in seen:
            continue
        seen.add(issue.casefold())
        owner = re.search(
            r"\[owner\s*=\s*(lit|idea|novelty|exp-design|exp-run|results|figure|narrative|paper)\]",
            issue,
            re.IGNORECASE,
        )
        target = re.search(r"\[target\s*=\s*([^\]]+)\]", issue, re.IGNORECASE)
        from pathlib import Path
        from ..services.paper_canonical_author_target import canonical_author_target, presentation_repair_metadata
        targets = [canonical_author_target(Path(context.project_path), value)
            for value in host._revision_target_files(target.group(1) if target else issue)]
        findings.append(
            {
                "id": f"REVIEW-{len(context.rounds)}-{index}",
                "severity": "blocker",
                "category": "peer_review",
                "message": issue,
                "plain_message": issue,
                "owner_node": owner.group(1).casefold() if owner else "",
                "target_files": targets,
                **presentation_repair_metadata(Path(context.project_path), targets),
            }
        )
    known = {
        (str(item.get("id") or ""), str(item.get("message") or "")) for item in findings
    }
    for item in outcome.active_layout_findings:
        marker = str(item.get("id") or ""), str(item.get("message") or "")
        if marker not in known:
            findings.append(dict(item))
            known.add(marker)
    return findings


def review_gate_details(
    host: ReviewAcceptanceHost,
    context: ReviewAcceptanceContext,
    outcome: ReviewOutcome,
) -> dict[str, Any]:
    findings = review_revision_findings(host, context, outcome)
    details = {
        "score": outcome.score,
        "verdict": outcome.verdict,
        "source": outcome.source,
        "state_path": str(context.state_path),
        "managed_review": context.state.get("managed_by") == "cross_model_review_loop",
        "evidence_mode": str(context.state.get("evidence_mode") or "")
        .strip()
        .casefold(),
        "publication_ready": bool(context.state.get("publication_ready")),
        "semantic_threshold_met": outcome.semantic_threshold_met,
        "threshold_met": outcome.threshold_met,
        "bounded_complete": outcome.bounded_complete,
        "visual_evidence": outcome.visual_evidence,
        "deterministic_layout_findings": context.layout_findings,
        "active_layout_findings": outcome.active_layout_findings,
        "target_files": host._revision_target_files(
            [item.get("target_files") for item in findings]
        ),
        "issues": list(
            dict.fromkeys(
                [
                    *(str(item.get("message") or "") for item in findings),
                    *(
                        str(item)
                        for item in outcome.visual_evidence.get("issues") or []
                        if str(item).strip()
                    ),
                ]
            )
        ),
        "review_findings": findings,
    }
    reconciliation = context.state.get("paper_reconciliation")
    if isinstance(reconciliation, dict):
        details["paper_reconciliation"] = reconciliation
    if context.state_error:
        details["state_warning"] = context.state_error
    return details
