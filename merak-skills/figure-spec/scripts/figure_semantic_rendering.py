"""Faithful publication text and relation semantics for FigureSpec rendering."""

from __future__ import annotations

import math
from typing import Any, Callable
from xml.etree.ElementTree import SubElement


def render_composition_endpoint(
    svg: Any, edge: dict[str, Any], source: tuple[float, float],
    target: tuple[float, float], color: str,
) -> None:
    """Draw the parent diamond as vectors retained by SVG/PDF/PNG converters."""
    if edge.get("scientific_kind") != "containment":
        return
    x, y = source
    dx, dy = target[0] - x, target[1] - y
    length = math.hypot(dx, dy)
    if length <= 0:
        raise ValueError("a containment connector needs distinct source and target positions")
    ux, uy = dx / length, dy / length
    points = [(x, y), (x + 6 * ux - 4.5 * uy, y + 6 * uy + 4.5 * ux),
              (x + 12 * ux, y + 12 * uy), (x + 6 * ux + 4.5 * uy, y + 6 * uy - 4.5 * ux)]
    SubElement(svg, "polygon", {
        "points": " ".join(f"{px:.1f},{py:.1f}" for px, py in points),
        "fill": color, "stroke": color, "data-relation-marker": "containment-parent",
    })


def relation_attributes(edge: dict[str, Any], arrow_id: str) -> dict[str, str]:
    """Keep typed containment visible while retaining arrows for directed flow."""
    kind = str(edge.get("scientific_kind") or "")
    attributes = {"data-relation-kind": kind} if kind else {}
    if kind != "containment":
        attributes["marker-end"] = f"url(#{arrow_id})"
    return attributes


def render_node_text(
    svg: Any, node: dict[str, Any], base_font: float,
    wrap_text: Callable[..., list[str]],
) -> None:
    """Render every word or reject the box; publication labels are never elided."""
    x, y, width, height = node["x"], node["y"], node["width"], node["height"]
    font = node.get("font_size") or base_font
    text_width = max(36.0, width - 28.0)
    label = str(node.get("label") or "")
    main_lines = wrap_text(label, text_width, font, max_lines=max(1, len(label)))
    sub_font = max(8, font - 3)
    sublabel = str(node.get("sublabel") or "")
    sub_lines = wrap_text(sublabel, text_width, sub_font, max_lines=max(1, len(sublabel)))
    main_height, sub_height = font + 2, sub_font + 2
    block_height = len(main_lines) * main_height + len(sub_lines) * sub_height
    top = y - height / 2
    reserved_top = 33 if node.get("visual_kind") == "signal" else 6
    usable_height = height - reserved_top - 6
    if block_height > usable_height:
        raise ValueError(f"FigureSpec node {node['id']} cannot display its complete label inside its box")
    start_y = top + reserved_top + (usable_height - block_height) / 2 + font
    for index, text in enumerate(main_lines):
        element = SubElement(svg, "text", {
            "x": f"{x:.1f}", "y": f"{start_y + index * main_height:.1f}",
            "font-size": str(font), "fill": node["text_color"],
            "text-anchor": "middle", "font-weight": "bold",
        })
        element.text = text
    for index, text in enumerate(sub_lines):
        element = SubElement(svg, "text", {
            "x": f"{x:.1f}",
            "y": f"{start_y + len(main_lines) * main_height + index * sub_height:.1f}",
            "font-size": str(sub_font), "fill": "#888888", "text-anchor": "middle",
        })
        element.text = text
