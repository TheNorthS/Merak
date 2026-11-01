"""Compile one source-bound scientific method scene into a bounded FigureSpec.

The method contract owns objects and relations. This producer only selects the
figure-scoped scene and places its existing objects; it never invents a node or
silently removes an authored relation from that projection.
"""

from __future__ import annotations

import re
from collections import defaultdict
from itertools import chain
from typing import Any

from .figure_semantic_projection import project_figure_semantics
from .figurespec_layout_policy import figurespec_layout_issues_payload
from .scientific_architecture_models import ArchitectureCompilation
from .scientific_scene import validate_scientific_scene
from .scientific_scene_labels import public_mechanism_overrides, public_scene_text, scene_label_parts
from .scientific_scene_placement import (
    containment_star,
    input_aligned_ranks,
    label_box_height,
    normalize_placement,
    perimeter_placement,
    relation_ranks,
)


class ScientificSceneFigureError(ValueError):
    """A source-scoped method figure cannot be composed without losing meaning."""


_CONTROL_KINDS = frozenset({"control", "constraint"})
_COLORS = {
    "input": ("#EAF3FF", "#2563EB"),
    "method": ("#E8F7F3", "#0F766E"),
    "objective": ("#F1ECFE", "#6D45B5"),
    "control": ("#FFF3DF", "#B96512"),
    "output": ("#EAF1F8", "#345A7D"),
}


def _source_scene(asset: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    scene = asset.get("scientific_scene")
    issues = validate_scientific_scene(scene)
    if issues:
        raise ScientificSceneFigureError("invalid authored scientific_scene: " + "; ".join(issues))
    projection = project_figure_semantics(asset)
    objects = [dict(item) for item in projection["entities_states_transformations"]]
    relations = [dict(item) for item in projection["relations"]]
    if len(objects) < 2 or not relations:
        raise ScientificSceneFigureError(
            "method projection needs at least two source objects and one authored relation"
        )
    budget = dict((asset.get("scene_contract") or {}).get("complexity_budget") or {})
    maximum = min(8, max(2, int(budget.get("maximum_primary_objects") or 8)))
    layout = asset.get("layout_plan") or {}
    if len(objects) > maximum and not layout.get("split_required"):
        raise ScientificSceneFigureError(
            f"method projection has {len(objects)} objects (budget {maximum}); "
            "split the authored figure portfolio before rendering"
        )
    if len(relations) > 24:
        raise ScientificSceneFigureError(
            "method projection has more than 24 relations; split the figure portfolio"
        )
    return objects, relations, projection


def _control_ids(objects: list[dict[str, Any]], relations: list[dict[str, Any]]) -> set[str]:
    outgoing: dict[str, set[str]] = defaultdict(set)
    for item in relations:
        outgoing[str(item["from"])].add(str(item["kind"]))
    ids = {str(item["id"]) for item in objects}
    selected = {
        identity for identity, kinds in outgoing.items()
        if kinds <= _CONTROL_KINDS and kinds & _CONTROL_KINDS
    } & ids
    return selected if len(selected) < len(objects) else set()


def _ranks(objects: list[dict[str, Any]], relations: list[dict[str, Any]]) -> dict[str, int]:
    return relation_ranks(objects, relations)


def _visual_kind(item: dict[str, Any], control: bool) -> tuple[str, str]:
    kind = str(item["kind"])
    label = str(item["label"]).casefold()
    if control:
        return "audit", "control"
    if kind in {"input", "sample", "population"}:
        return ("signal" if re.search(r"signal|wave|eeg|sensor|time[- ]series", label) else "database"), "input"
    if kind in {"state", "tensor", "variable"}:
        return "embedding", "method"
    if kind in {"output", "measurement"}:
        return "metric_card", "output"
    if re.search(r"objective|loss|consistency|criterion", label):
        return "loss", "objective"
    if re.search(r"token|patch|stem|encoder", label):
        return "tensor_stack", "method"
    return "module", "method"


def _public_mechanism_names(asset: dict[str, Any], objects: list[dict[str, Any]]) -> dict[str, str]:
    """Use concise authored publication names only when IDs bind unambiguously."""
    overrides = public_mechanism_overrides(asset, objects)
    return {str(item["id"]): public_scene_text(asset, item, overrides) for item in objects}


def _nodes(
    objects: list[dict[str, Any]], positions: dict[str, tuple[float, float, float]],
    controls: set[str], public_names: dict[str, str],
) -> list[dict[str, Any]]:
    nodes = []
    for item in objects:
        identity = str(item["id"])
        x, y, width = positions[identity]
        visual, role = _visual_kind(item, identity in controls)
        fill, stroke = _COLORS[role]
        label = public_names.get(identity) or " ".join(str(item["label"]).split())
        primary, qualifier = scene_label_parts(label)
        nodes.append({
            "id": identity, "label": primary, **({"sublabel": qualifier} if qualifier else {}),
            "x": round(x, 1), "y": round(y, 1),
            "width": width, "height": label_box_height(label, width, identity in controls),
            "font_size": 20,
            "visual_kind": visual, "fill": fill, "stroke": stroke,
            "text_color": "#182535",
        })
    return nodes


def _edges(relations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    edges = []
    for item in relations:
        kind = str(item["kind"])
        label = " ".join(str(item.get("label") or "").split())
        if len(label) > 30:
            raise ScientificSceneFigureError(
                f"relation {item['from']}→{item['to']} has a label too long for a connector"
            )
        edges.append({
            "from": str(item["from"]), "to": str(item["to"]),
            "scientific_kind": kind,
            "label": label, "style": "dashed" if kind in _CONTROL_KINDS else "solid",
            "color": "#B96512" if kind in _CONTROL_KINDS else "#346A83",
            "thickness": 2.4,
        })
    return edges


def _horizontal_positions(
    primary: list[dict[str, Any]], controls: list[dict[str, Any]],
    relations: list[dict[str, Any]], *, top_controls: bool,
) -> tuple[dict[str, tuple[float, float, float]], float, float]:
    ranks = _ranks(primary, relations)
    by_rank: dict[int, list[str]] = defaultdict(list)
    for item in primary:
        by_rank[ranks[str(item["id"])]].append(str(item["id"]))
    if max(by_rank) > 2:
        raise ScientificSceneFigureError(
            "horizontal layout exceeds paper-scale typography; use a stacked layout"
        )
    positions: dict[str, tuple[float, float, float]] = {}
    base_y = 240 if controls else 170
    for rank, identities in sorted(by_rank.items()):
        for index, identity in enumerate(identities):
            y = base_y + (index - (len(identities) - 1) / 2) * 170
            if top_controls and controls:
                y += 180
            positions[identity] = (225 + rank * 300, y, 260)
    for index, item in enumerate(controls):
        identity = str(item["id"])
        targets = [str(edge["to"]) for edge in relations if edge["from"] == identity]
        target_x = [positions[target][0] for target in targets if target in positions]
        x = sum(target_x) / len(target_x) if target_x else 225
        y = 110 + index * 145 if top_controls else 525 + index * 145
        positions[identity] = (x, y, 260)
    width = max(980, 450 + max(by_rank) * 300)
    height = max(640 if controls else 340, max(y for _, y, _ in positions.values()) + 115)
    return positions, width, height


def _vertical_positions(
    primary: list[dict[str, Any]], controls: list[dict[str, Any]],
    relations: list[dict[str, Any]], *, left_controls: bool, align_inputs: bool = False,
) -> tuple[dict[str, tuple[float, float, float]], float, float]:
    ranks = input_aligned_ranks(primary, relations) if align_inputs else _ranks(primary, relations)
    by_rank: dict[int, list[str]] = defaultdict(list)
    for item in primary:
        by_rank[ranks[str(item["id"])]].append(str(item["id"]))
    positions: dict[str, tuple[float, float, float]] = {}
    objects_by_id = {str(item["id"]): item for item in primary}
    row_y, previous_height = 135.0, 0.0
    for rank, identities in sorted(by_rank.items()):
        count = len(identities)
        width = 470 if count == 1 else 330 if count == 2 else 245
        row_height = max(label_box_height(str(objects_by_id[identity]["label"]), width) for identity in identities)
        if previous_height:
            row_y += previous_height / 2 + row_height / 2 + 52
        for index, identity in enumerate(identities):
            x = 490 + (index - (count - 1) / 2) * (width + 46)
            positions[identity] = (x, row_y, width)
        previous_height = row_height
    for index, item in enumerate(controls):
        identity = str(item["id"])
        x = 155 if left_controls else 825
        y = 135 + index * 155
        positions[identity] = (x, y, 245)
    height = max(540, 280 + max(by_rank) * 155)
    return positions, 980, height


def _candidate(
    asset: dict[str, Any], objects: list[dict[str, Any]],
    relations: list[dict[str, Any]], controls: set[str],
    public_names: dict[str, str],
    layout: tuple[dict[str, tuple[float, float, float]], float, float],
) -> dict[str, Any]:
    try:
        labels = {str(item["id"]): public_names.get(str(item["id"])) or str(item["label"]) for item in objects}
        positions, width, height = normalize_placement(layout, controls, asset, relations, labels)
    except ValueError as error:
        raise ScientificSceneFigureError(str(error)) from error
    brief = asset.get("method_brief") or {}
    publication = brief.get("publication") or {}
    title = str(publication.get("method_name") or asset.get("scientific_question") or "Method overview")
    return {
        "title": title, "canvas": {"width": width, "height": height},
        "style": {
            "font_family": "Arial, Helvetica, sans-serif", "font_size": 20,
            "bg_color": "#FFFFFF",
            "palette": ["#2563EB", "#0F766E", "#6D45B5", "#B96512"],
        },
        "nodes": _nodes(objects, positions, controls, public_names),
        "edges": _edges(relations), "groups": [], "labels": [],
    }


def compile_scientific_scene_figure(asset: dict[str, Any]) -> ArchitectureCompilation:
    """Return a FigureSpec for the projected scene or a precise producer error.

    Layout alternatives are bounded and independently validated. The original
    object IDs, labels, and relation endpoints remain unchanged in every option.
    """
    objects, relations, projection = _source_scene(asset)
    from .scientific_scene_panel_figure import compile_partitioned_scene

    try:
        partitioned = compile_partitioned_scene(
            asset, objects, relations, projection, candidate=_candidate,
            control_ids=_control_ids, public_names=_public_mechanism_names,
        )
    except ValueError as error:
        raise ScientificSceneFigureError(str(error)) from error
    if partitioned is not None:
        return partitioned
    controls = _control_ids(objects, relations)
    primary = [item for item in objects if str(item["id"]) not in controls]
    supporting = [item for item in objects if str(item["id"]) in controls]
    public_names = _public_mechanism_names(asset, objects)
    options = (
        ("containment-composition", lambda: containment_star(objects, relations)),
        ("horizontal-control-bottom", lambda: _horizontal_positions(primary, supporting, relations, top_controls=False)),
        ("horizontal-control-top", lambda: _horizontal_positions(primary, supporting, relations, top_controls=True)),
        ("vertical-control-left", lambda: _vertical_positions(primary, supporting, relations, left_controls=True)),
        ("vertical-control-right", lambda: _vertical_positions(primary, supporting, relations, left_controls=False)),
        ("vertical-input-aligned-left", lambda: _vertical_positions(primary, supporting, relations, left_controls=True, align_inputs=True)),
        ("vertical-input-aligned-right", lambda: _vertical_positions(primary, supporting, relations, left_controls=False, align_inputs=True)),
        ("relation-perimeter", lambda: perimeter_placement(objects)),
        ("relation-perimeter-rotated", lambda: perimeter_placement(objects, rotation=0.0)),
    )
    from .scientific_scene_topology_layout import topology_placements
    topology = (("topology-perimeter", lambda placement=placement: placement)
                for placement in topology_placements(objects, relations, public_names))
    failures = []
    for name, arrange in chain(options, topology):
        try:
            spec = _candidate(asset, objects, relations, controls, public_names, arrange())
        except ValueError as error:
            if len(failures) < 12:
                failures.append(f"{name}: {error}")
            continue
        issues = figurespec_layout_issues_payload(spec)
        if issues:
            if len(failures) < 12:
                failures.append(f"{name}: {'; '.join(issues[:3])}")
            continue
        mappings = [{
            "element_id": str(item["id"]),
            "source_path": str(item["source_path"]),
            "source_label": str(item["label"]),
            "semantic_role": f"authored scientific {item['kind']}",
            **({"source_symbol": str(item["source_symbol"])}
               if str(item.get("source_symbol") or "").strip() else {}),
        } for item in objects]
        return ArchitectureCompilation(spec, mappings, {
            "compiler": "scientific-scene-figurespec-v2",
            "layout_strategy": name,
            "covered_component_ids": [str(item["id"]) for item in objects],
            "rendered_node_count": len(objects),
            "rendered_relation_count": len(relations),
            "excluded_component_ids": sorted((projection.get("excluded") or {}).keys()),
        })
    raise ScientificSceneFigureError(
        "source-scoped method scene has no collision-free FigureSpec layout: "
        + " | ".join(failures)
    )
