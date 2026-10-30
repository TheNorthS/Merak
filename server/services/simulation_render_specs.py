"""Build the seven domain-adapted simulation figure render specifications."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .publication_labels import publication_metric_label
from .publication_figure_labels import concept_labels


def build_render_specs(
    service: Any, *, assets: dict[str, dict[str, str]],
    asset_profile: dict[str, Any], data_paths: dict[str, Path],
    simulated_figures: Path, claim_ids: list[str], primary_metric: str,
    primary_metric_axis_label: str, metric_direction: str,
    publication_style: dict[str, Any], progression_axis: str, axis: str,
    slice_field: str, slice_metric_axis_label: str,
    validation_curve_labels: tuple[str, str], coverage_y_axis_label: str,
    simulated_ablation: list[dict[str, str]],
    simulated_efficiency: list[dict[str, str]], use_eeg_shift_renderer: bool,
) -> list[dict[str, Any]]:
    common = (assets, asset_profile, data_paths, simulated_figures, claim_ids)
    specs = [
        _main(service, *common, primary_metric, primary_metric_axis_label,
              metric_direction, publication_style),
        _sensitivity(service, *common, primary_metric_axis_label,
                     metric_direction, publication_style, simulated_ablation),
        _progression(service, *common, progression_axis,
                     primary_metric_axis_label, publication_style),
        _robustness(service, *common, axis, primary_metric_axis_label,
                    publication_style, use_eeg_shift_renderer),
        _case_analysis(service, *common, slice_field, slice_metric_axis_label,
                       publication_style),
        _coverage(service, *common, validation_curve_labels,
                  coverage_y_axis_label, publication_style),
        _burden(service, *common, primary_metric_axis_label, metric_direction,
                publication_style, simulated_efficiency),
    ]
    metric_labels = [
        publication_metric_label(primary_metric)
        if asset_profile.get('specialized_domain') in {'eeg', 'vision', 'language', 'timeseries'}
        else primary_metric_axis_label,
        primary_metric_axis_label, primary_metric_axis_label,
        primary_metric_axis_label, slice_metric_axis_label,
        coverage_y_axis_label, primary_metric_axis_label,
    ]
    for spec, metric_label in zip(specs, metric_labels, strict=True):
        spec['producer_kind'] = 'deterministic'
        spec['publication_labels'] = concept_labels(
            [metric_label], namespace=spec['id'], kind='metric',
        )
    return specs


def _base(
    asset: dict[str, str], data_paths: dict[str, Path], directory: Path,
    claim_ids: list[str], axis_field: str, band: bool = False,
) -> dict[str, Any]:
    slug = asset["slug"]
    return {
        "id": f"synthetic_preview_{slug}", "role": asset["scientific_role"],
        "domain_asset_role": asset["domain_asset_role"],
        "analysis_subtype": asset["analysis_subtype"], "axis_field": axis_field,
        "label": asset["label"], "description": asset["description"],
        "scientific_question": asset["scientific_question"],
        "claim_ids": claim_ids, "intended_comparison": asset["intended_comparison"],
        "visual_encoding": asset["visual_encoding"], "plot_family": asset["plot_family"],
        "uncertainty_encoding": (
            "Pointwise two-sided 95% bands encoded by ci_low and ci_high."
            if band else
            "Two-sided 95% intervals encoded by the ci_low and ci_high fields."
        ),
        "data": data_paths[f"{slug}.csv"],
        "script": directory / f"simulated_{slug}.py", "stem": f"simulated_{slug}",
    }


def _main(
    service: Any, assets: dict[str, dict[str, str]], profile: dict[str, Any],
    paths: dict[str, Path], directory: Path, claims: list[str], metric: str,
    metric_label: str, direction: str, style: dict[str, Any],
) -> dict[str, Any]:
    spec = _base(assets["main"], paths, directory, claims, "method")
    relative = f"experiments/results/simulated/{assets['main']['slug']}.csv"
    specialized = profile.get("specialized_domain") in {"eeg", "vision", "language", "timeseries"}
    spec["code"] = (
        service._multitask_matrix_script(
            relative, publication_metric_label(metric), spec["stem"], style, direction,
        ) if specialized else service._bar_script(
            relative, "method", metric_label, spec["stem"], style, variant="ranked",
        )
    )
    return spec


def _sensitivity(
    service: Any, assets: dict[str, dict[str, str]], profile: dict[str, Any],
    paths: dict[str, Path], directory: Path, claims: list[str], metric: str,
    direction: str, style: dict[str, Any], rows: list[dict[str, str]],
) -> dict[str, Any]:
    field = str(profile["sensitivity_field"])
    spec = _base(assets["sensitivity"], paths, directory, claims, field)
    spec["code"] = service._ablation_delta_script(
        f"experiments/results/simulated/{assets['sensitivity']['slug']}.csv",
        field, metric, spec["stem"], style, rows[0][field], direction,
    )
    return spec


def _progression(
    service: Any, assets: dict[str, dict[str, str]], profile: dict[str, Any],
    paths: dict[str, Path], directory: Path, claims: list[str], axis: str,
    metric: str, style: dict[str, Any],
) -> dict[str, Any]:
    spec = _base(assets["progression"], paths, directory, claims, axis, True)
    relative = f"experiments/results/simulated/{assets['progression']['slug']}.csv"
    spec["code"] = (
        service._eeg_scaling_script(relative, axis, metric, style, spec["stem"])
        if profile.get("specialized_domain") == "eeg"
        else service._robustness_script(relative, axis, metric, style, spec["stem"])
    )
    return spec


def _robustness(
    service: Any, assets: dict[str, dict[str, str]], profile: dict[str, Any],
    paths: dict[str, Path], directory: Path, claims: list[str], axis: str,
    metric: str, style: dict[str, Any], use_eeg: bool,
) -> dict[str, Any]:
    del profile
    spec = _base(assets["robustness"], paths, directory, claims, axis, True)
    relative = f"experiments/results/simulated/{assets['robustness']['slug']}.csv"
    spec["code"] = (
        service._eeg_shift_script(relative, metric, spec["stem"], style)
        if use_eeg else
        service._robustness_script(relative, axis, metric, style, spec["stem"])
    )
    return spec


def _case_analysis(
    service: Any, assets: dict[str, dict[str, str]], profile: dict[str, Any],
    paths: dict[str, Path], directory: Path, claims: list[str], field: str,
    metric: str, style: dict[str, Any],
) -> dict[str, Any]:
    spec = _base(assets["case_analysis"], paths, directory, claims, field)
    relative = f"experiments/results/simulated/{assets['case_analysis']['slug']}.csv"
    specialized = profile.get("specialized_domain") in {"eeg", "vision", "language", "timeseries"}
    spec["code"] = (
        service._domain_error_heatmap_script(relative, field, metric, spec["stem"], style)
        if specialized else service._slice_risk_bar_script(
            relative, field, metric, spec["stem"], style,
            str(profile["slice_scenarios"][0][0]),
        )
    )
    return spec


def _coverage(
    service: Any, assets: dict[str, dict[str, str]], profile: dict[str, Any],
    paths: dict[str, Path], directory: Path, claims: list[str],
    labels: tuple[str, str], y_label: str, style: dict[str, Any],
) -> dict[str, Any]:
    del profile
    spec = _base(assets["coverage"], paths, directory, claims, "coverage", True)
    spec["code"] = service._risk_coverage_script(
        f"experiments/results/simulated/{assets['coverage']['slug']}.csv",
        style, labels[0], y_label, spec["stem"],
    )
    return spec


def _burden(
    service: Any, assets: dict[str, dict[str, str]], profile: dict[str, Any],
    paths: dict[str, Path], directory: Path, claims: list[str], metric: str,
    direction: str, style: dict[str, Any], rows: list[dict[str, str]],
) -> dict[str, Any]:
    del profile
    spec = _base(assets["burden"], paths, directory, claims, "resource_5")
    spec["uncertainty_encoding"] = "Vertical two-sided 95% intervals encoded by ci_low and ci_high."
    spec["code"] = service._efficiency_script(
        f"experiments/results/simulated/{assets['burden']['slug']}.csv",
        metric, "resource_5", rows[0]["resource_5_label"], style,
        spec["stem"], direction,
    )
    return spec
