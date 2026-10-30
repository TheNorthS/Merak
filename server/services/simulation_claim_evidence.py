"""Generate latency observations and claim-level simulation decisions."""

from __future__ import annotations

from typing import Any, Callable

from .simulation_evidence_helpers import evidence_kind
from .simulation_claim_decisions import correct_claim_decisions


Row = dict[str, str]


def latency_rows(
    efficiency: list[Row], seed_ids: list[int], source_run_id: str,
    hardware_contract_id: str, software_image: str,
    simulate: Callable[[dict[str, Any]], Row],
) -> list[Row]:
    rows = []
    for method_index, item in enumerate(efficiency):
        base = float(item.get("latency_ms") or item.get("resource_3") or 1.0)
        for seed_id in seed_ids:
            for iteration in range(1, 31):
                jitter = ((iteration % 7) - 3) * 0.002 + (method_index - 1) * 0.001
                rows.append(simulate({
                    "row_id": f"latency-{method_index + 1}-{seed_id}-{iteration}",
                    "run_id": f"{source_run_id}:efficiency:{method_index + 1}:seed-{seed_id}",
                    "method": str(item.get("method") or f"system-{method_index + 1}"),
                    "model_id": str(item.get("model_id") or item.get("method") or f"system-{method_index + 1}"),
                    "seed": str(seed_id), "iteration": str(iteration),
                    "warmup_iterations": "10", "measured_iterations": "30",
                    "latency_ms": f"{base * (1.0 + jitter):.6f}",
                    "latency_unit": "milliseconds", "device_contract": hardware_contract_id,
                    "software_image": software_image, "completion_status": "completed",
                }))
    return rows


def claim_evidence_rows(
    *, claim_ids: list[str], method_contract: dict[str, Any],
    selected_contract: dict[str, Any], paired_rows: list[Row], anchor: float,
    maximize_primary: bool, primary_metric: str, metric_direction: str,
    simulate: Callable[[dict[str, Any]], Row],
    paired_contract: dict[str, Any] | None = None,
) -> list[Row]:
    plans = _claim_plans(method_contract)
    claims = _selected_claims(selected_contract)
    rows = []
    for claim_index, claim_id in enumerate(claim_ids):
        plan = plans.get(claim_id) or {}
        claim = claims.get(claim_id) or {}
        outcomes = _outcomes(claim_id, plan, claim)
        failures = " | ".join(
            str(value).strip() for value in plan.get("failure_conditions") or []
            if str(value).strip()
        )
        for outcome_index, outcome in enumerate(outcomes):
            rows.append(_claim_row(
                claim_index, outcome_index, claim_id, outcome, failures,
                anchor, maximize_primary, primary_metric,
                metric_direction, simulate,
            ))
    correction = correct_claim_decisions(rows, method_contract=method_contract, selected_contract=selected_contract,
                                         paired_rows=paired_rows, paired_contract=paired_contract)
    return list(correction.rows)


def _claim_plans(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("idea_claim_id") or item.get("claim_id") or "").strip(): item
        for item in contract.get("claim_evidence_plan") or []
        if isinstance(item, dict)
        and str(item.get("idea_claim_id") or item.get("claim_id") or "").strip()
    }


def _selected_claims(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("id") or "").strip(): item
        for item in contract.get("claims") or []
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }


def _outcomes(
    claim_id: str, plan: dict[str, Any], claim: dict[str, Any],
) -> list[str]:
    raw = (
        plan.get("outcomes") or claim.get("measurable_endpoints")
        or [claim.get("statement") or claim.get("claim")]
    )
    outcomes = [str(value).strip() for value in raw if str(value or "").strip()]
    return outcomes or [f"Registered outcome for {claim_id}"]


def _claim_row(
    claim_index: int, outcome_index: int, claim_id: str, outcome: str,
    failures: str, anchor: float, maximize: bool,
    metric: str, direction: str, simulate: Callable[[dict[str, Any]], Row],
) -> Row:
    offset = 0.009 * claim_index + 0.004 * outcome_index
    center = min(0.95, anchor + offset) if maximize else max(0.01, anchor - offset)
    return simulate({
        "row_id": f"claim-{claim_index + 1}-{outcome_index + 1}",
        "claim_id": claim_id, "registered_outcome": outcome,
        "evidence_kind": evidence_kind(outcome), "comparison": outcome,
        "split_protocol": "not_applicable_deterministic_scenario",
        "planned_split_protocol": _split_protocol(outcome), "metric": metric,
        "metric_direction": direction, "value": f"{center:.3f}",
        "ci_low": f"{max(0.0, center - 0.010):.3f}",
        "ci_high": f"{min(1.0, center + 0.010):.3f}",
        "failure_conditions": failures,
        "analysis_unit": "random_seed",
    })


def _split_protocol(outcome: str) -> str:
    lower = outcome.casefold()
    if "dataset" in lower:
        return "dataset_held_out"
    return "subject_held_out" if "subject" in lower else "registered_protocol"
