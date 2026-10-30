"""Assemble the experiment-depth supplement without executing research."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..services.run_spec import execution_seeds
from .experiment_protocol_profiles import ProtocolProfile, resolve_protocol


@dataclass(frozen=True)
class DepthContract:
    claims: list[dict[str, Any]]
    mechanisms: list[dict[str, Any]]
    evidence_by_claim: dict[str, dict[str, Any]]
    primary_outcomes: list[str]
    controls: list[str]
    component_tests: list[str]
    failure_conditions: list[str]


def _records(value: Any) -> list[dict[str, Any]]:
    return (
        [item for item in value if isinstance(item, dict)]
        if isinstance(value, list)
        else []
    )


def _strings(value: Any) -> list[str]:
    return (
        [" ".join(str(item).split()) for item in value if str(item).strip()]
        if isinstance(value, list)
        else []
    )


def _cell(value: Any, limit: int = 420) -> str:
    return " ".join(str(value or "").replace("|", "/").split())[:limit]


def _depth_contract(selected: dict[str, Any], method: dict[str, Any]) -> DepthContract:
    evaluation = method.get("evaluation_contract")
    evaluation = evaluation if isinstance(evaluation, dict) else {}
    claims = _records(selected.get("claims")) or [
        {
            "id": "C1",
            "statement": "The selected mechanism changes the declared primary outcome under the target evaluation setting.",
        }
    ]
    return DepthContract(
        claims=claims,
        mechanisms=_records(selected.get("mechanisms")),
        evidence_by_claim={
            str(item.get("idea_claim_id") or "").strip(): item
            for item in _records(method.get("claim_evidence_plan"))
            if item.get("idea_claim_id")
        },
        primary_outcomes=_strings(evaluation.get("primary_outcomes")),
        controls=_strings(evaluation.get("comparators_or_controls")),
        component_tests=_strings(evaluation.get("component_tests")),
        failure_conditions=list(
            dict.fromkeys(
                [
                    *_strings(selected.get("falsification_conditions")),
                    *_strings(evaluation.get("failure_conditions")),
                ]
            )
        ),
    )


def _fallback(values: list[str], index: int, default: str) -> str:
    return values[min(index, len(values) - 1)] if values else default


def _claim_matrix(contract: DepthContract) -> list[str]:
    lines = [
        "## Claim-to-Evidence Matrix",
        "| Claim ID | Falsifiable claim | Required evidence | Refutation condition |",
        "|---|---|---|---|",
    ]
    for index, claim in enumerate(contract.claims):
        claim_id = _cell(claim.get("id") or f"C{index + 1}", 40)
        plan = contract.evidence_by_claim.get(str(claim.get("id") or ""), {})
        outcomes = _strings(plan.get("outcomes"))
        failures = _strings(plan.get("failure_conditions"))
        required = "; ".join(outcomes[:2]) or _fallback(
            contract.primary_outcomes,
            index,
            "A prespecified comparison against declared controls on an identical held-out split.",
        )
        refutation = (
            failures[0]
            if failures
            else _fallback(
                contract.failure_conditions,
                index,
                "Reject or narrow the claim when its prespecified decision criterion is not met.",
            )
        )
        lines.append(
            f"| {claim_id} | {_cell(claim.get('statement'), 560)} | "
            f"{_cell(required, 560)} | {_cell(refutation, 560)} |"
        )
    return lines


def _mechanism_matrix(contract: DepthContract) -> list[str]:
    lines = [
        "## Mechanism-to-Implementation Traceability",
        "| Mechanism ID | Declared mechanism | Required implementation evidence |",
        "|---|---|---|",
    ]
    for index, mechanism in enumerate(contract.mechanisms):
        mechanism_id = _cell(mechanism.get("id") or f"M{index + 1}", 40)
        label = _cell(mechanism.get("name") or mechanism.get("description"), 460)
        lines.append(
            f"| {mechanism_id} | {label} | Executable symbol/config mapping in "
            "METHOD_CONTRACT plus an isolating component test. |"
        )
    if not contract.mechanisms:
        lines.append(
            "| M1 | Selected mechanism | Executable symbol/config mapping "
            "plus an isolating component test. |"
        )
    return lines


def _necessity_matrix(contract: DepthContract, profile: ProtocolProfile) -> list[str]:
    lines = [
        "## Mechanism Necessity and Sensitivity Matrix",
        "| Test ID | Mechanism-isolating test | Controlled interpretation |",
        "|---|---|---|",
    ]
    tests = contract.component_tests or [
        "remove, relax, or negate the required mechanism",
        "replace the mechanism with a domain-valid matched reference",
        "test the mechanism alone, jointly, and at a boundary or negative case",
    ]
    lines.extend(
        f"| N{index + 1} | {_cell(test, 500)} | {profile.mechanism_interpretation} |"
        for index, test in enumerate(tests)
    )
    return lines


def _analysis_sections(contract: DepthContract, profile: ProtocolProfile) -> list[str]:
    failures = contract.failure_conditions or [
        "The strongest matched control explains the observed effect.",
        "The effect disappears under the locked primary evaluation protocol.",
        "Leakage or an invalid independence assumption is detected.",
    ]
    return [
        "## Analysis, Inference, or Verification Plan",
        *profile.analysis_lines,
        "",
        "## Reproducibility and Provenance",
        *profile.reproducibility_lines,
        "",
        "## Falsification and Anti-Claims",
        *(
            f"- Anti-claim/F{i + 1}: {_cell(value, 700)}"
            for i, value in enumerate(failures)
        ),
        "",
        "## Staged Execution and Resource Budget",
        *profile.resource_lines,
    ]


def build_depth_supplement(
    selected: str,
    research_direction: str,
    selected_contract: dict[str, Any] | None,
    method_contract: dict[str, Any] | None,
    run_spec: dict[str, Any] | None,
    implementation_blueprint: dict[str, Any] | None,
) -> str:
    selected_contract = dict(selected_contract or {})
    method_contract = dict(method_contract or {})
    run_spec = dict(run_spec or {})
    blueprint = dict(implementation_blueprint or {})
    family = (
        str(
            blueprint.get("implementation_family")
            or run_spec.get("implementation_family")
            or "computational_general"
        )
        .strip()
        .casefold()
    )
    profile = resolve_protocol(
        family,
        str(blueprint.get("research_family") or "generic_quantitative")
        .strip()
        .casefold(),
        str(blueprint.get("study_archetype") or "generic_empirical").strip().casefold(),
        [str(seed) for seed in execution_seeds(run_spec)],
    )
    contract = _depth_contract(selected_contract, method_contract)
    lines = [
        "# MERAK Research Depth Contract Supplement",
        "",
        "This supplement is derived from the frozen research contracts. It does not "
        "report results and does not replace model-authored sections above.",
        "",
        "## Selected Scientific Context",
        f"- Research direction: {_cell(research_direction or 'declared research direction', 600)}",
        f"- Selected idea: {_cell(selected or 'selected method', 600)}",
        "- Evidence state: protocol only; every empirical claim remains pending "
        "until runtime-owned artifacts exist.",
        "",
        *_claim_matrix(contract),
        "",
        *_mechanism_matrix(contract),
        "",
        f"## {profile.protocol_title}",
        *profile.protocol_lines,
        "",
        "## Integrity, Independence, and Contamination Controls",
        *profile.independence_lines,
        "",
        "## Domain-valid References, Controls, and Fair Comparison",
        *(
            f"- Required reference/control: {_cell(value, 500)}."
            for value in contract.controls or profile.default_controls
        ),
        profile.fairness_line,
        "- Report the opportunity/resource/scope ledger needed to distinguish a "
        "mechanism effect from unequal information, assumptions, tuning, sampling, or compute.",
        "",
        *_necessity_matrix(contract, profile),
        "",
        *_analysis_sections(contract, profile),
    ]
    return "\n".join(lines) + "\n"
