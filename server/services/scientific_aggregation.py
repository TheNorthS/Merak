"""Select and aggregate normalized scientific result records."""

from __future__ import annotations

import math
import statistics

from .scientific_record_models import ResultRecord

_METRIC_PRIORITY = {
    "accuracy": 8, "macro f1": 8, "f1": 7, "auroc": 7,
    "hazard ratio": 8, "odds ratio": 8, "risk ratio": 8,
    "effect size": 8, "mean difference": 8, "net benefit": 8,
    "throughput": 7, "latency": 7, "survival": 7,
    "fold change": 7, "convergence rate": 7, "bound": 7,
    "rmse": 6, "mae": 6, "loss": 2, "p value": 1, "fdr": 1,
}
_T95 = {
    2: 12.706, 3: 4.303, 4: 3.182, 5: 2.776, 6: 2.571,
    7: 2.447, 8: 2.365, 9: 2.306, 10: 2.262, 11: 2.228,
    12: 2.201, 13: 2.179, 14: 2.160, 15: 2.145, 16: 2.131,
    17: 2.120, 18: 2.110, 19: 2.101, 20: 2.093,
}


def primary_group(
    records: list[ResultRecord],
) -> tuple[str, str, list[ResultRecord]]:
    groups: dict[tuple[str, str], list[ResultRecord]] = {}
    for record in records:
        if record.role == "result":
            groups.setdefault((record.metric, record.split), []).append(record)
    if not groups:
        return "", "", []
    (metric, split), selected = max(groups.items(), key=_group_score)
    return metric, split, selected


def _group_score(
    item: tuple[tuple[str, str], list[ResultRecord]],
) -> tuple[int, int, int, int]:
    (metric, split), records = item
    methods = len({
        (record.method, record.condition_name, record.condition_value)
        for record in records
    })
    preferred = max(
        (weight for name, weight in _METRIC_PRIORITY.items()
         if name in metric.casefold()),
        default=3,
    )
    return methods, int(split == "test"), len(records), preferred


def comparison_unit_count(records: list[ResultRecord]) -> int:
    return len({
        (record.method, record.condition_name, record.condition_value)
        for record in records
    })


def aggregate_records(records: list[ResultRecord]) -> list[dict[str, str]]:
    grouped: dict[tuple[str, str, str], list[ResultRecord]] = {}
    for record in records:
        grouped.setdefault((
            record.method, record.condition_name, record.condition_value,
        ), []).append(record)
    return [
        _aggregate_group(key, values)
        for key, values in sorted(grouped.items())
    ]


def _aggregate_group(
    key: tuple[str, str, str], values: list[ResultRecord]
) -> dict[str, str]:
    method, condition_name, condition_value = key
    numbers = [item.value for item in values]
    mean = statistics.fmean(numbers)
    std = statistics.stdev(numbers) if len(numbers) > 1 else 0.0
    critical = _T95.get(len(numbers), 1.96 if len(numbers) >= 30 else 2.086)
    margin = critical * std / math.sqrt(len(numbers)) if len(numbers) > 1 else 0.0
    reported = (
        len(values) == 1 and values[0].ci_low is not None
        and values[0].ci_high is not None
    )
    low = float(values[0].ci_low) if reported else mean - margin
    high = float(values[0].ci_high) if reported else mean + margin
    p_values = [item.p_value for item in values if item.p_value is not None]
    adjusted = [item.adjusted_p for item in values if item.adjusted_p is not None]
    return {
        "method": method, "condition_name": condition_name,
        "condition_value": condition_value, "x_value": condition_value,
        "n": str(len(numbers)), "mean": f"{mean:.10g}", "std": f"{std:.10g}",
        "ci95_low": f"{low:.10g}", "ci95_high": f"{high:.10g}",
        "ci_method": "reported" if reported else "student_t" if len(numbers) > 1
        else "not_estimable",
        "raw_values": ";".join(f"{value:.10g}" for value in numbers),
        "unit": "; ".join(dict.fromkeys(item.unit for item in values if item.unit)),
        "estimate_type": "; ".join(dict.fromkeys(
            item.estimate_type for item in values if item.estimate_type
        )),
        "p_value": f"{p_values[0]:.10g}" if p_values else "",
        "adjusted_p": f"{adjusted[0]:.10g}" if adjusted else "",
        "source_data": ";".join(sorted({item.source for item in values})),
    }
