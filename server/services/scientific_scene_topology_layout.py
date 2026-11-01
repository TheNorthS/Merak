"""Bounded cyclic order search preserves authored relations and complete labels.

Existing fast layouts run first. This candidate handles small planar relation
cycles whose source declaration order is not a usable drawing order.
"""
from __future__ import annotations

import itertools
import math
from typing import Iterator

from .scientific_scene_labels import scene_label_parts
from .scientific_scene_placement import Placement


def _noncrossing(order: tuple[str, ...], relations: list[dict]) -> bool:
    indices = {identity: index for index, identity in enumerate(order)}
    edges = [tuple(sorted((indices[str(edge["from"])], indices[str(edge["to"])]))) for edge in relations]
    for index, (a, b) in enumerate(edges):
        for c, d in edges[index + 1:]:
            if len({a, b, c, d}) == 4 and (a < c < b < d or c < a < d < b):
                return False
    return True


def topology_placements(objects: list[dict], relations: list[dict], labels: dict[str, str]) -> Iterator[Placement]:
    """Search at most four ellipses and 7! orders, without semantic rewrites."""
    identities = tuple(str(item["id"]) for item in sorted(objects, key=lambda item: (
        item.get("kind") not in {"input", "sample", "population"}, str(item["id"]))))
    if not 3 <= len(identities) <= 8:
        return
    widths = {}
    for identity in identities:
        _, qualifier = scene_label_parts(labels[identity])
        extent = sum(17 * (1.0 if ord(char) > 0x2E80 else 0.60) for char in qualifier)
        widths[identity] = max(270.0, math.ceil(extent / 2) + 40.0)
    for remaining in itertools.permutations(identities[1:]):
        order = (identities[0], *remaining)
        if not _noncrossing(order, relations):
            continue
        for radius_x, radius_y in ((300, 380), (300, 430), (290, 450), (280, 470)):
            positions = {}
            for index, identity in enumerate(order):
                angle = -math.pi / 2 + 2 * math.pi * index / len(order)
                positions[identity] = (radius_x * math.cos(angle), radius_y * math.sin(angle), widths[identity])
            yield positions, 980.0, 340.0
