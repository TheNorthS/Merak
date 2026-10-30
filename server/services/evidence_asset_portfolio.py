"""Select manuscript evidence assets from contribution and study structure."""

from __future__ import annotations


_ASSET_BY_ROLE = {
    "main_comparison": "synthetic_preview_main_comparison",
    "component_ablation": "synthetic_preview_ablation",
    "training_dynamics": "synthetic_preview_training_dynamics",
    "robustness_sensitivity": "synthetic_preview_robustness",
    "error_analysis": "synthetic_preview_error_analysis",
    "calibration_risk_coverage": "synthetic_preview_calibration",
    "efficiency_tradeoff": "synthetic_preview_efficiency",
}

_ROLE_PORTFOLIOS = {
    "model_architecture": ("main_comparison", "component_ablation", "training_dynamics", "efficiency_tradeoff"),
    "objective_mechanism": ("main_comparison", "component_ablation", "robustness_sensitivity", "calibration_risk_coverage"),
    "experimental_protocol": ("main_comparison", "robustness_sensitivity", "error_analysis"),
    "system_architecture": ("main_comparison", "robustness_sensitivity", "efficiency_tradeoff", "training_dynamics"),
    "dataset_benchmark": ("main_comparison", "error_analysis", "robustness_sensitivity"),
    "empirical_discovery": ("main_comparison", "error_analysis", "robustness_sensitivity"),
    "theory_proof": ("main_comparison", "component_ablation", "robustness_sensitivity"),
    "clinical_biological_mechanism": ("main_comparison", "error_analysis", "calibration_risk_coverage", "robustness_sensitivity"),
    "qualitative_framework": ("main_comparison", "error_analysis", "calibration_risk_coverage"),
}


def selected_evidence_asset_ids(contribution_type: str) -> set[str]:
    try:
        roles = _ROLE_PORTFOLIOS[contribution_type]
    except KeyError as exc:
        raise ValueError(f"unsupported contribution portfolio: {contribution_type}") from exc
    return {_ASSET_BY_ROLE[role] for role in roles}
