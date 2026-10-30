"""Validate the scientific connection itinerary of a figure storyboard."""

from __future__ import annotations

import re
from collections import defaultdict, deque
from typing import Any


_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{1,79}$")
_KINDS = {"main", "constraint", "feedback", "side_output"}


def _main_path_exists(
    source: str, target: str, connections: list[dict[str, str]],
) -> bool:
    outgoing: dict[str, list[str]] = defaultdict(list)
    for connection in connections:
        if connection["kind"] == "main":
            outgoing[connection["from"]].append(connection["to"])
    seen, queue = {source}, deque([source])
    while queue:
        for neighbor in outgoing.get(queue.popleft(), []):
            if neighbor == target:
                return True
            if neighbor not in seen:
                seen.add(neighbor)
                queue.append(neighbor)
    return source == target


def validate_storyboard_connections(
    value: Any, region_ids: list[str], reading_order: list[str],
) -> list[dict[str, str]]:
    """Require a connected causal itinerary without prescribing SVG geometry."""
    if not isinstance(value, list) or not 1 <= len(value) <= 16:
        raise ValueError("storyboard needs 1–16 scientific connections")
    normalized: list[dict[str, str]] = []
    identifiers: set[str] = set()
    used: set[str] = set()
    for raw in value:
        if not isinstance(raw, dict):
            raise ValueError("storyboard connection must be an object")
        identity = str(raw.get("id") or "").strip()
        source, target = (str(raw.get(key) or "").strip() for key in ("from", "to"))
        kind = str(raw.get("kind") or "").strip()
        meaning = " ".join(str(raw.get("scientific_meaning") or "").split())
        if not _IDENTIFIER.fullmatch(identity) or identity in identifiers:
            raise ValueError("storyboard connection ids must be unique snake_case")
        if source not in region_ids or target not in region_ids or source == target:
            raise ValueError(f"storyboard connection {identity} has invalid region endpoints")
        if kind not in _KINDS or not 8 <= len(meaning) <= 180:
            raise ValueError(f"storyboard connection {identity} needs kind and scientific_meaning")
        normalized.append({
            "id": identity, "from": source, "to": target,
            "kind": kind, "scientific_meaning": meaning,
        })
        identifiers.add(identity)
        used.update((source, target))
    if set(region_ids) != used:
        raise ValueError("every storyboard region must participate in a scientific connection")
    if not _main_path_exists(reading_order[0], reading_order[-1], normalized):
        raise ValueError("main connections must reach the final reading-order region")
    return normalized
