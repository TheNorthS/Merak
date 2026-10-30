"""Correct claim decisions, never scientific observations or research inputs.

Layout scenarios cannot establish arbitrary research claims. Only an explicit
claim-bound rule may interpret a complete matching registered statistical family.
It never writes project artifacts or changes historical numerical fields.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
import math
from typing import Any, Sequence


DECISION_FIELDS = frozenset({
    "claim_status", "supports_claim", "decision", "decision_complete", "decision_scope",
    "mpid_pass", "uncertainty_pass", "multiplicity_pass", "holm_reject", "single_factor_matched",
})


@dataclass(frozen=True)
class ClaimDecisionCorrection:
    rows: tuple[dict[str, str], ...]
    changes: tuple[dict[str, Any], ...]


def _decision(status: str, reason: str, complete: bool = False) -> dict[str, str]:
    supported = status == "supported"
    return {
        "claim_status": status, "supports_claim": str(supported).lower(), "decision": reason,
        "decision_complete": str(complete).lower(), "decision_scope": "registered_simulation_statistics_only",
        "mpid_pass": str(supported).lower(), "uncertainty_pass": str(complete).lower(),
        "multiplicity_pass": str(complete).lower(), "holm_reject": str(supported).lower() if complete else "not_applicable",
        "single_factor_matched": "false",
    }


def _number(value: Any) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Claim statistical evidence must be finite")
    return number


def _contracts(payload: dict[str, Any], key: str, identity: str) -> dict[str, dict[str, Any]]:
    records = payload.get(key) or []
    if not isinstance(records, list) or any(not isinstance(item, dict) for item in records):
        raise ValueError("Claim decisions require an explicit current claim inventory")
    result = {str(item.get(identity) or ""): item for item in records}
    if len(result) != len(records) or "" in result:
        raise ValueError("Claim decisions refuse missing or duplicate claim identities")
    return result


def _bound_rule(
    claim_id: str, rows: list[dict[str, str]], plan: dict[str, Any], claim: dict[str, Any],
    contract: dict[str, Any],
) -> dict[str, Any] | None:
    rule, outcomes = plan.get("decision_rule"), plan.get("outcomes")
    if (not isinstance(rule, dict) or rule.get("schema") != 1
            or rule.get("kind") != "registered_cross_axis_reversal"
            or rule.get("claim_id") != claim_id or not claim.get("statement")
            or rule.get("claim_statement") != claim["statement"]
            or not isinstance(outcomes, list) or not outcomes
            or rule.get("registered_outcomes") != outcomes
            or [row.get("registered_outcome") for row in rows] != outcomes):
        return None
    if any(rule.get(key) != contract.get(key) for key in ("model_ids", "seed_ids", "axes", "holm_alpha")):
        return None
    return rule


def _family(
    rows: Sequence[dict[str, str]], rule: dict[str, Any],
) -> dict[tuple[frozenset[str], str], dict[str, str]]:
    models, seeds, axes = rule["model_ids"], rule["seed_ids"], rule["axes"]
    if (len(models) < 2 or len(set(models)) != len(models) or len(seeds) < 2
            or len(set(seeds)) != len(seeds) or any(not isinstance(item, dict) for item in axes)):
        raise ValueError("Claim rule has no unique model, seed or axis inventory")
    axis_ids, reference = [item["axis_id"] for item in axes], rule["reference_axis_id"]
    if (len(axis_ids) < 2 or len(set(axis_ids)) != len(axis_ids) or reference not in axis_ids
            or not 0 < _number(rule["holm_alpha"]) < 1):
        raise ValueError("Claim rule has no complete reference and target axis family")
    pairs = {frozenset(pair) for pair in combinations(models, 2)}
    expected = {(pair, axis) for pair in pairs for axis in axis_ids}
    actual = {}
    for row in rows:
        key = (frozenset((row["reference_model_id"], row["candidate_model_id"])), row["axis_id"])
        if key in actual or key not in expected:
            raise ValueError("Claim paired evidence has duplicate or foreign model/axis identity")
        if (row.get("paired_seed_ids") != "|".join(map(str, seeds)) or int(row["paired_n"]) != len(seeds)
                or row.get("test_method") != "paired_student_t_two_sided"
                or int(row["family_size"]) != len(pairs) * (len(axis_ids) - 1)
                or _number(row["holm_alpha"]) != _number(rule["holm_alpha"])):
            raise ValueError("Claim paired evidence differs from its registered family or seeds")
        actual[key] = row
    if set(actual) != expected:
        raise ValueError("Claim paired evidence is incomplete")
    return actual


def _qualifies(row: dict[str, str], reference: dict[str, str], axis: dict[str, Any], alpha: float) -> bool:
    if (row["reference_model_id"] != reference["reference_model_id"]
            or row["candidate_model_id"] != reference["candidate_model_id"]
            or row["iid_axis_id"] != reference["axis_id"]
            or row["metric"] != axis["metric_key"] or row["metric_direction"] != axis["direction"]
            or _number(row["mpid"]) != _number(axis["mpid"])):
        raise ValueError("Claim statistical row is not bound to its registered comparison")
    effect, baseline = _number(row["oriented_mean_effect"]), _number(reference["oriented_mean_effect"])
    low, high = _number(row["paired_ci_low"]), _number(row["paired_ci_high"])
    base_low, base_high = _number(reference["paired_ci_low"]), _number(reference["paired_ci_high"])
    adjusted = _number(row["holm_adjusted_p"])
    if not low <= effect <= high or not base_low <= baseline <= base_high or not 0 <= adjusted <= 1:
        raise ValueError("Claim paired interval or adjusted probability is invalid")
    if any(_number(row[key]) != _number(reference[source]) for key, source in (
        ("iid_oriented_mean_effect", "oriented_mean_effect"), ("iid_paired_ci_low", "paired_ci_low"),
        ("iid_paired_ci_high", "paired_ci_high"),
    )):
        raise ValueError("Claim target row is bound to a different reference-axis result")
    qualifies = (effect * baseline < 0 and abs(effect) >= _number(axis["mpid"])
                 and abs(baseline) >= _number(reference["mpid"])
                 and (low > 0 if effect > 0 else high < 0)
                 and (base_low > 0 if baseline > 0 else base_high < 0) and adjusted < alpha)
    if (row.get("reversal_status") == "qualifying_reversal") != qualifies:
        raise ValueError("Claim reversal flag contradicts its paired statistical rule")
    return qualifies


def _registered_decision(rows: Sequence[dict[str, str]], rule: dict[str, Any]) -> dict[str, str]:
    family = _family(rows, rule)
    axes = {item["axis_id"]: item for item in rule["axes"]}
    reference_axis, count = rule["reference_axis_id"], 0
    for (pair, axis_id), row in family.items():
        reference = family[pair, reference_axis]
        if row.get("in_holm_family") != str(axis_id != reference_axis).lower():
            raise ValueError("Claim family membership conflicts with its explicit reference axis")
        qualifies = _qualifies(row, reference, axes[axis_id], _number(rule["holm_alpha"]))
        count += int(qualifies and axis_id != reference_axis)
    minimum = rule["minimum_qualifying_reversals"]
    if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 1:
        raise ValueError("Claim rule requires an explicit positive reversal count")
    if count >= minimum:
        return _decision("supported", "registered_cross_axis_reversal_rule_satisfied", True)
    return _decision("not_supported", "registered_cross_axis_reversal_rule_not_satisfied", True)


def correct_claim_decisions(
    rows: Sequence[dict[str, str]], *, method_contract: dict[str, Any], selected_contract: dict[str, Any],
    paired_rows: Sequence[dict[str, str]] = (), paired_contract: dict[str, Any] | None = None,
) -> ClaimDecisionCorrection:
    """Return decision-only copies; nondecision fields remain exactly unchanged.

    Callers supply verified frozen sources. Missing rules or incomplete evidence
    are UNRESOLVED. Historical numerical claim fields are not evidential estimates.
    """
    plans = _contracts(method_contract, "claim_evidence_plan", "idea_claim_id")
    claims = _contracts(selected_contract, "claims", "id")
    by_claim: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        by_claim.setdefault(str(row.get("claim_id") or ""), []).append(row)
    decisions = {}
    for claim_id, bound in by_claim.items():
        rule = _bound_rule(claim_id, bound, plans.get(claim_id) or {}, claims.get(claim_id) or {}, paired_contract or {})
        decision = _decision("unresolved", "no_source_bound_registered_claim_decision_rule")
        if rule is not None:
            try:
                decision = _registered_decision(paired_rows, rule)
            except (KeyError, TypeError, ValueError, OverflowError):
                decision = _decision("unresolved", "registered_claim_decision_evidence_incomplete_or_conflicting")
        decisions[claim_id] = decision
    corrected, changes = [], []
    for row in rows:
        updated = {**row, **decisions[str(row.get("claim_id") or "")]}
        changed = {key: {"before": row.get(key), "after": updated[key]} for key in DECISION_FIELDS if row.get(key) != updated[key]}
        if {key: value for key, value in updated.items() if key not in DECISION_FIELDS} != {
            key: value for key, value in row.items() if key not in DECISION_FIELDS
        }:
            raise AssertionError("Claim correction modified scientific observations")
        corrected.append(updated)
        if changed:
            changes.append({"row_id": row.get("row_id"), "claim_id": row.get("claim_id"), "fields": changed})
    return ClaimDecisionCorrection(tuple(corrected), tuple(changes))


def paired_decision_contract(manifest: dict[str, Any]) -> dict[str, Any]:
    """Read explicit frozen family identities; never infer model or axis names."""
    return {"model_ids": [item["model_id"] for item in manifest.get("registered_model_suite") or []],
            "seed_ids": list((manifest.get("replicate_contract") or {}).get("seed_ids") or []),
            "axes": list(manifest.get("registered_ranking_axes") or []),
            "holm_alpha": (manifest.get("registered_pair_contract") or {}).get("holm_alpha")}
