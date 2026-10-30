"""Normalize visual-review findings into actionable ownership boundaries.

The visual reviewer can see the composed pixels, but it cannot know which
authoring layer owns every visible element unless the contract makes that
boundary explicit.  This module keeps the contract deterministic after the
model response: every finding has one owner, concrete target identifiers, and
one repair action.
"""

from __future__ import annotations

import re
from typing import Any


REVIEW_TARGET_LAYERS = (
    "planner",
    "runtime",
    "glyph",
    "scientific_contract",
)

RUNTIME_TARGET_IDS = (
    "composition",
    "mechanism_connections",
    "mechanism_connection_labels",
    "mechanism_frames",
    "canvas_region_headers",
)

_LAYER_ACTIONS = {
    "planner": (
        "Revise the figure decomposition, hierarchy, or reading order before "
        "rendering another candidate."
    ),
    "runtime": (
        "Repair the deterministic labels, connectors, frames, or composition "
        "owned by the SVG runtime; do not redraw a domain glyph for this issue."
    ),
    "glyph": (
        "Repair only the named text-free domain glyph while preserving the "
        "runtime-owned labels, ports, and connectors."
    ),
    "scientific_contract": (
        "Correct the typed scientific relation, notation, decision rule, or "
        "evidence claim before regenerating the visual composition."
    ),
}


def review_target_catalog(
    metadata: dict[str, Any] | None,
    *, artifact_id: str = "",
) -> dict[str, list[str]]:
    """Return target IDs that the reviewer may legally name for each layer."""
    payload = metadata if isinstance(metadata, dict) else {}
    blueprint = payload.get("visual_blueprint")
    blueprint = blueprint if isinstance(blueprint, dict) else {}
    primitive_ids = [
        str(item.get("id") or "").strip()
        for item in blueprint.get("primitives") or []
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    ]
    identity = str(
        artifact_id or payload.get("id") or payload.get("semantic_key") or "figure"
    ).strip()
    return {
        "planner": ["figure_plan"],
        "runtime": list(RUNTIME_TARGET_IDS),
        "glyph": list(dict.fromkeys(primitive_ids)) or ["domain_glyphs"],
        "scientific_contract": ["scientific_contract"],
        "artifact": [identity or "figure"],
    }


def reviewer_ownership_prompt(catalog: dict[str, list[str]]) -> str:
    """Describe the single-owner repair protocol for a native-image reviewer."""
    return f"""\
For every defect, also return one structured finding. Assign exactly one
target_layer based on who can actually repair it:
- planner: information overload, wrong decomposition, hierarchy, or reading order
- runtime: labels, wrapping, typography, boxes, alignment, whitespace, ports,
  arrows, branches, merges, or other composed geometry
- glyph: the scientific appearance of one text-free domain primitive
- scientific_contract: an incorrect/missing scientific relation, notation,
  comparison, decision rule, or evidence claim

Use only these target IDs:
- planner: {', '.join(catalog['planner'])}
- runtime: {', '.join(catalog['runtime'])}
- glyph: {', '.join(catalog['glyph'])}
- scientific_contract: {', '.join(catalog['scientific_contract'])}

Each finding must contain target_layer, target_ids, severity, message, and a
concrete repair_action. Never route a runtime label/connector/layout defect to
a glyph. Mark scientific or unreadable defects blocker; mark optional visual
polish advisory. Every free-text issue must have a matching structured finding;
an unmatched issue is conservatively blocking. Return findings=[] when there
is no defect."""


def _compact(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _infer_layer(text: str) -> str:
    normalized = text.casefold()
    if any(marker in normalized for marker in (
        "scientific relation", "scientific claim", "decision rule", "formula",
        "equation", "notation", "causal meaning", "comparison rule",
        "evidence claim", "unsupported claim", "invented result",
    )):
        return "scientific_contract"
    if any(marker in normalized for marker in (
        "too much information", "information overload", "split the figure",
        "decomposition", "reading order", "five-second", "five second",
        "focal hierarchy", "generic card", "card wall", "narrative hierarchy",
    )):
        return "planner"
    if any(marker in normalized for marker in (
        "glyph", "icon", "waveform", "domain-specific", "domain specific",
        "scientific primitive", "depiction", "illustration", "shape encoding",
    )):
        return "glyph"
    return "runtime"


def _targets(
    raw: Any, layer: str, message: str, catalog: dict[str, list[str]],
) -> list[str]:
    allowed = list(catalog.get(layer) or [])
    requested = raw if isinstance(raw, list) else []
    cleaned = [
        _compact(value) for value in requested
        if _compact(value) in allowed
    ]
    if cleaned:
        return list(dict.fromkeys(cleaned))
    mentioned = [identity for identity in allowed if identity in message]
    if mentioned:
        return mentioned
    return allowed[:1]


def normalize_review_findings(
    review: dict[str, Any], metadata: dict[str, Any] | None = None,
    *, artifact_id: str = "",
) -> list[dict[str, Any]]:
    """Return validated findings, deriving legacy string issues when needed."""
    catalog = review_target_catalog(metadata, artifact_id=artifact_id)
    raw_findings = review.get("findings")
    candidates: list[Any] = (
        list(raw_findings) if isinstance(raw_findings, list) else []
    )
    # Blind readback and deterministic gates may append issues after the model
    # response. Merge those strings even when the reviewer supplied findings so
    # every blocking issue still reaches an actionable owner.
    represented = {
        _compact(item.get("message") or item.get("issue")).casefold()
        for item in candidates if isinstance(item, dict)
    }
    candidates.extend(
        {"message": issue}
        for issue in review.get("issues") or []
        if _compact(issue) and _compact(issue).casefold() not in represented
    )
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, tuple[str, ...], str]] = set()
    for raw in candidates:
        item = raw if isinstance(raw, dict) else {"message": raw}
        message = _compact(item.get("message") or item.get("issue"))
        if not message:
            continue
        proposed = _compact(item.get("target_layer")).casefold()
        layer = proposed if proposed in REVIEW_TARGET_LAYERS else _infer_layer(message)
        target_ids = _targets(item.get("target_ids"), layer, message, catalog)
        severity = _compact(item.get("severity")).casefold()
        if severity not in {"blocker", "advisory"}:
            severity = "blocker"
        action = _compact(item.get("repair_action")) or _LAYER_ACTIONS[layer]
        key = (layer, tuple(target_ids), message.casefold())
        if key in seen:
            continue
        seen.add(key)
        normalized.append({
            "target_layer": layer,
            "target_ids": target_ids,
            "severity": severity,
            "message": message,
            "repair_action": action,
        })
    return normalized[:24]


def group_review_findings(
    findings: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Group already-normalized findings without losing their target IDs."""
    grouped = {layer: [] for layer in REVIEW_TARGET_LAYERS}
    for finding in findings:
        layer = str(finding.get("target_layer") or "")
        if layer in grouped:
            grouped[layer].append(dict(finding))
    return grouped
