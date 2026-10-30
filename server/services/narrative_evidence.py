"""Read current claim/protocol evidence without promoting historical support labels."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .protocol_conformance import ProtocolConformanceError, read_protocol_readiness
from .simulation_claim_decision_report import build_claim_decision_report


def current_narrative_evidence(root: Path, *, synthetic: bool) -> dict[str, Any]:
    """Recompute decisions from bound inputs; a persisted self-signed report is not proof."""
    decisions, decision_issue, protocol, protocol_issue = {}, "", None, ""
    if synthetic:
        try:
            decisions = build_claim_decision_report(root)
        except (OSError, ValueError) as error:
            decision_issue = str(error)
    try:
        value = read_protocol_readiness(root)
        protocol = value.to_dict() if value is not None else None
    except ProtocolConformanceError as error:
        protocol_issue = str(error)
    return {"claim_decision_report": decisions, "claim_decision_issue": decision_issue,
            "protocol_readiness": protocol, "protocol_readiness_issue": protocol_issue}


def claim_decision(context: dict[str, Any], identity: str) -> tuple[str, str]:
    """An unresolved or incomplete outcome cannot become overall claim support."""
    rows = [row for row in context.get("claim_decision_report", {}).get("rows", [])
            if row.get("claim_id") == identity]
    statuses = {row.get("claim_status") for row in rows}
    complete = rows and all(row.get("decision_complete") == "true" for row in rows)
    if complete and statuses == {"supported"}:
        status = "SUPPORTED_WITHIN_REGISTERED_SIMULATION_STATISTICS_ONLY"
    elif complete and statuses == {"not_supported"}:
        status = "NOT_SUPPORTED_WITHIN_REGISTERED_SIMULATION_STATISTICS_ONLY"
    else:
        status = "UNRESOLVED"
    reasons = "; ".join(dict.fromkeys(str(row.get("decision") or "") for row in rows))
    return status, reasons or context.get("claim_decision_issue") or "No current source-bound registered claim decision"


def protocol_narrative_lines(context: dict[str, Any]) -> list[str]:
    value = context.get("protocol_readiness")
    if context.get("protocol_readiness_issue"):
        return ["Protocol readiness is BLOCKED: " + context["protocol_readiness_issue"],
                "No execution or implementation-conformance conclusion can be inferred from this invalid ledger."]
    if value is None:
        return ["Protocol readiness is not validated: no current conformance ledger is available. "
                "Absence of a ledger is not proof that the registered research was executed or implemented conformantly."]
    return ["Current protocol implementation status: " + str(value["status"]).upper() +
            ". Scientific execution is prohibited; implementation conformance and research evidence are not established.",
            *["- " + str(row["id"]) + ": " + str(row["status"]) + "; declared: " + str(row["declared"]) +
              "; observed: " + str(row["observed"]) for row in value["findings"]]]


def benchmark_description_lines(context: dict[str, Any]) -> list[str]:
    report = context.get("claim_decision_report") or {}
    if not report:
        return ["The current source-bound benchmark decision audit is unavailable; historical analysis text "
                "and legacy support labels cannot establish current ordering or scientific claim support."]
    summary = report["primary_comparison"]
    lines = ["Current descriptive primary table: metric " + str(summary["metric"]) +
             ", direction " + str(summary["metric_direction"]) + ". " + report["scope"]]
    for item in summary["methods"]:
        lines.append("- " + str(item["method"]) + ": target-macro mean " + str(item["target_macro_mean"]) +
                     "; target ranks " + ", ".join(map(str, item["target_ranks"])) +
                     "; matched targets " + str(item["target_count"]) + ".")
    return lines
