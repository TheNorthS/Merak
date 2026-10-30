"""One contribution-selected table contract shared by renderer and registration.

Stable public labels belong to the producer; data filenames come from the frozen
current simulation profile, never guessed consumer aliases or manuscript refs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .evidence_asset_portfolio import selected_evidence_asset_ids
from .simulation_policy import SIMULATION_MANIFEST_SCHEMA, SIMULATION_RENDERER_VERSION, SIMULATION_STABLE_IDS


_TABLE_ROLES = {
    "main_comparison": ("main", "tab:preview-main-results", "result"),
    "component_ablation": ("sensitivity", "tab:preview-ablation", "ablation"),
    "robustness_sensitivity": ("robustness", "tab:preview-robustness-calibration", "robustness"),
    "error_analysis": ("case_analysis", "tab:preview-error-analysis", "error_analysis"),
    "calibration_risk_coverage": ("coverage", "tab:preview-calibration", "calibration"),
    "efficiency_tradeoff": ("burden", "tab:preview-efficiency", "efficiency"),
}


@dataclass(frozen=True)
class SimulationTableBinding:
    stable_role: str
    asset_id: str
    label: str
    scientific_role: str
    data_path: str = ""
    caption: str = ""


def selected_simulation_table_bindings(profile: dict[str, Any]) -> tuple[SimulationTableBinding, ...]:
    """Require each selected role's declared public label to match its producer."""
    selected = selected_evidence_asset_ids(str(profile.get("contribution_type") or ""))
    assets = profile.get("assets") or {}
    result = []
    for role, (key, label, scientific_role) in _TABLE_ROLES.items():
        if SIMULATION_STABLE_IDS[role] not in selected:
            continue
        asset = assets.get(key) or {}
        if asset.get("table_label") != label:
            raise ValueError(f"{role}: selected table has a missing or unsupported producer label")
        result.append(SimulationTableBinding(role, SIMULATION_STABLE_IDS[role], label,
                                             scientific_role, caption=str(asset.get("table_description")
                                                                          or asset.get("description") or "")))
    return tuple(result)


def simulation_table_bindings_from_manifest(
    payload: dict[str, Any], contribution_type: str,
) -> tuple[SimulationTableBinding, ...]:
    """Bind current selected labels to exact current-profile CSV paths, without migration."""
    if (payload.get("schema") != SIMULATION_MANIFEST_SCHEMA
            or payload.get("renderer_version") != SIMULATION_RENDERER_VERSION):
        raise ValueError("Simulation table registration requires the current schema and renderer")
    profiles = payload.get("domain_asset_profile")
    if not isinstance(profiles, list) or any(not isinstance(item, dict) for item in profiles):
        raise ValueError("Simulation table registration requires a declared domain asset profile")
    by_role = {str(item.get("stable_role") or ""): item for item in profiles}
    if len(by_role) != len(profiles):
        raise ValueError("Simulation table registration refuses duplicate domain roles")
    declared = {str(item.get("path") or "") for item in payload.get("data_files") or []}
    selected = selected_evidence_asset_ids(contribution_type)
    result = []
    for role, (_key, label, scientific_role) in _TABLE_ROLES.items():
        if SIMULATION_STABLE_IDS[role] not in selected:
            continue
        profile = by_role.get(role) or {}
        filename = str(profile.get("data_file") or "")
        relative = "experiments/results/simulated/" + filename
        if (profile.get("semantic_id") != SIMULATION_STABLE_IDS[role] or not filename
                or "/" in filename or "\\" in filename or relative not in declared):
            raise ValueError(f"{role}: selected table data is not bound to its frozen simulation profile")
        result.append(SimulationTableBinding(role, SIMULATION_STABLE_IDS[role], label,
                                             scientific_role, data_path=relative))
    return tuple(result)
