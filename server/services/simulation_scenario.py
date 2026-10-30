"""Prepare immutable scenario contracts for a deterministic simulation study."""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any, Callable

from .experiment_placeholder_context import (
    json_object,
    yaml_object,
    simulation_domain_context,
    normalized_metric_direction,
)
from .publication_labels import publication_metric_label, publication_metric_axis_label
from .simulation_asset_profile import simulation_asset_profile
from .simulation_evidence_helpers import is_primary_reference_axis


@dataclass(frozen=True)
class SimulationScenario:
    simulation_seed: str
    simulation_id: str
    source_run_id: str
    disclosure: str
    simulated_data: Path
    simulated_figures: Path
    table_dir: Path
    selected_contract: dict[str, Any]
    method_contract: dict[str, Any]
    configured_contract: dict[str, Any]
    configured_method: dict[str, Any]
    asset_profile: dict[str, Any]
    configured_training_horizon: int | None
    coverage_y_axis_label: str
    assets: dict[str, dict[str, str]]
    registered_axes: list[dict[str, Any]]
    primary_reference_axis: Callable[[dict[str, Any]], bool]
    holm_alpha: float
    has_registered_ablation_contract: bool
    primary_metric_axis_label: str


def prepare_simulation_scenario(
    root: Path,
    publication_style: dict[str, Any],
    direction: str,
    validation_curve_labels: tuple[str, str],
    primary_metric: str,
    metric_direction: str,
) -> SimulationScenario:
    seed = "1729"
    identity = "merak-structural-simulation-v1"
    directories = (
        root / "experiments" / "results" / "simulated",
        root / "figures" / "simulated",
        root / "paper" / "tables",
    )
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)
    selected = json_object(root / "ideas" / "SELECTED_IDEA.json")
    method = json_object(root / "experiments" / "METHOD_CONTRACT.json")
    configured = yaml_object(root / "experiments" / "configs" / "main.yaml")
    context = simulation_domain_context(
        root,
        direction=direction,
        selected_contract=selected,
        method_contract=method,
        configured_contract=configured,
    )
    profile = simulation_asset_profile(publication_style, context)
    publication = selected.get("publication") if isinstance(selected.get("publication"), dict) else {}
    profile["contribution_type"] = str((publication or {}).get("contribution_type") or "")
    from .simulation_publication_names import bind_profile_focal_names
    bind_profile_focal_names(profile, str((publication or {}).get("method_name") or ""))
    horizon = _bounded_progression(profile, configured)
    coverage_y = f"{validation_curve_labels[1]} (lower is better)"
    profile.update(
        coverage_x_label=validation_curve_labels[0], coverage_y_label=coverage_y
    )
    configured_method = _mapping(configured.get("method"))
    registry = _mapping(configured_method.get("ranking_registry"))
    primary_axis = partial(is_primary_reference_axis, primary_metric=primary_metric)
    axes = _registered_axes(registry, primary_metric, metric_direction, primary_axis)
    registered_ablation = _has_ablations(
        selected, _mapping(configured.get("experiment"))
    )
    metric_label = publication_metric_axis_label(primary_metric, metric_direction)
    return SimulationScenario(
        seed,
        identity,
        f"simulation:{identity}:seed-{seed}",
        "SIMULATED DATA -- NOT EXPERIMENTAL RESULTS",
        *directories,
        selected,
        method,
        configured,
        configured_method,
        profile,
        horizon,
        coverage_y,
        profile["assets"],
        axes,
        primary_axis,
        float(registry.get("alpha") or 0.05),
        registered_ablation,
        metric_label,
    )


def _bounded_progression(profile: dict[str, Any], config: dict[str, Any]) -> int | None:
    if str(profile.get("progression_axis") or "").casefold() != "epoch":
        return None
    try:
        horizon = int(_mapping(config.get("execution")).get("max_epochs"))
    except (TypeError, ValueError):
        return None
    if horizon <= 0:
        return None
    levels = {
        int(level)
        for level in profile.get("progression_levels") or []
        if isinstance(level, (int, float)) and 1 <= int(level) <= horizon
    }
    profile["progression_levels"] = sorted(levels | {1, horizon})
    return horizon


def _registered_axes(
    registry: dict[str, Any],
    metric: str,
    direction: str,
    primary_axis: Callable[[dict[str, Any]], bool],
) -> list[dict[str, Any]]:
    axes = [
        {
            "axis_id": str(item.get("axis_id") or item.get("metric_key") or "").strip(),
            "metric_key": str(
                item.get("metric_key") or item.get("axis_id") or ""
            ).strip(),
            "direction": normalized_metric_direction(item.get("direction"))
            or direction,
            "mpid": float(item.get("mpid") or 0.0),
        }
        for item in registry.get("axes", [])
        if isinstance(item, dict)
        and str(item.get("axis_id") or item.get("metric_key") or "").strip()
    ]
    if not axes:
        axes = [
            {
                "axis_id": metric,
                "metric_key": metric,
                "direction": direction,
                "mpid": 0.01,
            }
        ]
    for axis in axes:
        axis["family_role"] = "primary_reference" if primary_axis(axis) else "target"
    return axes


def _has_ablations(selected: dict[str, Any], experiment: dict[str, Any]) -> bool:
    mechanisms = [
        item
        for item in selected.get("mechanisms") or []
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    ]
    ablations = [
        item
        for item in experiment.get("ablations") or []
        if str(
            (item.get("id") or item.get("name") or "")
            if isinstance(item, dict)
            else item
        ).strip()
    ]
    return bool(mechanisms or ablations)


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
