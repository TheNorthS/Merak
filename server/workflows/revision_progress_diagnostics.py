"""Classify targeted revisions by scientific finding progress, not byte churn."""

from __future__ import annotations

from typing import Iterable
from typing import Any


def revision_stall_classification(
    *, target_changed: bool, resolved: Iterable[str], new: Iterable[str],
    draft_review_changed: bool = False,
) -> str:
    if list(resolved) or list(new):
        return "finding_set_changed"
    if draft_review_changed:
        return "draft_review_progress"
    if target_changed:
        return "ineffective_content_change"
    return "no_artifact_change"


def revision_stall_message(classification: str, attempts: int) -> tuple[str, str]:
    if classification == 'finding_set_changed':
        return (
            f'The finding set changed, but prior findings remain unevaluated after {attempts} repair attempts.',
            'Review the outstanding findings and their source bindings before another bounded repair; '
            'this stop does not establish unchanged artifacts or identical findings.',
        )
    if classification == "ineffective_content_change":
        return (
            "Artifacts changed, but no structured finding was resolved after "
            f"{attempts} targeted repair attempts.",
            "Possible causes: the edit was ineffective, a different producer overwrote it, "
            "or the producer and validator contracts are inconsistent.",
        )
    return (
        "The same structured findings and target-artifact fingerprints remained "
        f"unchanged after {attempts} targeted repair attempts.",
        "No content change was detected in the files or semantic assets implicated "
        "by the current findings.",
    )


def measure_revision_progress(
    *, current: set[str], previous: set[str], scope_signature: str,
    previous_scope_signature: str, previous_count: int, revision_started: bool,
    transport_attempted: bool, draft_review_changed: bool = False,
    draft_review_signature: str = "",
    evaluation_complete: bool = True,
    new_author_scope: bool = False,
) -> dict[str, Any]:
    not_evaluated = sorted(previous - current) if not evaluation_complete else []
    resolved = sorted(previous - current) if evaluation_complete else []
    new = sorted(current - previous)
    target_changed = bool(
        previous_scope_signature and scope_signature != previous_scope_signature
    )
    repeated = (
        revision_started
        and not resolved
        and not transport_attempted
        and not draft_review_changed
        and not (new_author_scope and current and not current.intersection(previous))
    )
    count = previous_count + 1 if repeated else 0
    classification = revision_stall_classification(
        target_changed=target_changed, resolved=resolved, new=new,
        draft_review_changed=draft_review_changed,
    )
    return {
        "resolved_finding_ids": resolved,
        "not_evaluated_finding_ids": not_evaluated,
        "evaluation_complete": evaluation_complete,
        "new_finding_ids": new,
        "target_changed": target_changed,
        "consecutive_no_progress": count,
        "finding_ids": sorted(current),
        "scope_signature": scope_signature,
        "draft_review_signature": draft_review_signature,
        "draft_review_changed": draft_review_changed,
        "stall_classification": classification,
    }
