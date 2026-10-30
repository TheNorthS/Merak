"""Bounded placement candidates for authored scientific relations.

Containment contributes hierarchy, not an invented execution edge. Complete
box extents determine canvas coordinates; the publication width limits growth.
"""

from __future__ import annotations

import math
import textwrap
from collections import defaultdict
from typing import Any


Position = tuple[float, float, float]
Placement = tuple[dict[str, Position], float, float]
_NON_HIERARCHICAL = frozenset({"feedback", "shared", "control", "constraint"})


def relation_ranks(
    objects: list[dict[str, Any]], relations: list[dict[str, Any]],
) -> dict[str, int]:
    """Rank directional and containment relations without ordering feedback."""
    identities = {str(item["id"]) for item in objects}
    parents: dict[str, set[str]] = {identity: set() for identity in identities}
    for relation in relations:
        source, target = str(relation["from"]), str(relation["to"])
        if source in identities and target in identities and relation["kind"] not in _NON_HIERARCHICAL:
            parents[target].add(source)
    ranks: dict[str, int] = {}
    remaining = set(identities)
    while remaining:
        ready = sorted(identity for identity in remaining if parents[identity] <= ranks.keys())
        if not ready:
            ranks.update({identity: 0 for identity in remaining})
            break
        for identity in ready:
            ranks[identity] = max((ranks[parent] + 1 for parent in parents[identity]), default=0)
        remaining.difference_update(ready)
    return ranks


def input_aligned_ranks(
    objects: list[dict[str, Any]], relations: list[dict[str, Any]],
) -> dict[str, int]:
    """Place independent inputs immediately before their first consuming stage.

    This changes placement only. Incoming, cyclic and nonhierarchical relations
    retain their original ranks; no scientific edge or object is added or removed.
    """
    ranks = relation_ranks(objects, relations)
    incoming = {str(edge["to"]) for edge in relations}
    for obj in objects:
        identity = str(obj["id"])
        if obj["kind"] not in {"input", "sample", "population"} or identity in incoming:
            continue
        outgoing = [edge for edge in relations if str(edge["from"]) == identity]
        if not outgoing or any(edge["kind"] in _NON_HIERARCHICAL for edge in outgoing):
            continue
        targets = [ranks[str(edge["to"])] for edge in outgoing if str(edge["to"]) in ranks]
        if targets:
            ranks[identity] = max(ranks[identity], min(targets) - 1)
    return ranks


def containment_star(
    objects: list[dict[str, Any]], relations: list[dict[str, Any]],
    *, rotation: float = -math.pi / 2,
) -> Placement:
    """Lay out a source-authored composition around its containing parent."""
    if not relations or any(item["kind"] != "containment" for item in relations):
        raise ValueError("composition layout requires only authored containment relations")
    outgoing: dict[str, set[str]] = defaultdict(set)
    for item in relations:
        outgoing[str(item["from"])].add(str(item["to"]))
    if len(outgoing) != 1:
        raise ValueError("composition layout requires one containing parent")
    parent, children = next(iter(outgoing.items()))
    identities = {str(item["id"]) for item in objects}
    if children != identities - {parent} or parent in children:
        raise ValueError("composition layout must cover every authored child exactly")
    ordered = [str(item["id"]) for item in objects if str(item["id"]) != parent]
    positions: dict[str, Position] = {parent: (0.0, 0.0, 260.0)}
    radius_x, radius_y = (320.0 if len(ordered) == 3 else 280.0, 280.0)
    if len(ordered) > 4:
        radius_x, radius_y = 300.0, 510.0
    if len(ordered) == 7:
        radius_x = 315.0
    for index, identity in enumerate(ordered):
        angle = rotation + 2 * math.pi * index / len(ordered)
        positions[identity] = (radius_x * math.cos(angle), radius_y * math.sin(angle), 260.0)
    return positions, 980.0, 340.0


def perimeter_placement(
    objects: list[dict[str, Any]], *, rotation: float = -math.pi / 2,
) -> Placement:
    """Preserve cyclic relations in a bounded perimeter candidate, not a flow."""
    positions = {}
    for index, item in enumerate(objects):
        angle = rotation + 2 * math.pi * index / len(objects)
        positions[str(item["id"])] = (370 * math.cos(angle), 480 * math.sin(angle), 260.0)
    return positions, 980.0, 340.0


def label_box_height(label: str, width: float, control: bool = False) -> float:
    """Fit the full authored label at 20px; never truncate or shrink the text."""
    chars = max(6, int((width - 28) / (20 * 0.60)))
    lines = max(1, len(textwrap.wrap(
        " ".join(label.split()), width=chars, break_long_words=True, break_on_hyphens=False,
    )))
    return max(110 if control else 140, 20 + lines * 26)


def normalize_placement(
    placement: Placement, controls: set[str], asset: dict[str, Any],
    relations: list[dict[str, Any]],
    labels: dict[str, str] | None = None,
) -> Placement:
    """Translate all boxes into bounds; reject growth that shrinks print text."""
    positions, requested_width, requested_height = placement
    heights = {identity: label_box_height((labels or {}).get(identity, ""), box, identity in controls)
               for identity, (_, _, box) in positions.items()}
    left = min(x - width / 2 for x, _, width in positions.values())
    right = max(x + width / 2 for x, _, width in positions.values())
    top = min(y - heights[identity] / 2 for identity, (_, y, _) in positions.items())
    bottom = max(y + heights[identity] / 2 for identity, (_, y, _) in positions.items())
    width = max(requested_width, right - left + 128)
    height = max(requested_height, bottom - top + 128, width / 3.2)
    width = max(width, height * 0.70)
    contract = asset.get("scene_contract") or {}
    fraction = max(0.25, min(1.0, float(contract.get("target_width_fraction") or 1.0)))
    budget = contract.get("complexity_budget") or {}
    minimum = max(8.0, float(contract.get("minimum_placed_font_pt") or budget.get("minimum_placed_font_pt") or 8.0))
    font = 17.0 if any(str(item.get("label") or "").strip() for item in relations) else 20.0
    if font * 468 * fraction / width < minimum:
        raise ValueError("layout exceeds paper-scale typography; split the authored figure portfolio")
    offset_x = (width - (right - left)) / 2 - left
    offset_y = (height - (bottom - top)) / 2 - top
    normalized = {identity: (x + offset_x, y + offset_y, box_width)
                  for identity, (x, y, box_width) in positions.items()}
    return normalized, round(width, 1), round(height, 1)
