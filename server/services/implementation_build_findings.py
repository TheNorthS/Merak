"""Stable producer-owned diagnostics for staged build acceptance failures."""

from __future__ import annotations

import hashlib
from typing import Any


def implementation_findings(
    reports: list[dict[str, Any]], issues: list[str],
) -> list[dict[str, Any]]:
    """Bind every blocking issue to the stage artifacts its producer can fix."""
    by_id = {str(report.get("stage_id") or ""): report for report in reports}
    findings: list[dict[str, Any]] = []
    for issue in issues:
        stage_id = issue.split(":", 1)[0]
        report = by_id.get(stage_id) or {}
        targets = list(dict.fromkeys([
            *list(report.get("repair_targets") or []),
            *list(report.get("targets") or []),
        ]))
        identity = hashlib.sha256(issue.encode("utf-8")).hexdigest()[:12]
        findings.append({
            "id": f"IMPLEMENTATION-{stage_id.upper()}-{identity}",
            "severity": "blocker", "category": "staged_implementation",
            "message": issue, "plain_message": issue,
            "target_files": targets, "semantic_asset_ids": [stage_id],
            "owner_node": "exp-design", "upstream_node": "exp-design",
            "remediation": "Repair the named implementation stage using its typed evidence patch and declared source targets; preserve frozen design artifacts.",
        })
    return findings


def implementation_repair_scope(findings: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "target_files": list(dict.fromkeys(
            target for finding in findings for target in finding["target_files"]
        )),
        "asset_ids": list(dict.fromkeys(
            identity for finding in findings for identity in finding["semantic_asset_ids"]
        )),
    }
