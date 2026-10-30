"""Pure generation of simulation ablation, robustness, calibration, and analysis rows."""

from __future__ import annotations

from typing import Any, Callable

Row = dict[str, str]
Simulate = Callable[[dict[str, Any]], Row]


def build_ablation_rows(
    ablation_rows: list[Row],
    configured_method: dict[str, Any],
    anchor: float,
    maximize_primary: bool,
    simulation_seed: str,
    metric_direction: str,
    asset_profile: dict[str, Any],
    simulated: Simulate,
) -> list[Row]:
    simulated_ablation: list[dict[str, str]] = []
    ablation_contract = configured_method.get("ablations")
    ablation_contract = ablation_contract if isinstance(ablation_contract, dict) else {}
    matched_control_fields = [
        str(value).strip().replace("_", " ")
        for value in ablation_contract.get("matched_fields") or []
        if str(value).strip()
    ]
    matched_control_summary = ", ".join(matched_control_fields[:4]) or (
        "data, split, seed set, and evaluation budget"
    )
    for index, row in enumerate(ablation_rows):
        # Ablations are protocol-valid single-factor contrasts.  Audit and
        # provenance mechanisms are never presented as if removing them
        # changed predictive performance, and matched capacity is held
        # fixed even for an architecture-family contrast.
        value = (
            max(0.2, anchor - 0.012 * index)
            if maximize_primary
            else anchor + 0.012 * index
        )
        item = simulated(row)
        delta = value - anchor
        item.update(
            {
                "seed": simulation_seed,
                "metric_direction": metric_direction,
                "value": f"{value:.3f}",
                "ci_low": f"{value - 0.010:.3f}",
                "ci_high": f"{value + 0.010:.3f}",
                "delta": f"{delta:+.3f}",
                "parameters_m": "13.20",
                "single_factor_matched": "true",
                "matched_capacity": "true",
                "changed_factor_count": "0" if index == 0 else "1",
                "reversal_state_change": "false",
                "changed_factor": (
                    str(row.get("changed_factor") or "Full specification")
                    if index == 0
                    else str(
                        row.get("changed_factor")
                        or row.get("component_setting")
                        or f"Factor {index}"
                    )
                ),
                "matched_controls": matched_control_summary,
                "primary_effect_vs_full": f"{delta:+.3f}",
                "worst_shift_effect_vs_full": f"{1.25 * delta:+.3f}",
                "calibration_error_change_vs_full": f"{0.30 * abs(delta):+.3f}",
                "reversal_count_change_vs_full": "0",
            }
        )
        item[str(asset_profile["sensitivity_field"])] = str(
            item.get("component_setting") or ""
        )
        simulated_ablation.append(item)
    return simulated_ablation


def build_robustness_rows(
    robustness_rows: list[Row],
    maximize_primary: bool,
    simulation_seed: str,
    metric_direction: str,
    simulated: Simulate,
) -> list[Row]:
    method_offsets: dict[str, int] = {}
    simulated_robustness: list[dict[str, str]] = []
    for row in robustness_rows:
        method = row["method"]
        level_index = method_offsets.get(method, 0)
        method_offsets[method] = level_index + 1
        method_index = list(method_offsets).index(method)
        if maximize_primary:
            start = 0.662 + 0.049 * method_index
            change = -(0.052 - 0.016 * method_index)
        else:
            start = 0.338 - 0.049 * method_index
            change = 0.052 - 0.016 * method_index
        value = max(0.0, start + change * level_index)
        item = simulated(row)
        item.update(
            {
                "seed": simulation_seed,
                "metric_direction": metric_direction,
                "value": f"{value:.3f}",
                "ci_low": f"{max(0.0, value - 0.014):.3f}",
                "ci_high": f"{min(1.0, value + 0.014):.3f}",
            }
        )
        simulated_robustness.append(item)
    return simulated_robustness


def build_calibration_rows(
    calibration_rows: list[Row],
    asset_profile: dict[str, Any],
    simulated: Simulate,
) -> list[Row]:
    coverage_offsets: dict[str, int] = {}
    simulated_calibration: list[dict[str, str]] = []
    eeg_calibration_datasets = [
        label for label, _n, _v, _w in asset_profile["slice_scenarios"]
    ]
    for row in calibration_rows:
        method = row["method"]
        coverage_index = coverage_offsets.get(method, 0)
        coverage_offsets[method] = coverage_index + 1
        method_index = list(coverage_offsets).index(method)
        value = 0.052 + 0.022 * (1 - method_index) + 0.040 * coverage_index
        item = simulated(row)
        item.update(
            {
                "metric_direction": "minimize",
                "value": f"{value:.3f}",
                "ci_low": f"{max(0.0, value - 0.010):.3f}",
                "ci_high": f"{value + 0.010:.3f}",
            }
        )
        if asset_profile.get("specialized_domain"):
            dataset_index = coverage_index % len(eeg_calibration_datasets)
            ece = 0.032 + 0.006 * method_index + 0.004 * dataset_index
            selective_risk = value + 0.055 - 0.018 * coverage_index
            item.update(
                {
                    "dataset": eeg_calibration_datasets[dataset_index],
                    "value": f"{ece:.3f}",
                    "ci_low": f"{max(0.0, ece - 0.006):.3f}",
                    "ci_high": f"{ece + 0.006:.3f}",
                    "risk": f"{selective_risk:.3f}",
                    "risk_ci_low": f"{max(0.0, selective_risk - 0.010):.3f}",
                    "risk_ci_high": f"{selective_risk + 0.010:.3f}",
                }
            )
        simulated_calibration.append(item)
    return simulated_calibration


def build_efficiency_rows(
    efficiency_rows: list[Row],
    simulated_main: list[Row],
    publication_style: dict[str, Any],
    primary_metric: str,
    metric_direction: str,
    simulated: Simulate,
) -> list[Row]:
    archetype = str(publication_style.get("study_archetype") or "generic_empirical")
    resource_bases = {
        "algorithm_benchmark": [11.8, 3.8, 4.4, 5.1, 17.0],
        "systems_testbed": [42.0, 820.0, 18.0, 5.2, 1.8],
        "observational_cohort": [1200.0, 420.0, 18.0, 6.5, 2.8],
        "diagnostic_prognostic": [980.0, 360.0, 24.0, 5.8, 3.2],
        "intervention_trial": [420.0, 388.0, 91.0, 7.6, 4.0],
        "omics_discovery": [320.0, 14800.0, 18.0, 6.5, 12.0],
        "controlled_experiment": [6.0, 3.0, 48.0, 9.0, 2.5],
        "simulation_modeling": [1_000_000.0, 1e-6, 38.0, 24.0, 11.0],
        "formal_theory": [5.0, 8.0, 14.0, 0.8, 0.4],
        "qualitative_mixed": [28.0, 3.0, 160.0, 35.0, 180.0],
        "generic_empirical": [500.0, 180.0, 12.0, 3.5, 2.0],
    }[archetype]
    simulated_efficiency: list[dict[str, str]] = []
    main_by_method = {row["method"]: row for row in simulated_main}
    for index, row in enumerate(efficiency_rows):
        item = simulated(row)
        for position, base in enumerate(resource_bases, start=1):
            item[f"resource_{position}"] = (
                f"{base + index * (0.35 if position > 1 else 1.0):.2f}"
            )
        matched_result = main_by_method.get(row["method"], simulated_main[-1])
        performance = float(matched_result["value"])
        interval_width = max(
            0.006,
            (float(matched_result["ci_high"]) - float(matched_result["ci_low"])) / 2.0,
        )
        item.update(
            {
                "parameters_m": item["resource_1"],
                "flops_g": item["resource_2"],
                "latency_ms": item["resource_3"],
                "peak_memory_gb": item["resource_4"],
                "gpu_hours": item["resource_5"],
                "metric": primary_metric,
                "metric_direction": metric_direction,
                "value": f"{performance:.3f}",
                "ci_low": f"{performance - interval_width:.3f}",
                "ci_high": f"{performance + interval_width:.3f}",
            }
        )
        simulated_efficiency.append(item)
    return simulated_efficiency


def build_progression_rows(
    simulated_main: list[Row],
    asset_profile: dict[str, Any],
    maximize_primary: bool,
    assets: dict[str, Any],
    primary_metric: str,
    metric_direction: str,
    simulated: Simulate,
) -> list[Row]:
    main_by_method = {row["method"]: row for row in simulated_main}
    simulated_progression: list[dict[str, str]] = []
    progression_axis = str(asset_profile["progression_axis"])
    progression_levels = list(asset_profile["progression_levels"])
    for method_index, method in enumerate(
        (simulated_main[0]["method"], simulated_main[-1]["method"])
    ):
        target = float(main_by_method[method]["value"])
        offset = 0.205 - 0.025 * method_index
        start = target - offset if maximize_primary else target + offset
        final_index = max(1, len(progression_levels) - 1)
        for level_index, level in enumerate(progression_levels):
            progress = (level_index + 1) / (final_index + 1)
            value = start + (target - start) * progress
            interval_width = max(0.008, 0.024 - 0.0024 * level_index)
            progression_row = {
                "row_id": f"progression-{method_index + 1}-{level_index + 1}",
                "method": method,
                progression_axis: str(level),
                "phase": str(assets["progression"]["analysis_subtype"]),
                "metric": primary_metric,
                "metric_direction": metric_direction,
                "value": f"{value:.3f}",
                "ci_low": f"{max(0.0, value - interval_width):.3f}",
                "ci_high": f"{min(1.0, value + interval_width):.3f}",
                "n": "32",
            }
            if (
                asset_profile["domain"] == "algorithmic"
                or asset_profile.get("specialized_domain") == "eeg"
            ):
                progression_row["training_loss"] = (
                    f"{max(0.08, 0.92 / (1.0 + float(level) / 8.0) + 0.03 * (1 - method_index)):.3f}"
                )
            simulated_progression.append(simulated(progression_row))
    return simulated_progression
