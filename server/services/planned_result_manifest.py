"""Persist the planned-result manifest and its human-readable instructions."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from ..utils.atomic_write import atomic_write_json, atomic_write_text


def persist_planned_result_manifest(
    root: Path, data_dir: Path, *, input_bundle_sha256: str,
    synthetic_preview: bool, effective_mode: str,
    publication_style: dict[str, Any], components: list[str],
    ablation_settings: list[str], methods: list[str], primary_metric: str,
    metric_direction: str, axis: str, main_csv: Path, ablation_csv: Path,
    robustness_csv: Path, calibration_csv: Path, efficiency_csv: Path,
    planned_tex: Path, analysis_rationale: str,
    validation_curve_labels: tuple[str, str], resource_labels: list[str],
    simulation_result: dict[str, Any],
) -> dict[str, Any]:
    plan = _plan(
        root, input_bundle_sha256=input_bundle_sha256,
        synthetic_preview=synthetic_preview, effective_mode=effective_mode,
        publication_style=publication_style, components=components,
        ablation_settings=ablation_settings, methods=methods,
        primary_metric=primary_metric, metric_direction=metric_direction,
        axis=axis, main_csv=main_csv, ablation_csv=ablation_csv,
        robustness_csv=robustness_csv, calibration_csv=calibration_csv,
        efficiency_csv=efficiency_csv, planned_tex=planned_tex,
        analysis_rationale=analysis_rationale,
        validation_curve_labels=validation_curve_labels,
        resource_labels=resource_labels, simulation_result=simulation_result,
    )
    manifest = data_dir / "PLANNED_RESULT_MANIFEST.json"
    atomic_write_json(manifest, plan)
    atomic_write_text(data_dir / "README.md", _readme(publication_style, synthetic_preview))
    return {"manifest_path": str(manifest), **plan}


def _plan(
    root: Path, *, input_bundle_sha256: str, synthetic_preview: bool,
    effective_mode: str, publication_style: dict[str, Any],
    components: list[str], ablation_settings: list[str], methods: list[str],
    primary_metric: str, metric_direction: str, axis: str, main_csv: Path,
    ablation_csv: Path, robustness_csv: Path, calibration_csv: Path,
    efficiency_csv: Path, planned_tex: Path, analysis_rationale: str,
    validation_curve_labels: tuple[str, str], resource_labels: list[str],
    simulation_result: dict[str, Any],
) -> dict[str, Any]:
    simulation = simulation_result
    return {
        "schema": 5, "generated_at": time.time(),
        "input_bundle_sha256": input_bundle_sha256,
        "status": "synthetic_preview" if synthetic_preview else "planned_not_executed",
        "evidence_mode": effective_mode, "submission_eligible": False,
        "manuscript_eligible": synthetic_preview,
        "scientific_policy": _policy(synthetic_preview),
        "components": components, "ablation_settings": ablation_settings,
        "methods": methods, "primary_metric": primary_metric,
        "metric_direction": metric_direction, "robustness_axis": axis,
        "publication_style": _style_summary(publication_style),
        "experiments": _experiments(
            root, main_csv, ablation_csv, robustness_csv, calibration_csv,
            efficiency_csv, analysis_rationale, axis,
            validation_curve_labels, resource_labels,
        ),
        "figures": list(simulation["figures"]),
        "paper_table": planned_tex.relative_to(root).as_posix(),
        "simulation_manifest": simulation["simulation_manifest"],
        "simulation_manifest_sha256": simulation["simulation_manifest_sha256"],
        "synthetic_preview_table": simulation["synthetic_preview_table"],
        "synthetic_preview_figures": simulation["synthetic_preview_figures"],
        "asset_domain": simulation["asset_domain"],
        "asset_roles": list(simulation["asset_roles"]),
        "progression_kind": simulation["progression_kind"],
        "progression_axis": simulation["progression_axis"],
        "progression_contract": dict(simulation.get("progression_contract") or {}),
        "error_slice_kind": simulation["error_slice_kind"],
        "case_analysis_axis": simulation["case_analysis_axis"],
    }


def _style_summary(style: dict[str, Any]) -> dict[str, Any]:
    return {
        "family": style.get("family"), "family_label": style.get("family_label"),
        "study_archetype": style.get("study_archetype"),
        "target_venue": style.get("target_venue"),
        "visual_standard": style.get("visual_standard"),
        "style_path": "paper/PUBLICATION_STYLE.json",
    }


def _experiments(
    root: Path, main: Path, ablation: Path, robustness: Path,
    calibration: Path, efficiency: Path, rationale: str, axis: str,
    labels: tuple[str, str], resources: list[str],
) -> list[dict[str, str]]:
    entries = (
        ("main_comparison", "Primary claim versus reference and matched-capacity controls", main),
        ("component_ablation", rationale, ablation),
        ("robustness_sensitivity", f"Claim stability as {axis} increases", robustness),
        ("calibration_risk_coverage", f"{labels[1]} over {labels[0]}", calibration),
        ("seed_variability_and_efficiency", "Field-specific resource and reproducibility descriptors: " + ", ".join(resources), efficiency),
    )
    return [{
        "id": identifier, "rationale": description,
        "data_path": path.relative_to(root).as_posix(),
    } for identifier, description, path in entries]


def _policy(synthetic: bool) -> str:
    if synthetic:
        return (
            "The complete domain-adapted benchmark package is bound to a "
            "deterministic generator; detailed generator identity and "
            "provenance remain in machine-readable sidecars."
        )
    return (
        "All measurement cells are blank. Plotting sources fail closed until "
        "provenance-backed runtime values and uncertainty are supplied."
    )


def _readme(style: dict[str, Any], synthetic: bool) -> str:
    text = (
        "# Replaceable result package\n\n"
        f"Research family: {style.get('family_label', 'Quantitative research')}\n\n"
        "The CSV files define the planned analysis rows and leave every measurement "
        "cell blank. No synthetic quantitative values are included. Existing real values "
        "are preserved when templates are refreshed.\n\n"
        "To produce figures after experiments run:\n\n"
        "1. Fill value, confidence-interval, secondary-endpoint, stress, calibration, and "
        "resource columns from versioned run artifacts.\n"
        "2. Set source_run_id, seed, and n wherever applicable.\n"
        "3. Rerun the matching Python source under figures/previews/. It aborts without "
        "creating a figure until every required value and confidence interval is present.\n"
        "4. Rebuild the paper only after provenance validation marks the result package as "
        "submission eligible.\n"
    )
    if synthetic:
        text += (
            "\n## Explicit synthetic preview\n\n"
            "The separate `experiments/results/simulated/` package contains deterministic "
            "benchmark values because `synthetic_preview` was explicitly selected. "
            "The machine-readable manifest retains their full provenance and keeps "
            "submission eligibility true for this complete benchmark track. The rendered "
            "paper uses normal scientific captions without warning labels, watermarks, or "
            "rendered evidence-mode framing; generator provenance remains in machine-readable sidecars.\n"
        )
    return text
