"""Read the current selected asset reference inventory without inventing labels."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PublicationAssetReference:
    label: str
    kind: str
    scientific_role: str
    source_path: str


def _payload(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Selected asset reference inventory is unreadable: {path.name}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Selected asset reference inventory must be an object: {path.name}")
    return value


def selected_publication_references(root: Path) -> tuple[PublicationAssetReference, ...]:
    """Require every selected registered table label to occur in its real source."""
    figures = _payload(root / "figures/FIGURE_MANIFEST.json")
    tables = _payload(root / "paper/tables/TABLE_MANIFEST.json")
    if tables and (tables.get("schema") != 3 or not isinstance(tables.get("tables"), list)):
        raise ValueError("Selected table reference inventory has an unsupported manifest schema")
    result = []
    plan = _payload(root / "figures/SCIENTIFIC_ASSET_PLAN.json")
    has_figure_portfolio = isinstance(plan.get("assets"), list)
    selected_ids = {str(item.get("id") or "") for item in plan.get("assets") or []
                    if isinstance(item, dict) and item.get("kind") == "figure"
                    and item.get("manuscript_eligible") is not False and item.get("generation_policy") != "skip"}
    figure_records = figures.get("figures") or []
    if not isinstance(figure_records, list) or any(not isinstance(item, dict) for item in figure_records):
        raise ValueError("Selected figure reference inventory must contain declared figure records")
    for item in figure_records:
        metadata = item.get("metadata") or {}
        if has_figure_portfolio and str(metadata.get("semantic_key") or item.get("id") or "") not in selected_ids:
            continue
        if metadata.get("paper_selected") is False or metadata.get("manuscript_eligible") is False:
            continue
        label = str(metadata.get("label") or "")
        if label:
            result.append(PublicationAssetReference(label, "figure", str(metadata.get("scientific_role") or ""),
                                                    str(item.get("output_path") or "")))
    for item in tables.get("tables") or []:
        if not isinstance(item, dict):
            raise ValueError("Selected table reference inventory contains a non-object record")
        if item.get("paper_selected") is False or item.get("manuscript_eligible") is False:
            continue
        label, relative = str(item.get("label") or ""), str(item.get("latex_path") or "")
        source = (root / relative).resolve()
        if not label or not relative or not source.is_relative_to(root.resolve()) or not source.is_file():
            raise ValueError("Selected table reference has no source-bound public label")
        text = source.read_text(encoding="utf-8-sig")
        if len(re.findall(r"\\label\{" + re.escape(label) + r"\}", text)) != 1:
            raise ValueError(f"Selected table reference {label} is missing or duplicated in {relative}")
        result.append(PublicationAssetReference(label, "table", str(item.get("scientific_role") or ""), relative))
    return tuple(result)


def result_publication_references(root: Path) -> tuple[PublicationAssetReference, ...]:
    """Return the selected result portfolio, excluding method/design sources."""
    return tuple(reference for reference in selected_publication_references(root)
                 if reference.scientific_role not in {"method", "evaluation_design", "method_components", "study_design"})


def selected_reference_prompt(root: Path) -> str:
    references = result_publication_references(root)
    return "\n".join(
        f"- {reference.kind.title()}~\\ref{{{reference.label}}}: {reference.scientific_role}"
        for reference in references
    ) or "No registered result references are available; do not invent a label or claim."


def selected_result_analysis_requirements(root: Path, requirements: dict[str, str]) -> dict[str, str]:
    """Keep prose checks for the actual selected figure/table union, not all seven roles."""
    roles = {reference.scientific_role for reference in result_publication_references(root)}
    selected = {}
    for name, pattern in requirements.items():
        normalized = name.casefold()
        if any(term in normalized for term in ("trajectory", "progression", "training trend", "convergence", "saturation")):
            applicable = bool(roles & {"training_dynamics", "analysis"})
        elif any(term in normalized for term in ("trade-off", "burden")):
            applicable = "efficiency" in roles
        elif any(term in normalized for term in ("error-slice", "negative-case", "counterexample")):
            applicable = "error_analysis" in roles
        elif any(term in normalized for term in ("ablation", "sensitivity", "necessity")):
            applicable = bool(roles & {"ablation", "sensitivity"})
        elif "robustness" in normalized or "stress" in normalized:
            applicable = "robustness" in roles
        elif "calibration" in normalized or "selective-risk" in normalized:
            applicable = "calibration" in roles
        else:
            applicable = True
        if applicable:
            selected[name] = pattern
    return selected
