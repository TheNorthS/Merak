"""Domain-aware contracts for complete simulation figure and table suites."""

from __future__ import annotations

import re
from typing import Any


_DEFAULT_ASSETS = [
    ("main", "main_comparison", "result", "Primary comparison", ""),
    ("sensitivity", "ablation", "ablation", "Component-ablation analysis", ""),
    ("progression", "training_dynamics", "analysis", "Training dynamics", "training_dynamics"),
    ("robustness", "robustness", "robustness", "Robustness and sensitivity", ""),
    ("case_analysis", "error_analysis", "error_analysis", "Error-slice analysis", ""),
    ("coverage", "calibration", "calibration", "Selective risk--coverage analysis", ""),
    ("burden", "efficiency", "efficiency", "Performance--resource trade-off", ""),
]

_STABLE_CONTRACT = {
    "main": ("main_comparison", "main_comparison", "fig:preview-main-comparison", "tab:preview-main-results"),
    "sensitivity": ("ablation", "component_ablation", "fig:preview-ablation", "tab:preview-ablation"),
    "progression": ("training_dynamics", "training_dynamics", "fig:preview-training-dynamics", ""),
    "robustness": ("robustness", "robustness_sensitivity", "fig:preview-robustness", "tab:preview-robustness-calibration"),
    "case_analysis": ("error_analysis", "error_analysis", "fig:preview-error-analysis", "tab:preview-error-analysis"),
    "coverage": ("calibration", "calibration_risk_coverage", "fig:preview-calibration", "tab:preview-calibration"),
    "burden": ("efficiency", "efficiency_tradeoff", "fig:preview-efficiency", "tab:preview-efficiency"),
}

_PLOT_CONTRACTS = {
    "main": ("ranked_interval_forest", "Ranked comparison of methods using point estimates and two-sided 95% intervals."),
    "sensitivity": ("ablation_delta_waterfall", "Component-removal losses relative to the full method, with uncertainty whiskers."),
    "progression": ("learning_progression_curve", "Progression trajectories with pointwise uncertainty bands and endpoint separation."),
    "robustness": ("stress_response_curve", "Stress-response trajectories with uncertainty bands and retention under the strongest perturbation."),
    "case_analysis": ("slice_risk_bar", "Slice-level outcome bars with uncertainty, sample size, and an overall-reference line."),
    "coverage": ("risk_coverage_frontier", "Retained-coverage versus risk curves with uncertainty bands."),
    "burden": ("resource_pareto_frontier", "Performance-resource scatter with uncertainty and a highlighted Pareto frontier."),
}


def simulation_asset_profile(
    publication_style: dict[str, Any], context: str = "", direction: str = "",
) -> dict[str, Any]:
    """Build the stable seven-role asset profile for one research domain."""

    domain = _domain(publication_style)
    profile = _base_profile(domain)
    specialized = _specialized_domain(f"{context} {direction}")
    if specialized == "eeg":
        _apply_eeg_profile(profile)
    elif specialized:
        _apply_cross_domain_profile(profile, specialized)
    assets = _normalize_assets(profile.pop("assets"), domain)
    profile["assets"] = assets
    return profile


def _domain(style: dict[str, Any]) -> str:
    archetype = str(style.get("study_archetype") or "generic_empirical").strip().casefold()
    family = str(style.get("family") or "").strip().casefold()
    if family == "clinical_biomedical" or archetype in {
        "observational_cohort", "diagnostic_prognostic", "intervention_trial",
    }:
        return "clinical"
    if archetype == "formal_theory" or family == "theoretical_formal":
        return "formal"
    if archetype == "qualitative_mixed" or family == "qualitative_humanities":
        return "qualitative"
    return "algorithmic"


def _base_profile(domain: str) -> dict[str, Any]:
    builders = {
        "algorithmic": _algorithmic_profile,
        "clinical": _clinical_profile,
        "formal": _formal_profile,
        "qualitative": _qualitative_profile,
    }
    return {"domain": domain, **builders[domain]()}


def _algorithmic_profile() -> dict[str, Any]:
    return {
        "progression_axis": "epoch",
        "progression_levels": [1, 5, 10, 20, 30, 40, 50],
        "sensitivity_field": "component_setting",
        "sensitivity_label": "Component setting",
        "slice_field": "error_slice",
        "slice_label": "Analysis slice",
        "slice_metric": "Error rate",
        "slice_scenarios": [
            ("Overall", 240, 0.185, 0.018),
            ("Rare / low-support cases", 48, 0.292, 0.041),
            ("Distribution-shift cases", 64, 0.268, 0.035),
            ("Noisy / incomplete inputs", 72, 0.316, 0.038),
            ("High-uncertainty cases", 40, 0.354, 0.046),
        ],
        "assets": list(_DEFAULT_ASSETS),
        "main_secondary_label": "Auxiliary accuracy (higher)",
        "main_stress_label": "Worst-shift accuracy (higher)",
        "main_calibration_label": "Calibration error (lower)",
        "sensitivity_cost_label": "Complexity index",
        "summary": "main comparison, component ablation, training dynamics, robustness/sensitivity, error-slice analysis, calibration/risk coverage, and performance/resource efficiency",
    }


def _clinical_profile() -> dict[str, Any]:
    return {
        "progression_axis": "validation_fraction",
        "progression_levels": [0.10, 0.25, 0.40, 0.60, 0.80, 1.00],
        "sensitivity_field": "clinical_specification",
        "sensitivity_label": "Clinical specification",
        "slice_field": "subgroup",
        "slice_label": "Prespecified subgroup",
        "slice_metric": "Outcome risk",
        "slice_scenarios": [
            ("Overall population", 480, 0.185, 0.018),
            ("Older participants", 132, 0.226, 0.031),
            ("Higher baseline severity", 118, 0.254, 0.035),
            ("Incomplete follow-up", 74, 0.284, 0.041),
            ("External validation cohort", 156, 0.239, 0.029),
        ],
        "assets": [
            ("main", "clinical_effect_comparison", "result", "Primary clinical effect comparison", ""),
            ("sensitivity", "specification_sensitivity", "sensitivity", "Clinical specification and estimand sensitivity", ""),
            ("progression", "validation_trajectory", "analysis", "Validation trajectory", "validation_trajectory"),
            ("robustness", "population_robustness", "robustness", "Population and protocol robustness", ""),
            ("case_analysis", "subgroup_analysis", "sensitivity", "Prespecified subgroup outcome analysis", ""),
            ("coverage", "clinical_utility", "calibration", "Clinical utility and retained-coverage analysis", ""),
            ("burden", "feasibility_burden", "efficiency", "Clinical feasibility and acquisition burden", ""),
        ],
        "main_secondary_label": "Secondary endpoint",
        "main_stress_label": "Population shift",
        "main_calibration_label": "Clinical calibration",
        "sensitivity_cost_label": "Specification burden",
        "summary": "clinical effect comparison, specification sensitivity, validation trajectory, population robustness, prespecified subgroup analysis, clinical utility/coverage, and feasibility burden",
    }


def _formal_profile() -> dict[str, Any]:
    return {
        "progression_axis": "proof_stage",
        "progression_levels": [1, 2, 3, 4, 5, 6, 7],
        "sensitivity_field": "assumption_setting",
        "sensitivity_label": "Assumption setting",
        "slice_field": "counterexample_regime",
        "slice_label": "Counterexample regime",
        "slice_metric": "Guarantee gap",
        "slice_scenarios": [
            ("Declared theorem domain", 64, 0.080, 0.012),
            ("Boundary construction", 32, 0.142, 0.021),
            ("Relaxed regularity", 40, 0.198, 0.028),
            ("Adversarial construction", 28, 0.262, 0.036),
            ("Known impossibility regime", 24, 0.334, 0.044),
        ],
        "assets": [
            ("main", "theorem_guarantee_comparison", "result", "Theorem guarantee and reference-bound comparison", ""),
            ("sensitivity", "assumption_necessity", "sensitivity", "Assumption-necessity analysis", ""),
            ("progression", "proof_progression", "analysis", "Proof-construction progression", "proof_progression"),
            ("robustness", "assumption_relaxation", "robustness", "Assumption-relaxation robustness", ""),
            ("case_analysis", "counterexample_analysis", "failure_analysis", "Counterexample and boundary-regime analysis", ""),
            ("coverage", "guarantee_coverage", "calibration", "Assumption coverage versus guarantee gap", ""),
            ("burden", "proof_complexity", "efficiency", "Proof complexity and verification burden", ""),
        ],
        "main_secondary_label": "Reference guarantee",
        "main_stress_label": "Boundary gap",
        "main_calibration_label": "Assumption gap",
        "sensitivity_cost_label": "Assumption count",
        "summary": "theorem guarantee comparison, assumption necessity, proof progression, assumption relaxation, counterexample analysis, guarantee coverage, and proof complexity",
    }


def _qualitative_profile() -> dict[str, Any]:
    return {
        "progression_axis": "cases_reviewed",
        "progression_levels": [4, 8, 12, 16, 20, 24, 28],
        "sensitivity_field": "analytic_specification",
        "sensitivity_label": "Analytic specification",
        "slice_field": "divergent_case",
        "slice_label": "Divergent or negative case",
        "slice_metric": "Unresolved contradiction rate",
        "slice_scenarios": [
            ("Convergent primary cases", 18, 0.090, 0.018),
            ("Negative cases", 6, 0.176, 0.031),
            ("Cross-source disagreement", 8, 0.224, 0.036),
            ("Coder-disagreement cases", 7, 0.258, 0.041),
            ("Boundary-context cases", 5, 0.302, 0.047),
        ],
        "assets": [
            ("main", "theme_comparison", "result", "Cross-source thematic comparison", ""),
            ("sensitivity", "triangulation_sensitivity", "sensitivity", "Triangulation and coding sensitivity", ""),
            ("progression", "saturation_progression", "analysis", "Thematic saturation progression", "saturation_progression"),
            ("robustness", "negative_case_robustness", "robustness", "Negative-case robustness", ""),
            ("case_analysis", "divergent_case_analysis", "failure_analysis", "Divergent-case and coder-disagreement analysis", ""),
            ("coverage", "source_coverage", "calibration", "Source coverage versus unresolved contradiction", ""),
            ("burden", "auditability_burden", "efficiency", "Auditability and coding-burden trade-off", ""),
        ],
        "main_secondary_label": "Triangulated support",
        "main_stress_label": "Negative-case stability",
        "main_calibration_label": "Coder agreement",
        "sensitivity_cost_label": "Coding burden",
        "summary": "thematic comparison, triangulation sensitivity, saturation progression, negative-case robustness, divergent-case analysis, source coverage, and auditability burden",
    }


def _specialized_domain(context: str) -> str:
    lower = context.casefold()
    patterns = {
        "eeg": r"\beeg\b|electroencephal|brain[-_ ]?computer|\bbi?ci\b|\btueg\b|\btuev\b|\bchb[-_ ]?mit\b|physionet|seizure|motor imagery|sleep staging",
        "vision": r"\bimages?\b|\bcomputer[-_ ]vision\b|\bvision model\b|\bcnn\b|\bresnet\b|\bsegmentation\b|\bobject detection\b",
        "language": r"\blanguage\b|\btext(?:ual)?\b|\bnlp\b|\bllms?\b|\bmachine translation\b|\bquestion answering\b",
        "timeseries": r"\btime[-_ ]?series\b|\bsensors?\b|\bforecast(?:ing)?\b|\bsignals?\b|\bindustrial\b|\biot\b",
    }
    return next((name for name, pattern in patterns.items() if re.search(pattern, lower)), "")


def _apply_eeg_profile(profile: dict[str, Any]) -> None:
    profile.update({
        "specialized_domain": "eeg",
        "progression_axis": "pretraining_hours",
        "progression_levels": [1, 10, 100, 500, 1000, 2000, 5000, 9000],
        "sensitivity_field": "component_setting",
        "sensitivity_label": "Pre-training / architecture factor",
        "slice_field": "dataset_task",
        "slice_label": "Downstream dataset / task",
        "slice_metric": "Error rate",
        "slice_scenarios": [
            ("FACED / emotion", 10332, 0.185, 0.018),
            ("SEED-V / emotion", 9774, 0.198, 0.019),
            ("PhysioNet-MI / motor imagery", 11888, 0.214, 0.021),
            ("SHU-MI / motor imagery", 11988, 0.226, 0.023),
            ("ISRUC / sleep staging", 82940, 0.238, 0.020),
            ("CHB-MIT / seizure", 32693, 0.252, 0.024),
            ("TUEV / event type", 112491, 0.266, 0.026),
            ("TUAB / abnormality", 409455, 0.279, 0.028),
        ],
        "main_secondary_label": "Secondary metric",
        "main_stress_label": "Worst-shift score",
        "main_calibration_label": "ECE (15-bin)",
        "specialized_summary": "cross-dataset task matrix, objective/architecture ablation, pre-training scaling, shift robustness, dataset-level error map, calibration frontier, and parameter/FLOPs trade-off",
        "assets": _specialized_assets("Cross-dataset task comparison", "Pre-training data and convergence scaling", "pretraining_scaling"),
    })


def _apply_cross_domain_profile(profile: dict[str, Any], domain: str) -> None:
    configurations = {
        "vision": (
            "label_fraction", [0.01, 0.05, 0.10, 0.25, 0.50, 0.75, 1.00],
            [("In-domain / classification", 12000, 0.120, 0.012), ("Corrupted inputs / ImageNet-C", 10000, 0.185, 0.016), ("Cross-domain / DomainNet", 9000, 0.214, 0.018), ("Long-tail / rare classes", 4200, 0.248, 0.021), ("Adverse conditions", 3800, 0.271, 0.023)],
            "Cross-domain vision benchmark",
        ),
        "language": (
            "training_examples", [100, 500, 1000, 5000, 10000, 50000, 100000],
            [("In-domain / classification", 18000, 0.105, 0.010), ("Domain shift / legal", 6200, 0.162, 0.014), ("Long-context / retrieval", 5400, 0.188, 0.016), ("Low-resource language", 3100, 0.232, 0.019), ("Adversarial / noisy text", 4700, 0.256, 0.021)],
            "Cross-domain language benchmark",
        ),
        "timeseries": (
            "observed_history_fraction", [0.05, 0.10, 0.20, 0.35, 0.50, 0.75, 1.00],
            [("In-domain / short horizon", 18000, 0.118, 0.011), ("Seasonal shift", 12000, 0.164, 0.014), ("Sensor dropout", 9000, 0.203, 0.017), ("Regime change", 7600, 0.238, 0.019), ("Rare event / tail", 3400, 0.286, 0.024)],
            "Cross-regime time-series benchmark",
        ),
    }
    axis, levels, scenarios, label = configurations[domain]
    profile.update({
        "specialized_domain": domain,
        "progression_axis": axis,
        "progression_levels": levels,
        "slice_scenarios": scenarios,
        "assets": _specialized_assets(label, "Data and training scaling", "training_dynamics"),
    })


def _specialized_assets(main_title: str, progression_title: str, subtype: str) -> list[tuple[str, str, str, str, str]]:
    return [
        ("main", "cross_dataset_task_matrix", "result", main_title, ""),
        ("sensitivity", "objective_architecture_ablation", "ablation", "Objective and architecture ablation", ""),
        ("progression", "data_scaling" if subtype == "training_dynamics" else "pretraining_scaling", "analysis", progression_title, subtype),
        ("robustness", "cross_shift_generalization", "robustness", "Cross-domain generalization" if subtype == "training_dynamics" else "Cross-shift generalization", ""),
        ("case_analysis", "dataset_error_map", "error_analysis", "Slice-level error analysis" if subtype == "training_dynamics" else "Dataset-level error analysis", ""),
        ("coverage", "task_calibration_frontier", "calibration", "Calibration and risk coverage" if subtype == "training_dynamics" else "Task calibration and risk coverage", ""),
        ("burden", "parameter_flops_tradeoff", "efficiency", "Performance and resource trade-off" if subtype == "training_dynamics" else "Parameter and FLOPs trade-off", ""),
    ]


def _normalize_assets(
    raw_assets: list[tuple[str, str, str, str, str]], domain: str,
) -> dict[str, dict[str, str]]:
    assets: dict[str, dict[str, str]] = {}
    for key, domain_role, role, title, subtype in raw_assets:
        slug, completeness_role, label, table_label = _STABLE_CONTRACT[key]
        assets[key] = {
            "slug": slug,
            "completeness_role": completeness_role,
            "domain_asset_role": domain_role,
            "scientific_role": role,
            "description": f"{title} with uncertainty intervals.",
            "table_description": f"{title} with uncertainty intervals.",
            "scientific_question": f"What does the prespecified {title.casefold()} show?",
            "intended_comparison": f"Registered analyses for {title.casefold()}.",
            "visual_encoding": f"{title} with two-sided 95% intervals or bands.",
            "analysis_subtype": subtype or domain_role,
            "label": label,
            "table_label": table_label,
        }
    for key, (plot_family, visual_encoding) in _PLOT_CONTRACTS.items():
        asset = assets[key]
        asset["plot_family"] = plot_family
        asset["visual_encoding"] = visual_encoding
        prefix = asset["description"].removesuffix(" with uncertainty intervals.")
        asset["description"] = f"{prefix}. {visual_encoding}"
    if domain == "algorithmic":
        assets["main"]["description"] = "Primary method comparison with 95% confidence intervals."
        assets["main"]["table_description"] = "Primary comparison with 95% confidence intervals."
    from .simulation_interval_caption import scenario_interval_caption
    for role, asset in assets.items():
        for field in ("description", "table_description", "visual_encoding"):
            asset[field] = scenario_interval_caption(asset[field], assigned_bounds=role in {'sensitivity', 'robustness', 'coverage'})
    return assets
