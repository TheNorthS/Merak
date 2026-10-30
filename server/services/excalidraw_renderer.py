"""Model-authored Excalidraw scene normalization and publication rendering."""

from __future__ import annotations

import hashlib
import json
import math
import re
import textwrap
import time
from pathlib import Path
from typing import Any, Iterable

from .excalidraw_scene_rendering import ExcalidrawSceneError


SUPPORTED_ELEMENT_TYPES = {
    "rectangle",
    "ellipse",
    "diamond",
    "text",
    "arrow",
    "line",
    "frame",
}
SHAPE_TYPES = {"rectangle", "ellipse", "diamond", "frame"}
CONNECTOR_TYPES = {"arrow", "line"}
DEFAULT_STROKE = "#334155"
DEFAULT_FILL = "#f8fafc"


def _number(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _positive(value: Any, default: float) -> float:
    return max(1.0, _number(value, default))


def _stable_seed(value: str) -> int:
    return int(hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:8], 16) % 2_147_483_646 + 1


def _safe_id(value: Any, index: int) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "-", str(value or "")).strip("-")
    return cleaned[:64] or f"element-{index + 1}"


def _wrap_line(line: str, capacity: int) -> list[str]:
    if len(line) <= capacity:
        return [line]
    if " " in line:
        return textwrap.wrap(
            line,
            width=capacity,
            break_long_words=True,
            break_on_hyphens=False,
        ) or [line]
    return [line[index:index + capacity] for index in range(0, len(line), capacity)]


def _wrap_text(value: Any, width: float, font_size: float) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    capacity = max(5, int(max(24.0, width) / max(7.0, font_size * 0.56)))
    wrapped: list[str] = []
    for raw_line in text.splitlines() or [""]:
        wrapped.extend(_wrap_line(raw_line, capacity))
    return "\n".join(wrapped)


def _base_element(
    raw: dict[str, Any],
    *,
    element_id: str,
    element_type: str,
    index: int,
    x: float,
    y: float,
    width: float,
    height: float,
) -> dict[str, Any]:
    requested_roughness = _number(raw.get("roughness"), 0.9)
    roughness = (
        0.0
        if element_type == "text"
        else max(0.55, min(1.35, requested_roughness))
    )
    return {
        "id": element_id,
        "type": element_type,
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "angle": _number(raw.get("angle"), 0.0),
        "strokeColor": str(raw.get("strokeColor") or DEFAULT_STROKE),
        "backgroundColor": str(
            raw.get("backgroundColor")
            or ("transparent" if element_type in CONNECTOR_TYPES | {"text", "frame"} else DEFAULT_FILL)
        ),
        "fillStyle": str(raw.get("fillStyle") or "solid"),
        "strokeWidth": max(1.0, min(4.0, _number(raw.get("strokeWidth"), 2.0))),
        "strokeStyle": str(raw.get("strokeStyle") or ("dashed" if element_type == "frame" else "solid")),
        "roughness": roughness,
        "opacity": max(20, min(100, int(_number(raw.get("opacity"), 100)))),
        "groupIds": list(raw.get("groupIds") or []),
        "frameId": raw.get("frameId"),
        "index": str(raw.get("index") or f"a{index:04x}"),
        "roundness": raw.get("roundness"),
        "seed": int(_number(raw.get("seed"), _stable_seed(element_id))),
        "version": max(1, int(_number(raw.get("version"), 1))),
        "versionNonce": int(_number(raw.get("versionNonce"), _stable_seed(element_id + "-version"))),
        "isDeleted": False,
        "boundElements": list(raw.get("boundElements") or []),
        "updated": int(_number(raw.get("updated"), int(time.time() * 1000))),
        "link": raw.get("link"),
        "locked": bool(raw.get("locked", False)),
        "customData": {
            **dict(raw.get("customData") or {}),
            **({"role": raw.get("role")} if raw.get("role") else {}),
            **({"codeSymbol": raw.get("codeSymbol")} if raw.get("codeSymbol") else {}),
            **({"sourcePath": raw.get("sourcePath")} if raw.get("sourcePath") else {}),
        },
    }


def _text_element(
    raw: dict[str, Any],
    *,
    element_id: str,
    index: int,
    text: str,
    x: float,
    y: float,
    width: float,
    height: float,
    container_id: str | None = None,
) -> dict[str, Any]:
    font_size = max(12.0, min(38.0, _number(raw.get("fontSize"), 18.0)))
    wrapped = _wrap_text(text, width, font_size)
    line_count = max(1, len(wrapped.splitlines()))
    line_height = max(1.15, min(1.5, _number(raw.get("lineHeight"), 1.25)))
    required_height = line_count * font_size * line_height + 6
    base = _base_element(
        raw,
        element_id=element_id,
        element_type="text",
        index=index,
        x=x,
        y=y,
        width=max(24.0, width),
        height=max(height, required_height),
    )
    base.update({
        "fontSize": font_size,
        "fontFamily": int(_number(raw.get("fontFamily"), 2)),
        "text": wrapped,
        "textAlign": str(raw.get("textAlign") or ("center" if container_id else "left")),
        "verticalAlign": str(raw.get("verticalAlign") or "middle"),
        "containerId": container_id,
        "originalText": str(text),
        "autoResize": False,
        "lineHeight": line_height,
        "backgroundColor": "transparent",
        "strokeColor": str(raw.get("textColor") or raw.get("strokeColor") or "#0f172a"),
        "strokeWidth": 1,
        "roughness": 0,
    })
    return base


def _shape_edge_point(source: dict[str, Any], target: dict[str, Any], gap: float = 12.0) -> tuple[float, float]:
    sx = float(source["x"]) + float(source["width"]) / 2
    sy = float(source["y"]) + float(source["height"]) / 2
    tx = float(target["x"]) + float(target["width"]) / 2
    ty = float(target["y"]) + float(target["height"]) / 2
    dx, dy = tx - sx, ty - sy
    if abs(dx) < 1e-6 and abs(dy) < 1e-6:
        return sx, sy
    half_width = float(source["width"]) / 2 + gap
    half_height = float(source["height"]) / 2 + gap
    scale = min(
        half_width / abs(dx) if abs(dx) > 1e-6 else float("inf"),
        half_height / abs(dy) if abs(dy) > 1e-6 else float("inf"),
    )
    return sx + dx * scale, sy + dy * scale


def _normalize_points(raw_points: Any) -> list[list[float]]:
    points: list[list[float]] = []
    for raw_point in raw_points if isinstance(raw_points, list) else []:
        if isinstance(raw_point, dict):
            points.append([_number(raw_point.get("x")), _number(raw_point.get("y"))])
        elif isinstance(raw_point, (list, tuple)) and len(raw_point) >= 2:
            points.append([_number(raw_point[0]), _number(raw_point[1])])
    return points


def _scene_payload(code: str) -> dict[str, Any]:
    try:
        payload = json.loads(code)
    except json.JSONDecodeError as exc:
        raise ExcalidrawSceneError(f"Excalidraw code must be complete JSON: {exc}") from exc
    if isinstance(payload, list):
        payload = {"elements": payload}
    if not isinstance(payload, dict) or not isinstance(payload.get("elements"), list):
        raise ExcalidrawSceneError("Excalidraw JSON must contain an elements array.")
    if not payload["elements"]:
        raise ExcalidrawSceneError("Excalidraw scene contains no elements.")
    if len(payload["elements"]) > 160:
        raise ExcalidrawSceneError("Excalidraw scene exceeds the 160-element publication limit.")
    return payload


def _normalize_primary_elements(
    raw_elements: list[Any],
) -> tuple[list[dict[str, Any]], list[tuple[dict[str, Any], str, dict[str, Any], int]], set[str], list[tuple[dict[str, Any], str, int]]]:
    normalized: list[dict[str, Any]] = []
    labels: list[tuple[dict[str, Any], str, dict[str, Any], int]] = []
    seen_ids: set[str] = set()
    connectors: list[tuple[dict[str, Any], str, int]] = []
    for index, item in enumerate(raw_elements):
        if not isinstance(item, dict) or item.get("isDeleted"):
            continue
        element_type = str(item.get("type") or "").strip().lower()
        element_type = {"box": "rectangle", "node": "rectangle"}.get(element_type, element_type)
        if element_type not in SUPPORTED_ELEMENT_TYPES:
            raise ExcalidrawSceneError(
                f"Unsupported Excalidraw element type at index {index}: {element_type or 'empty'}"
            )
        element_id = _safe_id(item.get("id"), index)
        if element_id in seen_ids:
            raise ExcalidrawSceneError(f"Duplicate Excalidraw element id: {element_id}")
        seen_ids.add(element_id)
        if element_type in CONNECTOR_TYPES:
            connectors.append((item, element_id, index))
            continue
        x, y = _number(item.get("x")), _number(item.get("y"))
        if element_type == "text":
            font_size = max(12.0, min(38.0, _number(item.get("fontSize"), 18.0)))
            width = _positive(item.get("width"), max(120.0, len(str(item.get("text") or "")) * font_size * 0.52))
            height = _positive(item.get("height"), font_size * 1.4)
            normalized.append(_text_element(
                item, element_id=element_id, index=index,
                text=str(item.get("text") or ""), x=x, y=y,
                width=width, height=height, container_id=item.get("containerId"),
            ))
            continue
        shape = _base_element(
            item, element_id=element_id, element_type=element_type, index=index,
            x=x, y=y, width=_positive(item.get("width"), 220.0),
            height=_positive(item.get("height"), 90.0),
        )
        normalized.append(shape)
        label_text = str(item.get("text") or "").strip()
        if label_text:
            labels.append((shape, label_text, item, index))
    return normalized, labels, seen_ids, connectors


def _append_connectors(
    normalized: list[dict[str, Any]],
    connectors: list[tuple[dict[str, Any], str, int]],
) -> None:
    shapes = {
        str(element["id"]): element
        for element in normalized if element["type"] in SHAPE_TYPES
    }
    for raw, element_id, index in connectors:
        start_id = str(raw.get("startElementId") or raw.get("start", {}).get("id") or "")
        end_id = str(raw.get("endElementId") or raw.get("end", {}).get("id") or "")
        points = _normalize_points(raw.get("points"))
        x, y = _number(raw.get("x")), _number(raw.get("y"))
        if start_id in shapes and end_id in shapes and len(points) < 2:
            start_abs = _shape_edge_point(shapes[start_id], shapes[end_id])
            end_abs = _shape_edge_point(shapes[end_id], shapes[start_id])
            x, y = start_abs
            points = [[0.0, 0.0], [end_abs[0] - x, end_abs[1] - y]]
        elif len(points) < 2:
            raise ExcalidrawSceneError(
                f"Connector {element_id} needs two points or valid startElementId/endElementId."
            )
        width = max(point[0] for point in points) - min(point[0] for point in points)
        height = max(point[1] for point in points) - min(point[1] for point in points)
        connector = _base_element(
            raw, element_id=element_id,
            element_type=str(raw.get("type") or "arrow").lower(), index=index,
            x=x, y=y, width=max(1.0, abs(width)), height=max(1.0, abs(height)),
        )
        connector.update({
            "points": points,
            "lastCommittedPoint": None,
            "startBinding": {"elementId": start_id, "focus": 0, "gap": 8} if start_id in shapes else None,
            "endBinding": {"elementId": end_id, "focus": 0, "gap": 8} if end_id in shapes else None,
            "startArrowhead": raw.get("startArrowhead"),
            "endArrowhead": raw.get("endArrowhead") or (
                "arrow" if str(raw.get("type") or "arrow").lower() == "arrow" else None
            ),
            "elbowed": bool(raw.get("elbowed", False)),
        })
        normalized.append(connector)


def _append_shape_labels(
    normalized: list[dict[str, Any]],
    labels: list[tuple[dict[str, Any], str, dict[str, Any], int]],
    seen_ids: set[str],
    raw_element_count: int,
) -> None:
    for shape, label_text, raw, index in labels:
        label_id = _safe_id(raw.get("labelId") or f"{shape['id']}-label", index)
        suffix = 2
        while label_id in seen_ids:
            label_id = f"{shape['id']}-label-{suffix}"
            suffix += 1
        seen_ids.add(label_id)
        label_width = max(40.0, float(shape["width"]) - 24.0)
        font_size = max(12.0, min(32.0, _number(raw.get("fontSize"), 18.0)))
        line_count = max(1, len(_wrap_text(label_text, label_width, font_size).splitlines()))
        label_height = line_count * font_size * 1.25 + 6
        label_y = float(shape["y"]) + max(8.0, (float(shape["height"]) - label_height) / 2)
        normalized.append(_text_element(
            raw, element_id=label_id, index=raw_element_count + index,
            text=label_text, x=float(shape["x"]) + 12.0, y=label_y,
            width=label_width, height=label_height, container_id=str(shape["id"]),
        ))
        shape["boundElements"] = [
            *[item for item in shape.get("boundElements", []) if item.get("id") != label_id],
            {"id": label_id, "type": "text"},
        ]


def normalize_scene(code: str) -> dict[str, Any]:
    """Convert the skill's model-friendly JSON into a valid Excalidraw scene."""

    payload = _scene_payload(code)
    raw_elements = payload["elements"]
    normalized, labels, seen_ids, connectors = _normalize_primary_elements(
        raw_elements
    )
    _append_connectors(normalized, connectors)
    _append_shape_labels(normalized, labels, seen_ids, len(raw_elements))
    if not normalized:
        raise ExcalidrawSceneError(
            "Excalidraw scene contains no supported visible elements."
        )
    return {
        "type": "excalidraw",
        "version": 2,
        "source": "https://merak-research.local/model-excalidraw",
        "elements": normalized,
        "appState": {
            "viewBackgroundColor": str(
                dict(payload.get("appState") or {}).get("viewBackgroundColor")
                or "#ffffff"
            ),
            "gridSize": None,
        },
        "files": dict(payload.get("files") or {}),
    }


def _bounds(element: dict[str, Any]) -> tuple[float, float, float, float]:
    x = float(element.get("x") or 0)
    y = float(element.get("y") or 0)
    if element.get("type") in CONNECTOR_TYPES:
        points = element.get("points") or [[0, 0]]
        xs = [x + _number(point[0]) for point in points]
        ys = [y + _number(point[1]) for point in points]
        return min(xs), min(ys), max(xs), max(ys)
    return x, y, x + float(element.get("width") or 0), y + float(element.get("height") or 0)


def _intersection_area(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(
        0.0, min(a[3], b[3]) - max(a[1], b[1])
    )


def _contains(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    return a[0] <= b[0] and a[1] <= b[1] and a[2] >= b[2] and a[3] >= b[3]


def _orientation(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> int:
    value = (b[1] - a[1]) * (c[0] - b[0]) - (b[0] - a[0]) * (c[1] - b[1])
    if abs(value) < 1e-7:
        return 0
    return 1 if value > 0 else 2


def _segments_cross(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
    d: tuple[float, float],
) -> bool:
    return _orientation(a, b, c) != _orientation(a, b, d) and _orientation(c, d, a) != _orientation(c, d, b)


def _connector_segments(element: dict[str, Any]) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    x = float(element.get("x") or 0)
    y = float(element.get("y") or 0)
    points = [(x + _number(point[0]), y + _number(point[1])) for point in element.get("points") or []]
    return list(zip(points, points[1:]))


def _segment_hits_box(
    start: tuple[float, float],
    end: tuple[float, float],
    box: tuple[float, float, float, float],
    inset: float = 5.0,
) -> bool:
    left, top, right, bottom = box
    left += inset
    top += inset
    right -= inset
    bottom -= inset
    if right <= left or bottom <= top:
        return False
    if left < start[0] < right and top < start[1] < bottom:
        return True
    if left < end[0] < right and top < end[1] < bottom:
        return True
    corners = [(left, top), (right, top), (right, bottom), (left, bottom)]
    return any(
        _segments_cross(start, end, corners[index], corners[(index + 1) % 4])
        for index in range(4)
    )


def scene_layout_issues(scene: dict[str, Any]) -> list[str]:
    """Return actionable geometry defects for the model revision loop."""
    elements = [item for item in scene.get("elements", []) if not item.get("isDeleted")]
    shapes = [item for item in elements if item.get("type") in SHAPE_TYPES]
    texts = [item for item in elements if item.get("type") == "text"]
    connectors = [item for item in elements if item.get("type") in CONNECTOR_TYPES]
    issues: list[str] = []
    if len(shapes) < 3:
        issues.append("scene needs at least three domain-specific visual components")
    visible_labels = [str(item.get("text") or "").strip() for item in texts if str(item.get("text") or "").strip()]
    if len(visible_labels) < 3:
        issues.append("scene needs at least three readable domain-specific labels")

    foreground_shapes = [
        item for item in shapes
        if str((item.get("customData") or {}).get("role") or "").casefold()
        not in {"zone", "background", "frame"}
        and item.get("type") != "frame"
    ]
    for index, first in enumerate(foreground_shapes):
        first_bounds = _bounds(first)
        first_area = max(1.0, float(first.get("width") or 0) * float(first.get("height") or 0))
        for second in foreground_shapes[index + 1:]:
            second_bounds = _bounds(second)
            if _contains(first_bounds, second_bounds) or _contains(second_bounds, first_bounds):
                continue
            overlap = _intersection_area(first_bounds, second_bounds)
            second_area = max(1.0, float(second.get("width") or 0) * float(second.get("height") or 0))
            if overlap / min(first_area, second_area) > 0.08:
                issues.append(f"overlap between {first['id']} and {second['id']}")

    for connector in connectors:
        linked = {
            str((connector.get("startBinding") or {}).get("elementId") or ""),
            str((connector.get("endBinding") or {}).get("elementId") or ""),
        }
        for shape in foreground_shapes:
            if str(shape.get("id")) in linked:
                continue
            if any(
                _segment_hits_box(start, end, _bounds(shape))
                for start, end in _connector_segments(connector)
            ):
                issues.append(f"connector {connector['id']} crosses unrelated element {shape['id']}")

    crossing_count = 0
    for index, first in enumerate(connectors):
        first_linked = {
            str((first.get("startBinding") or {}).get("elementId") or ""),
            str((first.get("endBinding") or {}).get("elementId") or ""),
        }
        for second in connectors[index + 1:]:
            second_linked = {
                str((second.get("startBinding") or {}).get("elementId") or ""),
                str((second.get("endBinding") or {}).get("elementId") or ""),
            }
            if (first_linked & second_linked) - {""}:
                continue
            if any(
                _segments_cross(a, b, c, d)
                for a, b in _connector_segments(first)
                for c, d in _connector_segments(second)
            ):
                crossing_count += 1
    if crossing_count > 2:
        issues.append(f"scene has {crossing_count} unrelated connector crossings")

    all_bounds = [_bounds(item) for item in elements if item.get("type") != "text" or not item.get("containerId")]
    if all_bounds:
        width = max(item[2] for item in all_bounds) - min(item[0] for item in all_bounds)
        height = max(item[3] for item in all_bounds) - min(item[1] for item in all_bounds)
        if width < 600 or height < 280:
            issues.append(f"scene is undersized for publication ({round(width)}x{round(height)})")
        if width / max(1.0, height) > 4.2:
            issues.append(f"scene aspect ratio is too wide ({width / height:.2f})")
    return list(dict.fromkeys(issues))


def scene_text(scene: dict[str, Any]) -> str:
    return "\n".join(
        str(element.get("text") or "").strip()
        for element in scene.get("elements", [])
        if element.get("type") == "text" and str(element.get("text") or "").strip()
    )


def scene_element_ids(scene: dict[str, Any]) -> set[str]:
    return {
        str(element.get("id") or "")
        for element in scene.get("elements", [])
        if str(element.get("id") or "")
    }


def _source_symbol_present(content: str, symbol: str) -> bool:
    if symbol in content:
        return True
    components = [
        item for item in re.split(r"[.:#]+", symbol) if item
    ]
    if not components:
        return False
    # Qualified Python references are normally persisted as Class.member while
    # source code declares the class and member on separate lines.
    required = components[-2:] if len(components) >= 2 else components
    return all(
        re.search(rf"(?<![A-Za-z0-9_]){re.escape(item)}(?![A-Za-z0-9_])", content)
        for item in required
    )


def verify_element_mappings(
    scene: dict[str, Any],
    mappings: Iterable[dict[str, Any]],
    project_root: str | Path,
) -> list[str]:
    """Verify model-declared diagram nodes against real code/contract sources."""
    root = Path(project_root).expanduser().resolve()
    ids = scene_element_ids(scene)
    issues: list[str] = []
    for index, raw in enumerate(mappings):
        mapping = dict(raw or {})
        element_id = str(mapping.get("element_id") or "").strip()
        source_path = str(mapping.get("source_path") or "").strip()
        symbol = str(mapping.get("source_symbol") or "").strip()
        if not element_id or element_id not in ids:
            issues.append(f"element mapping {index + 1} references missing element_id {element_id or '(empty)'}")
            continue
        if not source_path:
            issues.append(f"element mapping {index + 1} has no source_path")
            continue
        candidate = Path(source_path)
        candidate = candidate if candidate.is_absolute() else root / candidate
        try:
            candidate = candidate.resolve()
            candidate.relative_to(root)
        except (OSError, ValueError):
            issues.append(f"element mapping {index + 1} escapes the project: {source_path}")
            continue
        if not candidate.is_file() or candidate.stat().st_size == 0:
            issues.append(f"element mapping {index + 1} source is missing: {source_path}")
            continue
        if symbol:
            content = candidate.read_text(encoding="utf-8", errors="replace")
            if not _source_symbol_present(content, symbol):
                issues.append(
                    f"element mapping {index + 1} symbol {symbol!r} is absent from {source_path}"
                )
    return issues
