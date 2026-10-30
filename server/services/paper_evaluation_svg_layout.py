"""Reflow a canonical evaluation SVG at print-safe font sizes without losing relations.

Only numeric, axis-aligned geometry of the current deterministic evaluation
producer is supported. Every original visible word, object ID and path remains;
line wrapping and monotone vertical expansion preserve graph topology.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from bisect import bisect_right
from typing import Any


def reflow_evaluation_svg(original: bytes, multiplier: float) -> bytes:
    """Wrap current source-bound labels and expand rows; never shrink readable fonts."""
    from .paper_derived_svg_projection import scaled_svg_typography

    root = ET.fromstring(scaled_svg_typography(original, multiplier))
    view = [float(item) for item in root.attrib.get("viewBox", "").split()]
    if len(view) != 4 or view[0] != 0 or view[1] != 0 or view[2] <= 0:
        raise ValueError("Evaluation print reflow requires a zero-origin numeric canvas")
    identities = {element.attrib.get("id") for element in root.iter()}
    if not {"eval_group_split", "eval_publication_labels", "eval_matched_comparisons"}.issubset(identities):
        raise ValueError("Evaluation reflow requires the current canonical semantic groups")
    before = _visible_text(root)
    original_root = ET.fromstring(original)
    text_nodes = [element for element in root.iter() if element.tag.rsplit("}", 1)[-1] == "text"]
    old_text = [element for element in original_root.iter() if element.tag.rsplit("}", 1)[-1] == "text"]
    if len(text_nodes) != len(old_text):
        raise ValueError("Evaluation typography projection changed its source text inventory")
    layouts = _text_layouts(root, text_nodes, old_text, view[2])
    warp = _vertical_warp(layouts, multiplier)
    _transform_geometry(root, warp, view)
    _write_text_layouts(layouts, warp)
    _horizontal_gap_check(layouts)
    if before != _visible_text(root):
        raise ValueError("Evaluation paper reflow changed a visible scientific word")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _visible_text(root: Any) -> tuple[str, ...]:
    return tuple(" ".join("".join(element.itertext()).split()) for element in root.iter()
                 if element.tag.rsplit("}", 1)[-1] == "text")


def _number(element: Any, key: str, default: float = 0) -> float:
    value = element.get(key, str(default))
    if not re.fullmatch(r"[+-]?[0-9]+(?:\.[0-9]+)?", value):
        raise ValueError("Evaluation paper reflow cannot alter unresolved geometry")
    return float(value)


def _text_layouts(root: Any, nodes: list, old: list, width: float) -> list[dict]:
    rectangles = [element for element in root.iter() if element.tag.rsplit("}", 1)[-1] == "rect"
                  and "x" in element.attrib and "y" in element.attrib]
    layouts = []
    adjusted = _horizontal_baselines(nodes, old)
    for node, prior in zip(nodes, old, strict=True):
        if list(node) or node.get("transform"):
            raise ValueError("Canonical evaluation text needs direct numeric baseline coordinates")
        x, y, size = adjusted[id(node)], _number(prior, "y"), _number(node, "font-size")
        enclosing = [rect for rect in rectangles if _number(rect, "x") <= x <= _number(rect, "x") + _number(rect, "width")
                     and _number(rect, "y") <= y <= _number(rect, "y") + _number(rect, "height")]
        rect = min(enclosing, key=lambda item: _number(item, "width") * _number(item, "height")) if enclosing else None
        left, right = (_number(rect, "x") + 18, _number(rect, "x") + _number(rect, "width") - 18) if rect is not None else (18, width - 18)
        anchor = node.get("text-anchor", "start")
        available = 2 * min(x - left, right - x) if anchor == "middle" else x - left if anchor == "end" else right - x
        if available <= 0:
            raise ValueError("Evaluation source text has no bound paper-layout region")
        text = " ".join("".join(node.itertext()).split())
        lines = _wrap(text, available, size, node.get("font-weight") == "700")
        layouts.append({"node": node, "x": x, "y": y, "size": size, "lines": lines, "text": text, "old_size": _number(prior, "font-size")})
    return layouts


def _horizontal_baselines(nodes: list, prior: list) -> dict[int, float]:
    """Separated title/body labels cannot touch after native typography grows."""
    import fitz

    result = {id(node): _number(old, "x") for node, old in zip(nodes, prior, strict=True)}
    groups: dict[float, list] = {}
    for node, old in zip(nodes, prior, strict=True):
        if node.get("text-anchor", "start") == "start":
            groups.setdefault(_number(old, "y"), []).append((node, old))
    for items in groups.values():
        right = None
        for node, old in sorted(items, key=lambda pair: _number(pair[1], "x")):
            x = max(_number(old, "x"), right + 18) if right is not None else _number(old, "x")
            result[id(node)] = x
            size = _number(node, "font-size")
            right = x + fitz.get_text_length(" ".join("".join(node.itertext()).split()),
                                            fontname="hebo" if node.get("font-weight") == "700" else "helv", fontsize=size)
    return result


def _wrap(text: str, width: float, size: float, bold: bool) -> list[str]:
    import fitz

    lines, line = [], ""
    measure = lambda value: fitz.get_text_length(value, fontname="hebo" if bold else "helv", fontsize=size)
    for word in text.split():
        trial = f"{line} {word}".strip()
        if measure(trial) <= width:
            line = trial
            continue
        if line:
            lines.append(line)
            line = ""
        # Compound public labels may wrap at their authored slash or hyphen.
        # No character is removed and no synthetic hyphen or space is inserted.
        for part in re.findall(r"[^/\-]+[/\-]?|[/\-]", word):
            if measure(part) > width:
                raise ValueError("Evaluation source contains a word wider than its print-safe region")
            if line and measure(line + part) > width:
                lines.append(line)
                line = ""
            line += part
    if line:
        if measure(line) > width:
            raise ValueError("Evaluation source contains an unbreakable print label")
        lines.append(line)
    return lines


def _vertical_warp(layouts: list[dict], multiplier: float):
    import fitz
    rows = sorted({item["y"] for item in layouts})
    anchors, positions, placed = [], [], []
    offset = 0.0
    for index, row in enumerate(rows):
        current = [item for item in layouts if item['y'] == row]
        position = row + offset
        for item in current:
            width = max(fitz.get_text_length(line, fontsize=item['size'],
                        fontname='hebo' if item['node'].get('font-weight') == '700' else 'helv') for line in item['lines'])
            anchor = item['node'].get('text-anchor', 'start')
            left = item['x'] - (width/2 if anchor == 'middle' else width if anchor == 'end' else 0)
            item['horizontal_bounds'] = (left, left + width)
            for prior, baseline in placed:
                lo, hi = prior['horizontal_bounds']
                if min(hi, left+width) <= max(lo, left):
                    continue
                required = (len(prior['lines'])-1)*prior['size']*1.4 + max(prior['size'],item['size'])*1.45
                position = max(position, baseline + required)
        offset = position - row
        anchors.append(row)
        positions.append(position)
        placed.extend((item,position) for item in current)

    def warp(value: float) -> float:
        index = bisect_right(anchors, value) - 1
        if index < 0:
            return value
        if 0 <= index < len(anchors) - 1:
            fraction = (value - anchors[index]) / (anchors[index + 1] - anchors[index])
            return positions[index] + fraction * (positions[index + 1] - positions[index])
        return positions[index] + value - anchors[index]
    return warp


def _transform_geometry(root: Any, warp: Any, view: list[float]) -> None:
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag in {"svg", "text", "marker", "metadata", "title", "desc"}:
            continue
        if tag == "path" and "d" in element.attrib:
            if element.get("id") or element.get("marker-end"):
                element.set("d", _warped_path(element.get("d"), warp))
            continue
        if element.get("transform"):
            raise ValueError("Evaluation paper reflow cannot safely modify transformed graph geometry")
        if "y" in element.attrib:
            top = _number(element, "y")
            element.set("y", f"{warp(top):.8g}")
            if "height" in element.attrib:
                element.set("height", f"{warp(top + _number(element, 'height')) - warp(top):.8g}")
        for key in ("y1", "y2", "cy"):
            if key in element.attrib:
                element.set(key, f"{warp(_number(element, key)):.8g}")
    height = warp(view[3]) + 20
    root.set("height", f"{height:.8g}")
    root.set("viewBox", f"0 0 {view[2]:.8g} {height:.8g}")
    for element in root:
        if element.tag.rsplit("}", 1)[-1] == "rect" and "y" not in element.attrib and "height" in element.attrib:
            element.set("height", f"{height:.8g}")


def _warped_path(path: str, warp: Any) -> str:
    tokens = re.findall(r"[A-Za-z]|[+-]?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)", path)
    result, command, position = [], "", 0
    counts = {"M": 2, "L": 2, "C": 6, "Q": 4, "H": 1, "V": 1, "Z": 0}
    for token in tokens:
        if token.isalpha():
            if token not in counts:
                raise ValueError("Evaluation paper reflow supports only absolute canonical graph paths")
            command, position = token, 0
            result.append(token)
        else:
            if not command or counts[command] == 0:
                raise ValueError("Evaluation graph path has unsupported numeric geometry")
            value = float(token)
            if command == "V" or command not in {"H"} and position % 2 == 1:
                value = warp(value)
            result.append(f"{value:.8g}")
            position = (position + 1) % counts[command]
    return " ".join(result)


def _write_text_layouts(layouts: list[dict], warp: Any) -> None:
    namespace = "{http://www.w3.org/2000/svg}"
    for item in layouts:
        node = item["node"]
        node.set("x", f"{item['x']:.8g}")
        node.set("y", f"{warp(item['y']):.8g}")
        if len(item["lines"]) == 1:
            node.text = item["lines"][0]
            continue
        node.text = None
        original = item["text"]
        offset = 0
        for index, line in enumerate(item["lines"]):
            tspan = ET.SubElement(node, namespace + "tspan", {
                "x": f"{item['x']:.8g}", "y": f"{warp(item['y']) + index * item['size'] * 1.4:.8g}"})
            offset += len(line)
            separator = " " if original[offset:offset + 1] == " " else ""
            offset += len(separator)
            tspan.text = line + separator


def _horizontal_gap_check(layouts: list[dict]) -> None:
    """Check separate source labels even when a PDF renderer merges their text blocks."""
    import fitz

    groups: dict[float, list] = {}
    for item in layouts:
        if item["node"].get("text-anchor", "start") == "start":
            groups.setdefault(item["y"], []).append(item)
    for items in groups.values():
        right = None
        for item in sorted(items, key=lambda value: value["x"]):
            if right is not None and item["x"] - right < 17.99:
                raise ValueError("Evaluation paper labels have no readable horizontal separation")
            right = item["x"] + max(fitz.get_text_length(line,
                fontname="hebo" if item["node"].get("font-weight") == "700" else "helv", fontsize=item["size"])
                for line in item["lines"])
