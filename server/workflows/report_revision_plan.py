"""Classify explicit producer targets without interpreting filenames as scientific verdicts."""

import hashlib
import json
from pathlib import Path
import re


def report_revision_plan(root: Path, consumer: str, findings: list[dict], *, options: dict | None = None) -> dict | None:
    """Only bounded authored targets enter this queue; research/runtime repairs stay explicit."""
    if consumer not in {"review", "audit"}:
        return None
    blockers = [f for f in findings if f.get("severity", "blocker") == "blocker"]
    if not blockers:
        return None
    groups: dict[str, dict] = {}
    for finding in blockers:
        owner = finding.get("upstream_node") or finding.get("owner_node")
        targets = finding.get("legal_write_targets", finding.get("target_files", []))
        if not isinstance(targets, list) or not targets or finding.get("producer_kind") == "deterministic":
            return None
        if owner not in {"lit", "results", "narrative", "paper"}:
            return None
        if owner == 'results':
            from ..services.node_execution_contract import resolve_execution_contract
            contract = resolve_execution_contract('results', options, project_path=str(root))
            if contract.kind != 'hybrid' or contract.blocking_issues:
                return None
        for target in targets:
            valid = (owner == "lit" and target == "literature/references.bib") or (
                owner == 'results' and target == 'experiments/results/analysis.md') or (
                owner == 'narrative' and target == 'NARRATIVE_REPORT.md') or (
                owner == "paper" and re.fullmatch(r"paper/sections/\d{2}_[A-Za-z0-9_]+\.tex", target))
            path = root / target
            if not valid or not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
                return None
        group = groups.setdefault(owner, {"owner": owner, "targets": [], "findings": []})
        group["targets"] = sorted(set(group["targets"]) | set(targets))
        group["findings"].append(finding)
    ordered = [groups[owner] for owner in ("lit", "results", "narrative", "paper") if owner in groups]
    identities = sorted(str(f.get("id") or hashlib.sha256(str(f.get("message")).encode()).hexdigest()) for f in blockers)
    identity = hashlib.sha256(json.dumps([consumer, identities], sort_keys=True).encode()).hexdigest()[:24]
    return {"id": identity, "consumer": consumer, "groups": ordered, "finding_ids": identities,
            "scope": "impact_review_required", "targets": sorted({p for g in ordered for p in g["targets"]})}
