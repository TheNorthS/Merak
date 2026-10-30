"""Normalize provenance-approved CSV and JSON measurements."""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any

from .scientific_record_models import ResultRecord

_COMPLETE_STATUSES = {
    "complete", "completed", "success", "succeeded", "executed",
    "accepted", "done",
}
_METHOD_FIELDS = (
    "method", "model", "baseline", "variant", "component_setting", "approach",
    "predictor", "exposure", "intervention", "comparator", "system",
    "configuration", "pathway", "feature", "theorem", "condition",
)
_METRIC_FIELDS = (
    "metric", "metric_name", "endpoint", "outcome", "estimate_type",
    "effect_measure", "measurement",
)
_ESTIMATE_FIELDS = (
    "value", "metric_value", "score_value", "estimate", "effect",
    "hazard_ratio", "odds_ratio", "risk_ratio", "relative_risk",
    "coefficient", "beta", "mean_difference", "log2_fold_change",
    "response", "throughput", "latency", "bound", "mean_delta",
)
_LOW_FIELDS = (
    "ci95_low", "ci_low", "ci_lower", "lower_ci", "lower_95_ci", "lcl",
    "lower_bound",
)
_HIGH_FIELDS = (
    "ci95_high", "ci_high", "ci_upper", "upper_ci", "upper_95_ci", "ucl",
    "upper_bound",
)
_UNIT_FIELDS = ("unit", "units", "measurement_unit")
_TYPE_FIELDS = ("estimate_type", "effect_measure", "statistic", "measure")


class ScientificNumericParsingMixin:
    @staticmethod
    def _path_method(path: Path, results_root: Path) -> str:
        from .scientific_assets import _clean_name

        relative = path.relative_to(results_root)
        parent = relative.parent.name
        if parent and parent not in {"results", "logs", "aggregates"}:
            return _clean_name(parent)
        stem = re.sub(
            r"(?:metrics?|history|predictions?|results?)", "", path.stem,
            flags=re.I,
        )
        return _clean_name(stem, "Recorded method")

    @staticmethod
    def _condition(row: dict[str, Any]) -> tuple[str, str]:
        from .scientific_assets import _first

        for key in (
            "missing_channel_rate", "missing_rate", "noise_level", "severity",
            "stress_level", "corruption", "condition", "perturbation",
            "subgroup", "cohort", "site", "dose", "concentration", "timepoint",
            "time_point", "workload", "scale", "sample_size", "resolution",
            "pathway", "theme", "case", "quantile", "percentile",
        ):
            value = _first(row, (key,))
            if str(value).strip():
                return key, str(value).strip()[:80]
        return "", ""

    @staticmethod
    def _declared_metrics(root: Path) -> set[str]:
        from .scientific_assets import _json

        names: set[str] = set()

        def add(value: Any) -> None:
            if isinstance(value, str) and value.strip():
                names.add(re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_"))
            elif isinstance(value, list):
                for item in value:
                    add(item)
            elif isinstance(value, dict):
                for key, item in value.items():
                    if str(key).casefold() in {
                        "metric", "metrics", "primary_metric", "secondary_metrics",
                        "primary_endpoint", "evaluation_metric",
                    } or isinstance(item, (dict, list)):
                        add(item)

        add(_json(root / "experiments" / "RUN_SPEC.json"))
        for config in (root / "experiments" / "configs").glob("*.json"):
            add(_json(config))
        return {name for name in names if name}

    @staticmethod
    def _is_metric_field(name: str, declared: set[str]) -> bool:
        from .scientific_assets import _METRIC

        normalized = re.sub(r"[^a-z0-9]+", "_", str(name).casefold()).strip("_")
        if normalized in {
            "ci95_low", "ci95_high", "ci_low", "ci_high", "ci_lower",
            "ci_upper", "lower_ci", "upper_ci", "lower_95_ci", "upper_95_ci",
            "lcl", "ucl", "standard_error", "stderr", "std_error",
        }:
            return False
        if not normalized or re.search(
            r"(?:^|_)(?:epoch|step|seed|timestamp|run_id|sample_id|subject_id|"
            r"fold_id|parameter_count)(?:_|$)",
            normalized,
        ):
            return False
        return bool(_METRIC.search(normalized) or normalized in declared)

    def _records_from_csv(self, root: Path, path: Path) -> list[ResultRecord]:
        rows = _read_csv(path)
        if not rows:
            return []
        results_root = root / "experiments" / "results"
        path_method = self._path_method(path, results_root)
        declared = self._declared_metrics(root)
        source = path.relative_to(root).as_posix()
        records: list[ResultRecord] = []
        for row in rows:
            if not _row_is_complete(row):
                continue
            context = _row_context(self, row, path_method, path, results_root)
            explicit = _explicit_record(row, source, context)
            if explicit is not None:
                records.append(explicit)
                continue
            records.extend(_wide_records(self, row, source, context, declared))
        return records

    def _records_from_json(self, root: Path, path: Path) -> list[ResultRecord]:
        from .scientific_assets import _clean_name, _first, _json

        payload = _json(path)
        if not payload:
            return []
        results_root = root / "experiments" / "results"
        base_method = _clean_name(
            _first(payload, ("method", "model", "variant", "approach")),
            self._path_method(path, results_root),
        )
        base = {
            "method": base_method,
            "seed": str(_first(payload, ("seed", "random_seed"))).strip()[:40],
            "split": _clean_name(
                _first(payload, ("split", "dataset_split"))
            ).casefold(),
            "condition": self._condition(payload),
            "role": _role(
                path.relative_to(results_root).as_posix(), base_method,
                *self._condition(payload), fallback="result",
            ),
        }
        records: list[ResultRecord] = []
        _walk_json(
            self, payload, "", base, path.relative_to(root).as_posix(),
            path.relative_to(results_root).as_posix(),
            self._declared_metrics(root), records,
        )
        return records


def _read_csv(path: Path) -> list[dict[str, Any]]:
    try:
        with path.open(
            "r", encoding="utf-8-sig", errors="replace", newline=""
        ) as handle:
            return list(csv.DictReader(handle))
    except (OSError, csv.Error):
        return []


def _row_is_complete(row: dict[str, Any]) -> bool:
    from .scientific_assets import _first

    status = str(_first(row, ("status", "run_status"))).strip().casefold()
    return not status or status in _COMPLETE_STATUSES


def _row_context(
    service: Any, row: dict[str, Any], fallback_method: str,
    path: Path, results_root: Path,
) -> dict[str, Any]:
    from .scientific_assets import _clean_name, _first

    method = _clean_name(_first(row, _METHOD_FIELDS), fallback_method)
    condition = service._condition(row)
    return {
        "method": method,
        "seed": str(_first(row, ("seed", "random_seed"))).strip()[:40],
        "split": _clean_name(
            _first(row, ("split", "dataset_split", "axis"))
        ).casefold(),
        "condition": condition,
        "role": _role(
            path.relative_to(results_root).as_posix(), method,
            condition[0], condition[1], fallback="result",
        ),
    }


def _role(
    source: str, method: str, condition_name: str,
    condition_value: str, *, fallback: str,
) -> str:
    from .scientific_assets import _ABLATION, _ROBUSTNESS

    text = " ".join((source, method, condition_name, condition_value))
    if _ABLATION.search(text):
        return "ablation"
    if _ROBUSTNESS.search(text):
        return "robustness"
    return fallback


def _explicit_record(
    row: dict[str, Any], source: str, context: dict[str, Any]
) -> ResultRecord | None:
    from .scientific_assets import _clean_name, _first, _number

    metric = _clean_name(_first(row, _METRIC_FIELDS))
    estimate_key = next(
        (name for name in _ESTIMATE_FIELDS
         if _number(_first(row, (name,))) is not None),
        "",
    )
    value = _number(_first(row, (estimate_key,))) if estimate_key else None
    if not metric or value is None or re.search(
        r"(?:epoch|step|seed|timestamp|parameter count)", metric, re.I
    ):
        return None
    estimate_type = _estimate_type(row, estimate_key)
    if estimate_type and estimate_type.casefold() not in metric.casefold():
        metric = f"{metric} ({estimate_type})"
    return _make_record(row, source, context, metric, value, estimate_type)


def _estimate_type(row: dict[str, Any], estimate_key: str = "") -> str:
    from .scientific_assets import _clean_name, _first

    estimate_type = _clean_name(_first(row, _TYPE_FIELDS))
    if not estimate_type and estimate_key not in {
        "", "value", "metric_value", "score_value", "estimate", "effect",
    }:
        estimate_type = _clean_name(estimate_key)
    return estimate_type


def _make_record(
    row: dict[str, Any], source: str, context: dict[str, Any],
    metric: str, value: float, estimate_type: str,
) -> ResultRecord:
    from .scientific_assets import _clean_name, _first, _number

    condition = context["condition"]
    return ResultRecord(
        method=context["method"], metric=metric, value=float(value), source=source,
        seed=context["seed"], split=context["split"],
        condition_name=condition[0], condition_value=condition[1],
        role=context["role"], ci_low=_number(_first(row, _LOW_FIELDS)),
        ci_high=_number(_first(row, _HIGH_FIELDS)),
        unit=_clean_name(_first(row, _UNIT_FIELDS)), estimate_type=estimate_type,
        p_value=_number(_first(row, ("p_value", "pvalue", "p"))),
        adjusted_p=_number(_first(row, (
            "adjusted_p", "adjusted_p_value", "q_value", "fdr",
        ))),
    )


def _wide_records(
    service: Any, row: dict[str, Any], source: str,
    context: dict[str, Any], declared: set[str],
) -> list[ResultRecord]:
    from .scientific_assets import _clean_name, _number

    estimate_type = _estimate_type(row)
    records = []
    for key, raw in row.items():
        if not service._is_metric_field(str(key), declared):
            continue
        value = _number(raw)
        if value is not None:
            records.append(
                _make_record(
                    row, source, context, _clean_name(key), value, estimate_type
                )
            )
    return records


def _walk_json(
    service: Any, value: Any, prefix: str, context: dict[str, Any],
    source: str, relative_source: str, declared: set[str],
    records: list[ResultRecord],
) -> None:
    if isinstance(value, dict):
        local = _json_context(service, value, context, relative_source)
        explicit = _explicit_record(value, source, local)
        if explicit is not None:
            records.append(explicit)
        consumed = _consumed_json_keys(explicit is not None)
        for key, child in value.items():
            if str(key).casefold() not in consumed:
                _walk_json(
                    service, child, f"{prefix}.{key}" if prefix else str(key),
                    local, source, relative_source, declared, records,
                )
        return
    if isinstance(value, list):
        for index, child in enumerate(value[-50:]):
            _walk_json(
                service, child, f"{prefix}[{index}]", context,
                source, relative_source, declared, records,
            )
        return
    _append_json_leaf(service, value, prefix, context, source, declared, records)


def _json_context(
    service: Any, value: dict[str, Any], inherited: dict[str, Any],
    relative_source: str,
) -> dict[str, Any]:
    from .scientific_assets import _clean_name, _first

    method = _clean_name(_first(value, _METHOD_FIELDS), inherited["method"])
    condition = service._condition(value)
    if not condition[0]:
        condition = inherited["condition"]
    seed = str(
        _first(value, ("seed", "random_seed")) or inherited["seed"]
    ).strip()[:40]
    split = _clean_name(
        _first(value, ("split", "dataset_split")) or inherited["split"]
    ).casefold()
    return {
        "method": method, "condition": condition, "seed": seed, "split": split,
        "role": _role(
            relative_source, method, condition[0], condition[1],
            fallback=inherited["role"],
        ),
    }


def _consumed_json_keys(explicit: bool) -> set[str]:
    keys = {
        *_METRIC_FIELDS, *_LOW_FIELDS, *_HIGH_FIELDS, *_UNIT_FIELDS,
        "p_value", "pvalue", "p", "adjusted_p", "adjusted_p_value",
        "q_value", "fdr",
    }
    if explicit:
        keys.update(_ESTIMATE_FIELDS)
    return keys


def _append_json_leaf(
    service: Any, value: Any, prefix: str, context: dict[str, Any],
    source: str, declared: set[str], records: list[ResultRecord],
) -> None:
    from .scientific_assets import _clean_name, _number

    leaf = prefix.rsplit(".", 1)[-1]
    if not service._is_metric_field(leaf, declared):
        return
    number = _number(value)
    if number is None:
        return
    condition = context["condition"]
    records.append(ResultRecord(
        method=context["method"], metric=_clean_name(leaf), value=number,
        source=source, seed=context["seed"], split=context["split"],
        condition_name=condition[0], condition_value=condition[1],
        role=context["role"],
    ))
