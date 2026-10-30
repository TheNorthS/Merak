"""Check active experiment configuration against implemented method claims."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

import yaml


FindingAdder = Callable[[str, str, list[str], str], None]
_CONFIG_ARGUMENT = re.compile(r"(?:^|\s)--config(?:=|\s+)(?:\"([^\"]+)\"|'([^']+)'|([^\s]+))")


def _active_config(root: Path, run_spec: dict[str, Any]) -> tuple[Path | None, dict[str, Any]]:
    candidates: list[str] = []
    for field in ("command", "scientific_command", "execution_command"):
        command = str(run_spec.get(field) or "")
        for match in _CONFIG_ARGUMENT.finditer(command):
            candidates.append(next(value for value in match.groups() if value is not None))
    if not candidates:
        candidates.extend(f"experiments/configs/main.{suffix}" for suffix in ("yaml", "yml", "json"))
    for raw_path in candidates:
        candidate = (root / raw_path).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            continue
        if not candidate.is_file() or candidate.suffix.casefold() not in {".yaml", ".yml", ".json"}:
            continue
        try:
            payload = yaml.safe_load(candidate.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, yaml.YAMLError):
            continue
        if isinstance(payload, dict):
            return candidate, payload
    return None, {}


def _probe_heads(model: dict[str, Any], roles: list[str]) -> tuple[list[str], list[str]]:
    missing: list[str] = []
    configured: list[str] = []
    for role in roles:
        key = f"{role}_classes"
        if key not in model:
            continue  # A separate or dynamically sized probe is possible.
        count = model[key]
        if count is None or (isinstance(count, int) and not isinstance(count, bool) and count < 2):
            missing.append(f"model.{key}={count!r}")
        else:
            configured.append(f"model.{key}={count!r}")
    return missing, configured


def _probe_training_mode(probe: dict[str, Any], weights: dict[str, Any]) -> str:
    if probe.get("enabled") is not True:
        return "disabled"
    declared = str(
        probe.get("training_mode") or probe.get("probe_mode") or probe.get("mode") or ""
    ).strip().casefold().replace("-", "_")
    if declared in {"joint", "joint_objective", "in_model", "adversarial", "gradient_reversal"}:
        return "joint_objective"
    if declared in {"frozen", "frozen_downstream", "downstream", "posthoc", "post_hoc", "linear"}:
        return "frozen_downstream"
    if any(
        isinstance(weight, (int, float)) and not isinstance(weight, bool) and weight > 0
        for weight in weights.values()
    ):
        return "joint_objective"
    return "unspecified"


def _joint_objective_status(enabled: bool, roles: list[str], weights: dict[str, Any]) -> str:
    if not enabled:
        return "disabled"
    if not weights:
        return "unverified"
    if any(
        isinstance(weight, (int, float)) and not isinstance(weight, bool) and weight <= 0
        for weight in weights.values()
    ):
        return "inactive"
    if len(weights) == len(roles) and all(
        isinstance(weight, (int, float)) and not isinstance(weight, bool) and weight > 0
        for weight in weights.values()
    ):
        return "enabled"
    return "unverified"


def _probe_head_status(mode: str, missing: list[str], configured: list[str]) -> str:
    if mode == "disabled":
        return "disabled"
    if mode == "frozen_downstream":
        return "not_required"
    if mode == "unspecified":
        return "unverified_mode"
    if missing:
        return "unconfigured"
    if configured:
        return "head_configured"
    return "unverified_dynamic"


def _probe_state(
    name: str, probe: dict[str, Any], model: dict[str, Any],
    objective: dict[str, Any], relative: str,
) -> dict[str, Any]:
    roles = name.removesuffix("_probe").split("_")
    weights = {
        f"objective.{role}_probe_weight": objective[f"{role}_probe_weight"]
        for role in roles if f"{role}_probe_weight" in objective
    }
    missing, configured = _probe_heads(model, roles)
    mode = _probe_training_mode(probe, weights)
    return {
        "name": name,
        "mechanism_id": str(probe.get("mechanism_id") or ""),
        "source_path": relative,
        "training_mode": mode,
        "head_status": _probe_head_status(mode, missing, configured),
        "configured_heads": configured,
        "missing_heads": missing,
        "joint_objective_status": _joint_objective_status(probe.get("enabled") is True, roles, weights),
        "objective_weights": weights,
    }


def active_probe_configuration_findings(
    root: Path,
    method: dict[str, Any],
    run_spec: dict[str, Any],
    *,
    add: FindingAdder,
) -> list[dict[str, Any]]:
    """Report probe configuration without conflating downstream and joint probes.

    A frozen downstream probe need not have a head in the main model or a joint
    loss weight. Only a probe explicitly configured for joint training (or with
    a positive joint weight) can be rejected for an impossible main-model head.
    """
    config_path, config = _active_config(root, run_spec)
    ablations = config.get("ablations")
    if config_path is None or not isinstance(ablations, dict):
        return []
    model = config.get("model")
    model = model if isinstance(model, dict) else {}
    objective = config.get("objective")
    objective = objective if isinstance(objective, dict) else {}
    relative = config_path.relative_to(root).as_posix()
    states: list[dict[str, Any]] = []
    for name, probe in ablations.items():
        if not isinstance(name, str) or not name.endswith("_probe") or not isinstance(probe, dict):
            continue
        state = _probe_state(name, probe, model, objective, relative)
        states.append(state)
        if state["training_mode"] == "joint_objective" and state["missing_heads"]:
            add(
                "IMPL-CONFIG-PROBE-" + name.upper().replace("_", "-"),
                f"Configured {name} is enabled, but its model head cannot be constructed: "
                + ", ".join(state["missing_heads"]) + ".",
                ["experiments/METHOD_CONTRACT.json", "experiments/RUN_SPEC.json", relative],
                "Configure at least two development-derived classes for each required probe, "
                "verify its outputs in the bounded integration check, or revise the method "
                "contract and evaluation claim if the probe is not part of the implemented method.",
            )
    return states
