"""Paper-scale geometry and readability policy for FigureSpec scenes."""

from __future__ import annotations

import json
import math
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


Geometry = tuple[float, float, float, float]
Polyline = list[tuple[float, float]]


@dataclass
class LayoutState:
    payload: dict[str, Any]
    width: float
    height: float
    nodes: list[Any]
    edges: list[Any]
    default_font: float
    issues: list[str] = field(default_factory=list)
    node_ids: set[str] = field(default_factory=set)
    labels: list[str] = field(default_factory=list)
    node_boxes: list[tuple[str, float, float, float, float]] = field(default_factory=list)
    geometry: dict[str, Geometry] = field(default_factory=dict)
    edge_paths: list[tuple[str, str, Polyline]] = field(default_factory=list)


def _state(payload: Any) -> tuple[LayoutState | None, list[str]]:
    if not isinstance(payload, dict):
        return None, ["FigureSpec must be a JSON object"]
    canvas, nodes, edges = payload.get("canvas") or {}, payload.get("nodes") or [], payload.get("edges") or []
    if not isinstance(canvas, dict) or not isinstance(nodes, list):
        return None, ["FigureSpec canvas/nodes structure is invalid"]
    try:
        width, height = float(canvas.get("width") or 800), float(canvas.get("height") or 400)
    except (TypeError, ValueError):
        return None, ["FigureSpec canvas dimensions must be numeric"]
    if width <= 0 or height <= 0:
        return None, ["FigureSpec canvas dimensions must be positive"]
    style = payload.get("style") or {}
    default_font = float(style.get("font_size", 14)) if isinstance(style, dict) else 14.0
    state = LayoutState(payload, width, height, nodes, edges, default_font)
    ratio = width / height
    if ratio < 0.70 or ratio > 3.20:
        state.issues.append(f"FigureSpec canvas has extreme aspect ratio {ratio:.2f}")
    if len(nodes) < 2:
        state.issues.append("FigureSpec needs at least two semantic nodes")
    if len(nodes) > 18:
        state.issues.append(f"FigureSpec has {len(nodes)} nodes; five-second paper limit is 18")
    if isinstance(edges, list) and len(edges) > 24:
        state.issues.append(f"FigureSpec has {len(edges)} edges; five-second paper limit is 24")
    return state, []


def _text_lines(text: str, width: float, height: float, font: float) -> tuple[int, int]:
    chars = max(6, int((width - 16) / max(7.0, font * 0.58)))
    required = sum(max(1, len(textwrap.wrap(
        line, width=chars, break_long_words=True, break_on_hyphens=False,
    ))) for line in text.splitlines() or [text])
    allowed = max(1, int((height - 12) / max(13.0, font * 1.30)))
    return required, allowed


def _node(state: LayoutState, raw: Any, index: int) -> None:
    if not isinstance(raw, dict):
        state.issues.append(f"FigureSpec node {index + 1} is not an object")
        return
    node_id = str(raw.get("id") or "").strip()
    label = " ".join(str(raw.get("label") or "").split())
    sublabel = " ".join(str(raw.get("sublabel") or "").split())
    if node_id in state.node_ids:
        state.issues.append(f"FigureSpec has duplicate node id {node_id}")
    if node_id:
        state.node_ids.add(node_id)
    if label:
        state.labels.append(label.casefold())
        if len(label) > 84:
            state.issues.append(f"FigureSpec node {node_id or index + 1} label is too long for rapid reading ({len(label)} characters)")
    try:
        x, y = float(raw.get("x")), float(raw.get("y"))
        width, height = float(raw.get("width", 120)), float(raw.get("height", 50))
        font = float(raw.get("font_size") or state.default_font)
    except (TypeError, ValueError):
        state.issues.append(f"FigureSpec node {node_id or index + 1} has invalid geometry")
        return
    if str(raw.get("shape") or "rounded") == "circle":
        width = height = max(width, height)
    geometry_id = node_id or str(index + 1)
    state.node_boxes.append((geometry_id, x, y, width, height))
    if node_id:
        state.geometry[node_id] = (x, y, width, height)
    if x - width / 2 < 4 or y - height / 2 < 4 or x + width / 2 > state.width - 4 or y + height / 2 > state.height - 4:
        state.issues.append(f"FigureSpec node {geometry_id} crosses the canvas boundary")
    if font < 12:
        state.issues.append(f"FigureSpec node {geometry_id} font is too small ({font:g}px)")
    if label:
        required, allowed = _text_lines(label, width, height, font)
        if required > allowed:
            state.issues.append(f"FigureSpec node {geometry_id} needs {required} text lines but its box allows {allowed}")
    if sublabel:
        subfont, max_width = max(8.0, font - 3.0), max(36.0, width - 28.0)
        visual_width = sum(subfont * (1.0 if ord(char) > 0x2E80 else 0.60) for char in sublabel)
        required = max(1, math.ceil(visual_width / max_width))
        if required > 2:
            state.issues.append(f"FigureSpec node {geometry_id} sublabel would be truncated ({required} lines needed, 2 rendered)")


def _free_labels(state: LayoutState) -> None:
    for index, raw in enumerate(state.payload.get("labels") or []):
        if not isinstance(raw, dict):
            continue
        text = " ".join(str(raw.get("text") or "").split())
        if not text:
            continue
        try:
            font = float(raw.get("font_size") or state.default_font)
        except (TypeError, ValueError):
            font = state.default_font
        width = sum(font * (1.0 if ord(char) > 0x2E80 else 0.60) for char in text)
        if width > state.width - 64:
            state.issues.append(
                f"FigureSpec free label {index + 1} overflows the canvas; use a compact "
                "figure heading and keep the full title in the caption"
            )


def _node_overlaps(state: LayoutState) -> None:
    for index, first in enumerate(state.node_boxes):
        first_id, x1, y1, width1, height1 = first
        for second_id, x2, y2, width2, height2 in state.node_boxes[index + 1:]:
            horizontal = (width1 + width2) / 2 - abs(x1 - x2)
            vertical = (height1 + height2) / 2 - abs(y1 - y2)
            if horizontal > 5 and vertical > 5:
                state.issues.append(f"FigureSpec nodes {first_id} and {second_id} overlap ({horizontal:.0f}x{vertical:.0f}px)")
            elif (horizontal > -12 and vertical > 8) or (vertical > -12 and horizontal > 8):
                state.issues.append(f"FigureSpec nodes {first_id} and {second_id} are too close for clear print separation")


def _group_box(
    state: LayoutState, raw: dict[str, Any], group_id: str,
    members: list[Geometry], member_ids: list[str],
) -> tuple[str, float, float, float, float] | None:
    try:
        padding = max(12.0, float(raw.get("padding") or 20.0))
    except (TypeError, ValueError):
        padding = 20.0
    bounds = raw.get("bounds")
    if isinstance(bounds, dict) and all(key in bounds for key in ("x", "y", "width", "height")):
        try:
            left, top = float(bounds["x"]), float(bounds["y"])
            right, bottom = left + float(bounds["width"]), top + float(bounds["height"])
        except (TypeError, ValueError):
            state.issues.append(f"FigureSpec group {group_id} has invalid fixed bounds")
            return None
        if right <= left or bottom <= top:
            state.issues.append(f"FigureSpec group {group_id} fixed bounds must be positive")
            return None
        for member_id in member_ids:
            geometry = state.geometry.get(member_id)
            if geometry is None:
                continue
            x, y, width, height = geometry
            if x - width / 2 < left + 8 or x + width / 2 > right - 8 or y - height / 2 < top + 24 or y + height / 2 > bottom - 8:
                state.issues.append(f"FigureSpec node {member_id} does not fit inside fixed group {group_id}")
    else:
        left = min(x - width / 2 for x, y, width, height in members) - padding
        right = max(x + width / 2 for x, y, width, height in members) + padding
        top = min(y - height / 2 for x, y, width, height in members) - padding - 16.0
        bottom = max(y + height / 2 for x, y, width, height in members) + padding
    if left < 2 or top < 2 or right > state.width - 2 or bottom > state.height - 2:
        state.issues.append(f"FigureSpec group {group_id} crosses the canvas boundary")
    return group_id, left, top, right, bottom


def _groups(state: LayoutState) -> None:
    groups = state.payload.get("groups") or []
    if not isinstance(groups, list):
        state.issues.append("FigureSpec groups must be a list")
        return
    boxes: list[tuple[str, float, float, float, float]] = []
    ownership: dict[str, str] = {}
    for index, raw in enumerate(groups):
        if not isinstance(raw, dict):
            state.issues.append(f"FigureSpec group {index + 1} is not an object")
            continue
        group_id = str(raw.get("id") or raw.get("label") or index + 1).strip()
        member_ids = [str(value).strip() for value in raw.get("node_ids") or [] if str(value).strip()]
        if not member_ids:
            state.issues.append(f"FigureSpec group {group_id} has no member nodes")
            continue
        for member_id in member_ids:
            if member_id not in state.geometry:
                state.issues.append(f"FigureSpec group {group_id} references unknown node {member_id}")
            elif ownership.get(member_id) and ownership[member_id] != group_id:
                state.issues.append(f"FigureSpec node {member_id} appears in overlapping groups {ownership[member_id]} and {group_id}")
            else:
                ownership[member_id] = group_id
        members = [state.geometry[item] for item in member_ids if item in state.geometry]
        if members and (box := _group_box(state, raw, group_id, members, member_ids)):
            boxes.append(box)
    for index, first in enumerate(boxes):
        first_id, left1, top1, right1, bottom1 = first
        for second_id, left2, top2, right2, bottom2 in boxes[index + 1:]:
            width, height = min(right1, right2) - max(left1, left2), min(bottom1, bottom2) - max(top1, top2)
            if width > 3 and height > 3:
                state.issues.append(f"FigureSpec groups {first_id} and {second_id} overlap ({width:.0f}x{height:.0f}px)")


def _polyline(state: LayoutState, source_id: str, target_id: str, curved: bool) -> Polyline:
    source, target = state.geometry.get(source_id), state.geometry.get(target_id)
    if source is None or target is None or source_id == target_id:
        return []
    sx, sy, tx, ty = source[0], source[1], target[0], target[1]
    if not curved:
        return [(sx, sy), (tx, ty)]
    dx, dy = tx - sx, ty - sy
    length = max(1.0, math.hypot(dx, dy))
    control = ((sx + tx) / 2 - dy / length * 30, (sy + ty) / 2 + dx / length * 30)
    return [(
        (1 - step / 8) ** 2 * sx + 2 * (1 - step / 8) * (step / 8) * control[0] + (step / 8) ** 2 * tx,
        (1 - step / 8) ** 2 * sy + 2 * (1 - step / 8) * (step / 8) * control[1] + (step / 8) ** 2 * ty,
    ) for step in range(9)]


def _segment_hits(start: tuple[float, float], end: tuple[float, float], geometry: Geometry) -> bool:
    cx, cy, width, height = geometry
    inset = min(5.0, width * 0.08, height * 0.08)
    left, right = cx - width / 2 + inset, cx + width / 2 - inset
    top, bottom = cy - height / 2 + inset, cy + height / 2 - inset
    x0, y0 = start
    dx, dy = end[0] - x0, end[1] - y0
    lower, upper = 0.0, 1.0
    for denominator, numerator in zip((-dx, dx, -dy, dy), (x0 - left, right - x0, y0 - top, bottom - y0)):
        if abs(denominator) < 1e-9:
            if numerator < 0:
                return False
            continue
        ratio = numerator / denominator
        lower, upper = (max(lower, ratio), upper) if denominator < 0 else (lower, min(upper, ratio))
        if lower > upper:
            return False
    return True


def _segments_cross(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float], d: tuple[float, float]) -> bool:
    def orientation(first: tuple[float, float], second: tuple[float, float], third: tuple[float, float]) -> float:
        return (second[0] - first[0]) * (third[1] - first[1]) - (second[1] - first[1]) * (third[0] - first[0])
    values = orientation(a, b, c), orientation(a, b, d), orientation(c, d, a), orientation(c, d, b)
    epsilon = 1e-7
    return ((values[0] > epsilon and values[1] < -epsilon) or (values[0] < -epsilon and values[1] > epsilon)) and ((values[2] > epsilon and values[3] < -epsilon) or (values[2] < -epsilon and values[3] > epsilon))


def _edges(state: LayoutState) -> None:
    if not isinstance(state.edges, list):
        state.issues.append("FigureSpec edges must be a list")
        return
    seen: set[tuple[str, str, str]] = set()
    for index, raw in enumerate(state.edges):
        if not isinstance(raw, dict):
            state.issues.append(f"FigureSpec edge {index + 1} is not an object")
            continue
        source, target = str(raw.get("from") or "").strip(), str(raw.get("to") or "").strip()
        label = " ".join(str(raw.get("label") or "").casefold().split())
        if len(label) > 30:
            state.issues.append(f"FigureSpec edge {index + 1} label is too long for connector reading ({len(label)} characters)")
        if source not in state.node_ids:
            state.issues.append(f"FigureSpec edge {index + 1} has unknown from endpoint {source or '(empty)'}")
        if target not in state.node_ids:
            state.issues.append(f"FigureSpec edge {index + 1} has unknown to endpoint {target or '(empty)'}")
        signature = source, target, label
        if signature in seen:
            state.issues.append(f"FigureSpec edge {index + 1} duplicates {source}->{target}{f' ({label})' if label else ''}")
        seen.add(signature)
        path = _polyline(state, source, target, bool(raw.get("curve")))
        if path:
            state.edge_paths.append((source, target, path))


def _edge_collisions(state: LayoutState) -> None:
    for index, (source, target, path) in enumerate(state.edge_paths):
        for node_id, geometry in state.geometry.items():
            if node_id not in {source, target} and any(
                _segment_hits(start, end, geometry) for start, end in zip(path, path[1:])
            ):
                state.issues.append(f"FigureSpec edge {source}->{target} passes through unrelated node {node_id}")
        for other_source, other_target, other_path in state.edge_paths[index + 1:]:
            if {source, target} & {other_source, other_target}:
                continue
            if any(
                _segments_cross(a, b, c, d)
                for a, b in zip(path, path[1:])
                for c, d in zip(other_path, other_path[1:])
            ):
                state.issues.append(f"FigureSpec edges {source}->{target} and {other_source}->{other_target} cross")


def figurespec_layout_issues_payload(payload: Any) -> list[str]:
    state, early = _state(payload)
    if state is None:
        return early
    for index, raw in enumerate(state.nodes):
        _node(state, raw, index)
    _free_labels(state)
    _node_overlaps(state)
    _groups(state)
    _edges(state)
    _edge_collisions(state)
    generic = {"input", "data", "model", "method", "process", "output", "result", "input data", "model architecture", "proposed method"}
    if state.labels and set(state.labels) <= generic:
        state.issues.append("FigureSpec uses only generic Input/Model/Output labels")
    return list(dict.fromkeys(state.issues))


def figurespec_layout_issues(source: Path) -> list[str]:
    try:
        payload = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return ["FigureSpec source cannot be parsed"]
    return figurespec_layout_issues_payload(payload)
