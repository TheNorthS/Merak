"""Generated table presentation defects are not failures of scientific analysis."""

from __future__ import annotations

import hashlib
from typing import Any


def publication_table_findings(issues: list[str]) -> list[dict[str, Any]]:
    """Assign display/source contracts to the table producer without changing data."""
    findings = []
    for issue in issues:
        relative = str(issue).split(" ", 1)[0].replace("\\", "/")
        if not relative.startswith("tables/") or not relative.endswith(".tex"):
            continue
        target = "paper/" + relative
        runtime = target == "paper/tables/synthetic_preview_results.tex"
        identity = hashlib.sha256(f"{target}:{issue}".encode("utf-8")).hexdigest()[:12]
        findings.append({
            "id": f"PAPER-TABLE-PRESENTATION-{identity.upper()}", "severity": "blocker",
            "category": "publication_table", "owner_node": "paper", "upstream_node": "paper",
            "message": issue, "plain_message": issue, "target_files": [target],
            "producer_kind": "deterministic" if runtime else "model",
            "runtime_operation": "refresh_paper_runtime_inputs" if runtime else "",
            "remediation": "Repair the registered table's public presentation from its unchanged scientific rows; do not rewrite experiments/results/analysis.md or regenerate numeric evidence.",
        })
    return findings
