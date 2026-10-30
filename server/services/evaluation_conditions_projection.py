"""Bind declared publication conditions without inventing a primary comparison."""

from __future__ import annotations

from typing import Any

from .evaluation_design_contract import GENERIC_PLANNED_COMPARATORS
from ..contracts.preparation import PreparationContractError


def project_evaluation_conditions(
    method_contract: dict[str, Any], publication: dict[str, Any],
) -> dict[str, Any]:
    """Project all named conditions when no primary comparison is declared.

    A named method comparison or explicit primary remains owned by its method
    contract. Publication conditions may include both focal and control variants,
    so this projection never casts their order as a focal-vs-control ranking.
    """
    contract = method_contract.get("evaluation_contract") or {}
    controls = contract.get("comparators_or_controls") or []
    if contract.get("primary_comparator"):
        return {}
    named = bool(controls) and any(
        isinstance(value, str) and value.strip() not in GENERIC_PLANNED_COMPARATORS for value in controls
    )
    declared = controls if named else publication.get("comparator_names") or []
    if not isinstance(declared, list) or any(
        not isinstance(value, str) or not value.strip() for value in declared
    ):
        raise PreparationContractError("evaluation_design declared comparison conditions must contain names",
                                       paths=("experiments/METHOD_CONTRACT.json", "ideas/SELECTED_IDEA.json"))
    if not declared:
        return {}
    if len(declared) > 8:
        raise PreparationContractError("evaluation_design has more than eight declared conditions; "
                         "split them into companion evaluation figures instead of omitting conditions",
                         paths=("experiments/METHOD_CONTRACT.json", "ideas/SELECTED_IDEA.json"))
    return {
        "mode": "declared_conditions", "conditions": list(dict.fromkeys(declared)),
        "source_path": "experiments/METHOD_CONTRACT.json" if named else "ideas/SELECTED_IDEA.json",
        "source_symbol": "evaluation_contract.comparators_or_controls" if named else "publication.comparator_names",
    }
