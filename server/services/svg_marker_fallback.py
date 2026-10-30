"""Expand SVG end markers for converters that ignore marker-end."""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET


_TOKEN = re.compile(r"[A-Za-z]|[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")
_TRANSFORM = re.compile(r"([A-Za-z]+)\s*\(([^)]*)\)")
_NUMBER = re.compile(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")
_IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _multiply(
    left: tuple[float, float, float, float, float, float],
    right: tuple[float, float, float, float, float, float],
) -> tuple[float, float, float, float, float, float]:
    """Compose two SVG affine matrices as ``left(right(point))``."""
    la, lb, lc, ld, le, lf = left
    ra, rb, rc, rd, re_, rf = right
    return (
        la * ra + lc * rb,
        lb * ra + ld * rb,
        la * rc + lc * rd,
        lb * rc + ld * rd,
        la * re_ + lc * rf + le,
        lb * re_ + ld * rf + lf,
    )


def _transform_matrix(value: str) -> tuple[float, float, float, float, float, float]:
    """Parse the SVG transform forms used by authored and runtime layers."""
    matrix = _IDENTITY
    for name, arguments in _TRANSFORM.findall(str(value or "")):
        values = [float(item) for item in _NUMBER.findall(arguments)]
        operation = _IDENTITY
        key = name.casefold()
        if key == "matrix" and len(values) >= 6:
            operation = tuple(values[:6])  # type: ignore[assignment]
        elif key == "translate" and values:
            operation = (1.0, 0.0, 0.0, 1.0, values[0], values[1] if len(values) > 1 else 0.0)
        elif key == "scale" and values:
            sy = values[1] if len(values) > 1 else values[0]
            operation = (values[0], 0.0, 0.0, sy, 0.0, 0.0)
        elif key == "rotate" and values:
            angle = math.radians(values[0])
            rotation = (math.cos(angle), math.sin(angle), -math.sin(angle), math.cos(angle), 0.0, 0.0)
            if len(values) >= 3:
                cx, cy = values[1], values[2]
                operation = _multiply(
                    _multiply((1.0, 0.0, 0.0, 1.0, cx, cy), rotation),
                    (1.0, 0.0, 0.0, 1.0, -cx, -cy),
                )
            else:
                operation = rotation
        elif key == "skewx" and values:
            operation = (1.0, 0.0, math.tan(math.radians(values[0])), 1.0, 0.0, 0.0)
        elif key == "skewy" and values:
            operation = (1.0, math.tan(math.radians(values[0])), 0.0, 1.0, 0.0, 0.0)
        matrix = _multiply(matrix, operation)
    return matrix


def _point(
    matrix: tuple[float, float, float, float, float, float], x: float, y: float,
) -> tuple[float, float]:
    a, b, c, d, e, f = matrix
    return a * x + c * y + e, b * x + d * y + f


def _root_coordinates(
    element: ET.Element, root: ET.Element, parents: dict[ET.Element, ET.Element],
    tangent: tuple[float, float, float, float],
) -> tuple[tuple[float, float, float, float], float]:
    """Map local path coordinates into the coordinate system of root children."""
    chain = []
    current: ET.Element | None = element
    while current is not None and current is not root:
        chain.append(current)
        current = parents.get(current)
    matrix = _IDENTITY
    for item in reversed(chain):
        matrix = _multiply(matrix, _transform_matrix(str(item.attrib.get("transform") or "")))
    x0, y0 = _point(matrix, tangent[0], tangent[1])
    x1, y1 = _point(matrix, tangent[2], tangent[3])
    a, b, c, d, _e, _f = matrix
    scale = max(math.hypot(a, b), math.hypot(c, d), 0.01)
    return (x0, y0, x1, y1), scale


def _pair(values: list[float], relative: bool, current: tuple[float, float]) -> tuple[float, float]:
    point = values[-2], values[-1]
    return (point[0] + current[0], point[1] + current[1]) if relative else point


def _step(
    command: str, values: list[float], current: tuple[float, float],
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    relative = command.islower()
    key = command.upper()
    if key in {"M", "L", "T"} and len(values) >= 2:
        endpoint = _pair(values, relative, current)
        return endpoint, current
    if key == "H" and values:
        endpoint = (current[0] + values[-1], current[1]) if relative else (values[-1], current[1])
        return endpoint, current
    if key == "V" and values:
        endpoint = (current[0], current[1] + values[-1]) if relative else (current[0], values[-1])
        return endpoint, current
    if key in {"C", "S", "Q"} and len(values) >= 4:
        endpoint = _pair(values, relative, current)
        control = values[-4], values[-3]
        if relative:
            control = control[0] + current[0], control[1] + current[1]
        return endpoint, control
    if key == "A" and len(values) >= 7:
        endpoint = _pair(values, relative, current)
        return endpoint, current
    return None


def path_end_tangent(path_data: str) -> tuple[float, float, float, float] | None:
    """Return the final segment's start/end points for common SVG path commands."""
    tokens = _TOKEN.findall(path_data)
    command = ""
    values: list[float] = []
    current = 0.0, 0.0
    tangent: tuple[float, float, float, float] | None = None
    for token in tokens + ["Z"]:
        if token.isalpha():
            if command and values:
                result = _step(command, values, current)
                if result:
                    endpoint, origin = result
                    tangent = origin[0], origin[1], endpoint[0], endpoint[1]
                    current = endpoint
            command, values = token, []
        else:
            values.append(float(token))
    return tangent


def _triangle(tangent: tuple[float, float, float, float], size: float) -> str | None:
    x0, y0, x1, y1 = tangent
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy)
    if length <= 0.01:
        return None
    ux, uy = dx / length, dy / length
    back_x, back_y = x1 - ux * size, y1 - uy * size
    half = size * 0.48
    points = (
        (x1, y1), (back_x - uy * half, back_y + ux * half),
        (back_x + uy * half, back_y - ux * half),
    )
    return " ".join(f"{x:.2f},{y:.2f}" for x, y in points)


def expand_end_markers(root: ET.Element) -> None:
    """Append vector arrowheads above nodes while retaining authored path geometry."""
    namespace = root.tag.partition("}")[0] + "}" if "}" in root.tag else ""
    parents = {child: parent for parent in root.iter() for child in list(parent)}
    arrows: list[tuple[str, str]] = []
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1].casefold() != "path":
            continue
        marker = str(element.attrib.get("marker-end") or "")
        if not marker.startswith("url("):
            continue
        tangent = path_end_tangent(str(element.attrib.get("d") or ""))
        width = float(element.attrib.get("stroke-width") or 2.5)
        if tangent:
            tangent, scale = _root_coordinates(element, root, parents, tangent)
            points = _triangle(tangent, max(10.0, width * 4.0) * scale)
        else:
            points = None
        if points:
            arrows.append((points, str(element.attrib.get("stroke") or "#52627A")))
            element.attrib.pop("marker-end", None)
    if not arrows:
        return
    layer = ET.SubElement(root, f"{namespace}g", {"data-renderer-layer": "marker-fallback"})
    for points, fill in arrows:
        ET.SubElement(layer, f"{namespace}polygon", {"points": points, "fill": fill})
