"""Apply quality, risk, research, and execution gates in a stable order."""

from __future__ import annotations

from typing import Any

from .acceptance_context import AcceptanceContext


def finalize_gate(context: AcceptanceContext, gate: dict[str, Any]) -> dict[str, Any]:
    from ..services.node_risk_audit import node_risk_audit_service
    from ..services.research_quality import research_quality_service
    from ..services.skill_orchestrator import skill_orchestrator
    from .research_gates import apply_research_gates

    quality_mode = str(context.options.get("research_quality_mode") or "rigorous")
    result = research_quality_service.apply_gate(
        gate,
        context.run.project_path,
        context.node.id,
        context.assurance,
        quality_mode,
    )
    result = node_risk_audit_service.apply_gate(
        result,
        context.run.project_path,
        context.node.id,
        context.options,
    )
    result = apply_research_gates(
        result,
        context.node.id,
        context.run.project_path,
        context.options,
    )
    evidence = skill_orchestrator.execution_gate(
        context.run.project_path,
        context.run.id,
        context.node.id,
    )
    issues = _execution_owner_issues(evidence)
    result.setdefault("details", {})["execution_evidence"] = evidence
    result["details"]["execution_gate_applied"] = True
    if result.get("accepted") and issues:
        return {
            "accepted": False,
            "reason": "declared node execution was not verified",
            "summary": "; ".join(issues[:8]),
            "details": {
                "issues": issues,
                "execution_evidence": evidence,
                "execution_gate_applied": True,
            },
        }
    return result


def _execution_owner_issues(evidence: dict[str, Any]) -> list[str]:
    """Keep identity, contract and asset failures, not only model-message strings.

Hybrid gate completion is recorded immediately after this provisional check.
Its missing runtime record alone is deferred to verify_runtime_execution;
all other execution defects remain blocking at this boundary.
"""
    deferred_runtime = str(evidence.get("execution_kind") or "") == "hybrid"
    return [
        str(issue) for issue in evidence.get("issues", [])
        if not (deferred_runtime and str(issue).startswith(
            "missing verified current-run runtime execution for "
        ))
    ]
