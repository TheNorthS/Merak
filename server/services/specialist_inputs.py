"""Stable scientific-input identities for specialist subnodes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .specialist_catalog import SpecialistSpec


def input_relatives(node_id: str) -> tuple[str, ...]:
    stable = ("ideas/SELECTED_IDEA.json",)
    if node_id != "results":
        return stable
    return (
        *stable,
        "literature/survey.md", "literature/references.bib",
        "experiments/EXPERIMENT_PLAN.md", "experiments/METHOD_CONTRACT.json",
        "experiments/RUN_SPEC.json", "experiments/configs/main.yaml",
        "experiments/specialists/DOMAIN_METHODOLOGY.md",
        "experiments/specialists/DATA_QUALITY_AUDIT.md",
        "experiments/specialists/STATISTICAL_ANALYSIS_PLAN.md",
        "experiments/specialists/ABLATION_PLAN.md",
        "experiments/specialists/ETHICS_GOVERNANCE.md",
        "experiments/specialists/SYSTEM_PROFILE.md",
        "experiments/results/analysis.md",
        "experiments/results/templates/PLANNED_RESULT_MANIFEST.json",
        "experiments/results/templates/README.md",
    )


def scientific_input_bytes(path: Path) -> bytes:
    return canonical_scientific_input_bytes(path, path.read_bytes())


def canonical_scientific_input_bytes(path: Path, raw: bytes) -> bytes:
    """Project supplied source bytes without reading, writing or rebinding evidence.

The canonical current planned manifest owns paper-selection metadata, not
scientific outcomes. Only its typed figure-level selection flags are excluded;
other paths, schemas and scientific fields retain their existing identities.
"""
    if path.suffix.casefold() != ".json":
        return raw
    try:
        value = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError):
        return raw
    value = _without_planned_paper_selection(path, value)
    volatile = {
        "generated_at", "updated_at", "created_at", "input_bundle_sha256",
        "simulation_manifest_sha256", "output_bytes", "output_sha256",
        "source_sha256", "rendered_variant_sha256",
    }

    def project(item: Any) -> Any:
        if isinstance(item, dict):
            return {
                str(key): project(child) for key, child in item.items()
                if str(key).casefold() not in volatile
            }
        if isinstance(item, list):
            return [project(child) for child in item]
        return item

    return json.dumps(
        project(value), sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")


def _without_planned_paper_selection(path: Path, value: Any) -> Any:
    """Remove one producer-owned presentation field only from its exact schema."""
    if (path.parts[-4:] != ("experiments", "results", "templates", "PLANNED_RESULT_MANIFEST.json")
            or not isinstance(value, dict) or type(value.get("schema")) is not int or value["schema"] != 5):
        return value
    figures = value.get("figures")
    if not isinstance(figures, list) or not figures or any(
        not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"].strip()
        or not isinstance(item.get("metadata"), dict)
        or ("paper_selected" in item["metadata"] and type(item["metadata"]["paper_selected"]) is not bool)
        for item in figures
    ) or len({item["id"] for item in figures}) != len(figures):
        return value
    return {**value, "figures": [
        {**item, "metadata": {key: child for key, child in item["metadata"].items() if key != "paper_selected"}}
        for item in figures
    ]}


def specialist_input_digest(
    root: Path,
    style: dict[str, Any],
    spec: SpecialistSpec,
    options: dict[str, Any],
) -> str:
    digest = hashlib.sha256()
    digest.update(json.dumps({
        "family": style.get("family"),
        "study_archetype": style.get("study_archetype"),
        "target_venue": style.get("target_venue"),
        "evidence_mode": "executed" if options.get("run_experiment") is True
        else options.get("non_experiment_evidence_mode", "design_only"),
        "spec": spec.as_dict(),
    }, sort_keys=True, ensure_ascii=False).encode("utf-8"))
    for relative in input_relatives(spec.node_id):
        path = root / relative
        if path.is_file():
            digest.update(relative.encode("utf-8"))
            digest.update(scientific_input_bytes(path))
    return digest.hexdigest()
