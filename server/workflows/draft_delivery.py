"""Explicit draft delivery preserves scientific verdicts and requires separate integrity review."""

import copy
from contextvars import ContextVar
from pathlib import Path
from typing import Any


DRAFT = "reviewable_draft"
SUBMISSION = "submission_candidate"
AUDIT_DELIVERY: ContextVar[str] = ContextVar("audit_delivery_goal", default=SUBMISSION)
DRAFT_POLICY = """
The researcher explicitly requests a reviewable scientific draft, not submission acceptance.
Keep your honest scientific score/verdict, weaknesses, evidence gaps and future research actions.
Also return draft_blockers: an array of concrete current defects that prevent honest draft delivery.
Include fabricated/misrepresented evidence, contradictory values or claims, incorrect citations,
broken provenance, unreadable/corrupt artifacts and actual mathematical errors. Each blocker
must identify its existing canonical [owner=...] [target=...] and the concrete correction.
Missing real experiments, unresolved prospective estimands, limited novelty, low publication
score and a missed soft page preference are research limitations, not draft_blockers, provided
they are accurately disclosed and the claims are bounded. Do not demand new training or invent
data to complete this draft. An empty array explicitly attests no such current integrity defect;
it does not raise the scientific score, imply publication readiness, or erase any finding.
For a claim-based blocker quote the precise current visible manuscript statement and name
its canonical authored source. Assess its surrounding qualifications, not an older planning
document as though it were published prose. If missing evidence is correctly disclosed,
retain it as a scientific weakness. If a claim overstates that evidence, route the offending
claim to its author; do not require new experiments to satisfy the draft delivery goal.
"""


def delivery_goal(options: dict[str, Any] | None) -> str:
    value = str((options or {}).get("delivery_goal") or SUBMISSION)
    if value not in {DRAFT, SUBMISSION}:
        raise ValueError("Unsupported workflow delivery_goal")
    return value


def run_delivery_goal(project_path: str, run_id: str) -> str:
    if not run_id:
        return SUBMISSION
    from .run_state import RunState
    saved = RunState(project_path, run_id).load() or {}
    return delivery_goal((saved.get("config") or {}).get("options"))


def archive_previous_review(project_path: str) -> None:
    import hashlib
    from ..utils.atomic_write import atomic_write_bytes
    path = Path(project_path) / "review-stage/REVIEW_STATE.json"
    if path.is_file():
        raw = path.read_bytes()
        target = path.parent / "history" / f"review-{hashlib.sha256(raw).hexdigest()}.json"
        if not target.exists():
            atomic_write_bytes(target, raw)


def draft_schema(schema: dict[str, Any]) -> dict[str, Any]:
    updated = copy.deepcopy(schema)
    updated["properties"]["draft_blockers"] = {"type": "array", "items": {"type": "string", "minLength": 1}}
    updated["required"] = [*updated.get("required", []), "draft_blockers"]
    return updated


def draft_blockers(value: Any) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError("draft_blockers must be an explicit array of nonempty findings")
    return list(value)


def draft_audit_findings(root: Path, bundle: dict[str, Any]) -> list[str]:
    """Require independent integrity responses while preserving scientific verdicts."""
    from .draft_review_evidence import draft_response_matches
    entries = bundle.get("entries") or []
    blockers = []
    for item in entries:
        findings = draft_blockers(item.get("draft_blockers"))
        if (item.get("delivery_goal") != DRAFT or item.get("method") != "model" or findings is None
                or not draft_response_matches(root, item)):
            blockers.append(f"Audit layer {item.get('layer')} lacks a current independent draft integrity verdict")
        else:
            blockers.extend(findings)
        if item.get("verdict") in {"ERROR", "BLOCKED"}:
            blockers.append(f"Audit layer {item.get('layer')} did not complete: {item.get('summary')}")
    if len(entries) != 5 or (bundle.get("proof_payload") or {}).get("verdict") not in {"PASS", "WARN", "NOT_APPLICABLE"}:
        blockers.append("Draft delivery requires all five scientific audits and a non-failing proof check")
    return blockers


def draft_audit_gate(host: Any, bundle: dict[str, Any], artifacts: list[Path]) -> dict[str, Any]:
    blockers = draft_audit_findings(artifacts[0].parent.parent.resolve(), bundle)
    entries = bundle.get("entries") or []
    details = {"delivery_goal": DRAFT, "publication_ready": False, "verdicts": bundle.get("verdicts", []),
               "draft_blockers": blockers, "unresolved_scientific_findings": entries, "issues": blockers}
    if blockers:
        from .draft_audit_routing import draft_blocker_findings
        details['findings'] = draft_blocker_findings(artifacts[0].parent.parent.resolve(), blockers)
        details['issues'] = [finding['message'] for finding in details['findings']]
        return {"accepted": False, "reason": "draft integrity audit requires repair", "summary": "; ".join(details['issues']), "details": details}
    return {"accepted": True, "verdict_id": host._verdict_id("audit", artifacts),
            "reviewer": "independent:draft-integrity", "details": details,
            "summary": "Independent draft audits completed; original scientific verdicts and evidence gaps retained; publication_ready=false."}
