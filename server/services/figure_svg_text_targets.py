"""Bind rendered text findings to the SVG group that owns each label."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Iterable
from typing import Any


def _tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def text_group_targets(root: ET.Element) -> dict[str, str]:
    """Return the deepest named group for each visible text label."""
    targets: dict[str, str] = {}

    def visit(element: ET.Element, groups: tuple[str, ...]) -> None:
        next_groups = groups
        if _tag(element) == "g" and element.attrib.get("id"):
            next_groups = (*groups, str(element.attrib["id"]))
        if _tag(element) == "text":
            label = " ".join("".join(element.itertext()).split())
            if label:
                owner = next_groups[-1] if next_groups else "full_svg"
                previous = targets.setdefault(label, owner)
                if previous != owner:
                    targets[label] = "full_svg"
        for child in list(element):
            visit(child, next_groups)

    visit(root, ())
    return targets


def target_for_label(targets: dict[str, str], label: object) -> str:
    """Resolve a PDF label to its SVG owner, including truncated labels."""
    normalized = " ".join(str(label or "").split())
    if normalized in targets:
        return targets[normalized]
    prefix = normalized[:30]
    matched = {
        target for candidate, target in targets.items()
        if prefix and (candidate.startswith(prefix) or prefix in candidate)
    }
    if len(matched) == 1:
        return matched.pop()
    return "full_svg"


def attach_text_targets(
    content: str, findings: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Add stable group targets to rendered text geometry findings."""
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return [dict(item) for item in findings]
    targets = text_group_targets(root)
    enriched: list[dict[str, Any]] = []
    for item in findings:
        result = dict(item)
        group_ids = list(dict.fromkeys(
            target_for_label(targets, label)
            for label in result.get("labels") or []
        ))
        result["fragment_ids"] = group_ids
        result["target_ids"] = group_ids
        enriched.append(result)
    return enriched
