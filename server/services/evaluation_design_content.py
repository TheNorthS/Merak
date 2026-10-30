"""Validate publication content for the deterministic evaluation producer."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .evaluation_design_contract import declared_removal_conditions
from .evaluation_conditions_projection import project_evaluation_conditions


@dataclass(frozen=True)
class EvaluationContent:
    focal_name: str
    has_mechanism: bool
    removal_conditions: tuple[str, ...]
    comparator_name: str
    secondary_controls: tuple[str, ...]
    primary_split: str
    analysis_unit: str
    require_subject_isolation: bool
    require_session_isolation: bool
    require_external_group: bool
    paired_comparison: bool
    endpoint_label: str
    declared_splits: tuple[dict[str, str], ...]
    active_holdout_axis: str
    source_bindings: dict[str, dict[str, str]]
    declared_conditions: tuple[str, ...]
    conditions_source_path: str


def _declared_comparators(
    contract: dict[str, Any], brief: dict[str, Any],
) -> tuple[str, tuple[str, ...]]:
    controls = contract.get("comparators_or_controls") or brief.get("comparators") or []
    comparators = tuple(dict.fromkeys(
        str(value).strip().replace("_", " ") for value in controls if str(value).strip()
    ))
    preferred = str(contract.get("primary_comparator") or "").strip().replace("_", " ")
    if preferred and preferred not in comparators:
        raise ValueError("evaluation_design primary_comparator is not a declared control")
    primary = preferred
    focal = str(contract.get("focal_condition") or (brief.get("publication") or {}).get("method_name")
                or "").strip().replace("_", " ")
    return primary, tuple(value for value in comparators if value not in {primary, focal})


def _declared_split_facts(protocol: dict[str, Any]) -> tuple[dict[str, str], ...]:
    facts = protocol.get("declared_splits") or []
    if not isinstance(facts, list):
        raise ValueError("evaluation_design declared_splits must be a list")
    if any(not isinstance(item, dict) or any(
        not isinstance(item.get(key), str) or not item[key].strip()
        for key in ("split_id", "display_name", "source_path", "source_symbol")
    ) for item in facts):
        raise ValueError("evaluation_design declared split lacks named source-bound facts")
    if len({item["split_id"] for item in facts}) != len(facts):
        raise ValueError("evaluation_design declared splits contain duplicate identities")
    return tuple(dict(item) for item in facts)


def _declared_conditions(brief: dict[str, Any]) -> tuple[tuple[str, ...], str]:
    conditions = brief.get("evaluation_conditions") or {}
    if not conditions:
        contract = dict(brief.get("evaluation_contract") or {})
        if not contract.get("comparators_or_controls") and brief.get("comparators"):
            contract["comparators_or_controls"] = brief["comparators"]
        conditions = project_evaluation_conditions({"evaluation_contract": contract}, brief.get("publication") or {})
    if conditions.get("mode") != "declared_conditions":
        return (), ""
    declared = conditions.get("conditions")
    if not isinstance(declared, list) or not declared or any(
        not isinstance(value, str) or not value.strip() for value in declared
    ) or not conditions.get("source_path"):
        raise ValueError("evaluation_design declared conditions lack named source-bound facts")
    if len(declared) > 8:
        raise ValueError("evaluation_design has more than eight declared conditions; "
                         "split them into companion evaluation figures instead of omitting conditions")
    return tuple(declared), str(conditions["source_path"])


def _focal_condition(brief: dict[str, Any], comparator: str, declared: tuple[str, ...]) -> tuple[str, dict[str, str]]:
    """A whole-method focal role needs an explicit contract/publication name.

    A mechanism list describes parts, not the scientific treatment condition.
    In a neutral portfolio no focal-vs-control relationship is manufactured.
    """
    contract, publication = brief.get("evaluation_contract") or {}, brief.get("publication") or {}
    value = contract.get("focal_condition") or publication.get("method_name") or ""
    focal = str(value).strip().replace("_", " ")
    binding = {"source_path": "experiments/METHOD_CONTRACT.json" if contract.get("focal_condition")
               else "ideas/SELECTED_IDEA.json", "source_symbol": "evaluation_contract.focal_condition"
               if contract.get("focal_condition") else "publication.method_name"}
    if declared:
        return focal or "Declared study conditions", binding if focal else {}
    if comparator and not focal:
        raise ValueError("evaluation_design explicit comparison requires a declared focal condition")
    if comparator and focal.casefold() == comparator.casefold():
        raise ValueError("evaluation_design focal condition and primary comparator must be distinct")
    return focal, binding


def evaluation_content(metadata: dict[str, Any]) -> EvaluationContent:
    """Fail closed on missing scientific facts; never fill plausible defaults."""
    brief = metadata.get("method_brief") or {}
    mechanisms = [
        item for item in brief.get("mechanism_nodes") or []
        if isinstance(item, dict)
        and str(item.get("publication_name") or item.get("name") or "").strip()
        and not any(term in str(item.get("publication_name") or item.get("name") or "").casefold()
                    for term in ("evaluation", "validation", "audit"))
    ]
    contract = brief.get("evaluation_contract") or {}
    protocol = brief.get("evaluation_protocol") or {}
    removals = tuple(value.replace("_", " ") for value in declared_removal_conditions(
        brief.get("study_conditions"),
    ))
    if len(removals) > 3:
        raise ValueError("evaluation_design has more than three declared removals; "
                         "split them into companion evaluation figures instead of omitting conditions")
    comparator, secondary = _declared_comparators(contract, brief)
    declared, conditions_source = _declared_conditions(brief)
    if declared:
        comparator, secondary = "", ()
    focal_name, focal_binding = _focal_condition(brief, comparator, declared)
    bindings = dict(protocol.get("source_bindings") or {})
    if focal_binding:
        bindings["focal_condition"] = focal_binding
    if comparator:
        bindings["primary_comparator"] = {"source_path": "experiments/METHOD_CONTRACT.json",
            "source_symbol": "evaluation_contract.primary_comparator"}
    primary = str(protocol.get("primary_metric_publication") or next(iter(
        contract.get("primary_outcomes") or brief.get("endpoints") or [],
    ), "")).strip().replace("_", " ")
    split = str(protocol.get("primary_split") or contract.get("primary_split") or "").strip()
    if not focal_name or not (comparator or declared) or not primary or not split:
        missing = [name for name, value in (
            ("focal condition", focal_name), ("declared comparator", comparator or declared),
            ("primary outcome", primary), ("primary evaluation split", split),
        ) if not value]
        raise ValueError("evaluation_design source contract missing " + ", ".join(missing))
    return EvaluationContent(
        focal_name=focal_name, has_mechanism=bool(mechanisms), removal_conditions=removals,
        comparator_name=comparator, secondary_controls=secondary,
        primary_split=split.replace("_", " "),
        analysis_unit=str(protocol.get("analysis_unit") or "").strip().replace("_", " "),
        require_subject_isolation=protocol.get("require_subject_isolation") is True,
        require_session_isolation=protocol.get("require_session_isolation") is True,
        require_external_group=protocol.get("require_external_group") is True,
        paired_comparison=re.search(r"\bpaired\b", str(contract.get("statistics") or ""), re.I) is not None,
        endpoint_label=primary, declared_splits=_declared_split_facts(protocol),
        active_holdout_axis=str(protocol.get("active_holdout_axis") or ""),
        source_bindings=bindings,
        declared_conditions=declared,
        conditions_source_path=conditions_source,
    )
