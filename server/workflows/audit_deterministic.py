"""Deterministic proof detection and bounded audit fallback."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .review_models import AuditResult, Verdict


def proof_detector_result(
    project_path: str,
    *,
    policy_loaded: Callable[[str], bool],
) -> AuditResult | None:
    from .review_audit import proof_source_bundle

    _, input_hashes, source_paths, theorem_count, errors = proof_source_bundle(
        project_path
    )
    loaded = policy_loaded("proof-checker")
    if errors:
        return AuditResult(
            layer=6, layer_name="Proof Checker", verdict=Verdict.BLOCKED,
            summary=(
                "Proof-checker could not read every declared TeX source; "
                "proof coverage cannot be certified."
            ),
            details={
                "theorems_audited": 0,
                "issues": [_source_issue(item) for item in errors],
                "formal_environments_detected": theorem_count,
            },
            evidence=[str(path) for path in source_paths],
            method="deterministic_detector", skill_name="proof-checker",
            policy_loaded=loaded, reason_code="source_unreadable",
            audited_input_hashes=input_hashes,
        )
    if theorem_count:
        return None
    return AuditResult(
        layer=6, layer_name="Proof Checker", verdict=Verdict.NOT_APPLICABLE,
        summary=(
            "No theorem, lemma, proposition, corollary, or proof environment "
            "was found; /proof-checker is not applicable."
        ),
        details={
            "theorems_audited": 0, "issues": [],
            "formal_environments_detected": 0,
            "detector": "latex-formal-environment-v1",
        },
        evidence=[], method="deterministic_detector", skill_name="proof-checker",
        policy_loaded=loaded, reason_code="no_theorems",
        audited_input_hashes={},
    )


def _source_issue(item: str) -> dict[str, str]:
    return {
        "id": "SOURCE-UNREADABLE", "severity": "CRITICAL",
        "category": "source_unreadable", "location": item.split(": ", 1)[0],
        "note": item,
    }


def deterministic_fallback(
    layer_num: int,
    layer_name: str,
    project_path: str,
    error: Exception,
    *,
    evidence_mode: str = "design_only",
) -> AuditResult:
    from ..services.node_risk_audit import node_risk_audit_service

    nodes_by_layer = {
        1: ("exp-design", "exp-run"), 2: ("results", "paper"),
        3: ("results", "paper"), 4: ("lit", "paper"),
        5: ("review", "paper"),
    }
    reports = [
        node_risk_audit_service.audit_node(
            project_path, node_id,
            {
                "run_experiment": False, "gpu_target": "none",
                "non_experiment_evidence_mode": evidence_mode,
            },
            persist=False,
        )
        for node_id in nodes_by_layer.get(layer_num, ())
    ]
    blockers = _findings(reports, "blocker")
    warnings = _findings(reports, "warning")
    evidence = _fallback_evidence(reports, project_path)
    verdict = Verdict.FAIL if blockers else Verdict.WARN
    summary = _finding_summary(blockers if blockers else warnings)
    if not summary:
        summary = "No objective contradiction was found by local stage validators."
    label = "Simulation-benchmark" if evidence_mode == "synthetic_preview" else "Planned-mode"
    return AuditResult(
        layer=layer_num, layer_name=layer_name, verdict=verdict,
        summary=(
            f"{label} semantic audit was unavailable; deterministic fallback "
            f"returned {verdict.value}. {summary}"
        ),
        details=(
            f"Model audit interruption: {type(error).__name__}: {error}. "
            "This is workflow-stage evidence only and not an independent semantic audit."
        ),
        evidence=evidence, method="deterministic_fallback",
    )


def _findings(reports: list[dict[str, Any]], severity: str) -> list[dict[str, Any]]:
    return [
        finding for report in reports for finding in report.get("findings", [])
        if finding.get("severity") == severity
    ]


def _finding_summary(findings: list[dict[str, Any]]) -> str:
    return "; ".join(
        str(item.get("plain_message") or item.get("message") or "")
        for item in findings[:5]
    )


def _fallback_evidence(
    reports: list[dict[str, Any]], project_path: str
) -> list[str]:
    evidence = list(dict.fromkeys(
        str(path)
        for report in reports
        for finding in report.get("findings", [])
        for path in finding.get("evidence", [])
        if str(path).strip()
    ))
    if evidence:
        return evidence
    return [
        relative for relative in (
            "paper/main.tex", "experiments/METHOD_CONTRACT.json",
            "experiments/results/analysis.md", "literature/references.bib",
        )
        if (Path(project_path) / relative).is_file()
    ]
