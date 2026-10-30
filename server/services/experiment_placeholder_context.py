"""Semantic input parsing for planned and simulated result artifacts."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


COMPONENT_RULES = [
    (r"montage|channel[-_ ]set|electrode", "Channel/montage adapter"),
    (r"frequency|spectral|band[-_ ]aware", "Frequency/spectral conditioner"),
    (r"contrastive|alignment loss", "Contrastive alignment objective"),
    (r"graph|spatial", "Spatial/graph module"),
    (r"temporal|sequence|long[-_ ]context", "Temporal context module"),
    (r"attention|transformer", "Attention interaction block"),
    (r"adapter|lora|parameter[-_ ]efficient", "Parameter-efficient adapter"),
    (r"augmentation|dropout|masking", "Training augmentation"),
    (r"calibrat|uncertainty", "Calibration/uncertainty module"),
]


def input_bundle_sha256(
    project_path: str | Path,
    direction: str = "",
    *,
    evidence_mode: str = "design_only",
    target_venue: str = "",
    research_family: str = "",
    study_archetype: str = "",
) -> str:
    """Bind every consumed planning source using the versioned semantic identity."""
    from .planning_input_identity import planning_identity
    return planning_identity(Path(project_path).resolve(), direction, evidence_mode=evidence_mode,
                             target_venue=target_venue, research_family=research_family,
                             study_archetype=study_archetype)["sha256"]



def context(root: Path, direction: str) -> str:
    parts = [direction]
    for relative in (
        "ideas/ideas.md", "ideas/novelty_report.md", "experiments/EXPERIMENT_PLAN.md",
    ):
        path = root / relative
        if path.is_file():
            parts.append(path.read_text(encoding="utf-8", errors="replace")[:30000])
    return "\n".join(parts)


def simulation_domain_context(
    root: Path,
    *,
    direction: str,
    selected_contract: dict[str, Any],
    method_contract: dict[str, Any],
    configured_contract: dict[str, Any],
) -> str:
    """Build routing input only from selected-study contracts, not literature."""
    del root
    selected = _selected_fields(selected_contract)
    method = _method_fields(method_contract)
    configured = {
        key: configured_contract.get(key)
        for key in ("data", "task", "model", "method", "evaluation")
        if configured_contract.get(key) not in (None, "", [], {})
    }
    return "\n".join((
        str(direction or ""),
        json.dumps(selected, ensure_ascii=False, sort_keys=True),
        json.dumps(method, ensure_ascii=False, sort_keys=True),
        json.dumps(configured, ensure_ascii=False, sort_keys=True),
    ))


def _selected_fields(contract: dict[str, Any]) -> dict[str, Any]:
    return {
        key: contract.get(key)
        for key in (
            "title", "problem", "problem_statement", "hypothesis",
            "research_question", "claims", "mechanisms", "datasets",
            "tasks", "inputs", "outputs", "domain",
        )
        if contract.get(key) not in (None, "", [], {})
    }


def _method_fields(contract: dict[str, Any]) -> dict[str, Any]:
    return {
        key: contract.get(key)
        for key in (
            "title", "problem_statement", "implementation_family",
            "method_summary", "models", "datasets", "tasks", "inputs",
            "outputs", "mechanisms", "evaluation_contract",
        )
        if contract.get(key) not in (None, "", [], {})
    }


def components(value: str) -> list[str]:
    lower = value.lower()
    found = [label for pattern, label in COMPONENT_RULES if re.search(pattern, lower)]
    defaults = ["Core proposed module", "Auxiliary training objective"]
    return (list(dict.fromkeys(found)) or defaults)[:3]


def json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def yaml_object(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError:
        return {}
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, ValueError, yaml.YAMLError):
        return {}
    return payload if isinstance(payload, dict) else {}


def label(value: str) -> str:
    words = " ".join(str(value or "").replace("-", "_").split("_")).title().split()
    acronyms = {
        "Ai": "AI", "Cpu": "CPU", "Cnn": "CNN", "Eeg": "EEG",
        "Gpu": "GPU", "Gru": "GRU", "Iid": "IID", "Llm": "LLM",
        "Lstm": "LSTM", "Mlp": "MLP", "Nll": "NLL", "Ood": "OOD",
    }
    return " ".join(acronyms.get(word, word) for word in words)


def normalized_metric_direction(value: Any) -> str:
    if isinstance(value, bool):
        return "maximize" if value else "minimize"
    normalized = str(value or "").strip().casefold().replace("-", "_").replace(" ", "_")
    if normalized in {"maximize", "max", "higher", "higher_is_better", "larger_is_better"}:
        return "maximize"
    if normalized in {"minimize", "min", "lower", "lower_is_better", "smaller_is_better"}:
        return "minimize"
    return ""


def metric_direction(metric: str, *explicit_values: Any) -> str:
    for value in explicit_values:
        direction = normalized_metric_direction(value)
        if direction:
            return direction
    normalized = str(metric or "").strip().casefold().replace("_", " ")
    lower_is_better = re.search(
        r"(?:^|[^a-z0-9])(?:rmse|mae|mse|mape|smape|loss|error|nll|"
        r"brier|ece|latency|runtime|wall.?time|memory|cost|risk|gap|"
        r"distance|perplexity|wer|cer|false.?positive|false.?negative)"
        r"(?:$|[^a-z0-9])",
        normalized,
        re.I,
    )
    return "minimize" if lower_is_better else "maximize"


def infer_primary_metric(
    value: str, configured: str = "", *, study_archetype: str = "",
) -> str:
    configured_text = str(configured or "").strip()
    placeholders = {"mean score", "primary estimate", "primary metric", "effect estimate"}
    if configured_text and configured_text.casefold() not in placeholders:
        return configured_text
    lower = str(value or "").casefold()
    patterns = (
        (r"balanced accuracy|balanced_accuracy", "Balanced accuracy"),
        (r"accuracy|classification|imagenet|motor imagery|sleep staging|seizure", "Accuracy"),
        (r"macro[-_ ]?f1|f1[-_ ]?score|f1 score", "Macro-F1"),
        (r"auroc|roc[-_ ]?auc|area under the curve", "AUROC"),
        (r"forecast|regression|rmse|mean absolute error|mae", "RMSE"),
    )
    matched = next((metric for pattern, metric in patterns if re.search(pattern, lower)), "")
    if matched:
        return matched
    return _archetype_metric(study_archetype)


def _archetype_metric(study_archetype: str) -> str:
    defaults = {
        "systems_testbed": "Throughput",
        "observational_cohort": "Adjusted effect estimate",
        "diagnostic_prognostic": "AUROC",
        "intervention_trial": "Treatment effect estimate",
        "omics_discovery": "Standardized effect size",
        "controlled_experiment": "Standardized response",
        "simulation_modeling": "Validation error",
        "formal_theory": "Guarantee gap",
        "qualitative_mixed": "Triangulated support",
        "generic_empirical": "Primary outcome",
    }
    return defaults.get(str(study_archetype or "").strip().casefold(), "Accuracy")


def robustness_axis(value: str, study_archetype: str = "") -> tuple[str, list[str]]:
    archetype_axes = {
        "observational_cohort": ("cohort_shift_level", ["0", "1", "2", "3"]),
        "diagnostic_prognostic": ("population_shift_level", ["0", "1", "2", "3"]),
        "intervention_trial": ("protocol_deviation_rate", ["0.0", "0.05", "0.10", "0.20"]),
        "omics_discovery": ("batch_shift_level", ["0", "1", "2", "3"]),
        "controlled_experiment": ("perturbation_level", ["0", "1", "2", "3", "4"]),
        "systems_testbed": ("workload_stress_level", ["0", "1", "2", "3", "4"]),
        "simulation_modeling": ("parameter_shift_level", ["0", "1", "2", "3"]),
        "formal_theory": ("assumption_relaxation_level", ["0", "1", "2", "3"]),
        "qualitative_mixed": ("case_divergence_level", ["0", "1", "2", "3"]),
    }
    if study_archetype in archetype_axes:
        return archetype_axes[study_archetype]
    lower = value.lower()
    inferred = (
        (r"eeg|electrode|montage|channel", "missing_channel_rate", ["0.0", "0.1", "0.2", "0.3", "0.5"]),
        (r"image|vision|pixel|segmentation", "corruption_severity", ["0", "1", "2", "3", "4", "5"]),
        (r"language|text|llm|nlp", "distribution_shift_level", ["0", "1", "2", "3"]),
        (r"time series|timeseries|sensor|signal", "missing_timestep_rate", ["0.0", "0.1", "0.2", "0.3", "0.5"]),
    )
    for pattern, axis, levels in inferred:
        if re.search(pattern, lower):
            return axis, levels
    return "input_corruption_level", ["0", "1", "2", "3", "4"]
