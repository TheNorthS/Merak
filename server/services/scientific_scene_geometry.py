"""Bounded print-point scene geometry independent of domain glyphs or templates."""

from __future__ import annotations

import math
from typing import Any


def _levels(objects: list[dict[str, Any]], relations: list[dict[str, Any]]) -> dict[str, int]:
    ids = {item['id'] for item in objects}
    parents = {identity: set() for identity in ids}
    for edge in relations:
        if edge.get('kind') not in {'feedback', 'shared', 'containment', 'constraint'}:
            parents[edge['to']].add(edge['from'])
    result = {}
    remaining = set(ids)
    while remaining:
        ready = sorted(identity for identity in remaining if parents[identity] <= result.keys())
        if not ready:
            result.update({identity: 0 for identity in remaining})
            break
        for identity in ready:
            result[identity] = max((result[parent] + 1 for parent in parents[identity]), default=0)
        remaining.difference_update(ready)
    return result


def solve_scientific_panel(
    objects: list[dict[str, Any]], relations: list[dict[str, Any]],
    width_pt: float = 468.0,
) -> dict[str, Any]:
    """Solve non-overlapping regions at fixed print width without shrinking labels.

    Geometry is in points; these regions guide domain glyph composition rather
    than forming a universal final card diagram. Scientific cycles are preserved.
    """
    if not objects or len(objects) > 12:
        raise ValueError('a scene geometry panel requires 1–12 scientific objects')
    identities = {item['id'] for item in objects}
    local = [edge for edge in relations if edge['from'] in identities and edge['to'] in identities]
    levels = _levels(objects, local)
    font_pt, margin, gap = 8.5, 20.0, 16.0
    rows = {}
    for item in objects:
        rows.setdefault(levels[item['id']], []).append(item)
    nodes, y = [], margin
    for rank, items in sorted(rows.items()):
        for start in range(0, len(items), 3):
            band = items[start:start + 3]
            box_width = (width_pt - 2 * margin - gap * (len(band) - 1)) / len(band)
            heights = [max(40.0, 20 + math.ceil(len(str(item['label'])) * font_pt * 0.52
                       / max(1, box_width - 16)) * 12) for item in band]
            row_height = max(heights)
            for index, item in enumerate(band):
                nodes.append({'id': item['id'], 'x': margin + index * (box_width + gap),
                              'y': y, 'width': box_width, 'height': row_height,
                              'font_pt': font_pt, 'rank': rank,
                              'scientific_kind': item['kind'], 'label': item['label']})
            y += row_height + 30
    return {'width_pt': width_pt, 'height_pt': y + margin, 'nodes': nodes,
            'relations': local, 'coordinate_unit': 'print_pt',
            'glyph_geometry_owned_by_renderer': True, 'minimum_font_pt': font_pt}
