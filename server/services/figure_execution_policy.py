"""Resolve workflow execution ownership from current canonical figure producers.

This read-only policy does not render, repair, migrate, or accept figures. Only a
complete, unambiguous deterministic portfolio removes the model requirement.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .figure_producer_policy import figure_production_issues


FIGURE_RUNTIME_SERVICE = "figure_renderers+figure_quality_gate"
_DETERMINISTIC_STRATEGIES = frozenset({
    "deterministic_architecture", "deterministic_plot", "deterministic_template",
})
_MODEL_STRATEGIES = frozenset({"model_composed_full_svg", "model_generated_image"})
_LEGACY_MODEL_SKILLS = frozenset({"rich-svg-figure", "paper-illustration"})


@dataclass(frozen=True)
class FigureExecutionPolicy:
    """Producer declarations, not claimed execution evidence or acceptance."""

    kind: str
    policy_required: bool
    model_execution_mode: str
    model_skills: tuple[str, ...] = ()
    issues: tuple[str, ...] = ()
    reason: str = ""
    assets: tuple[dict[str, Any], ...] = ()


def _blocked(issues: list[str]) -> FigureExecutionPolicy:
    return FigureExecutionPolicy(
        kind="hybrid", policy_required=True, model_execution_mode="primary",
        issues=tuple(issues), reason="Figure producer declarations are unresolved; " + "; ".join(issues),
    )


def _read_object(path: Path) -> tuple[dict[str, Any], list[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {}, [f"{path.name} is missing or unreadable: {type(exc).__name__}"]
    if not isinstance(payload, dict):
        return {}, [f"{path.name} root must be an object"]
    return payload, []


def _records(payload: dict[str, Any], key: str, name: str) -> tuple[list[dict[str, Any]], list[str]]:
    values = payload.get(key)
    if not isinstance(values, list):
        return [], [f"{name}.{key} must be a list"]
    active = [item for item in values if isinstance(item, dict)
              and item.get("kind") == "figure" and item.get("generation_policy") != "skip"]
    if key == "figures" and len(active) != len(values):
        return [], [f"{name} contains an invalid or skipped canonical figure"]
    ids = [str(item.get("id") or "").strip() for item in active]
    if not active or any(not identity for identity in ids) or len(set(ids)) != len(ids):
        return [], [f"{name} needs non-empty unique active figure IDs"]
    return active, []


def _asset_policy(record: dict[str, Any]) -> tuple[str, str, list[str]]:
    identity = str(record["id"])
    producer = str(record.get("producer_kind") or "").strip()
    strategy = str(record.get("production_strategy") or "").strip()
    skill = str(record.get("recommended_skill") or "").strip()
    if not strategy:
        if (producer == "model" and skill in _LEGACY_MODEL_SKILLS
                and record.get("composition_owner") in {"model", "glyph"}
                and record.get("full_svg_authority") is not True):
            return "model", skill, []
        return "", "", [f"{identity}: explicit production_strategy is required"]
    issues = [f"{identity}: {issue}" for issue in figure_production_issues(record)]
    if strategy not in _DETERMINISTIC_STRATEGIES | _MODEL_STRATEGIES:
        issues.append(f"{identity}: unsupported production_strategy: {strategy}")
    if issues:
        return "", "", issues
    return producer, skill if producer == "model" else "", []


def _plan_conflicts(root: Path, figures: list[dict[str, Any]]) -> list[str]:
    path = root / "figures/SCIENTIFIC_ASSET_PLAN.json"
    if not path.exists():
        return []
    plan, issues = _read_object(path)
    if issues:
        return issues
    if plan.get("schema") != 2:
        return ["SCIENTIFIC_ASSET_PLAN.json has an unsupported producer schema"]
    assets, issues = _records(plan, "assets", path.name)
    by_id = {str(item["id"]): item for item in assets}
    if set(by_id) != {str(item["id"]) for item in figures}:
        issues.append("FIGURE_SPECS.json and SCIENTIFIC_ASSET_PLAN.json active figures disagree")
    for figure in figures:
        asset = by_id.get(str(figure["id"]))
        if asset is not None and any(asset.get(key) != figure.get(key) for key in (
            "producer_kind", "production_strategy", "composition_owner", "recommended_skill",
        )):
            issues.append(f"{figure['id']}: canonical figure producer declarations conflict")
    return issues


def resolve_figure_execution_policy(project_path: str | Path | None) -> FigureExecutionPolicy:
    """Require all active assets to attest deterministic ownership before waiving models."""
    if not project_path:
        return _blocked(["project_path is required to resolve canonical figure producers"])
    root = Path(project_path).expanduser().resolve()
    payload, issues = _read_object(root / "figures/FIGURE_SPECS.json")
    if issues:
        return _blocked(issues)
    if (payload.get("schema") != 4 or payload.get("publication_label_schema") != 1
            or payload.get("production_policy_schema") != 1):
        return _blocked(["FIGURE_SPECS.json has an unsupported producer/label/policy schema"])
    figures, issues = _records(payload, "figures", "FIGURE_SPECS.json")
    issues.extend(_plan_conflicts(root, figures))
    models = []
    for figure in figures:
        producer, skill, asset_issues = _asset_policy(figure)
        issues.extend(asset_issues)
        if producer == "model":
            models.append(skill)
    if issues:
        return _blocked(issues)
    if models:
        return FigureExecutionPolicy(
            kind="hybrid", policy_required=True, model_execution_mode="any_component",
            model_skills=tuple(dict.fromkeys(models)),
            reason="Declared model-owned figure assets require verified asset-scoped model execution.",
            assets=tuple(figures),
        )
    return FigureExecutionPolicy(
        kind="runtime_owned", policy_required=False, model_execution_mode="primary",
        reason="Every active figure has an explicit deterministic producer; runtime renders and validates it.",
        assets=tuple(figures),
    )
