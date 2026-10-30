"""Resolve planned-result domain contracts before writing any artifacts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .experiment_placeholder_context import (
    components as infer_components,
    infer_primary_metric,
    label,
    metric_direction as resolve_metric_direction,
    robustness_axis,
)


@dataclass(frozen=True)
class PlannedStudyContract:
    components: list[str]
    claim_ids: list[str]
    archetype: str
    analysis_rationale: str
    ablation_settings: list[str]
    registered_single_factors: list[str]
    method_ablation_contract: dict[str, Any]
    methods: list[str]
    model_id_by_method: dict[str, str]
    primary_metric: str
    metric_direction: str
    secondary_metric: str
    calibration_metric: str
    validation_curve_labels: tuple[str, str]
    axis: str
    levels: list[str]


def planned_study_contract(
    selected: dict[str, Any],
    method_contract: dict[str, Any],
    config: dict[str, Any],
    run_spec: dict[str, Any],
    publication_style: dict[str, Any],
    context: str,
) -> PlannedStudyContract:
    experiment, evaluation, model_config, method_config = [
        config.get(key) if isinstance(config.get(key), dict) else {}
        for key in ("experiment", "evaluation", "model", "method")
    ]
    components, claims, archetype, rationale = _components(
        selected, publication_style, context
    )
    publication = selected.get("publication") if isinstance(selected.get("publication"), dict) else {}
    settings, factors, ablation_contract, primary_method = _ablations(
        experiment,
        method_config,
        archetype,
        components,
        str(publication.get("method_name") or ""),
    )
    methods, model_ids = _methods(
        experiment,
        model_config,
        method_config,
        run_spec,
        archetype,
        primary_method,
        [str(item) for item in publication.get("comparator_names") or []],
    )
    primary, direction = _primary_metric(
        context,
        experiment,
        evaluation,
        method_contract,
        publication_style,
        archetype,
    )
    secondary, calibration, labels = _secondary_metrics(
        evaluation,
        primary,
        publication_style,
        archetype,
    )
    axis, levels = _stress_axis(context, archetype, evaluation)
    return PlannedStudyContract(
        components,
        claims,
        archetype,
        rationale,
        settings,
        factors,
        ablation_contract,
        methods,
        model_ids,
        primary,
        direction,
        secondary,
        calibration,
        labels,
        axis,
        levels,
    )


def item_id(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("id") or item.get("name") or "").strip()
    return str(item or "").strip()


def _components(
    selected: dict[str, Any], publication_style: dict[str, Any], context: str
) -> tuple[list[str], list[str], str, str]:
    mechanisms = []
    for index, item in enumerate(selected.get("mechanisms", []), start=1):
        if not isinstance(item, dict) or not str(item.get("name") or "").strip():
            continue
        preferred = str(item.get("publication_name") or "").strip()
        if not preferred:
            raise ValueError(f"mechanism {index} has no publication_name")
        mechanisms.append(preferred)
    claim_ids = [
        str(item.get("id") or f"C{index + 1}").strip()
        for index, item in enumerate(selected.get("claims") or [])
        if isinstance(item, dict) and str(item.get("id") or f"C{index + 1}").strip()
    ]
    claim_ids = list(dict.fromkeys(claim_ids)) or ["C1"]
    archetype = str(publication_style.get("study_archetype") or "generic_empirical")
    analysis_rationale = {
        "algorithm_benchmark": "Mechanism necessity under matched capacity and compute",
        "systems_testbed": "Component and configuration necessity under matched resources",
        "observational_cohort": "Adjustment and specification sensitivity",
        "diagnostic_prognostic": "Predictor, calibration, and validation sensitivity",
        "intervention_trial": "Intervention-component and estimand sensitivity",
        "omics_discovery": "Pipeline and biological-validation sensitivity",
        "controlled_experiment": "Control-condition and mechanistic-factor analysis",
        "simulation_modeling": "Model-component and parameter sensitivity",
        "formal_theory": "Assumption necessity and counterexamples",
        "qualitative_mixed": "Alternative coding, negative cases, and triangulation",
        "generic_empirical": "Primary control and sensitivity analysis",
    }[archetype]
    default_components = DEFAULT_COMPONENTS
    inferred_components = (
        infer_components(context) if archetype == "algorithm_benchmark" else []
    )
    components = mechanisms or inferred_components or default_components[archetype]
    if components == ["Core proposed module", "Auxiliary training objective"]:
        components = default_components[archetype]
    return components, claim_ids, archetype, analysis_rationale


def _ablations(
    experiment: dict[str, Any],
    method_config: dict[str, Any],
    archetype: str,
    components: list[str],
    method_name: str,
) -> tuple[list[str], list[str], dict[str, Any], str]:
    configured_ablations = [
        item_id(item) for item in experiment.get("ablations", []) if item_id(item)
    ]
    method_ablation_contract = (
        method_config.get("ablations")
        if isinstance(method_config.get("ablations"), dict)
        else {}
    )
    registered_single_factors = [
        item_id(item)
        for item in method_ablation_contract.get("allowed_single_factors", [])
        if item_id(item)
    ]
    full_label = method_name or {
        "intervention_trial": "Primary intervention analysis",
        "controlled_experiment": "Full experimental condition",
        "observational_cohort": "Primary adjusted analysis",
        "diagnostic_prognostic": "Full prespecified model",
        "omics_discovery": "Full analysis pipeline",
        "systems_testbed": "Full system",
        "formal_theory": "Full theorem conditions",
        "qualitative_mixed": "Triangulated primary analysis",
    }.get(archetype, "Full method")
    primary_method_label = label(full_label)
    alternative_prefix = {
        "observational_cohort": "Alternative specification: ",
        "diagnostic_prognostic": "Sensitivity model without ",
        "intervention_trial": "Component-control analysis: ",
        "omics_discovery": "Pipeline sensitivity without ",
        "controlled_experiment": "Control condition without ",
        "simulation_modeling": "Model sensitivity without ",
        "formal_theory": "Assumption removed: ",
        "qualitative_mixed": "Alternative coding without ",
    }.get(archetype, "Without ")
    ablation_settings = [full_label] + (
        [f"{label(item)} single-factor variant" for item in registered_single_factors]
        if registered_single_factors
        else [label(item) for item in configured_ablations]
        if configured_ablations
        else [f"{alternative_prefix}{item}" for item in components[:5]]
    )
    return (
        ablation_settings,
        registered_single_factors,
        method_ablation_contract,
        primary_method_label,
    )


def _methods(
    experiment: dict[str, Any],
    model_config: dict[str, Any],
    method_config: dict[str, Any],
    run_spec: dict[str, Any],
    archetype: str,
    primary_method_label: str,
    publication_comparators: list[str],
) -> tuple[list[str], dict[str, str]]:
    baseline_source = (
        experiment.get("baselines")
        if isinstance(experiment.get("baselines"), list)
        else model_config.get("baselines")
    )
    configured_baselines = [
        item_id(item)
        for item in (baseline_source if isinstance(baseline_source, list) else [])
        if item_id(item)
    ]
    registered_models = [
        item_id(item)
        for item in (
            ((run_spec.get("matrix") or {}).get("models") or [])
            if isinstance(run_spec.get("matrix"), dict)
            else []
        )
        if item_id(item)
    ] or [
        item_id(item) for item in method_config.get("model_suite", []) if item_id(item)
    ]
    methods = [label(item) for item in dict.fromkeys(registered_models)]
    if not methods and publication_comparators:
        methods = list(dict.fromkeys(publication_comparators))
    if not methods and configured_baselines:
        methods = [label(item) for item in configured_baselines[:4]] + [
            primary_method_label
        ]
    if not methods:
        raise ValueError("publication comparator names are required for the planned study")
    model_id_by_method = {label(model_id): model_id for model_id in registered_models}
    return methods, model_id_by_method


def _primary_metric(
    context: str,
    experiment: dict[str, Any],
    evaluation: dict[str, Any],
    method_contract: dict[str, Any],
    publication_style: dict[str, Any],
    archetype: str,
) -> tuple[str, str]:
    primary_metric = infer_primary_metric(
        context,
        str(
            experiment.get("primary_metric")
            or evaluation.get("primary_metric")
            or (publication_style.get("reporting") or {}).get("effect_label")
            or ""
        ),
        study_archetype=archetype,
    )
    contract_metric_directions = method_contract.get("metric_directions")
    contract_metric_directions = (
        contract_metric_directions
        if isinstance(contract_metric_directions, dict)
        else {}
    )
    evaluation_metric_directions = evaluation.get("metric_directions")
    evaluation_metric_directions = (
        evaluation_metric_directions
        if isinstance(evaluation_metric_directions, dict)
        else {}
    )
    metric_direction = resolve_metric_direction(
        primary_metric,
        method_contract.get("primary_metric_direction"),
        contract_metric_directions.get(primary_metric),
        experiment.get("metric_direction"),
        experiment.get("higher_is_better"),
        evaluation.get("metric_direction"),
        evaluation_metric_directions.get(primary_metric),
    )
    return primary_metric, metric_direction


def _secondary_metrics(
    evaluation: dict[str, Any],
    primary_metric: str,
    publication_style: dict[str, Any],
    archetype: str,
) -> tuple[str, str, tuple[str, str]]:
    configured_metrics = [
        str(item).strip() for item in evaluation.get("metrics", []) if str(item).strip()
    ]
    secondary_metric = next(
        (
            item
            for item in configured_metrics
            if item.casefold() != primary_metric.casefold()
            and not re.search(r"(?:ece|nll|brier|calibrat|loss)", item, re.I)
        ),
        str(
            (publication_style.get("reporting") or {}).get("secondary_label")
            or "Secondary metric"
        ),
    )
    calibration_metric = next(
        (
            item
            for item in configured_metrics
            if re.search(r"(?:ece|brier|calibrat)", item, re.I)
        ),
        str(
            (publication_style.get("reporting") or {}).get("calibration_label")
            or "Calibration error"
        ),
    )
    validation_curve_labels = {
        "algorithm_benchmark": ("Retained coverage", "Selective risk"),
        "systems_testbed": ("Supported workload fraction", "Failure / resource cost"),
        "observational_cohort": ("Retained cohort fraction", "Estimate instability"),
        "diagnostic_prognostic": ("Retained coverage", "Clinical prediction risk"),
        "intervention_trial": ("Outcome completeness", "Treatment-effect uncertainty"),
        "omics_discovery": ("Retained discovery fraction", "Validation error"),
        "controlled_experiment": ("Replicate coverage", "Relative measurement error"),
        "simulation_modeling": ("Parameter-domain coverage", "Validation discrepancy"),
        "formal_theory": ("Assumption coverage", "Guarantee gap"),
        "qualitative_mixed": ("Source coverage", "Unresolved contradiction rate"),
        "generic_empirical": ("Evidence coverage", "Uncertainty / error"),
    }[archetype]
    return secondary_metric, calibration_metric, validation_curve_labels


def _stress_axis(
    context: str, archetype: str, evaluation: dict[str, Any]
) -> tuple[str, list[str]]:
    axis, levels = robustness_axis(context, archetype)
    for stress in evaluation.get("stress_tests", []):
        if not isinstance(stress, dict):
            continue
        if isinstance(stress.get("missing_ratios"), list) and stress["missing_ratios"]:
            axis = f"{stress.get('id') or 'missing_input'}_rate"
            levels = ["0.0", *[str(item) for item in stress["missing_ratios"]]]
            break
        if isinstance(stress.get("keep_ratios"), list) and stress["keep_ratios"]:
            axis = f"{stress.get('id') or 'retained_input'}_ratio"
            levels = [str(item) for item in stress["keep_ratios"]]
            break
    return axis, levels


DEFAULT_COMPONENTS = {
    "algorithm_benchmark": [
        "Core mechanism",
        "Training objective",
        "Input representation",
    ],
    "systems_testbed": [
        "Core subsystem",
        "Optimization policy",
        "Failure-handling path",
    ],
    "observational_cohort": [
        "Primary adjustment set",
        "Missing-data strategy",
        "Sensitivity specification",
    ],
    "diagnostic_prognostic": [
        "Predictor set",
        "Calibration procedure",
        "External-validation protocol",
    ],
    "intervention_trial": [
        "Intervention component",
        "Adherence strategy",
        "Prespecified adjustment",
    ],
    "omics_discovery": [
        "Quality-control stage",
        "Batch correction",
        "Biological validation stage",
    ],
    "controlled_experiment": [
        "Active condition",
        "Mechanistic factor",
        "Orthogonal validation",
    ],
    "simulation_modeling": [
        "Model component",
        "Boundary condition",
        "Uncertainty model",
    ],
    "formal_theory": ["Key assumption", "Construction step", "Auxiliary lemma"],
    "qualitative_mixed": [
        "Coding framework",
        "Triangulation source",
        "Negative-case analysis",
    ],
    "generic_empirical": [
        "Primary mechanism",
        "Control specification",
        "Sensitivity analysis",
    ],
}

