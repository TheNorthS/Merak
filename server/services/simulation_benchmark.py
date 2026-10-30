"""Coordinate the deterministic benchmark through explicit typed stage results."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

from ..utils.atomic_write import atomic_write_json, atomic_write_text
from .simulation_analysis_rows import (
    build_ablation_rows,
    build_calibration_rows,
    build_efficiency_rows,
    build_progression_rows,
    build_robustness_rows,
)
from .simulation_claim_evidence import claim_evidence_rows, latency_rows
from .simulation_evidence_helpers import bind_seed_replicates
from .simulation_primary_comparison import PrimaryComparison, build_primary_comparison
from .experiment_placeholder_context import json_object
from .simulation_ranking_evidence import (
    RankingEvidence,
    align_efficiency_rows,
    materialize_ranking_evidence,
    paired_ranking_rows,
)
from .simulation_run_evidence import SimulationRunEvidence, materialize_run_evidence
from .simulation_runtime_artifacts import (
    RuntimeArtifactBundle,
    materialize_runtime_artifacts,
)
from .simulation_reproducibility import materialize_reproducibility_bundle
from .simulation_render_specs import build_render_specs
from .simulation_render_bundle import render_simulation_bundle
from .simulation_manifest_payload import (
    SimulationManifestContext,
    simulation_manifest_payload,
)
from .simulation_publication_registry import (
    register_simulation_figures,
    simulation_result,
)
from .simulation_scenario import SimulationScenario, prepare_simulation_scenario

Row = dict[str, str]


@dataclass(frozen=True)
class BenchmarkAnalysis:
    primary: PrimaryComparison
    ablation: list[Row]
    robustness: list[Row]
    calibration: list[Row]
    efficiency: list[Row]
    progression: list[Row]
    cases: list[Row]
    use_eeg_shift: bool
    metric: str
    direction: str

    def evidence_sources(self) -> dict[str, list[Row]]:
        return {
            "main_comparison": self.primary.rows,
            "component_ablation": self.ablation,
            "training_dynamics": self.progression,
            "robustness_sensitivity": self.robustness,
            "error_analysis": self.cases,
            "calibration_risk_coverage": self.calibration,
            "efficiency_tradeoff": self.efficiency,
        }


@dataclass(frozen=True)
class BenchmarkEvidence:
    runs: SimulationRunEvidence
    ranking: RankingEvidence
    paired: list[Row]
    claims: list[Row]
    latency: list[Row]
    runtime: RuntimeArtifactBundle
    reference_count: int
    holm_family_size: int


@dataclass(frozen=True)
class BenchmarkRender:
    figures: list[dict[str, Any]]
    table: Path
    paper_figures: Path
    claim_map: dict[str, Any]


async def build_simulation_benchmark(
    service: Any,
    *,
    root: Path,
    publication_style: dict[str, Any],
    direction: str,
    main_rows: list[Row],
    ablation_rows: list[Row],
    robustness_rows: list[Row],
    calibration_rows: list[Row],
    efficiency_rows: list[Row],
    claim_ids: list[str],
    axis: str,
    primary_metric: str,
    metric_direction: str,
    validation_curve_labels: tuple[str, str],
) -> dict[str, Any]:
    scenario = prepare_simulation_scenario(
        root,
        publication_style,
        direction,
        validation_curve_labels,
        primary_metric,
        metric_direction,
    )
    analysis = _analysis(
        root,
        scenario,
        publication_style,
        main_rows,
        ablation_rows,
        robustness_rows,
        calibration_rows,
        efficiency_rows,
        primary_metric,
        metric_direction,
    )
    evidence = _evidence(root, scenario, analysis, claim_ids, service._write_csv)
    _reproducibility(root, scenario, analysis, evidence)
    rendered = await _render(
        service,
        root,
        scenario,
        analysis,
        evidence,
        claim_ids,
        publication_style,
        axis,
        validation_curve_labels,
    )
    manifest, digest = _persist_manifest(
        root,
        scenario,
        analysis,
        evidence,
        rendered,
        publication_style,
        claim_ids,
        axis,
    )
    return _publication_result(
        root,
        scenario,
        analysis,
        rendered,
        manifest,
        digest,
        publication_style,
    )


def _simulate(scenario: SimulationScenario, row: dict[str, Any]) -> Row:
    return {
        **{str(key): str(value) for key, value in row.items()},
        "status": "synthetic_preview",
        "simulation_kind": "deterministic_layout_scenario",
        "simulation_seed": scenario.simulation_seed,
        "source_run_id": scenario.source_run_id,
    }


def _analysis(
    root: Path,
    scenario: SimulationScenario,
    style: dict[str, Any],
    main: list[Row],
    ablation: list[Row],
    robustness: list[Row],
    calibration: list[Row],
    efficiency: list[Row],
    metric: str,
    direction: str,
) -> BenchmarkAnalysis:
    simulate = partial(_simulate, scenario)
    profile = scenario.asset_profile
    primary = build_primary_comparison(
        main,
        ablation,
        profile,
        direction,
        metric,
        scenario.simulation_seed,
        scenario.has_registered_ablation_contract,
        json_object(root / "experiments" / "RUN_SPEC.json"),
        simulate,
    )
    maximize = direction == "maximize"
    anchor = float(primary.rows[-1]["value"])
    ablation_values = build_ablation_rows(
        primary.ablation_rows,
        scenario.configured_method,
        anchor,
        maximize,
        scenario.simulation_seed,
        direction,
        profile,
        simulate,
    )
    robustness_values = build_robustness_rows(
        robustness,
        maximize,
        scenario.simulation_seed,
        direction,
        simulate,
    )
    calibration_values = build_calibration_rows(calibration, profile, simulate)
    efficiency_values = build_efficiency_rows(
        efficiency, primary.rows, style, metric, direction, simulate
    )
    progression = build_progression_rows(
        primary.rows, profile, maximize, scenario.assets, metric, direction, simulate
    )
    cases = _case_rows(primary.rows[-1]["method"], profile, simulate)
    for rows in (
        ablation_values,
        progression,
        robustness_values,
        cases,
        calibration_values,
        efficiency_values,
    ):
        bind_seed_replicates(rows, primary.seed_ids, primary.critical_value)
    use_eeg = _uses_eeg_shift(profile, robustness)
    return BenchmarkAnalysis(
        primary,
        ablation_values,
        robustness_values,
        calibration_values,
        efficiency_values,
        progression,
        cases,
        use_eeg,
        metric,
        direction,
    )


def _uses_eeg_shift(profile: dict[str, Any], rows: list[Row]) -> bool:
    return bool(profile.get("specialized_domain") == "eeg" and rows and all(
        str(row.get("shift_axis") or "").strip()
        and str(row.get("shift_condition") or "").strip()
        for row in rows
    ))


def _case_rows(method: str, profile: dict[str, Any], simulate: Any) -> list[Row]:
    metric = str(profile["slice_metric"])
    profile["slice_metric_axis_label"] = f"{metric} (lower is better)"
    return [
        simulate(
            {
                "row_id": f"case-analysis-{index}",
                "method": method,
                str(profile["slice_field"]): label,
                "n": str(size),
                "metric": metric,
                "metric_direction": "minimize",
                "value": f"{value:.3f}",
                "ci_low": f"{max(0.0, value - width):.3f}",
                "ci_high": f"{min(1.0, value + width):.3f}",
            }
        )
        for index, (label, size, value, width) in enumerate(
            profile["slice_scenarios"], start=1
        )
    ]


def _evidence(
    root: Path,
    scenario: SimulationScenario,
    analysis: BenchmarkAnalysis,
    claim_ids: list[str],
    write_csv: Any,
) -> BenchmarkEvidence:
    simulate = partial(_simulate, scenario)
    seeds = analysis.primary.seed_ids
    runs = materialize_run_evidence(
        root,
        analysis.evidence_sources(),
        scenario.simulation_id,
        scenario.source_run_id,
        seeds,
        analysis.metric,
        analysis.direction,
        scenario.configured_contract,
        scenario.configured_method,
        simulate,
        write_csv,
    )
    ranking = materialize_ranking_evidence(
        simulated_main=analysis.primary.rows,
        registered_axes=scenario.registered_axes,
        seed_ids=seeds,
        source_run_id=scenario.source_run_id,
        simulate=simulate,
        provenance=runs.provenance,
        primary_axis=scenario.primary_reference_axis,
        run_level_rows=runs.rows,
        run_ledger_rows=runs.ledger,
    )
    count = len(ranking.methods) * max(0, len(ranking.methods) - 1) // 2
    reference_count = count * sum(
        scenario.primary_reference_axis(item) for item in scenario.registered_axes
    )
    family_size = count * len(scenario.registered_axes) - reference_count
    align_efficiency_rows(
        analysis.efficiency, scenario.registered_axes, ranking.axis_values
    )
    paired = paired_ranking_rows(
        ranking,
        scenario.registered_axes,
        seeds,
        scenario.holm_alpha,
        scenario.primary_reference_axis,
        simulate,
        critical_value=analysis.primary.critical_value,
    )
    latency = latency_rows(
        analysis.efficiency,
        seeds,
        scenario.source_run_id,
        runs.hardware_contract_id,
        runs.software_image,
        simulate,
    )
    claims = claim_evidence_rows(
        claim_ids=claim_ids,
        method_contract=scenario.method_contract,
        selected_contract=scenario.selected_contract,
        paired_rows=paired,
        anchor=float(analysis.primary.rows[-1]["value"]),
        maximize_primary=analysis.direction == "maximize",
        primary_metric=analysis.metric,
        metric_direction=analysis.direction,
        simulate=simulate,
        paired_contract={"model_ids": [model_id for _method, model_id in ranking.methods],
                         "seed_ids": list(seeds), "axes": scenario.registered_axes,
                         "holm_alpha": scenario.holm_alpha},
    )
    bind_seed_replicates(claims, seeds, analysis.primary.critical_value)
    runtime = _runtime(
        scenario, analysis, runs, ranking, paired, claims, latency, write_csv, simulate
    )
    return BenchmarkEvidence(
        runs, ranking, paired, claims, latency, runtime, reference_count, family_size
    )


def _runtime(
    scenario: SimulationScenario,
    analysis: BenchmarkAnalysis,
    runs: SimulationRunEvidence,
    ranking: RankingEvidence,
    paired: list[Row],
    claims: list[Row],
    latency: list[Row],
    write_csv: Any,
    simulate: Any,
) -> RuntimeArtifactBundle:
    roles = (
        "main",
        "sensitivity",
        "progression",
        "robustness",
        "case_analysis",
        "coverage",
        "burden",
    )
    groups = (
        analysis.primary.rows,
        analysis.ablation,
        analysis.progression,
        analysis.robustness,
        analysis.cases,
        analysis.calibration,
        analysis.efficiency,
    )
    data = {
        f"{scenario.assets[role]['slug']}.csv": rows
        for role, rows in zip(roles, groups)
    }
    data.update(
        {
            "claim_evidence.csv": claims,
            "run_level_results.csv": runs.rows,
            "paired_comparisons.csv": paired,
            "run_ledger.csv": runs.ledger,
            "latency_samples.csv": latency,
            "registered_axis_results.csv": ranking.axis_rows,
        }
    )
    return materialize_runtime_artifacts(
        simulated_data=scenario.simulated_data,
        simulation_id=scenario.simulation_id,
        software_image=runs.software_image,
        hardware_contract_id=runs.hardware_contract_id,
        run_level_rows=runs.rows,
        run_ledger_rows=runs.ledger,
        data_rows=data,
        frozen_data_manifest=runs.frozen_manifest,
        write_csv=write_csv,
        simulate=simulate,
    )


def _reproducibility(
    root: Path,
    scenario: SimulationScenario,
    analysis: BenchmarkAnalysis,
    evidence: BenchmarkEvidence,
) -> None:
    evidence.runtime.data_paths.update(
        materialize_reproducibility_bundle(
            root,
            scenario.simulated_data,
            generator_source=Path(__file__),
            simulation_id=scenario.simulation_id,
            simulation_seed=scenario.simulation_seed,
            seed_ids=analysis.primary.seed_ids,
            method_records=evidence.ranking.methods,
            registered_axes=scenario.registered_axes,
            holm_family_size=evidence.holm_family_size,
            holm_alpha=scenario.holm_alpha,
        )
    )


async def _render(
    service: Any,
    root: Path,
    scenario: SimulationScenario,
    analysis: BenchmarkAnalysis,
    evidence: BenchmarkEvidence,
    claim_ids: list[str],
    style: dict[str, Any],
    axis: str,
    validation_labels: tuple[str, str],
) -> BenchmarkRender:
    profile = scenario.asset_profile
    specs = build_render_specs(
        service,
        assets=scenario.assets,
        asset_profile=profile,
        data_paths=evidence.runtime.data_paths,
        simulated_figures=scenario.simulated_figures,
        claim_ids=claim_ids,
        primary_metric=analysis.metric,
        primary_metric_axis_label=scenario.primary_metric_axis_label,
        metric_direction=analysis.direction,
        publication_style=style,
        progression_axis=str(profile["progression_axis"]),
        axis=axis,
        slice_field=str(profile["slice_field"]),
        slice_metric_axis_label=str(profile["slice_metric_axis_label"]),
        validation_curve_labels=validation_labels,
        coverage_y_axis_label=scenario.coverage_y_axis_label,
        simulated_ablation=analysis.ablation,
        simulated_efficiency=analysis.efficiency,
        use_eeg_shift_renderer=analysis.use_eeg_shift,
    )
    products = await render_simulation_bundle(
        root=root,
        render_specs=specs,
        metric_direction=analysis.direction,
        render_script=service._render,
        simulation_tables=service._simulation_tables,
        figures_tex=service._simulation_figures_tex,
        simulated_main=analysis.primary.rows,
        simulated_ablation=analysis.ablation,
        simulated_robustness=analysis.robustness,
        simulated_calibration=analysis.calibration,
        simulated_efficiency=analysis.efficiency,
        simulated_case_analysis=analysis.cases,
        claim_evidence_rows=evidence.claims,
        paired_rows=evidence.paired,
        axis=axis,
        metric_label=scenario.primary_metric_axis_label,
        asset_profile=profile,
        claim_ids=claim_ids,
        table_dir=scenario.table_dir,
    )
    return BenchmarkRender(*products)


def _persist_manifest(
    root: Path,
    scenario: SimulationScenario,
    analysis: BenchmarkAnalysis,
    evidence: BenchmarkEvidence,
    rendered: BenchmarkRender,
    style: dict[str, Any],
    claim_ids: list[str],
    axis: str,
) -> tuple[Path, str]:
    paths = evidence.runtime.data_paths
    profile = scenario.asset_profile
    context = SimulationManifestContext(
        asset_profile=profile,
        assets=scenario.assets,
        axis=axis,
        claim_evidence_map=rendered.claim_map,
        claim_evidence_rows=evidence.claims,
        claim_ids=claim_ids,
        configured_training_horizon=scenario.configured_training_horizon,
        data_paths=paths,
        disclosure=scenario.disclosure,
        generator_source_path=paths["generator_source.py"],
        holm_alpha=scenario.holm_alpha,
        holm_family_size=evidence.holm_family_size,
        join_coverage_rows=evidence.runtime.join_coverage_rows,
        method_contract_snapshot=paths["method_contract.json"],
        method_records=evidence.ranking.methods,
        metric_direction=analysis.direction,
        paired_rows=evidence.paired,
        preview_figures=rendered.paper_figures,
        preview_table=rendered.table,
        primary_metric=analysis.metric,
        progression_axis=str(profile["progression_axis"]),
        progression_levels=list(profile["progression_levels"]),
        publication_style=style,
        reference_row_count=evidence.reference_count,
        registered_axes=scenario.registered_axes,
        rendered=rendered.figures,
        root=root,
        run_ledger_rows=evidence.runs.ledger,
        run_spec_snapshot=paths["run_spec.json"],
        scenario_config_snapshot=paths["scenario_config.yaml"],
        scenario_parameters_path=paths["scenario_parameters.json"],
        seed_ids=analysis.primary.seed_ids,
        simulation_id=scenario.simulation_id,
        simulation_seed=scenario.simulation_seed,
        t_critical_95=analysis.primary.critical_value,
        verifier_path=paths["verify_bundle.py"],
    )
    manifest = scenario.simulated_data / "SIMULATION_MANIFEST.json"
    atomic_write_json(manifest, simulation_manifest_payload(context))
    atomic_write_text(scenario.simulated_data / "README.md", _readme(scenario))
    return manifest, _sha256(manifest)


def _publication_result(
    root: Path,
    scenario: SimulationScenario,
    analysis: BenchmarkAnalysis,
    rendered: BenchmarkRender,
    manifest: Path,
    digest: str,
    style: dict[str, Any],
) -> dict[str, Any]:
    figures = register_simulation_figures(
        root,
        rendered.figures,
        style,
        scenario.simulation_id,
        scenario.simulation_seed,
        scenario.disclosure,
        manifest,
        digest,
    )
    profile = scenario.asset_profile
    return simulation_result(
        root,
        manifest,
        digest,
        rendered.table,
        rendered.paper_figures,
        profile,
        scenario.assets,
        str(profile["progression_axis"]),
        list(profile["progression_levels"]),
        scenario.configured_training_horizon,
        str(profile["slice_field"]),
        analysis.metric,
        analysis.direction,
        figures,
    )


def _readme(scenario: SimulationScenario) -> str:
    return (
        "# Synthetic simulation preview\n\n"
        "These files were generated only because `synthetic_preview` was explicitly selected.\n\n"
        "They are deterministic scenarios that support findings within the defined benchmark; after manifest and hash validation, they form the complete quantitative package for the selected paper track.\n\n"
        f"The {scenario.asset_profile['domain']} completeness pack covers {scenario.asset_profile['summary']}. "
        "Every inferential figure carries uncertainty and is rendered as vector PDF/SVG plus high-resolution PNG. Generator identity, seed, run identity, and eligibility remain exclusively in machine-readable sidecars. Charts, captions, tables, and manuscript prose contain no warning labels or watermarks and expose no evidence-mode framing.\n"
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
