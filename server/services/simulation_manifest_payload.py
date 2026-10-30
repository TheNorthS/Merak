"""Build the deterministic simulation manifest from explicit evidence inputs."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .figure_engine import PUBLICATION_STYLE_PROFILE
from .simulation_policy import SIMULATION_MANIFEST_SCHEMA, SIMULATION_RENDERER_VERSION


@dataclass(frozen=True)
class SimulationManifestContext:
    asset_profile: dict[str, Any]
    assets: dict[str, dict[str, str]]
    axis: str
    claim_evidence_map: dict[str, Any]
    claim_evidence_rows: list[dict[str, str]]
    claim_ids: list[str]
    configured_training_horizon: int | None
    data_paths: dict[str, Path]
    disclosure: str
    generator_source_path: Path
    holm_alpha: float
    holm_family_size: int
    join_coverage_rows: list[dict[str, str]]
    method_contract_snapshot: Path
    method_records: list[tuple[str, str]]
    metric_direction: str
    paired_rows: list[dict[str, str]]
    preview_figures: Path
    preview_table: Path
    primary_metric: str
    progression_axis: str
    progression_levels: list[int | float]
    publication_style: dict[str, Any]
    reference_row_count: int
    registered_axes: list[dict[str, Any]]
    rendered: list[dict[str, Any]]
    root: Path
    run_ledger_rows: list[dict[str, str]]
    run_spec_snapshot: Path
    scenario_config_snapshot: Path
    scenario_parameters_path: Path
    seed_ids: tuple[int, ...]
    simulation_id: str
    simulation_seed: str
    t_critical_95: float
    verifier_path: Path


def simulation_manifest_payload(context: SimulationManifestContext) -> dict[str, Any]:
    return {
        **_identity(context),
        **_claims(context),
        **_publication(context),
        **_files(context),
    }


def _identity(context: SimulationManifestContext) -> dict[str, Any]:
    return {
        "schema": SIMULATION_MANIFEST_SCHEMA,
        "renderer_version": SIMULATION_RENDERER_VERSION,
        "generated_at": time.time(),
        "simulation_id": context.simulation_id,
        "simulation_seed": context.simulation_seed,
        "simulation_kind": "deterministic_layout_scenario",
        "replicate_contract": {
            "unit": "random_seed",
            "seed_ids": list(context.seed_ids),
            "seed_count": len(context.seed_ids),
            "summary": "mean with two-sided 95% t interval",
            "critical_value": context.t_critical_95,
        },
        "registered_model_suite": [
            {"method": method, "model_id": model_id}
            for method, model_id in context.method_records
        ],
        "registered_ranking_axes": context.registered_axes,
        "registered_pair_contract": {
            "pairing": "all_unordered_pairs",
            "model_count": len(context.method_records),
            "axis_count": len(context.registered_axes),
            "expected_comparison_count": len(context.method_records)
            * max(0, len(context.method_records) - 1)
            // 2
            * len(context.registered_axes),
            "observed_comparison_count": len(context.paired_rows),
            "holm_alpha": context.holm_alpha,
            "holm_family_scope": "unordered_model_pairs_by_non_iid_target_axis",
            "holm_family_size": context.holm_family_size,
            "reference_row_count": context.reference_row_count,
            "test_method": "paired_student_t_two_sided",
            "complete": len(context.paired_rows)
            == len(context.method_records)
            * max(0, len(context.method_records) - 1)
            // 2
            * len(context.registered_axes),
        },
        "primary_metric": context.primary_metric,
        "metric_direction": context.metric_direction,
    }


def _claims(context: SimulationManifestContext) -> dict[str, Any]:
    return {
        "research_family": str(context.publication_style.get("family") or ""),
        "study_archetype": str(context.publication_style.get("study_archetype") or ""),
        "asset_domain": str(context.asset_profile["domain"]),
        "specialized_domain": str(
            context.asset_profile.get("specialized_domain") or ""
        ),
        "claim_ids": context.claim_ids,
        "claim_evidence_map": context.claim_evidence_map,
        "claim_evidence_contract": {
            "schema": 1,
            "data_file": "experiments/results/simulated/claim_evidence.csv",
            "rows": [
                {
                    "row_id": row["row_id"],
                    "claim_id": row["claim_id"],
                    "registered_outcome": row["registered_outcome"],
                    "evidence_kind": row["evidence_kind"],
                }
                for row in context.claim_evidence_rows
            ],
        },
        "evidence_package": _evidence_package(context),
        "explicit_user_mode": "synthetic_preview",
        "evidence_status": "synthetic_preview",
    }


def _publication(context: SimulationManifestContext) -> dict[str, Any]:
    return {
        "paper_selected": True,
        "manuscript_eligible": True,
        "submission_eligible": False,
        "disclosure": context.disclosure,
        "scientific_policy": "The complete domain-adapted benchmark package is bound to a deterministic generator; detailed generator identity and provenance remain in machine-readable sidecars.",
        "completeness_pack": [
            str(item["completeness_role"]) for item in context.assets.values()
        ],
        "asset_roles": [
            {
                "stable_role": str(item["completeness_role"]),
                "domain_role": str(item["domain_asset_role"]),
                "scientific_role": str(item["scientific_role"]),
                "label": str(item["label"]),
            }
            for item in context.assets.values()
        ],
        "domain_asset_profile": [
            {
                "stable_role": str(item["completeness_role"]),
                "domain_role": str(item["domain_asset_role"]),
                "semantic_id": f"synthetic_preview_{item['slug']}",
                "data_file": f"{item['slug']}.csv",
                "analysis_subtype": str(item["analysis_subtype"]),
                "plot_family": str(item["plot_family"]),
                "metric_direction": "minimize"
                if key in {"case_analysis", "coverage"}
                else context.metric_direction,
                "axis_field": str(context.asset_profile["progression_axis"])
                if key == "progression"
                else str(context.asset_profile["sensitivity_field"])
                if key == "sensitivity"
                else str(context.asset_profile["slice_field"])
                if key == "case_analysis"
                else context.axis
                if key == "robustness"
                else "coverage"
                if key == "coverage"
                else "resource_5"
                if key == "burden"
                else "method",
                "label": str(item["label"]),
            }
            for key, item in context.assets.items()
        ],
        "progression_kind": str(context.assets["progression"]["domain_asset_role"]),
        "progression_axis": str(context.asset_profile["progression_axis"]),
        "progression_contract": {
            "axis": context.progression_axis,
            "levels": list(context.progression_levels),
            "configured_training_horizon": context.configured_training_horizon,
            "horizon_source": "execution.max_epochs"
            if context.configured_training_horizon is not None
            else "domain_profile",
        },
        "error_slice_kind": str(context.assets["case_analysis"]["domain_asset_role"]),
    }


def _files(context: SimulationManifestContext) -> dict[str, Any]:
    return {
        "case_analysis_axis": str(context.asset_profile["slice_field"]),
        "visual_quality": {
            "palette": "colorblind-safe publication palette",
            "uncertainty": "95% fixed-configuration scenario intervals or bands; no population coverage claim",
            "vector_outputs": ["pdf", "svg"],
            "raster_output": "high-resolution PNG",
            "png_dpi": int(
                (context.publication_style.get("canvas") or {}).get("png_dpi") or 450
            ),
            "in_figure_disclosure": False,
            "repeated_caption_disclosure": False,
            "methods_disclosure": "",
        },
        "data_files": [
            {
                "path": path.relative_to(context.root).as_posix(),
                "sha256": _sha256_file(path),
            }
            for path in context.data_paths.values()
        ],
        "figure_files": [
            {
                "id": str(item["id"]),
                "producer_kind": item["producer_kind"],
                "publication_labels": item["publication_labels"],
                "scientific_role": str(item["role"]),
                "domain_asset_role": str(item["domain_asset_role"]),
                "analysis_subtype": str(item.get("analysis_subtype") or ""),
                "plot_family": str(item.get("plot_family") or ""),
                "metric_direction": str(item["metric_direction"]),
                "axis_field": str(item.get("axis_field") or ""),
                "label": str(item["label"]),
                "scientific_question": str(item["scientific_question"]),
                "claim_ids": list(item["claim_ids"]),
                "intended_comparison": str(item["intended_comparison"]),
                "visual_encoding": str(item["visual_encoding"]),
                "uncertainty_encoding": str(item["uncertainty_encoding"]),
                "style_profile": PUBLICATION_STYLE_PROFILE,
                "source": Path(item["script"]).relative_to(context.root).as_posix(),
                "source_sha256": _sha256_file(Path(item["script"])),
                "outputs": {
                    kind: path.relative_to(context.root).as_posix()
                    for kind, path in item["outputs"].items()
                },
                "output_sha256": {
                    kind: _sha256_file(path) for kind, path in item["outputs"].items()
                },
            }
            for item in context.rendered
        ],
        "paper_table": context.preview_table.relative_to(context.root).as_posix(),
        "paper_table_sha256": _sha256_file(context.preview_table),
        "paper_figures": context.preview_figures.relative_to(context.root).as_posix(),
        "paper_figures_sha256": _sha256_file(context.preview_figures),
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _evidence_package(context: SimulationManifestContext) -> dict[str, Any]:
    return {
    "schema": 1,
    "generator": "merak-deterministic-simulation-v3",
    "generator_seed": context.simulation_seed,
    "replicate_seeds": list(context.seed_ids),
    "run_level_results": "experiments/results/simulated/run_level_results.csv",
    "paired_comparisons": "experiments/results/simulated/paired_comparisons.csv",
    "run_ledger": "experiments/results/simulated/run_ledger.csv",
    "latency_samples": "experiments/results/simulated/latency_samples.csv",
    "registered_axis_results": "experiments/results/simulated/registered_axis_results.csv",
    "provenance_join_audit": "experiments/results/simulated/provenance_join_audit.csv",
    "runtime_artifacts": "experiments/results/simulated/runtime_artifacts.json",
    "data_manifest": "experiments/results/simulated/data_manifest.csv",
    "raw_checkpoints": "experiments/results/simulated/raw_checkpoints.jsonl",
    "raw_predictions": "experiments/results/simulated/raw_predictions.jsonl",
    "raw_measurements": "experiments/results/simulated/raw_measurements.jsonl",
    "generator_source": "experiments/results/simulated/reproducibility/generator_source.py",
    "generator_source_sha256": _sha256_file(context.generator_source_path),
    "scenario_parameters": "experiments/results/simulated/reproducibility/scenario_parameters.json",
    "scenario_parameters_sha256": _sha256_file(
        context.scenario_parameters_path
    ),
    "scenario_config": "experiments/results/simulated/reproducibility/scenario_config.yaml",
    "scenario_config_sha256": _sha256_file(context.scenario_config_snapshot),
    "run_spec": "experiments/results/simulated/reproducibility/run_spec.json",
    "run_spec_sha256": _sha256_file(context.run_spec_snapshot),
    "method_contract": "experiments/results/simulated/reproducibility/method_contract.json",
    "method_contract_sha256": _sha256_file(context.method_contract_snapshot),
    "reconstruction_tool": "experiments/results/simulated/reproducibility/verify_bundle.py",
    "reconstruction_tool_sha256": _sha256_file(context.verifier_path),
    "reconstruction_command": "python experiments/results/simulated/reproducibility/verify_bundle.py",
    "provenance_join_contract": {
        "ledger_rows": len(context.run_ledger_rows),
        "complete_rows": sum(
            (
                row.get("join_complete") == "true"
                for row in context.join_coverage_rows
            )
        ),
        "coverage": sum(
            (
                row.get("join_complete") == "true"
                for row in context.join_coverage_rows
            )
        )
        / len(context.join_coverage_rows)
        if context.join_coverage_rows
        else 0.0,
        "complete": bool(context.join_coverage_rows)
        and all(
            (
                row.get("join_complete") == "true"
                for row in context.join_coverage_rows
            )
        ),
    },
    "reconstruction_contract": f"Aggregate endpoints are arithmetic means of the registered seed-level values; two-sided t intervals use the recorded critical value; paired effects use matched seed identities; two-sided paired Student-t p-values for the {context.holm_family_size} non-i.i.d. target-axis comparisons are adjusted as the declared Holm family; i.i.d. reference rows remain outside that family.",
    "completion_rule": "Every registered row and seed has a completed ledger entry; negative decisions remain complete when all estimands, intervals, multiplicity fields, and exclusion states are present.",
    }
