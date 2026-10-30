"""Pure construction of simulation primary comparisons and repetition contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .run_spec import execution_seeds

Row = dict[str, str]


@dataclass(frozen=True)
class PrimaryComparison:
    rows: list[Row]
    ablation_rows: list[Row]
    seed_ids: tuple[int, ...]
    critical_value: float


def build_primary_comparison(
    main_rows: list[Row],
    ablation_rows: list[Row],
    profile: dict[str, Any],
    metric_direction: str,
    primary_metric: str,
    simulation_seed: str,
    has_registered_ablation_contract: bool,
    run_spec: dict[str, Any],
    simulated: Callable[[dict[str, Any]], Row],
) -> PrimaryComparison:
    maximize_primary = metric_direction == "maximize"
    rows = _base_rows(
        main_rows, maximize_primary, metric_direction, simulation_seed, simulated
    )
    if profile.get("specialized_domain"):
        rows = _dataset_matrix(
            rows, profile, primary_metric, metric_direction, simulation_seed, simulated
        )
        ablation_rows = _domain_ablations(
            ablation_rows,
            profile,
            primary_metric,
            metric_direction,
            has_registered_ablation_contract,
        )
    seed_ids, seed_offsets, critical = _seed_contract(run_spec)
    _bind_primary_replicates(rows, seed_ids, seed_offsets, critical)
    _bind_task_ranks(rows, maximize_primary)
    return PrimaryComparison(rows, ablation_rows, seed_ids, critical)


def _base_rows(
    main_rows: list[Row],
    maximize_primary: bool,
    metric_direction: str,
    simulation_seed: str,
    simulated: Callable[[dict[str, Any]], Row],
) -> list[Row]:
    simulated_main: list[dict[str, str]] = []
    for index, row in enumerate(main_rows):
        if maximize_primary:
            value = 0.655 + 0.014 * index
            if index == len(main_rows) - 1:
                value += 0.018
        else:
            value = 0.345 - 0.014 * index
            if index == len(main_rows) - 1:
                value -= 0.018
        width = max(0.008, 0.014 - 0.001 * min(index + 1, 5))
        item = simulated(row)
        item.update(
            {
                "dataset": "synthetic_layout_scenario",
                "split": "simulated",
                "seed": simulation_seed,
                "n": "32",
                "metric_direction": metric_direction,
                "value": f"{value:.3f}",
                "ci_low": f"{value - width:.3f}",
                "ci_high": f"{value + width:.3f}",
                "secondary_value": f"{min(0.995, value + 0.034):.3f}",
                "stress_value": (
                    f"{max(0.05, value - 0.135 + 0.012 * (index + 1)):.3f}"
                    if maximize_primary
                    else f"{value + 0.135 - 0.012 * (index + 1):.3f}"
                ),
                "calibration_value": f"{max(0.018, 0.098 - 0.012 * (index + 1)):.3f}",
            }
        )
        simulated_main.append(item)
    return simulated_main


def _dataset_matrix(
    simulated_main: list[Row],
    asset_profile: dict[str, Any],
    primary_metric: str,
    metric_direction: str,
    simulation_seed: str,
    simulated: Callable[[dict[str, Any]], Row],
) -> list[Row]:
    eeg_datasets = [label for label, _n, _v, _w in asset_profile["slice_scenarios"]]
    expanded_main: list[dict[str, str]] = []
    for method_index, method in enumerate(
        dict.fromkeys(row["method"] for row in simulated_main)
    ):
        source_method_row = next(
            row for row in simulated_main if row["method"] == method
        )
        for dataset_index, dataset in enumerate(eeg_datasets):
            base = 0.548 + 0.027 * method_index + 0.006 * (dataset_index % 3)
            interaction = 0.012 * (((method_index + 2) * (dataset_index + 1)) % 4 - 1.5)
            value = max(0.05, min(0.95, base + interaction))
            width = 0.009 + 0.001 * ((method_index + dataset_index) % 3)
            expanded_main.append(
                simulated(
                    {
                        "row_id": f"main-{method_index + 1}-{dataset_index + 1}",
                        "dataset": dataset,
                        "split": "group-disjoint test",
                        "method": method,
                        "model_id": str(source_method_row.get("model_id") or method),
                        "seed": simulation_seed,
                        "n": str(asset_profile["slice_scenarios"][dataset_index][1]),
                        "metric": primary_metric,
                        "metric_direction": metric_direction,
                        "value": f"{value:.3f}",
                        "ci_low": f"{value - width:.3f}",
                        "ci_high": f"{value + width:.3f}",
                        "secondary_value": f"{max(0.0, value - 0.04):.3f}",
                        "stress_value": f"{max(0.0, value - 0.08 - 0.006 * dataset_index):.3f}",
                        "calibration_value": f"{0.045 + 0.008 * ((method_index + dataset_index) % 5):.3f}",
                    }
                )
            )
    return expanded_main


DOMAIN_ABLATION_LABELS = {
    "eeg": [
        ("Full model", "full"),
        ("Contrastive objective", "objective"),
        ("Masked reconstruction objective", "objective"),
        ("Discrete-token objective", "objective"),
        ("w/o time-domain branch", "architecture"),
        ("w/o frequency-domain branch", "architecture"),
        ("w/o spatial attention", "architecture"),
        ("w/o temporal attention", "architecture"),
        ("Relaxed subject/session split", "protocol"),
    ],
    "vision": [
        ("Full model", "full"),
        ("w/o multi-scale features", "architecture"),
        ("w/o augmentation policy", "objective"),
        ("w/o contrastive pretraining", "objective"),
        ("w/o long-tail reweighting", "protocol"),
    ],
    "language": [
        ("Full model", "full"),
        ("w/o instruction tuning", "objective"),
        ("w/o retrieval augmentation", "architecture"),
        ("w/o long-context attention", "architecture"),
        ("Low-resource protocol", "protocol"),
    ],
    "timeseries": [
        ("Full model", "full"),
        ("w/o temporal mixer", "architecture"),
        ("w/o frequency features", "architecture"),
        ("w/o masking objective", "objective"),
        ("Regime-shift protocol", "protocol"),
    ],
}


def _domain_ablations(
    ablation_rows: list[Row],
    asset_profile: dict[str, Any],
    primary_metric: str,
    metric_direction: str,
    has_registered_ablation_contract: bool,
) -> list[Row]:
    fallback_labels = DOMAIN_ABLATION_LABELS.get(
        str(asset_profile.get("specialized_domain") or ""),
        [],
    )
    if fallback_labels and not has_registered_ablation_contract:
        ablation_rows = [
            {
                "row_id": f"ablation-domain-{index}",
                "status": "planned",
                "component_setting": label,
                "ablation_group": group,
                "seed": "replace_with_seed",
                "metric": primary_metric,
                "metric_direction": metric_direction,
                "value": "",
                "ci_low": "",
                "ci_high": "",
                "delta": "",
                "parameters_m": "",
                "source_run_id": "",
            }
            for index, (label, group) in enumerate(
                fallback_labels,
                start=1,
            )
        ]

    # The registered experiment/method contract owns ablation semantics.
    # A domain visual grammar may change layout, but must never replace
    # project-specific controls with a stock component list. Add only a
    # presentation grouping field to authoritative rows.
    ablation_rows = [
        {
            **row,
            "ablation_group": (
                "full" if index == 0 else str(row.get("ablation_group") or "mechanism")
            ),
        }
        for index, row in enumerate(ablation_rows)
    ]
    return ablation_rows


def _seed_contract(
    run_spec: dict[str, Any],
) -> tuple[tuple[int, ...], tuple[float, ...], float]:
    configured_seed_ids = execution_seeds(run_spec)
    seed_ids = tuple(configured_seed_ids or (11, 23, 37, 53, 71))
    if len(seed_ids) < 2:
        seed_ids = (seed_ids[0], seed_ids[0] + 1) if seed_ids else (11, 23)
    seed_offsets = tuple(
        0.006 * (index - (len(seed_ids) - 1) / 2.0) for index in range(len(seed_ids))
    )
    t_critical_95 = {
        2: 12.706,
        3: 4.303,
        4: 3.182,
        5: 2.776,
        6: 2.571,
        7: 2.447,
        8: 2.365,
        9: 2.306,
        10: 2.262,
    }.get(len(seed_ids), 1.960)
    return seed_ids, seed_offsets, t_critical_95


def _bind_primary_replicates(
    simulated_main: list[Row],
    seed_ids: tuple[int, ...],
    seed_offsets: tuple[float, ...],
    t_critical_95: float,
) -> None:
    for row_index, item in enumerate(simulated_main):
        center = float(item["value"])
        interaction = 0.001 * ((row_index % 3) - 1)
        values = [center + offset + interaction for offset in seed_offsets]
        mean_value = sum(values) / len(values)
        sample_variance = sum((value - mean_value) ** 2 for value in values) / (
            len(values) - 1
        )
        standard_error = (sample_variance / len(values)) ** 0.5
        ci_width = t_critical_95 * standard_error
        item.update(
            {
                "seed": "|".join(str(seed) for seed in seed_ids),
                "seed_count": str(len(seed_ids)),
                "seed_values": "|".join(f"{value:.4f}" for value in values),
                "replicate_unit": "random_seed",
                "value": f"{mean_value:.3f}",
                "ci_low": f"{mean_value - ci_width:.3f}",
                "ci_high": f"{mean_value + ci_width:.3f}",
            }
        )


def _bind_task_ranks(simulated_main: list[Row], maximize_primary: bool) -> None:
    reference_by_dataset: dict[str, float] = {}
    for item in simulated_main:
        dataset = str(item.get("dataset") or "aggregate")
        reference_by_dataset.setdefault(dataset, float(item["value"]))
        item["effect_vs_reference"] = (
            f"{float(item['value']) - reference_by_dataset[dataset]:+.3f}"
        )
    datasets = list(
        dict.fromkeys(
            str(item.get("dataset") or "aggregate") for item in simulated_main
        )
    )
    methods_in_results = list(dict.fromkeys(item["method"] for item in simulated_main))
    ranks_by_method: dict[str, list[int]] = {
        method: [] for method in methods_in_results
    }
    values_by_method: dict[str, list[float]] = {
        method: [] for method in methods_in_results
    }
    for dataset in datasets:
        dataset_rows = [
            item
            for item in simulated_main
            if str(item.get("dataset") or "aggregate") == dataset
        ]
        ranked = sorted(
            dataset_rows,
            key=lambda item: float(item["value"]),
            reverse=maximize_primary,
        )
        for rank, item in enumerate(ranked, start=1):
            item["task_rank"] = str(rank)
            ranks_by_method[item["method"]].append(rank)
            values_by_method[item["method"]].append(float(item["value"]))
    for item in simulated_main:
        method = item["method"]
        method_ranks = ranks_by_method[method]
        method_values = values_by_method[method]
        item["mean_task_rank"] = f"{sum(method_ranks) / len(method_ranks):.2f}"
        item["task_wins"] = str(sum(rank == 1 for rank in method_ranks))
        item["worst_task_value"] = (
            f"{(min(method_values) if maximize_primary else max(method_values)):.3f}"
        )
