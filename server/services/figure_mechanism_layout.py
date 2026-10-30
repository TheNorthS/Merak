"""Deterministic object placement and routing for a validated mechanism IR."""

from __future__ import annotations

import math
import re
from collections import defaultdict
from xml.sax.saxutils import escape
from typing import Any

from .figure_canvas_layout import REGION_HEADER_HEIGHT


PRIMITIVE_LABEL_HEIGHT = 78
PRIMITIVE_GAP = 12


def _wrap_words(value: str, max_chars: int) -> list[str]:
    """Wrap publication text at word boundaries without shrinking the font."""
    words = str(value).split()
    if not words:
        return []
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if len(candidate) <= max_chars:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _cells(region: dict[str, int], count: int) -> list[dict[str, int]]:
    x, y = region["x"] + 8, region["y"] + REGION_HEADER_HEIGHT + 8
    width, height = region["width"] - 16, region["height"] - REGION_HEADER_HEIGHT - 16
    if count == 1:
        return [{"x": x, "y": y, "width": width, "height": height}]
    if count == 4 and width >= 330:
        top_height = max(105, height * 28 // 100)
        lower_height = height - top_height - PRIMITIVE_GAP
        column = (width - 2 * PRIMITIVE_GAP) // 3
        return [
            {"x": x, "y": y, "width": width, "height": top_height},
            *[{
                "x": x + index * (column + PRIMITIVE_GAP),
                "y": y + top_height + PRIMITIVE_GAP,
                "width": column, "height": lower_height,
            } for index in range(3)],
        ]
    if count == 3 and width >= 330:
        cell_height = (height - 2 * PRIMITIVE_GAP) // 3
        return [{
            "x": x, "y": y + index * (cell_height + PRIMITIVE_GAP),
            "width": width, "height": cell_height,
        } for index in range(3)]
    columns = 2 if width >= 330 and count > 2 else 1
    rows = math.ceil(count / columns)
    cell_width = (width - PRIMITIVE_GAP * (columns - 1)) // columns
    cell_height = (height - PRIMITIVE_GAP * (rows - 1)) // rows
    return [{
        "x": x + (index % columns) * (cell_width + PRIMITIVE_GAP),
        "y": y + (index // columns) * (cell_height + PRIMITIVE_GAP),
        "width": cell_width, "height": cell_height,
    } for index in range(count)]


def _subitem_grid(
    subitems: list[dict[str, str]], width: int,
) -> tuple[int, list[list[dict[str, str]]]]:
    """Allocate deterministic runtime-owned label chips within a primitive header."""
    if not subitems:
        return 0, []
    columns = 2 if width >= 300 and len(subitems) > 1 else 1

    def fits(column_count: int) -> bool:
        cell_width = (width - 18 - 8 * (column_count - 1)) // column_count
        max_chars = max(8, (cell_width - 18) // 10)
        return all(
            len(
                f'{item["label"]} ({item["notation"]})'
                if item.get("notation") else item["label"]
            ) <= max_chars
            for item in subitems
        )

    if columns == 2 and not fits(columns):
        columns = 1
    if not fits(columns):
        raise ValueError("subitem label is too wide for its storyboard region")
    return columns, [
        subitems[index:index + columns]
        for index in range(0, len(subitems), columns)
    ]


def _primitives_by_region(
    mechanism_ir: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_id = {item["id"]: item for item in mechanism_ir["primitives"]}
    for identity in mechanism_ir["reading_order"]:
        primitive = by_id[identity]
        grouped[primitive["region_id"]].append(primitive)
    return grouped


def _label_height(
    label_lines: list[str], notation_lines: list[str], cues: list[str],
    subitem_rows: list[list[dict[str, str]]],
) -> int:
    line_count = len(label_lines) + len(notation_lines) + len(cues)
    subitem_height = 6 + 30 * len(subitem_rows) if subitem_rows else 0
    return max(
        PRIMITIVE_LABEL_HEIGHT,
        14 + 22 * line_count + 8 + subitem_height,
    )


def _primitive_text_layout(
    primitive: dict[str, Any], cell: dict[str, int],
) -> dict[str, Any]:
    max_chars = max(11, cell["width"] // 10)
    label_lines = _wrap_words(primitive["public_label"], max_chars)
    notation = str(primitive.get("notation") or "").strip()
    notation_lines = (
        _equation_lines(notation, cell["width"] - 18)
        if primitive.get("runtime_type") == "additive_objective" and notation
        else _wrap_words(notation, max_chars) if notation else []
    )
    subitem_columns, subitem_rows = _subitem_grid(
        list(primitive.get("subitems") or []), cell["width"],
    )
    cue_groups = [
        (str(cue), _wrap_words(str(cue), max_chars))
        for cue in primitive.get("semantic_cues") or []
    ]
    if primitive["role"] == "synthesis":
        hidden_cues = [cue for cue, _lines in cue_groups]
        visible_groups: list[tuple[str, list[str]]] = []
    else:
        hidden_cues = [
            cue for cue, lines in cue_groups if any(len(line) > max_chars for line in lines)
        ]
        visible_groups = [
            (cue, lines) for cue, lines in cue_groups
            if all(len(line) <= max_chars for line in lines)
        ]
    visible_cues = [line for _cue, group in visible_groups for line in group]
    height = _label_height(label_lines, notation_lines, visible_cues, subitem_rows)
    while visible_groups and cell["height"] - height < 40:
        hidden_cues.insert(0, visible_groups.pop()[0])
        visible_cues = [line for _cue, group in visible_groups for line in group]
        height = _label_height(label_lines, notation_lines, visible_cues, subitem_rows)
    if any(len(line) > max_chars for line in label_lines + notation_lines + visible_cues):
        raise ValueError(
            f"primitive {primitive['id']} contains a word too wide for its "
            "storyboard region; use a shorter publication phrase"
        )
    if cell["height"] - height < 40:
        raise ValueError(
            f"primitive {primitive['id']} label/notation exceeds the selected "
            "storyboard cell capacity"
        )
    return {
        "label_lines": label_lines, "notation_lines": notation_lines,
        "cue_lines": visible_cues, "subitem_columns": subitem_columns,
        "subitem_rows": subitem_rows, "hidden_semantic_cues": hidden_cues,
        "label_height": height,
    }


def _primitive_box(
    primitive: dict[str, Any], cell: dict[str, int],
) -> dict[str, Any]:
    text_layout = _primitive_text_layout(primitive, cell)
    label_height = int(text_layout["label_height"])
    return {
        **primitive, **cell, **text_layout,
        "glyph_x": cell["x"], "glyph_y": cell["y"] + label_height,
        "glyph_width": cell["width"],
        "glyph_height": cell["height"] - label_height,
    }


def mechanism_layout(
    canvas: dict[str, Any], mechanism_ir: dict[str, Any],
) -> dict[str, Any]:
    """Assign stable primitive boxes inside deterministic storyboard regions."""
    by_region = _primitives_by_region(mechanism_ir)
    boxes = []
    for region in canvas["regions"]:
        primitives = by_region[region["id"]]
        for primitive, cell in zip(primitives, _cells(region, len(primitives))):
            boxes.append(_primitive_box(primitive, cell))
    return {**canvas, "mechanism_ir": mechanism_ir, "primitive_boxes": boxes}


def _port(box: dict[str, Any], side: str, slot: int, count: int) -> tuple[int, int]:
    """Return a distinct glyph-area port so relations never share an endpoint."""
    fraction = (slot + 1) / (count + 1)
    if side in {"left", "right"}:
        top = box["glyph_y"]
        height = max(24, box["glyph_height"])
        return (
            box["x"] + (box["width"] if side == "right" else 0),
            round(top + height * fraction),
        )
    return (
        round(box["x"] + box["width"] * fraction),
        box["y"] + (box["height"] if side == "bottom" else 0),
    )


def _indexed_flows(
    flows: list[dict[str, Any]], key: str,
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for flow in flows:
        grouped[str(flow[key])].append(flow)
    return grouped


def _flow_color(flow: dict[str, Any]) -> str:
    return "#8B72B6" if flow["kind"] in {"control", "constraint"} else "#52627A"


BRANCH_COLORS = ["#D9655B", "#4E82C3", "#E89A4A", "#2B9A8A", "#8B72B6"]


def _math_tspans(value: str) -> str:
    """Render notation as one PDF text run, without code-style underscores."""
    subscript = {
        "0": "₀", "1": "₁", "2": "₂", "3": "₃", "4": "₄",
        "5": "₅", "6": "₆", "7": "₇", "8": "₈", "9": "₉",
        "a": "ₐ", "e": "ₑ", "h": "ₕ", "i": "ᵢ", "j": "ⱼ",
        "k": "ₖ", "l": "ₗ", "m": "ₘ", "n": "ₙ", "o": "ₒ",
        "p": "ₚ", "r": "ᵣ", "s": "ₛ", "t": "ₜ", "u": "ᵤ",
        "v": "ᵥ", "x": "ₓ",
    }

    def convert(token: str) -> str:
        converted = [subscript.get(char.casefold()) for char in token]
        return "".join(converted) if all(converted) else f"({token})"

    raw = re.sub(
        r"\blambda_?([0-9A-Za-z]+)",
        lambda match: "λ" + convert(match.group(1)),
        str(value), flags=re.I,
    )
    pattern = re.compile(r"_\{([^{}]+)\}|_([A-Za-z0-9-]+)")
    parts = []
    cursor = 0
    for match in pattern.finditer(raw):
        parts.append(raw[cursor:match.start()])
        parts.append(convert(match.group(1) or match.group(2)))
        cursor = match.end()
    parts.append(raw[cursor:])
    return escape("".join(parts))


def _label_svg(x: int, y: int, value: str, anchor: str = "middle") -> str:
    width = max(46, min(190, 10 * len(value) + 14))
    left = x - width // 2 if anchor == "middle" else x - width if anchor == "end" else x
    return (
        f'<g class="flow-label"><rect x="{left}" y="{y - 18}" width="{width}" '
        f'height="24" rx="5" fill="#FFFFFF" fill-opacity="0.94"/>'
        f'<text x="{x}" y="{y}" class="flow-text" text-anchor="{anchor}">'
        f'{_math_tspans(value)}</text></g>'
    )


def mechanism_connections_svg(layout: dict[str, Any]) -> str:
    """Route relations with separate ports, explicit fan-out, and skip lanes."""
    boxes = {item["id"]: item for item in layout["primitive_boxes"]}
    flows = list(layout["mechanism_ir"]["flows"])
    outgoing = _indexed_flows(flows, "from")
    incoming = _indexed_flows(flows, "to")
    paths = []
    for flow in flows:
        source, target = boxes[flow["from"]], boxes[flow["to"]]
        source_items = outgoing[flow["from"]]
        target_items = incoming[flow["to"]]
        source_index = source_items.index(flow)
        target_index = target_items.index(flow)
        target_is_right = target["x"] >= source["x"] + source["width"]
        skipped_box = any(
            item["x"] > source["x"] + source["width"]
            and item["x"] + item["width"] < target["x"]
            for item in boxes.values()
        )
        if target_is_right and skipped_box:
            sx, sy = _port(source, "bottom", source_index, len(source_items))
            tx, ty = _port(target, "left", target_index, len(target_items))
            lane = min(
                layout["canvas_height"] - 20,
                max(item["y"] + item["height"] for item in boxes.values())
                + 18 + 7 * target_index,
            )
            path = f"M{sx} {sy} V{lane} H{tx - 14} V{ty} H{tx}"
        elif target_is_right:
            sx, sy = _port(source, "right", source_index, len(source_items))
            tx, ty = _port(target, "left", target_index, len(target_items))
            bend = max(8, round((tx - sx) * 0.45))
            path = f"M{sx} {sy} C{sx + bend} {sy} {tx - bend} {ty} {tx} {ty}"
        else:
            sx, sy = _port(source, "bottom", source_index, len(source_items))
            tx, ty = _port(target, "top", target_index, len(target_items))
            mid = round((sy + ty) / 2)
            path = f"M{sx} {sy} V{mid} H{tx} V{ty}"
        if target["role"] == "synthesis":
            color = BRANCH_COLORS[target_index % len(BRANCH_COLORS)]
        elif len(source_items) > 1:
            color = BRANCH_COLORS[source_index % len(BRANCH_COLORS)]
        else:
            color = _flow_color(flow)
        dash = ' stroke-dasharray="7 5"' if flow["kind"] in {"control", "constraint"} else ""
        paths.append(
            f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2.5"'
            f'{dash} marker-end="url(#canvas-arrow)"/>'
        )
    return '<g id="mechanism_connections">' + "".join(paths) + "</g>"


def mechanism_connection_labels_svg(layout: dict[str, Any]) -> str:
    """Render carried quantities above frames, separate from path geometry."""
    boxes = {item["id"]: item for item in layout["primitive_boxes"]}
    flows = list(layout["mechanism_ir"]["flows"])
    outgoing = _indexed_flows(flows, "from")
    labels = []
    for flow in flows:
        source, target = boxes[flow["from"]], boxes[flow["to"]]
        if target["role"] == "synthesis":
            continue
        if len(outgoing[flow["from"]]) > 1:
            source_index = outgoing[flow["from"]].index(flow)
            sx, sy = _port(
                source, "right", source_index, len(outgoing[flow["from"]]),
            )
            labels.append(_label_svg(sx + 8, sy - 7, flow["label"], "start"))
            continue
        # Direct neighboring transitions remain explicit in the audited IR, but
        # their narrow inter-box gaps cannot carry paper-scale prose safely.
        # The source/target labels and arrow already communicate that relation.
        continue
    return '<g id="mechanism_connection_labels">' + "".join(labels) + "</g>"


def _equation_lines(value: str, width: int) -> list[str]:
    """Wrap an additive objective at operator boundaries, never mid-symbol."""
    terms = [part.strip() for part in re.split(r"\s*\+\s*", value) if part.strip()]
    if len(terms) <= 1:
        return [value]
    limit = max(15, width // 11)
    lines = []
    current = terms[0]
    for term in terms[1:]:
        candidate = f"{current} + {term}"
        if len(candidate) <= limit:
            current = candidate
        else:
            lines.append(current)
            current = f"+ {term}"
    lines.append(current)
    return lines


def mechanism_frames_svg(layout: dict[str, Any]) -> str:
    """Render runtime-owned labels and light scientific object boundaries."""
    clips = []
    items = []
    for box in layout["primitive_boxes"]:
        clips.append(
            f'<clipPath id="primitive-clip-{box["id"]}" clipPathUnits="userSpaceOnUse">'
            f'<rect x="{box["glyph_x"]}" y="{box["glyph_y"]}" '
            f'width="{box["glyph_width"]}" height="{box["glyph_height"]}"/></clipPath>'
        )
        cursor = box["y"] + 24
        label_svg = "".join(
            f'<text x="{box["x"] + 9}" y="{cursor + 22 * index}" '
            f'class="label">{escape(line)}</text>'
            for index, line in enumerate(box["label_lines"])
        )
        cursor += 22 * len(box["label_lines"])
        notation_svg = "".join(
            f'<text x="{box["x"] + 9}" y="{cursor + 22 * index}" '
            f'class="math">{_math_tspans(line)}</text>'
            for index, line in enumerate(box["notation_lines"])
        )
        cursor += 22 * len(box["notation_lines"])
        cue_svg = "".join(
            f'<text x="{box["x"] + 9}" y="{cursor + 22 * index}" '
            f'class="cue">{escape(line)}</text>'
            for index, line in enumerate(box["cue_lines"])
        )
        cursor += 22 * len(box["cue_lines"])
        subitem_svg = []
        rows = list(box.get("subitem_rows") or [])
        columns = int(box.get("subitem_columns") or 0)
        if rows and columns:
            available = box["width"] - 18
            chip_gap = 8
            chip_width = (available - chip_gap * (columns - 1)) // columns
            for row_index, row in enumerate(rows):
                top = cursor + 5 + row_index * 30
                for column_index, subitem in enumerate(row):
                    left = box["x"] + 9 + column_index * (chip_width + chip_gap)
                    value = str(subitem["label"])
                    if subitem.get("notation"):
                        value += f' ({subitem["notation"]})'
                    subitem_svg.extend([
                        f'<rect x="{left}" y="{top}" width="{chip_width}" height="25" '
                        f'rx="6" fill="#F4F7FB" stroke="#B7C3D3" stroke-width="1"/>',
                        f'<text x="{left + 8}" y="{top + 18}" class="cue">'
                        f'{_math_tspans(value)}</text>',
                    ])
        if box["role"] in {"interaction", "constraint"}:
            boundary = (
                f'<path d="M{box["x"]} {box["y"] + box["height"]} '
                f'H{box["x"] + box["width"]}" stroke="#D8E0EA" '
                f'stroke-width="1.5"/>'
            )
        else:
            boundary = (
                f'<rect x="{box["x"]}" y="{box["y"]}" '
                f'width="{box["width"]}" height="{box["height"]}" rx="9" '
                f'fill="#FFFFFF" stroke="#D8E0EA" stroke-width="1.5"/>'
            )
        items.append(
            f'<g id="frame-{box["id"]}">' + boundary
            + label_svg + notation_svg + cue_svg + "".join(subitem_svg)
            + '</g>'
        )
    return (
        '<g id="mechanism_frames"><defs>' + "".join(clips) + "</defs>"
        + "".join(items) + "</g>"
    )


def mechanism_runtime_glyph_svg(
    layout: dict[str, Any], primitive_id: str,
) -> str:
    """Draw one typed synthesis/readout from authoritative relations and labels."""
    boxes = {item["id"]: item for item in layout["primitive_boxes"]}
    box = boxes[primitive_id]
    flows = [
        flow for flow in layout["mechanism_ir"]["flows"]
        if flow["to"] == primitive_id
    ]
    runtime_type = str(box.get("runtime_type") or "")
    if not runtime_type:
        raise ValueError(f"primitive {primitive_id} does not declare a runtime type")
    width, height = box["glyph_width"], box["glyph_height"]
    node_x = max(58, round(width * 0.58))
    center_y = round(height / 2)
    items = []
    for index, flow in enumerate(flows):
        y = round(height * (index + 1) / (len(flows) + 1))
        color = BRANCH_COLORS[index % len(BRANCH_COLORS)]
        items.extend([
            f'<circle cx="8" cy="{y}" r="6" fill="{color}"/>',
            f'<path d="M16 {y} H{node_x - 52} V{center_y} H{node_x - 44}" '
            f'fill="none" stroke="{color}" stroke-width="3"/>',
            f'<text x="24" y="{y - 8}" class="flow-text">'
            f'{_math_tspans(flow["label"])}</text>',
        ])
    operators = {
        "additive_objective": "Σ",
        "comparison": "compare",
        "decision_gate": "gate",
        "causal_merge": "merge",
        "evidence_convergence": "evidence",
        "reported_endpoint": "endpoint",
        "proof_implication": "⇒",
    }
    defaults = {
        "additive_objective": str(box.get("notation") or "").split("=", 1)[0].strip(),
        "comparison": "comparison",
        "decision_gate": "decision",
        "causal_merge": "merged effect",
        "evidence_convergence": "converged evidence",
        "reported_endpoint": "reported endpoint",
        "proof_implication": "conclusion",
    }
    operator = operators[runtime_type]
    output = str(box.get("output_label") or defaults[runtime_type] or box["public_label"])
    node_width = min(94, max(62, width // 4))
    node_height = min(52, max(38, height // 4))
    left = node_x - node_width // 2
    top = center_y - node_height // 2
    items.extend([
        f'<rect x="{left}" y="{top}" width="{node_width}" height="{node_height}" '
        f'rx="{node_height // 2}" fill="#F1ECF8" stroke="#8B72B6" stroke-width="3"/>',
        f'<text x="{node_x}" y="{center_y + 7}" text-anchor="middle" '
        f'class="flow-text">{escape(operator)}</text>',
        f'<path d="M{left + node_width} {center_y} H{width - 12}" '
        f'fill="none" stroke="#17233C" stroke-width="3" '
        f'marker-end="url(#canvas-arrow)"/>',
        f'<text x="{width - 14}" y="{center_y + 26}" text-anchor="end" '
        f'class="cue">{_math_tspans(output)}</text>',
    ])
    return (
        f'<g id="{primitive_id}" clip-path="url(#primitive-clip-{primitive_id})">'
        f'<g transform="translate({box["glyph_x"]} {box["glyph_y"]})">'
        + "".join(items) + '</g></g>'
    )


def mechanism_synthesis_glyph_svg(
    layout: dict[str, Any], synthesis_id: str,
) -> str:
    """Backward-compatible name for the typed runtime renderer."""
    return mechanism_runtime_glyph_svg(layout, synthesis_id)
