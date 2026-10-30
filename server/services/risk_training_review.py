"""Normalize a read-only implementation review into producer-owned findings."""

from __future__ import annotations

from typing import Any
from .risk_artifact_support import _finding


def _failed_review_verdict(assessment: dict[str, Any]) -> dict[str, Any]:
    finding = _finding(
        "TRAINING-CHECK-VERDICT",
        "blocker",
        "implementation_review",
        str(
            assessment.get("summary")
            or "The pre-execution implementation review failed."
        ),
        str(assessment.get("summary") or "训练前实现审查未通过。"),
        ["experiments/src", "experiments/configs", "experiments/RUN_SPEC.json"],
        "Resolve the failed review verdict before starting the experiment.",
    )
    finding["owner_node"] = "exp-design"
    finding["upstream_node"] = "exp-design"
    return finding


def training_check_findings(options: dict[str, Any]) -> list[dict[str, Any]]:
    """Expose a failed model audit as focused exp-design blockers."""
    assessment = options.get("_training_check")
    if not isinstance(assessment, dict) or not assessment.get("blocking"):
        return []
    raw_findings = assessment.get("findings")
    from .training_review_policy import current_review_findings, review_blocks
    if not review_blocks(assessment, options):
        return []
    raw_findings = current_review_findings(assessment, options)
    if not isinstance(raw_findings, list):
        raw_findings = []
    if not raw_findings:
        raw_findings = [
            {
                "id": "TRAINING-CHECK-001",
                "message": str(
                    assessment.get("summary")
                    or "The pre-execution implementation review did not pass."
                ),
                "remediation": "Repair the experiment implementation and rerun the training check.",
            }
        ]
    findings: list[dict[str, Any]] = []
    blocker_count = 0
    for index, raw in enumerate(raw_findings, start=1):
        item = raw if isinstance(raw, dict) else {"message": str(raw)}
        message = str(
            item.get("message")
            or item.get("plain_message")
            or "The pre-execution implementation review did not pass."
        ).strip()
        evidence = item.get("target_files") or item.get("evidence") or []
        if isinstance(evidence, str):
            evidence = [evidence]
        evidence = [str(value) for value in evidence if str(value).strip()]
        raw_severity = str(
            item.get("severity")
            or (
                "blocker"
                if str(assessment.get("verdict") or "").upper() == "FAIL"
                else "warning"
            )
        ).casefold()
        severity = (
            "blocker"
            if raw_severity in {"blocker", "critical", "error", "fail"}
            else "warning"
        )
        blocker_count += int(severity == "blocker")
        finding = _finding(
            str(item.get("id") or f"TRAINING-CHECK-{index:03d}"),
            severity,
            str(item.get("category") or "implementation_review"),
            message,
            str(item.get("plain_message") or message),
            evidence
            or ["experiments/src", "experiments/configs", "experiments/RUN_SPEC.json"],
            str(
                item.get("remediation")
                or "Repair the named experiment files and rerun the read-only training check."
            ),
        )
        finding["owner_node"] = "exp-design"
        finding["upstream_node"] = "exp-design"
        findings.append(finding)
    if assessment.get("blocking") and blocker_count == 0:
        findings.append(_failed_review_verdict(assessment))
    return findings
