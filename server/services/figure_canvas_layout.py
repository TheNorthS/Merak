"""Deterministic canvas geometry for model-authored scientific regions."""

from __future__ import annotations

from typing import Any


CANVAS_WIDTH = 1200
CANVAS_HEIGHT = 675
CANVAS_MARGIN = 42
REGION_GAP = 24
REGION_HEADER_HEIGHT = 54


def _linear_boxes(regions: list[dict[str, Any]]) -> list[dict[str, int]]:
    available = CANVAS_WIDTH - 2 * CANVAS_MARGIN - REGION_GAP * (len(regions) - 1)
    base = 105
    remainder = available - base * len(regions)
    weights = [max(1, int(region.get("relative_weight") or 1)) for region in regions]
    weight_sum = sum(weights)
    widths = [base + remainder * weight // weight_sum for weight in weights]
    widths[-1] += available - sum(widths)
    x = CANVAS_MARGIN
    boxes = []
    for region, width in zip(regions, widths):
        boxes.append({
            "id": str(region["id"]), "x": x, "y": 62,
            "width": width, "height": 555,
        })
        x += width + REGION_GAP
    return boxes


def _grid_boxes(regions: list[dict[str, Any]]) -> list[dict[str, int]]:
    count = len(regions)
    columns = 2 if count <= 4 else 3
    rows = (count + columns - 1) // columns
    width = (CANVAS_WIDTH - 2 * CANVAS_MARGIN - REGION_GAP * (columns - 1)) // columns
    height = (CANVAS_HEIGHT - 2 * 62 - REGION_GAP * (rows - 1)) // rows
    return [{
        "id": str(region["id"]),
        "x": CANVAS_MARGIN + (index % columns) * (width + REGION_GAP),
        "y": 62 + (index // columns) * (height + REGION_GAP),
        "width": width, "height": height,
    } for index, region in enumerate(regions)]


def canvas_layout(candidate: dict[str, Any]) -> dict[str, Any]:
    """Return one stable paper-scale canvas without choosing scientific glyphs."""
    regions = [dict(item) for item in candidate.get("regions") or []]
    topology = str(candidate.get("topology") or "linear")
    boxes = (
        _linear_boxes(regions)
        if topology in {"linear", "causal", "timeline", "parallel"}
        else _grid_boxes(regions)
    )
    return {
        "schema": 1, "canvas_width": CANVAS_WIDTH,
        "canvas_height": CANVAS_HEIGHT, "minimum_font_units": 21,
        "regions": boxes,
        "connections": [dict(item) for item in candidate.get("connections") or []],
    }


def _port(box: dict[str, int], side: str, slot: int, count: int) -> tuple[int, int]:
    fraction = (slot + 1) / (count + 1)
    if side == "left":
        return box["x"], round(box["y"] + box["height"] * fraction)
    if side == "right":
        return box["x"] + box["width"], round(box["y"] + box["height"] * fraction)
    if side == "top":
        return round(box["x"] + box["width"] * fraction), box["y"]
    return round(box["x"] + box["width"] * fraction), box["y"] + box["height"]


def _route(
    source: dict[str, int], target: dict[str, int], index: int, total: int,
    kind: str,
) -> str:
    if kind == "feedback":
        start = _port(source, "bottom", index, total)
        end = _port(target, "bottom", index, total)
        lane = min(CANVAS_HEIGHT - 18, max(start[1], end[1]) + 28 + 10 * index)
        return f"M{start[0]} {start[1]} V{lane} H{end[0]} V{end[1]}"
    if target["x"] >= source["x"] + source["width"]:
        start = _port(source, "right", index, total)
        end = _port(target, "left", index, total)
        mid = round((start[0] + end[0]) / 2)
        return f"M{start[0]} {start[1]} H{mid} V{end[1]} H{end[0]}"
    start = _port(source, "bottom", index, total)
    end = _port(target, "top", index, total)
    mid = round((start[1] + end[1]) / 2)
    return f"M{start[0]} {start[1]} V{mid} H{end[0]} V{end[1]}"


def connection_ports(layout: dict[str, Any]) -> list[dict[str, Any]]:
    """Assign stable global and region-local endpoints to every scientific relation."""
    boxes = {str(item["id"]): item for item in layout["regions"]}
    connections = list(layout["connections"])
    ports = []
    for index, connection in enumerate(connections):
        source, target = boxes[str(connection["from"])], boxes[str(connection["to"])]
        if connection["kind"] == "feedback":
            source_side = target_side = "bottom"
        elif target["x"] >= source["x"] + source["width"]:
            source_side, target_side = "right", "left"
        else:
            source_side, target_side = "bottom", "top"
        for direction, region, box, side in (
            ("out", str(connection["from"]), source, source_side),
            ("in", str(connection["to"]), target, target_side),
        ):
            x, y = _port(box, side, index, len(connections))
            ports.append({
                "id": f'{connection["id"]}_{direction}',
                "connection_id": str(connection["id"]), "direction": direction,
                "region_id": region, "kind": str(connection["kind"]),
                "global_x": x, "global_y": y,
                "local_x": x - box["x"],
                "local_y": y - box["y"] - REGION_HEADER_HEIGHT,
            })
    return ports


def connection_svg(layout: dict[str, Any]) -> str:
    """Render only cross-region relations; local scientific geometry remains model-owned."""
    boxes = {str(item["id"]): item for item in layout["regions"]}
    connections = list(layout["connections"])
    paths = []
    ports = {item["id"]: item for item in connection_ports(layout)}
    for index, connection in enumerate(connections):
        kind = str(connection["kind"])
        dash = ' stroke-dasharray="8 6"' if kind != "main" else ""
        color = "#8B72B6" if kind in {"constraint", "feedback"} else "#52627A"
        source = ports[f'{connection["id"]}_out']
        target = ports[f'{connection["id"]}_in']
        source_box, target_box = boxes[str(connection["from"])], boxes[str(connection["to"])]
        path = _route(source_box, target_box, index, len(connections), kind)
        paths.append(
            f'<path d="{path}" fill="none" stroke="{color}" stroke-width="3"'
            f'{dash} marker-end="url(#canvas-arrow)"/>'
        )
        paths.append(
            f'<circle cx="{source["global_x"]}" cy="{source["global_y"]}" r="5" '
            f'fill="#FFFFFF" stroke="{color}" stroke-width="2"/>'
            f'<circle cx="{target["global_x"]}" cy="{target["global_y"]}" r="5" '
            f'fill="#FFFFFF" stroke="{color}" stroke-width="2"/>'
        )
    return '<g id="canvas_connections">' + "".join(paths) + "</g>"


def region_header_svg(layout: dict[str, Any]) -> str:
    """Render concise runtime-owned region labels outside model content."""
    labels = []
    for item in layout["regions"]:
        label = str(item["id"]).replace("_", " ").title()
        labels.append(
            f'<text x="{item["x"] + 10}" y="{item["y"] + 29}" '
            f'class="region-title">{label}</text>'
        )
    return '<g id="canvas_region_headers">' + "".join(labels) + "</g>"


def opening_svg(layout: dict[str, Any], artifact_name: str) -> str:
    """Provide publication-safe root styles and region clip paths."""
    clips = "".join(
        f'<clipPath id="clip-{item["id"]}" clipPathUnits="userSpaceOnUse">'
        f'<rect x="{item["x"]}" y="{item["y"]}" '
        f'width="{item["width"]}" height="{item["height"]}" rx="12"/></clipPath>'
        for item in layout["regions"]
    )
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {layout["canvas_width"]} {layout["canvas_height"]}" role="img">
<title>{artifact_name.replace("_", " ")}</title><defs>
<marker id="canvas-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L10 5L0 10Z" fill="#52627A"/></marker>{clips}
<style>.region-title{{font:700 21px Arial,sans-serif;fill:#17233C}}.heading{{font:700 24px Arial,sans-serif;fill:#17233C}}.label{{font:700 21px Arial,sans-serif;fill:#17233C}}.body{{font:400 21px Arial,sans-serif;fill:#17233C}}.muted{{font:400 21px Arial,sans-serif;fill:#52627A}}.math{{font:700 21px Arial,sans-serif;fill:#17233C}}.cue{{font:600 21px Arial,sans-serif;fill:#52627A}}.flow-text{{font:700 21px Arial,sans-serif;fill:#17233C}}.panel{{fill:#F8FAFC;stroke:#B7C3D3;stroke-width:2}}.flow{{fill:none;stroke:#52627A;stroke-width:3;marker-end:url(#canvas-arrow)}}</style></defs><rect width="{layout["canvas_width"]}" height="{layout["canvas_height"]}" fill="#FFFFFF"/>'''
