"""Dependency-free IDE previews for already-authored diagram sources."""

from __future__ import annotations

import html
import re
import textwrap
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageDraw, ImageOps

from .figure_artifact_support import _font, _short_label


def _save(image: Image.Image, output_path: str | Path, *, inset: int = 0) -> str:
    output = Path(output_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if inset:
        image = ImageOps.expand(image, border=(inset,) * 4, fill="#FFFFFF")
    image.save(output, format="PNG", optimize=True)
    return str(output)


def render_box_diagram(
    output_path: str | Path, *, title: str, labels: Iterable[str], subtitle: str = "",
) -> str:
    values = [_short_label(label, 72) for label in labels if str(label).strip()] or [
        "Input", "Method", "Evidence", "Output",
    ]
    width, height = max(1600, 285 * len(values)), 610
    image = Image.new("RGB", (width, height), "#ffffff")
    draw = ImageDraw.Draw(image)
    draw.text((70, 42), _short_label(title, 100), fill="#111827", font=_font(34, True))
    if subtitle:
        draw.text((72, 98), _short_label(subtitle, 140), fill="#4b5563", font=_font(20))
    margin, gap, box_y, box_h = 70, 46, 180, 230
    box_w = (width - margin * 2 - gap * (len(values) - 1)) // len(values)
    colors = ("#F1F5F9", "#E6F4F1", "#FFF7E6")
    for index, label in enumerate(values):
        left, right = margin + index * (box_w + gap), margin + index * (box_w + gap) + box_w
        draw.rounded_rectangle((left, box_y, right, box_y + box_h), radius=8, fill=colors[index % 3], outline="#475569", width=3)
        draw.text((left + 22, box_y + 18), f"{index + 1:02d}", fill="#64748b", font=_font(17))
        wrapped = "\n".join(textwrap.wrap(label, width=max(12, min(24, box_w // 11)), break_long_words=True, break_on_hyphens=True)[:5]) or label
        font = _font(20 if len(values) >= 6 else 22, True)
        bounds = draw.multiline_textbbox((0, 0), wrapped, font=font, spacing=7, align="center")
        draw.multiline_text((left + (box_w - bounds[2] + bounds[0]) / 2, box_y + (box_h - bounds[3] + bounds[1]) / 2 + 10), wrapped, fill="#0f172a", font=font, spacing=8, align="center")
        if index < len(values) - 1:
            start, end, y = right + 8, right + gap - 10, box_y + box_h // 2
            draw.line((start, y, end, y), fill="#334155", width=5)
            draw.polygon([(end, y), (end - 18, y - 11), (end - 18, y + 11)], fill="#334155")
    return _save(image, output_path)


def _mermaid_graph(code: str) -> tuple[dict[str, str], list[tuple[str, str]]]:
    nodes: dict[str, str] = {}
    for node_id, label in re.findall(r"([A-Za-z0-9_]+)\s*[\[\(\{]+([^\]\)\}]+)", code):
        clean = re.sub(r"<[^>]+>", " ", html.unescape(label.replace("<br/>", " "))).strip().strip('"\'')
        nodes.setdefault(node_id, clean)
    edges: list[tuple[str, str]] = []
    for line in code.splitlines():
        match = re.match(r"\s*([A-Za-z0-9_]+).*?(?:-->|==>|-\.[^>]*->)(?:\|[^|]*\|)?\s*([A-Za-z0-9_]+)", line)
        if match and match.group(1) in nodes and match.group(2) in nodes:
            edges.append((match.group(1), match.group(2)))
    return nodes, edges


def _levels(nodes: dict[str, str], edges: list[tuple[str, str]]) -> dict[int, list[str]]:
    incoming = {node: 0 for node in nodes}
    outgoing = {node: [] for node in nodes}
    for source, target in edges:
        incoming[target] += 1
        outgoing[source].append(target)
    levels = {node: 0 for node, count in incoming.items() if count == 0}
    queue = list(levels)
    while queue:
        source = queue.pop(0)
        for target in outgoing[source]:
            levels[target] = max(levels.get(target, 0), levels[source] + 1)
            incoming[target] -= 1
            if incoming[target] == 0:
                queue.append(target)
    for node in nodes:
        levels.setdefault(node, max(levels.values(), default=0) + 1)
    grouped: dict[int, list[str]] = {}
    for node in nodes:
        grouped.setdefault(levels[node], []).append(node)
    return grouped


def _positions(grouped: dict[int, list[str]], horizontal: bool) -> tuple[dict[str, tuple[int, int, int, int]], int, int]:
    columns = max(grouped) + 1
    rows = max(len(items) for items in grouped.values())
    width, height = 1800, max(700, 220 + rows * 210)
    box_width, box_height = min(300, max(180, int((width - 140) / max(1, columns) - 55))), 126
    positions: dict[str, tuple[int, int, int, int]] = {}
    for level, ids in grouped.items():
        for row, node_id in enumerate(ids):
            if horizontal:
                x = int(70 + level * ((width - 140 - box_width) / max(1, columns - 1)))
                y = int(155 + (row + 0.5) * ((height - 205) / len(ids)) - box_height / 2)
            else:
                x = int(70 + (row + 0.5) * ((width - 140) / len(ids)) - box_width / 2)
                y = int(145 + level * ((height - 205 - box_height) / max(1, columns - 1)))
            positions[node_id] = x, y, x + box_width, y + box_height
    return positions, width, height


def _fit_text(draw: Any, label: str, box: tuple[int, int, int, int]) -> tuple[str, Any, tuple[int, int, int, int]]:
    width, height = box[2] - box[0], box[3] - box[1]
    size = 24
    while True:
        font = _font(size, True)
        wrapped = "\n".join(textwrap.wrap(label, width=max(14, int(width / max(8, size * 0.56))), break_long_words=True, break_on_hyphens=False))
        bounds = draw.multiline_textbbox((0, 0), wrapped, font=font, spacing=5, align="center")
        if (bounds[2] - bounds[0] <= width - 12 and bounds[3] - bounds[1] <= height - 10) or size <= 15:
            return wrapped, font, bounds
        size -= 1


def _draw_mermaid(nodes: dict[str, str], edges: list[tuple[str, str]], positions: dict[str, tuple[int, int, int, int]], width: int, height: int, horizontal: bool, title: str) -> Image.Image:
    image = Image.new("RGB", (width, height), "#FFFFFF")
    draw = ImageDraw.Draw(image)
    draw.text((65, 38), _short_label(title, 110), fill="#111827", font=_font(32, True))
    for source, target in edges:
        if source not in positions or target not in positions:
            continue
        source_box, target_box = positions[source], positions[target]
        start = (source_box[2], (source_box[1] + source_box[3]) // 2) if horizontal else ((source_box[0] + source_box[2]) // 2, source_box[3])
        end = (target_box[0], (target_box[1] + target_box[3]) // 2) if horizontal else ((target_box[0] + target_box[2]) // 2, target_box[1])
        arrow = [(end[0], end[1]), (end[0] - 15, end[1] - 9), (end[0] - 15, end[1] + 9)] if horizontal else [(end[0], end[1]), (end[0] - 9, end[1] - 15), (end[0] + 9, end[1] - 15)]
        draw.line((*start, *end), fill="#475569", width=4)
        draw.polygon(arrow, fill="#475569")
    palette = ("#EDF2F7", "#E6F4F1", "#FFF4D6")
    level_by_node = {node: level for level, ids in _levels(nodes, edges).items() for node in ids}
    for node_id, label in nodes.items():
        box = positions[node_id]
        draw.rounded_rectangle(box, radius=8, fill=palette[level_by_node[node_id] % 3], outline="#334155", width=3)
        wrapped, font, bounds = _fit_text(draw, label, box)
        draw.multiline_text((box[0] + (box[2] - box[0] - bounds[2] + bounds[0]) / 2, box[1] + (box[3] - box[1] - bounds[3] + bounds[1]) / 2), wrapped, fill="#111827", font=font, spacing=5, align="center")
    return image


def render_mermaid_preview(code: str, output_path: str | Path, title: str = "Method workflow") -> str:
    nodes, edges = _mermaid_graph(code)
    if not nodes:
        labels = [part.strip() for part in re.split(r"-->|==>|---", code) if part.strip()][:6]
        return render_box_diagram(output_path, title=title, labels=labels)
    horizontal = not re.search(r"\bflowchart\s+(?:TB|TD|BT)\b", code, re.IGNORECASE)
    positions, width, height = _positions(_levels(nodes, edges), horizontal)
    return _save(_draw_mermaid(nodes, edges, positions, width, height, horizontal, title), output_path, inset=72)


def _drawio_cells(xml: str) -> tuple[dict[str, dict[str, Any]], list[tuple[str, str]]]:
    root = ET.fromstring(xml)
    cells: dict[str, dict[str, Any]] = {}
    edges: list[tuple[str, str]] = []
    for cell in root.iter("mxCell"):
        cell_id = str(cell.attrib.get("id") or "")
        if cell.attrib.get("edge") == "1":
            if cell.attrib.get("source") and cell.attrib.get("target"):
                edges.append((str(cell.attrib["source"]), str(cell.attrib["target"])))
            continue
        if cell.attrib.get("vertex") != "1":
            continue
        geometry = next((child for child in cell if child.tag.rsplit("}", 1)[-1] == "mxGeometry"), None)
        if geometry is None:
            continue
        try:
            x, y = float(geometry.attrib.get("x") or 0), float(geometry.attrib.get("y") or 0)
            width, height = float(geometry.attrib.get("width") or 180), float(geometry.attrib.get("height") or 70)
        except (TypeError, ValueError):
            continue
        style = str(cell.attrib.get("style") or "")
        def color(name: str, fallback: str) -> str:
            match = re.search(rf"(?:^|;){re.escape(name)}=([^;]+)", style)
            value = str(match.group(1) if match else fallback)
            return value if re.fullmatch(r"#[0-9A-Fa-f]{6}", value) else fallback
        cells[cell_id] = {"x": x, "y": y, "width": max(20, width), "height": max(20, height), "label": " ".join(re.sub(r"<[^>]+>", " ", html.unescape(str(cell.attrib.get("value") or ""))).split()), "fill": color("fillColor", "#F8FAFC"), "stroke": color("strokeColor", "#475569"), "text_only": "text;" in style, "bold": "fontStyle=1" in style, "rounded": "rounded=1" in style}
    return cells, edges


def _drawio_geometry(cells: dict[str, dict[str, Any]]) -> tuple[int, int, float, float, float]:
    min_x, min_y = min(item["x"] for item in cells.values()), min(item["y"] for item in cells.values())
    max_x = max(item["x"] + item["width"] for item in cells.values())
    max_y = max(item["y"] + item["height"] for item in cells.values())
    width = 1800
    height = max(650, min(1200, int(1800 * (max_y - min_y + 160) / max(1, max_x - min_x + 160))))
    scale = min((width - 140) / max(1, max_x - min_x), (height - 140) / max(1, max_y - min_y))
    return width, height, min_x, min_y, scale


def render_drawio_preview(xml: str, output_path: str | Path, title: str = "System architecture") -> str:
    try:
        cells, edges = _drawio_cells(xml)
    except ET.ParseError:
        return render_box_diagram(output_path, title=title, labels=["Invalid Draw.io source"])
    if not cells:
        return render_box_diagram(output_path, title=title, labels=["Empty Draw.io diagram"])
    width, height, min_x, min_y, scale = _drawio_geometry(cells)

    def rect(item: dict[str, Any]) -> tuple[int, int, int, int]:
        return (
            int(70 + (item["x"] - min_x) * scale),
            int(70 + (item["y"] - min_y) * scale),
            int(70 + (item["x"] - min_x + item["width"]) * scale),
            int(70 + (item["y"] - min_y + item["height"]) * scale),
        )

    image = Image.new("RGB", (width, height), "#FFFFFF")
    draw = ImageDraw.Draw(image)
    for source, target in edges:
        if source not in cells or target not in cells:
            continue
        first, second = rect(cells[source]), rect(cells[target])
        start, end = (first[2], (first[1] + first[3]) // 2), (second[0], (second[1] + second[3]) // 2)
        if end[0] < start[0]:
            start, end = ((first[0] + first[2]) // 2, first[3]), ((second[0] + second[2]) // 2, second[1])
        draw.line((*start, *end), fill="#475569", width=4)
        draw.polygon([end, (end[0] - 16, end[1] - 9), (end[0] - 16, end[1] + 9)], fill="#475569")
    for item in cells.values():
        box = rect(item)
        if not item["text_only"]:
            shape = draw.rounded_rectangle if item["rounded"] else draw.rectangle
            shape(box, **({"radius": 8} if item["rounded"] else {}), fill=item["fill"], outline=item["stroke"], width=3)
        if item["label"]:
            wrapped, font, bounds = _fit_text(draw, item["label"], box)
            draw.multiline_text((box[0] + (box[2] - box[0] - bounds[2] + bounds[0]) / 2, box[1] + max(2, (box[3] - box[1] - bounds[3] + bounds[1]) / 2)), wrapped, fill="#111827", font=font, spacing=5, align="center")
    return _save(image, output_path)
