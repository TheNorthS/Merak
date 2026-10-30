"""Mandatory publication semantics shared by figures, tables, and prose."""

from __future__ import annotations

from typing import Any


CONTRIBUTION_TYPES = frozenset({
    "model_architecture", "objective_mechanism", "experimental_protocol",
    "system_architecture", "dataset_benchmark", "empirical_discovery",
    "theory_proof", "clinical_biological_mechanism", "qualitative_framework",
})


def validate_publication_semantics(payload: dict[str, Any]) -> list[str]:
    publication = payload.get("publication")
    if not isinstance(publication, dict):
        return ["selected idea requires a publication object"]
    issues: list[str] = []
    language = str(publication.get("language") or "").strip().casefold()
    contribution = str(publication.get("contribution_type") or "").strip()
    for field in ("title", "method_name"):
        if not str(publication.get(field) or "").strip():
            issues.append(f"publication.{field} is required")
    if language not in {"en", "zh"}:
        issues.append("publication.language must be en or zh")
    if contribution not in CONTRIBUTION_TYPES:
        issues.append("publication.contribution_type is unsupported")
    comparators = publication.get("comparator_names")
    if not isinstance(comparators, list) or not comparators or not all(isinstance(item, str) and item.strip() for item in comparators):
        issues.append("publication.comparator_names must be a non-empty public-name list")
    for index, claim in enumerate(payload.get("claims") or []):
        if not isinstance(claim, dict) or not str(claim.get("publication_statement") or "").strip():
            issues.append(f"claims[{index}].publication_statement is required")
    for index, mechanism in enumerate(payload.get("mechanisms") or []):
        if not isinstance(mechanism, dict):
            issues.append(f"mechanisms[{index}] must be an object")
            continue
        if not str(mechanism.get("publication_name") or "").strip():
            issues.append(f"mechanisms[{index}].publication_name is required")
        if not str(mechanism.get("publication_description") or "").strip():
            issues.append(f"mechanisms[{index}].publication_description is required")
        if not str(mechanism.get("publication_evaluation") or "").strip():
            issues.append(f"mechanisms[{index}].publication_evaluation is required")
    return issues


def publication_semantics(payload: dict[str, Any]) -> dict[str, Any]:
    issues = validate_publication_semantics(payload)
    if issues:
        raise ValueError("Invalid publication semantics: " + "; ".join(issues))
    return dict(payload["publication"])
