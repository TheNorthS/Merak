"""Enforce object and branch bounds together without altering source semantics.

Partitions are presentation ownership, not a rewrite of the scientific scene.
Every source object remains owned, and edges crossing owners remain explicit.
"""

from __future__ import annotations

from typing import Any


def _local_targets(panel: list[dict[str, Any]], relations: list[dict[str, Any]]) -> dict[str, list[str]]:
    ids = {str(item["id"]) for item in panel}
    result: dict[str, list[str]] = {}
    for edge in relations:
        source, target = str(edge["from"]), str(edge["to"])
        if source in ids and target in ids and target not in result.setdefault(source, []):
            result[source].append(target)
    return result


def panel_budget_issues(
    panels: list[list[dict[str, Any]]], relations: list[dict[str, Any]], budget: dict[str, Any],
) -> list[str]:
    """Reject every local overflow rather than accepting a split flag alone."""
    issues = []
    maximum = int(budget["maximum_primary_objects"])
    labels = int(budget["maximum_visible_labels"])
    branches = int(budget["maximum_primary_branches"])
    for index, panel in enumerate(panels):
        count = sum(1 + len(item.get("subitems") or []) for item in panel)
        if not panel or len(panel) > maximum or count > labels:
            issues.append(f"panel {index + 1} exceeds object/label budget")
        if any(len(targets) > branches for targets in _local_targets(panel, relations).values()):
            issues.append(f"panel {index + 1} exceeds branch budget")
    return issues


def _related_score(ids: set[str], targets: set[str], relations: list[dict[str, Any]]) -> int:
    return sum(
        (str(edge["from"]) in ids and str(edge["to"]) in targets)
        or (str(edge["to"]) in ids and str(edge["from"]) in targets)
        for edge in relations
    )


def partition_combined_overflow(
    panels: list[list[dict[str, Any]]], relations: list[dict[str, Any]], budget: dict[str, Any],
) -> list[list[dict[str, Any]]]:
    """Move excess local branches to a related bounded owner, preserving cuts.

The node-bounded planner already owns all objects. This refinement handles the
case where that split still leaves an overloaded fan-out inside one panel.
No source object or relation is deleted, relabeled, or merged.
"""
    result = [list(panel) for panel in panels]
    maximum_branches = int(budget["maximum_primary_branches"])
    for _ in range(sum(len(panel) for panel in panels) * 2):
        overloaded = next((
            (index, targets[maximum_branches:])
            for index, panel in enumerate(result)
            for targets in _local_targets(panel, relations).values()
            if len(targets) > maximum_branches
        ), None)
        if overloaded is None:
            break
        owner, moved_ids = overloaded
        targets = set(moved_ids)
        moved = [item for item in result[owner] if str(item["id"]) in targets]
        result[owner] = [item for item in result[owner] if str(item["id"]) not in targets]
        candidates = sorted(
            (index for index in range(len(result)) if index != owner),
            key=lambda index: (-_related_score(
                {str(item["id"]) for item in result[index]}, targets, relations,
            ), index),
        )
        destination = next((
            index for index in candidates
            if not panel_budget_issues([result[index] + moved], relations, budget)
        ), None)
        if destination is None:
            result.append(moved)
        else:
            result[destination].extend(moved)
    issues = panel_budget_issues(result, relations, budget)
    if issues:
        raise ValueError("scientific scene needs an authored bounded partition: " + "; ".join(issues))
    return result


def disjoint_panel_ownership(
    object_ids: set[str], panel_contracts: list[dict[str, Any]],
) -> list[list[str]]:
    """Assign each source ID once; repeated context is a cross-panel interface.

One canonical FigureSpec cannot duplicate a source ID. Existing relations join
the single owned instance across panels instead of creating an invented edge.
"""
    seen: set[str] = set()
    owners = []
    for panel in panel_contracts:
        ids = [str(value) for value in panel.get("object_ids") or []]
        if any(identity not in object_ids for identity in ids):
            raise ValueError("scientific panel references an object outside its projection")
        selected = [identity for identity in ids if identity not in seen]
        seen.update(selected)
        if selected:
            owners.append(selected)
    if seen != object_ids:
        raise ValueError("scientific panel ownership does not cover its complete projection")
    return owners
