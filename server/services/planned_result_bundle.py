"""Materialize provenance-empty result templates and deferred plot sources."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..utils.atomic_write import atomic_write_text
from .publication_labels import publication_metric_label


@dataclass(frozen=True)
class PlannedResultBundle:
    main_rows: list[dict[str, str]]
    ablation_rows: list[dict[str, str]]
    robustness_rows: list[dict[str, str]]
    calibration_rows: list[dict[str, str]]
    efficiency_rows: list[dict[str, str]]
    main_csv: Path
    ablation_csv: Path
    robustness_csv: Path
    calibration_csv: Path
    efficiency_csv: Path
    planned_tex: Path
    resource_labels: list[str]


def write_planned_result_bundle(
    service: Any, root: Path, *, methods: list[str], model_ids: dict[str, str],
    primary_metric: str, metric_direction: str,
    secondary_metric: str, calibration_metric: str, axis: str,
    levels: list[str], ablation_settings: list[str],
    registered_factors: list[str], matched_fields: list[Any],
    validation_labels: tuple[str, str], publication_style: dict[str, Any],
    archetype: str, analysis_rationale: str,
) -> PlannedResultBundle:
    data_dir, figure_dir, table_dir = _directories(root)
    main_rows = _main_rows(
        methods, model_ids, primary_metric, metric_direction,
        secondary_metric, calibration_metric, axis,
    )
    ablation_rows = _ablation_rows(
        ablation_settings, registered_factors, matched_fields,
        primary_metric, metric_direction,
    )
    robustness_methods = [methods[0], methods[-1]]
    robustness_rows = _robustness_rows(
        robustness_methods, model_ids, levels, axis, primary_metric, metric_direction,
    )
    calibration_rows = _calibration_rows(
        robustness_methods, model_ids, validation_labels,
    )
    resource_labels = _resource_labels(archetype)
    efficiency_rows = _efficiency_rows(
        methods, model_ids, resource_labels, primary_metric, metric_direction,
    )
    paths = _write_csvs(
        service, data_dir, main_rows, ablation_rows, robustness_rows,
        calibration_rows, efficiency_rows,
    )
    _write_deferred_plots(
        service, figure_dir, publication_style, axis,
        primary_metric, metric_direction, validation_labels,
    )
    planned_tex = _write_planning_tables(
        service, root, table_dir, paths, ablation_settings, axis, levels,
        methods, primary_metric, publication_style, analysis_rationale,
        validation_labels,
    )
    return PlannedResultBundle(
        main_rows, ablation_rows, robustness_rows, calibration_rows,
        efficiency_rows, *paths, planned_tex, resource_labels,
    )


def _directories(root: Path) -> tuple[Path, Path, Path]:
    paths = (
        root / "experiments" / "results" / "templates",
        root / "figures" / "previews",
        root / "paper" / "tables",
    )
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)
    return paths




def _main_rows(
    methods: list[str], model_ids: dict[str, str], metric: str,
    direction: str, secondary: str, calibration: str, axis: str,
) -> list[dict[str, str]]:
    return [{
        "row_id": f"main-{index}", "status": "planned",
        "dataset": "replace_with_dataset", "split": "test", "method": method,
        "model_id": model_ids.get(method, method), "seed": "replace_with_seed",
        "n": "", "metric": metric, "metric_direction": direction, "value": "",
        "ci_low": "", "ci_high": "", "secondary_metric": secondary,
        "secondary_value": "", "stress_metric": f"worst_{axis}",
        "stress_value": "", "calibration_metric": calibration,
        "calibration_value": "", "source_run_id": "",
    } for index, method in enumerate(methods, start=1)]


def _ablation_rows(
    settings: list[str], factors: list[str], matched_fields: list[Any],
    metric: str, direction: str,
) -> list[dict[str, str]]:
    rows = []
    matched = "|".join(str(value) for value in matched_fields if str(value).strip())
    for index, setting in enumerate(settings, start=1):
        changed = "none" if index == 1 else (
            factors[index - 2] if index - 2 < len(factors)
            else f"registered_factor_{index - 1}"
        )
        rows.append({
            "row_id": f"ablation-{index}", "status": "planned",
            "component_setting": setting, "changed_factor": changed,
            "single_factor_matched": "true", "matched_fields": matched,
            "seed": "replace_with_seed", "metric": metric,
            "metric_direction": direction, "value": "", "ci_low": "",
            "ci_high": "", "delta": "", "parameters_m": "",
            "source_run_id": "",
        })
    return rows


def _robustness_rows(
    methods: list[str], model_ids: dict[str, str], levels: list[str],
    axis: str, metric: str, direction: str,
) -> list[dict[str, str]]:
    return [{
        "row_id": f"robustness-{method_index}-{level_index}",
        "status": "planned", "method": method, axis: level,
        "model_id": model_ids.get(method, method), "seed": "replace_with_seed",
        "metric": metric, "metric_direction": direction, "value": "",
        "ci_low": "", "ci_high": "", "source_run_id": "",
    } for method_index, method in enumerate(methods, start=1)
      for level_index, level in enumerate(levels, start=1)]


def _calibration_rows(
    methods: list[str], model_ids: dict[str, str], labels: tuple[str, str],
) -> list[dict[str, str]]:
    coverages = ("0.50", "0.65", "0.80", "0.90", "1.00")
    return [{
        "row_id": f"calibration-{method_index}-{coverage_index}",
        "status": "planned", "method": method,
        "model_id": model_ids.get(method, method), "coverage": coverage,
        "metric": labels[1], "metric_direction": "minimize", "value": "",
        "ci_low": "", "ci_high": "", "source_run_id": "",
    } for method_index, method in enumerate(methods, start=1)
      for coverage_index, coverage in enumerate(coverages, start=1)]


def _resource_labels(archetype: str) -> list[str]:
    labels = {
        "algorithm_benchmark": ["Parameters (M)", "GFLOPs", "Latency (ms)", "Peak memory (GB)", "GPU-hours"],
        "systems_testbed": ["Binary / model size", "Throughput", "Tail latency", "Peak memory", "Energy / cost"],
        "observational_cohort": ["Development N", "Validation N", "Variables", "Missingness (%)", "Analysis time"],
        "diagnostic_prognostic": ["Development N", "External N", "Predictors", "Missingness (%)", "Analysis time"],
        "intervention_trial": ["Randomized N", "Follow-up N", "Adherence (%)", "Missing outcome (%)", "Analysis time"],
        "omics_discovery": ["Samples", "Features after QC", "Peak memory", "Runtime", "Artifact size"],
        "controlled_experiment": ["Biological replicates", "Technical replicates", "Assay duration", "Instrument time", "Analysis time"],
        "simulation_modeling": ["Resolution / cells", "Solver tolerance", "Runtime", "Peak memory", "CPU/GPU-hours"],
        "formal_theory": ["Assumptions", "Auxiliary lemmas", "Proof length", "Checker time", "Artifact size"],
        "qualitative_mixed": ["Cases", "Coders", "Source documents", "Double-coded (%)", "Analysis time"],
        "generic_empirical": ["Primary N", "Validation N", "Variables / conditions", "Runtime", "Artifact size"],
    }
    return labels[archetype]


def _efficiency_rows(
    methods: list[str], model_ids: dict[str, str], labels: list[str],
    metric: str, direction: str,
) -> list[dict[str, str]]:
    return [{
        "row_id": f"efficiency-{index}", "status": "planned", "method": method,
        "model_id": model_ids.get(method, method), "parameters_m": "",
        "flops_g": "", "latency_ms": "", "peak_memory_gb": "",
        "gpu_hours": "", **{
            f"resource_{position + 1}_label": labels[position]
            for position in range(5)
        }, **{f"resource_{position + 1}": "" for position in range(5)},
        "metric": metric, "metric_direction": direction, "value": "",
        "source_run_id": "",
    } for index, method in enumerate(methods, start=1)]


def _write_csvs(
    service: Any, data_dir: Path, main: list[dict[str, str]],
    ablation: list[dict[str, str]], robustness: list[dict[str, str]],
    calibration: list[dict[str, str]], efficiency: list[dict[str, str]],
) -> tuple[Path, Path, Path, Path, Path]:
    paths = tuple(data_dir / name for name in (
        "main_comparison.csv", "ablation.csv", "robustness_sensitivity.csv",
        "calibration_risk_coverage.csv", "efficiency.csv",
    ))
    for path, rows in zip(paths, (main, ablation, robustness, calibration, efficiency)):
        service._write_csv(path, rows)
    return paths  # type: ignore[return-value]


def _write_deferred_plots(
    service: Any, figure_dir: Path, style: dict[str, Any],
    axis: str, metric: str,
    direction: str, labels: tuple[str, str],
) -> None:
    metric_label = (
        f"{publication_metric_label(metric)} "
        f"({'higher' if direction == 'maximize' else 'lower'} is better)"
    )
    scripts = {
        "main_comparison_preview.py": service._bar_script(
            "experiments/results/templates/main_comparison.csv", "method",
            metric_label, "main_comparison_preview", style,
        ),
        "robustness_curve_preview.py": service._robustness_script(
            "experiments/results/templates/robustness_sensitivity.csv",
            axis, metric_label, style,
        ),
        "calibration_risk_coverage_preview.py": service._risk_coverage_script(
            "experiments/results/templates/calibration_risk_coverage.csv",
            style, labels[0], labels[1],
        ),
    }
    for filename, code in scripts.items():
        atomic_write_text(figure_dir / filename, code)


def _write_planning_tables(
    service: Any, root: Path, table_dir: Path,
    paths: tuple[Path, Path, Path, Path, Path], settings: list[str], axis: str,
    levels: list[str], methods: list[str], metric: str, style: dict[str, Any],
    rationale: str, labels: tuple[str, str],
) -> Path:
    planned_tex = table_dir / "planned_result_templates.tex"
    atomic_write_text(planned_tex, service._tables(settings, axis, levels, methods, metric, style))
    purposes = (
        "Primary comparison plus matched-capacity control", rationale,
        f"Robustness across {axis}", f"{labels[1]} over {labels[0]}",
        "Field-specific resource, acquisition, and reproducibility accounting",
    )
    rows = [{
        "template": name, "data_path": path.relative_to(root).as_posix(),
        "status": "planned", "purpose": purpose,
    } for name, path, purpose in zip((
        "main_comparison", "ablation", "robustness_sensitivity",
        "calibration_risk_coverage", "efficiency",
    ), paths, purposes)]
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=["template", "data_path", "status", "purpose"])
    writer.writeheader()
    writer.writerows(rows)
    atomic_write_text(table_dir / "planned_result_templates.csv", buffer.getvalue(), encoding="utf-8-sig")
    return planned_tex
