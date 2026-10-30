"""Construct registered ranking axes and paired multiplicity decisions."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable

from .simulation_evidence_helpers import axis_center
from .simulation_statistics import paired_t_two_sided_p


Row = dict[str, str]
Simulate = Callable[[dict[str, Any]], Row]
Provenance = Callable[..., Row]


@dataclass(frozen=True)
class RankingEvidence:
    methods: list[tuple[str, str]]
    axis_values: dict[tuple[str, str], list[float]]
    axis_rows: list[Row]


def materialize_ranking_evidence(
    *, simulated_main: list[Row], registered_axes: list[dict[str, Any]],
    seed_ids: list[int], source_run_id: str, simulate: Simulate,
    provenance: Provenance, primary_axis: Callable[[dict[str, Any]], bool],
    run_level_rows: list[Row], run_ledger_rows: list[Row],
) -> RankingEvidence:
    methods = _method_records(simulated_main)
    iid_values = _iid_main_values(simulated_main)
    values: dict[tuple[str, str], list[float]] = {}
    axis_rows: list[Row] = []
    for model_index, (method, model_id) in enumerate(methods):
        for contract in registered_axes:
            axis_id = str(contract["axis_id"])
            axis_values = _axis_seed_values(
                model_index, model_id, contract, seed_ids, iid_values,
                primary_axis(contract),
            )
            values[(model_id, axis_id)] = axis_values
            rows = _axis_rows(
                model_index, method, model_id, contract, seed_ids, axis_values,
                source_run_id, simulate, provenance,
            )
            axis_rows.extend(rows)
            run_level_rows.extend(rows)
        run_ledger_rows.extend(_ranking_ledger_rows(
            method, model_id, seed_ids, source_run_id, simulate, provenance,
        ))
    return RankingEvidence(methods, values, axis_rows)


def _method_records(rows: list[Row]) -> list[tuple[str, str]]:
    records = []
    for row in rows:
        record = (
            str(row.get("method") or "registered-system"),
            str(row.get("model_id") or row.get("method") or "registered-system"),
        )
        if record not in records:
            records.append(record)
    return records


def _iid_main_values(rows: list[Row]) -> dict[str, float]:
    groups: dict[str, list[float]] = {}
    for row in rows:
        key = str(row.get("model_id") or row.get("method") or "")
        try:
            groups.setdefault(key, []).append(float(row.get("value") or 0.0))
        except (TypeError, ValueError):
            continue
    return {key: sum(values) / len(values) for key, values in groups.items() if values}


def _axis_seed_values(
    model_index: int, model_id: str, contract: dict[str, Any],
    seed_ids: list[int], iid_values: dict[str, float], primary: bool,
) -> list[float]:
    axis_id = str(contract["axis_id"])
    center, scale = axis_center(axis_id, str(contract["direction"]), model_index)
    if primary:
        center = iid_values.get(model_id, center)
        contrasts = (-1.0, 0.5, 0.0, -0.5, 1.0)
        return [
            center + 0.002 * (index - (len(seed_ids) - 1) / 2.0)
            + 0.020 * model_index * contrasts[index % len(contrasts)]
            for index in range(len(seed_ids))
        ]
    return [
        center + scale * (index - (len(seed_ids) - 1) / 2.0)
        * (1.0 + 0.12 * model_index)
        for index in range(len(seed_ids))
    ]


def _axis_rows(
    model_index: int, method: str, model_id: str, contract: dict[str, Any],
    seed_ids: list[int], values: list[float], source_run_id: str,
    simulate: Simulate, provenance: Provenance,
) -> list[Row]:
    axis_id = str(contract["axis_id"])
    rows = []
    for index, seed_id in enumerate(seed_ids):
        details = provenance(
            role="registered_ranking_axis", method=method, model_id=model_id,
            seed_id=seed_id, split_identity=axis_id,
        )
        rows.append(simulate({
            "row_id": f"axis-{model_index + 1}-{axis_id}-{seed_id}",
            "run_id": f"{source_run_id}:ranking:{model_id}:seed-{seed_id}",
            "artifact_role": "registered_ranking_axis",
            "construction_scope": "separate_deterministic_ranking_projection",
            "not_primary_grid_replicate": "true",
            "aggregate_row_id": f"axis-{model_index + 1}-{axis_id}",
            "method": method, "model_id": model_id,
            "dataset": "registered-evaluation-suite", "condition": axis_id,
            "axis_id": axis_id, "seed": str(seed_id),
            "metric": str(contract["metric_key"]),
            "metric_direction": str(contract["direction"]),
            "value": f"{values[index]:.6f}", "unit": _axis_unit(axis_id),
            "completion_status": "completed", **details,
        }))
    return rows


def _axis_unit(axis_id: str) -> str:
    lower = axis_id.casefold()
    if "latency" in lower:
        return "milliseconds"
    return "bytes" if "memory" in lower else "probability"


def _ranking_ledger_rows(
    method: str, model_id: str, seed_ids: list[int], source_run_id: str,
    simulate: Simulate, provenance: Provenance,
) -> list[Row]:
    rows = []
    for seed_id in seed_ids:
        details = provenance(
            role="registered_ranking_axis", method=method, model_id=model_id,
            seed_id=seed_id, split_identity="registered-evaluation-suite",
        )
        rows.append(simulate({
            "row_id": f"ledger-ranking-{model_id}-{seed_id}",
            "run_id": f"{source_run_id}:ranking:{model_id}:seed-{seed_id}",
            "artifact_role": "registered_ranking_axis",
            "aggregate_row_id": f"ranking-{model_id}", "method": method,
            "model_id": model_id, "seed": str(seed_id),
            "completion_status": "completed", "failure_reason": "", **details,
            "run_level_table": "experiments/results/simulated/run_level_results.csv",
            "latency_table": "experiments/results/simulated/latency_samples.csv",
        }))
    return rows


def align_efficiency_rows(
    rows: list[Row], registered_axes: list[dict[str, Any]],
    values: dict[tuple[str, str], list[float]],
) -> None:
    latency_axis = _matching_axis(registered_axes, "latency")
    memory_axis = _matching_axis(registered_axes, "memory")
    for index, item in enumerate(rows):
        model_id = str(item.get("model_id") or item.get("method") or "")
        latency = values.get((model_id, latency_axis), [])
        memory = values.get((model_id, memory_axis), [])
        if latency:
            _bind_latency(item, sum(latency) / len(latency))
        if memory:
            _bind_memory(item, sum(memory) / len(memory), index)
        item.update({
            "throughput_unit": "samples_per_second",
            "memory_unit": "bytes",
            "energy_j_per_1000_predictions": f"{38.0 + 2.5 * index:.3f}",
            "energy_unit": "joules_per_1000_predictions",
            "warmup_iterations": "10",
            "measurement_repetitions": "30",
            "device_contract_id": "simulation-fixed-device-v1",
        })
        if latency and memory:
            _bind_resource_projection(item)


def _matching_axis(axes: list[dict[str, Any]], marker: str) -> str:
    return next((
        str(item["axis_id"]) for item in axes
        if marker in str(item["axis_id"]).casefold()
    ), "")


def _bind_latency(item: Row, value: float) -> None:
    item.update({
        "latency_p50_ms": f"{value * 0.955:.3f}", "latency_p95_ms": f"{value:.3f}",
        "latency_p95_ci_low_ms": f"{value - 0.180:.3f}",
        "latency_p95_ci_high_ms": f"{value + 0.180:.3f}",
        "latency_ms": f"{value:.3f}", "throughput_per_s": f"{32000.0 / value:.3f}",
    })


def _bind_memory(item: Row, value: float, index: int) -> None:
    item.update({
        "peak_memory_bytes": f"{value:.0f}",
        "peak_memory_ci_low_bytes": f"{value - 4_194_304:.0f}",
        "peak_memory_ci_high_bytes": f"{value + 4_194_304:.0f}",
        "peak_memory_gb": f"{value / (1024 ** 3):.4f}",
        "energy_j_per_1000_predictions": f"{38.0 + 2.5 * index:.3f}",
    })


def _bind_resource_projection(item: Row) -> None:
    values = (
        ("Parameters (M)", item.get("parameters_m")),
        ("Throughput (samples/s)", item.get("throughput_per_s")),
        ("P95 latency (ms)", item.get("latency_p95_ms")),
        ("Peak memory (GiB)", item.get("peak_memory_gb")),
        ("Energy (J/1k predictions)", item.get("energy_j_per_1000_predictions")),
    )
    for index, (label, value) in enumerate(values, start=1):
        item[f"resource_{index}_label"] = label
        item[f"resource_{index}"] = str(value or "")


def paired_ranking_rows(
    evidence: RankingEvidence, registered_axes: list[dict[str, Any]],
    seed_ids: list[int], holm_alpha: float,
    primary_axis: Callable[[dict[str, Any]], bool], simulate: Simulate,
    *, critical_value: float = 2.776,
) -> list[Row]:
    comparisons = _comparisons(evidence, registered_axes, seed_ids, critical_value)
    iid_indexes = {
        index for index, item in enumerate(comparisons)
        if primary_axis({"axis_id": item["axis_id"], "metric_key": item["metric"]})
    }
    adjusted = _holm_adjusted(comparisons, iid_indexes)
    rows = []
    for index, item in enumerate(comparisons, start=1):
        iid = _iid_comparison(comparisons, item)
        rows.append(_paired_row(
            index, item, iid, adjusted[index - 1], holm_alpha,
            len(comparisons) - len(iid_indexes), (index - 1) in iid_indexes,
            seed_ids, simulate,
        ))
    return rows


def _comparisons(
    evidence: RankingEvidence, axes: list[dict[str, Any]], seed_ids: list[int],
    critical_value: float,
) -> list[dict[str, Any]]:
    items = []
    for ref_index, (ref_method, ref_id) in enumerate(evidence.methods):
        for method, model_id in evidence.methods[ref_index + 1:]:
            for axis in axes:
                axis_id = str(axis["axis_id"])
                ref = evidence.axis_values[(ref_id, axis_id)]
                candidate = evidence.axis_values[(model_id, axis_id)]
                effect = _oriented_effects(ref, candidate, str(axis["direction"]), seed_ids)
                if len(effect) < 2:
                    continue
                mean = sum(effect) / len(effect)
                variance = sum((value - mean) ** 2 for value in effect) / (len(effect) - 1)
                width = critical_value * math.sqrt(variance / len(effect))
                items.append({
                    "axis_id": axis_id, "metric": str(axis["metric_key"]),
                    "metric_direction": str(axis["direction"]), "mpid": float(axis["mpid"]),
                    "reference_method": ref_method, "reference_model_id": ref_id,
                    "candidate_method": method, "candidate_model_id": model_id,
                    "paired_n": len(effect), "reference_values": ref,
                    "candidate_values": candidate, "effects": effect,
                    "mean_effect": mean, "ci_low": mean - width,
                    "ci_high": mean + width, "p_value": paired_t_two_sided_p(effect),
                })
    return items


def _oriented_effects(
    reference: list[float], candidate: list[float], direction: str,
    seed_ids: list[int],
) -> list[float]:
    count = min(len(reference), len(candidate), len(seed_ids))
    if direction == "maximize":
        return [candidate[index] - reference[index] for index in range(count)]
    return [reference[index] - candidate[index] for index in range(count)]


def _holm_adjusted(
    comparisons: list[dict[str, Any]], iid_indexes: set[int],
) -> dict[int, float]:
    targets = [index for index in range(len(comparisons)) if index not in iid_indexes]
    ordered = sorted(targets, key=lambda index: comparisons[index]["p_value"])
    adjusted: dict[int, float] = {}
    running = 0.0
    for rank, index in enumerate(ordered):
        running = max(running, min(1.0, comparisons[index]["p_value"] * (len(targets) - rank)))
        adjusted[index] = running
    adjusted.update({index: 1.0 for index in iid_indexes})
    return adjusted


def _iid_comparison(
    comparisons: list[dict[str, Any]], item: dict[str, Any],
) -> dict[str, Any]:
    return next((candidate for candidate in comparisons
        if candidate["reference_model_id"] == item["reference_model_id"]
        and candidate["candidate_model_id"] == item["candidate_model_id"]
        and "iid" in str(candidate["axis_id"]).casefold()
        and "acc" in str(candidate["axis_id"]).casefold()), item)


def _paired_row(
    index: int, item: dict[str, Any], iid: dict[str, Any], holm_p: float,
    alpha: float, family_size: int, is_iid: bool, seed_ids: list[int],
    simulate: Simulate,
) -> Row:
    from .simulation_statistics import paired_seed_bootstrap_interval
    bootstrap_low, bootstrap_high = paired_seed_bootstrap_interval(item["effects"])
    opposite = item["mean_effect"] * iid["mean_effect"] < 0
    target_ci = item["ci_low"] > 0 if item["mean_effect"] > 0 else item["ci_high"] < 0
    iid_ci = iid["ci_low"] > 0 if iid["mean_effect"] > 0 else iid["ci_high"] < 0
    qualifies = opposite and abs(item["mean_effect"]) >= item["mpid"] and abs(iid["mean_effect"]) >= iid["mpid"] and target_ci and iid_ci and holm_p < alpha
    return simulate({
        "row_id": f"pair-{index}", "comparison_id": f"pair-{index}",
        "axis_id": str(item["axis_id"]), "dataset": "registered-evaluation-suite",
        "source_table": "experiments/results/simulated/registered_axis_results.csv",
        "construction_scope": "separate_deterministic_ranking_projection",
        "not_primary_grid_contrast": "true",
        "construction_note": "Primary-axis values add a model-index/configuration perturbation to each model's target-grid mean; these are not the primary-grid seed replicates. Other axes use their declared scenario centers and scales. Intervals describe constructed configuration variation, not sampled subjects or model training.",
        "reference_method": str(item["reference_method"]),
        "reference_model_id": str(item["reference_model_id"]),
        "candidate_method": str(item["candidate_method"]),
        "candidate_model_id": str(item["candidate_model_id"]),
        "metric": str(item["metric"]), "metric_direction": str(item["metric_direction"]),
        "paired_seed_ids": "|".join(str(seed) for seed in seed_ids[:item["paired_n"]]),
        "paired_n": str(item["paired_n"]),
        "reference_seed_values": "|".join(f"{value:.6f}" for value in item["reference_values"]),
        "candidate_seed_values": "|".join(f"{value:.6f}" for value in item["candidate_values"]),
        "paired_effects": "|".join(f"{value:+.6f}" for value in item["effects"]),
        "oriented_mean_effect": f"{item['mean_effect']:+.6f}",
        "paired_ci_low": f"{item['ci_low']:+.6f}", "paired_ci_high": f"{item['ci_high']:+.6f}",
        "bootstrap_ci_low": f"{bootstrap_low:+.6f}",
        "bootstrap_ci_high": f"{bootstrap_high:+.6f}",
        "bootstrap_method": "paired_seed_percentile_v1",
        "bootstrap_resamples": str(len(item["effects"]) ** len(item["effects"]) if len(item["effects"]) <= 5 else 10000),
        "paired_sd": f"{math.sqrt(sum((value-item['mean_effect'])**2 for value in item['effects'])/(item['paired_n']-1)):.6f}",
        "mpid": f"{item['mpid']:.6f}", "mpid_pass": str(abs(item["mean_effect"]) >= item["mpid"]).lower(),
        "p_value": f"{item['p_value']:.6f}", "holm_adjusted_p": f"{holm_p:.6f}",
        "holm_reject": str(holm_p < alpha).lower(), "holm_alpha": f"{alpha:.6f}",
        "family_size": str(family_size), "in_holm_family": str(not is_iid).lower(),
        "test_method": "paired_student_t_two_sided", "iid_axis_id": str(iid["axis_id"]),
        "iid_oriented_mean_effect": f"{iid['mean_effect']:+.6f}",
        "iid_paired_ci_low": f"{iid['ci_low']:+.6f}", "iid_paired_ci_high": f"{iid['ci_high']:+.6f}",
        "opposite_to_iid": str(opposite).lower(),
        "target_ci_supports_direction": str(target_ci).lower(),
        "iid_ci_supports_direction": str(iid_ci).lower(),
        "reversal_status": "qualifying_reversal" if qualifies else "no_qualifying_reversal",
        "exclusion_reason": "none" if qualifies else "same_direction_as_iid" if not opposite else "below_mpid_or_holm_threshold",
        "minimum_detectable_effect": f"{max(item['mpid'], abs(item['ci_high']-item['ci_low'])/2):.6f}",
        "equivalence_margin_excluded": "false",
        "decision": "qualifying_cross_axis_reversal" if qualifies else "no_qualifying_cross_axis_reversal_under_registered_rule",
    })
