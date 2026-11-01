"""Bounded paper-only FigureSpec typography with source-exact node/edge meaning.

The caller authenticates the canonical JSON and native renderer. This adapter
only grows fonts, complete label boxes and monotone vertical spacing. Native
glyphs and clipped relation endpoints are regenerated from the same typed graph;
line baselines are then changed by exact node-bound text identity, not regex.
No module-global renderer replacement or research artifact write is performed.
"""

from __future__ import annotations

from copy import deepcopy
import math
from types import ModuleType
from typing import Any
import xml.etree.ElementTree as ET

from .figurespec_layout_policy import figurespec_layout_issues_payload


LINE_HEIGHT = 1.4
GLYPH_HEADERS = frozenset({"signal", "metric_card", "audit", "ledger", "module_stack", "database"})


def _text_height_fraction(node: dict[str, Any]) -> float:
    # The native audit shield starts tapering into its curved base at 0.74h.
    return 0.74 if node.get("visual_kind") == "audit" else 1.0


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError("Paper FigureSpec requires a finite positive " + name)
    return float(value)


def _text_layout(node: dict[str, Any], base_font: float, renderer: ModuleType) -> tuple[list[str], list[str], float, float]:
    font = _number(node.get("font_size") or base_font, "node font")
    subfont = max(8.0, font - 3)
    width = max(36.0, _number(node.get("width", 120), "node width") - 28)
    main = str(node.get("label") or "")
    sub = str(node.get("sublabel") or "")
    return (renderer.wrap_text(main, width, font, max_lines=max(1, len(main))),
            renderer.wrap_text(sub, width, subfont, max_lines=max(1, len(sub))), font, subfont)


def _grow_nodes(spec: dict[str, Any], renderer: ModuleType, multiplier: float) -> None:
    style = spec.setdefault("style", {})
    original = _number(style.get("font_size", renderer.DEFAULT_STYLE["font_size"]), "base font")
    style["font_size"] = original * multiplier
    for node in spec["nodes"]:
        node["font_size"] = _number(node.get("font_size") or original, "node font") * multiplier
        words = str(node.get("label") or "").split() + str(node.get("sublabel") or "").split()
        # Keep two pixels beyond the native 28px inset: fractional font widths
        # must not cross wrap_text's exact <= boundary after subtraction.
        minimum_width = max((renderer.estimate_text_width(word, node["font_size"]) + 30 for word in words), default=0)
        subfont = max(8.0, node["font_size"] - 3)
        qualifier = str(node.get("sublabel") or "")
        qualifier_extent = sum(subfont * (1.0 if ord(char) > 0x2E80 else 0.60) for char in qualifier)
        minimum_width = max(minimum_width, math.ceil(qualifier_extent / 2) + 40 if qualifier else 0)
        node["width"] = max(_number(node.get("width", 120), "node width"), minimum_width)
        main, sub, font, subfont = _text_layout(node, style["font_size"], renderer)
        reserved = 33 if node.get("visual_kind") in GLYPH_HEADERS else 6
        block = len(main) * LINE_HEIGHT * font + len(sub) * LINE_HEIGHT * subfont
        node["height"] = max(_number(node.get("height", 50), "node height"),
                             (reserved + 12 + block) / _text_height_fraction(node))
        if node.get("shape") == "circle" and node["height"] > node.get("width", 120):
            raise ValueError("Paper circle label needs a separately authored wider figure")
    for label in spec.get("labels") or []:
        label["font_size"] = _number(label.get("font_size") or original, "label font") * multiplier


def _vertical_map(spec: dict[str, Any]) -> list[tuple[float, float]]:
    rows: dict[float, float] = {}
    for node in spec["nodes"]:
        y = float(node["y"])
        rows[y] = max(rows.get(y, 0.0), float(node["height"]))
    result, previous_bottom = [], None
    for original_y, height in sorted(rows.items()):
        y = max(original_y, height / 2 + 70)
        if previous_bottom is not None:
            y = max(y, previous_bottom + height / 2 + 28)
        result.append((original_y, y))
        previous_bottom = y + height / 2
    return result


def _map_y(value: float, mapping: list[tuple[float, float]]) -> float:
    if value <= mapping[0][0]:
        return value + mapping[0][1] - mapping[0][0]
    for (first, target_first), (second, target_second) in zip(mapping, mapping[1:]):
        if value <= second:
            return target_first + (value - first) * (target_second - target_first) / (second - first)
    return value + mapping[-1][1] - mapping[-1][0]


def _expand_vertical(spec: dict[str, Any]) -> None:
    mapping = _vertical_map(spec)
    for node in spec["nodes"]:
        node["y"] = _map_y(float(node["y"]), mapping)
    for item in [*(spec.get("regions") or []), *(group.get("bounds") for group in spec.get("groups") or [] if group.get("bounds"))]:
        top = float(item["y"])
        item["y"] = _map_y(top, mapping)
        item["height"] = _map_y(top + float(item["height"]), mapping) - item["y"]
    for label in spec.get("labels") or []:
        label["y"] = _map_y(float(label["y"]), mapping)
    bottom = max(float(node["y"]) + float(node["height"]) / 2 for node in spec["nodes"])
    spec["canvas"]["height"] = max(float(spec["canvas"]["height"]), bottom + 70)


def project_figurespec_typography(spec: dict[str, Any], renderer: ModuleType, multiplier: float) -> dict[str, Any]:
    """Return a presentation-only deep copy, rejecting unsafe geometry growth."""
    if not math.isfinite(multiplier) or not 1.0 <= multiplier <= 4.0:
        raise ValueError("Paper FigureSpec font multiplier must stay in 1..4")
    if not isinstance(spec, dict) or not isinstance(spec.get("nodes"), list) or not spec["nodes"]:
        raise ValueError("Paper FigureSpec typography requires its canonical typed nodes")
    projected = deepcopy(spec)
    _grow_nodes(projected, renderer, multiplier)
    _expand_vertical(projected)
    issues = figurespec_layout_issues_payload(projected)
    if issues:
        raise ValueError("Paper FigureSpec typography cannot preserve valid geometry: " + "; ".join(issues))
    return projected


def _bound_node_text(root: ET.Element, node: dict[str, Any], renderer: ModuleType, base: float) -> tuple[list[ET.Element], list[str], list[str], float, float]:
    main, sub, font, subfont = _text_layout(node, base, renderer)
    block = len(main) * (font + 2) + len(sub) * (subfont + 2)
    top = float(node["y"]) - float(node["height"]) / 2
    reserve = 33 if node.get("visual_kind") == "signal" else 6
    usable = float(node["height"]) - reserve - 6
    start = top + reserve + (usable - block) / 2 + font
    matches = []
    for index, text in enumerate([*main, *sub]):
        y = start + (index * (font + 2) if index < len(main)
                     else len(main) * (font + 2) + (index - len(main)) * (subfont + 2))
        candidates = [element for element in root.iter() if element.tag.rsplit("}", 1)[-1] == "text"
                      and element.text == text and abs(float(element.get("x", "nan")) - float(node["x"])) < 0.11
                      and abs(float(element.get("y", "nan")) - y) < 0.11]
        if len(candidates) != 1:
            raise ValueError("Paper FigureSpec cannot uniquely bind native node text: " + str(node["id"]))
        matches.append(candidates[0])
    return matches, main, sub, font, subfont


def render_figurespec_typography(spec: dict[str, Any], renderer: ModuleType, multiplier: float) -> str:
    """Render native scientific geometry with complete, non-overlapping text lines."""
    projected = project_figurespec_typography(spec, renderer, multiplier)
    native = renderer.render_svg(projected)
    root = ET.fromstring(native)
    base = float(projected["style"]["font_size"])
    for node in projected["nodes"]:
        elements, main, sub, font, subfont = _bound_node_text(root, node, renderer, base)
        heights = [LINE_HEIGHT * font] * len(main) + [LINE_HEIGHT * subfont] * len(sub)
        top = float(node["y"]) - float(node["height"]) / 2
        reserved = 33 if node.get("visual_kind") in GLYPH_HEADERS else 6
        safe_height = float(node["height"]) * _text_height_fraction(node)
        start = top + reserved + (safe_height - reserved - 6 - sum(heights)) / 2 + font
        for index, element in enumerate(elements):
            element.set("y", f"{start + sum(heights[:index]):.4f}")
    return ET.tostring(root, encoding="unicode")
