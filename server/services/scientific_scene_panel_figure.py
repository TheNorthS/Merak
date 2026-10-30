"""Compile a declared bounded scene partition with exact source IDs and edges.

Presentation panels share one canonical FigureSpec. A cross-panel scientific
relation is always drawn between its original endpoints, never dropped or
replaced by a plausible summary edge. Source/projection validators remain exact.
"""

from __future__ import annotations

from collections import defaultdict
import textwrap
from typing import Any, Callable

from .figurespec_layout_policy import figurespec_layout_issues_payload
from .scientific_architecture_models import ArchitectureCompilation
from .scientific_scene import plan_scientific_layout
from .scientific_scene_partitions import disjoint_panel_ownership, panel_budget_issues
from .scientific_scene_placement import relation_ranks


def _panel_columns(
    objects: list[dict[str, Any]], relations: list[dict[str, Any]],
    panels: list[list[dict[str, Any]]], *, reverse: bool,
) -> tuple[dict[str, tuple[float, float, float]], float, float]:
    """Place owned panels in separate reader-visible lanes at fixed text size."""
    ranks = relation_ranks(objects, relations)
    owner = {str(item["id"]): index for index, panel in enumerate(panels) for item in panel}
    for item in objects:
        identity = str(item["id"])
        upstream = [str(edge["from"]) for edge in relations
                    if edge["to"] == identity and edge["kind"] not in {"constraint", "control"}
                    and owner[str(edge["from"])] != owner[identity]]
        if item["kind"] == "output" and upstream:
            ranks[identity] = max(ranks[source] for source in upstream)
    positions = {}
    for index, panel in enumerate(panels):
        column = len(panels) - index - 1 if reverse else index
        center = 350 + column * 520
        rows: dict[int, list[str]] = defaultdict(list)
        for item in panel:
            rows[ranks[str(item["id"])]].append(str(item["id"]))
        for rank, identities in rows.items():
            width = 470.0 if len(identities) == 1 and len(panel) > 2 else 245.0
            for offset, identity in enumerate(identities):
                x = center + (offset - (len(identities) - 1) / 2) * 350
                positions[identity] = (x, 135 + rank * 125, width)
    return positions, 980.0, 340.0


def _visible_panels(spec: dict[str, Any], owners: list[dict[str, Any]]) -> None:
    """Draw the actual ownership regions, not a metadata-only budget exception."""
    spec["style"]["font_size"] = 22
    spec["groups"] = [{
        "id": panel["id"], "label": f"({chr(97 + index)})",
        "node_ids": panel["object_ids"], "padding": 22,
        "fill": "#F7FAFC", "stroke": "#CCD6E1",
    } for index, panel in enumerate(owners)]


def _compact_boxes(spec: dict[str, Any]) -> None:
    """Fit exact authored labels plus the existing glyph strip, at 20px."""
    for node in spec["nodes"]:
        chars = max(6, int((node["width"] - 28) / (node["font_size"] * 0.60)))
        lines = len(textwrap.wrap(node["label"], width=chars, break_on_hyphens=False))
        reserved = 44 if node["visual_kind"] == "signal" else 32
        node["height"] = max(80.0, reserved + max(1, lines) * 26)
        if node["visual_kind"] in {"audit", "metric_card"}:
            node["height"] = max(104.0, node["height"])


def _projection_layout(
    asset: dict[str, Any], objects: list[dict[str, Any]], relations: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[list[dict[str, Any]]]]:
    budget = dict((asset.get("scene_contract") or {}).get("complexity_budget") or {})
    layout = plan_scientific_layout(
        {"schema": 1, "objects": objects, "relations": relations},
        maximum_nodes=min(8, max(2, int(budget.get("maximum_primary_objects") or 8))),
        complexity_budget=budget,
    )
    by_id = {str(item["id"]): item for item in objects}
    owners = disjoint_panel_ownership(set(by_id), layout["panel_contracts"])
    panels = [[by_id[identity] for identity in owner] for owner in owners]
    issues = panel_budget_issues(panels, relations, layout["complexity_budget"])
    if issues:
        raise ValueError("source projection has an unbounded panel: " + "; ".join(issues))
    return layout, panels


def _mappings(objects: list[dict[str, Any]], owner: dict[str, str]) -> list[dict[str, str]]:
    return [{
        "element_id": str(item["id"]),
        "scientific_object_id": str(item["id"]),
        "panel_id": owner[str(item["id"])],
        "source_path": str(item["source_path"]),
        "semantic_role": f"authored scientific {item['kind']}",
        **({"source_reference": str(item["source_reference"])} if item.get("source_reference") else {}),
        **({"source_sha256": str(item["source_sha256"])} if item.get("source_sha256") else {}),
        **({"source_symbol": str(item["source_symbol"])}
           if str(item.get("source_symbol") or "").strip() else {}),
    } for item in objects]


def _profile(
    objects: list[dict[str, Any]], relations: list[dict[str, Any]],
    projection: dict[str, Any], layout: dict[str, Any], owners: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "compiler": "scientific-scene-figurespec-v2",
        "layout_strategy": "source-bound-panel-partition",
        "covered_component_ids": [str(item["id"]) for item in objects],
        "rendered_node_count": len(objects),
        "rendered_relation_count": len(relations),
        "excluded_component_ids": sorted((projection.get("excluded") or {}).keys()),
        "panel_contracts": owners,
        "branch_partitions": layout["branch_partitions"],
        "cross_panel_relations": layout["cross_panel_relations"],
        "complexity_budget": layout["complexity_budget"],
    }


def compile_partitioned_scene(
    asset: dict[str, Any], objects: list[dict[str, Any]],
    relations: list[dict[str, Any]], projection: dict[str, Any], *,
    candidate: Callable[..., dict[str, Any]], control_ids: Callable[..., set[str]],
    public_names: Callable[..., dict[str, str]],
) -> ArchitectureCompilation | None:
    """Honor a planner split without relaxing any per-panel or pixel gate.

The original scientific identities remain unique. Repeated context in a source
plan becomes a visible cross-panel interface rather than a duplicate source ID.
No source plan means an oversized scene still fails at its original boundary.
"""
    if not (asset.get("layout_plan") or {}).get("split_required"):
        return None
    layout, panels = _projection_layout(asset, objects, relations)
    if not layout["split_required"]:
        return None
    owners = [{
        "id": f"panel_{index + 1}",
        "object_ids": [str(item["id"]) for item in panel],
        "scientific_question": str(asset.get("scientific_question") or ""),
    } for index, panel in enumerate(panels)]
    ownership = {identity: panel["id"] for panel in owners for identity in panel["object_ids"]}
    controls, names = control_ids(objects, relations), public_names(asset, objects)
    failures = []
    for reverse in (False, True):
        try:
            spec = candidate(asset, objects, relations, controls, names, _panel_columns(objects, relations, panels, reverse=reverse))
        except ValueError as error:
            failures.append(str(error))
            continue
        _compact_boxes(spec)
        _visible_panels(spec, owners)
        issues = figurespec_layout_issues_payload(spec)
        if issues:
            failures.extend(issues[:3])
            continue
        for node in spec["nodes"]:
            node["panel_id"] = ownership[str(node["id"])]
        spec["scientific_panels"] = owners
        spec["cross_panel_relations"] = [
            dict(edge) for edge in relations
            if ownership[str(edge["from"])] != ownership[str(edge["to"])]
        ]
        return ArchitectureCompilation(
            spec, _mappings(objects, ownership), _profile(
                objects, relations, projection,
                {**layout, "cross_panel_relations": spec["cross_panel_relations"]}, owners,
            ),
        )
    raise ValueError("source-bound panel composition cannot preserve collision-free readable relations: " + "; ".join(failures))
