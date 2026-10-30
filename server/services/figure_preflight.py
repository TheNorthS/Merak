"""Pre-generation scientific and layout checks for model-owned figures."""

from __future__ import annotations

from typing import Any
import json

from ..contracts.repairs import repair_capability_for


def figure_preflight_findings(asset: dict[str, Any]) -> list[dict[str, Any]]:
    """Return owner-routable defects before any renderer/model call."""
    if asset.get("producer_kind") != "model" or asset.get("kind") != "figure":
        return []
    identity = str(asset.get("id") or "").strip()
    findings: list[dict[str, Any]] = []
    scene = asset.get("scientific_scene")
    scene = scene if isinstance(scene, dict) else {}
    objects = [item for item in scene.get("objects") or [] if isinstance(item, dict)]
    layout = asset.get("layout_plan")
    layout = layout if isinstance(layout, dict) else {}
    if identity == "method_architecture":
        findings.extend(_method_mapping_findings(asset, objects))
        findings.extend(_method_completeness_findings(asset))
    maximum = int((asset.get("scene_contract") or {}).get("maximum_primary_nodes") or 12)
    panels = layout.get("panels") if isinstance(layout.get("panels"), list) else []
    if len(objects) > maximum and not layout.get("split_required"):
        findings.append(_finding(
            identity, "FIGURE-PREFLIGHT-LAYOUT-COMPLEXITY", "visual_layout",
            f"{identity} has {len(objects)} scientific objects but no bounded panel split",
            ["figures/SCIENTIFIC_ASSET_PLAN.json"],
        ))
    if panels and any(len(panel) > maximum for panel in panels if isinstance(panel, list)):
        findings.append(_finding(
            identity, "FIGURE-PREFLIGHT-PANEL-COMPLEXITY", "visual_layout",
            f"{identity} contains a panel above the {maximum}-object limit",
            ["figures/SCIENTIFIC_ASSET_PLAN.json"],
        ))
    return findings


def _method_mapping_findings(
    asset: dict[str, Any], scene_objects: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    blueprint = asset.get("architecture_blueprint")
    blueprint = blueprint if isinstance(blueprint, dict) else {}
    components = [
        item for item in blueprint.get("components") or []
        if isinstance(item, dict)
        and str(item.get("source_path") or "").strip()
        and str(item.get("source_symbol") or "").strip()
    ]
    mappings = [
        item for item in asset.get("element_mappings") or []
        if isinstance(item, dict)
    ]
    if components or mappings:
        return []
    source_refs = [
        item for item in scene_objects
        if str(item.get("source_path") or "").strip()
    ]
    if source_refs:
        return []
    return [_finding(
        "method_architecture", "FIGURE-PREFLIGHT-SOURCE-MAPPING",
        "scientific_alignment",
        "method_architecture has no source-bound scene object or verified implementation component mapping",
        ["experiments/METHOD_CONTRACT.json", "experiments/src"],
    )]


def _method_completeness_findings(asset: dict[str, Any]) -> list[dict[str, Any]]:
    blueprint = asset.get("architecture_blueprint")
    blueprint = blueprint if isinstance(blueprint, dict) else {}
    issues = [
        str(item).strip() for item in blueprint.get("completeness_issues") or []
        if str(item).strip()
    ]
    return [
        _finding(
            "method_architecture",
            f"FIGURE-PREFLIGHT-METHOD-COMPLETENESS-{index + 1:03d}",
            "scientific_alignment",
            "component mapping cannot produce a complete scientific path: " + issue,
            ["experiments/METHOD_CONTRACT.json", "experiments/src/"],
        )
        for index, issue in enumerate(issues)
    ]


def _finding(
    asset_id: str, finding_id: str, category: str, message: str,
    targets: list[str],
) -> dict[str, Any]:
    capability = repair_capability_for(
        message=message, target_files=targets, category=category,
    )
    return {
        "id": finding_id,
        "severity": "blocker",
        "category": category,
        "message": message,
        "plain_message": message,
        "target_files": targets,
        "asset_ids": [asset_id],
        "owner_node": capability.owner if capability else "figure",
        "repair_capability": capability.identity if capability else "",
        "validator": capability.validator if capability else "",
        "remediation": (
            "Repair the source-bound scientific scene before rendering."
            if capability and capability.owner == "exp-design"
            else "Reduce or partition the scene before rendering."
        ),
    }


def asset_plan_preflight_findings(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        finding
        for asset in plan.get("assets") or [] if isinstance(asset, dict)
        for finding in figure_preflight_findings(asset)
    ]


def append_figure_preflight_prompt(prompt: str, plan: dict[str, Any]) -> str:
    findings = asset_plan_preflight_findings(plan)
    if not findings:
        return prompt
    return (
        prompt + "\n\n## Deterministic preflight blockers\n"
        + json.dumps(findings, ensure_ascii=False, indent=2)
        + "\nDo not call generate_figure for blocked assets. Return the owner "
        "findings unchanged so the workflow routes them to the declared producer."
    )
