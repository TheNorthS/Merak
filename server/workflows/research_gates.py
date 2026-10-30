"""Deterministic scientific gates for reference-based innovation workflows."""

from __future__ import annotations

from typing import Any

from ..services.research_intake import research_intake_service


def innovation_gate_issues(
    node_id: str,
    project_path: str,
    options: dict[str, Any],
) -> list[str]:
    """Return contract failures from reference intake through executed evidence."""
    if str(options.get("research_mode") or "from_scratch") != "paper_code_innovation":
        return []

    issues: list[str] = []
    context_ok, context_issues, _ = research_intake_service.validate_context(project_path)
    if not context_ok:
        issues.extend(context_issues)

    downstream_of_idea = {
        "idea", "novelty", "exp-design", "exp-run", "results", "figure",
        "narrative", "paper", "review", "audit", "compile", "ppt",
    }
    if node_id in downstream_of_idea:
        brief_ok, brief_issues = research_intake_service.validate_innovation_brief(project_path)
        if not brief_ok:
            issues.extend(brief_issues)

    downstream_of_design = {
        "exp-design", "exp-run", "results", "figure", "narrative",
        "paper", "review", "audit", "compile", "ppt",
    }
    if node_id in downstream_of_design:
        require_results = options.get("run_experiment") is True and node_id != "exp-design"
        contract_ok, contract_issues = research_intake_service.validate_experiment_contract(
            project_path,
            require_results=require_results,
        )
        if not contract_ok:
            issues.extend(contract_issues)

    return list(dict.fromkeys(issues))


def apply_innovation_gate(
    gate: dict[str, Any],
    node_id: str,
    project_path: str,
    options: dict[str, Any],
) -> dict[str, Any]:
    """Combine a normal artifact gate with the reference-innovation contract."""
    if not gate.get("accepted"):
        return gate
    issues = innovation_gate_issues(node_id, project_path, options)
    if issues:
        return {
            "accepted": False,
            "reason": "reference innovation contract failed",
            "summary": "; ".join(issues[:12]),
            "details": {
                "issues": issues,
                "research_mode": "paper_code_innovation",
            },
        }
    if str(options.get("research_mode") or "from_scratch") == "paper_code_innovation":
        gate.setdefault("details", {})["research_mode"] = "paper_code_innovation"
    return gate

def apply_research_gates(
    gate: dict[str, Any],
    node_id: str,
    project_path: str,
    options: dict[str, Any],
) -> dict[str, Any]:
    """Apply innovation-specific and general executed-evidence gates."""
    gate = apply_innovation_gate(gate, node_id, project_path, options)
    if not gate.get("accepted") or options.get("run_experiment") is not True:
        return gate
    evidence_nodes = {
        "exp-run", "results", "figure", "narrative", "paper",
        "review", "audit", "compile", "ppt",
    }
    if node_id not in evidence_nodes:
        return gate
    from ..services.scientific_evidence import scientific_evidence_service

    valid, issues, details = scientific_evidence_service.validate_executed_metrics(project_path)
    if not valid:
        return {
            "accepted": False,
            "reason": "executed scientific evidence contract failed",
            "summary": "; ".join(issues),
            "details": details | {"issues": issues},
        }
    gate.setdefault("details", {})["executed_evidence"] = details
    return gate
