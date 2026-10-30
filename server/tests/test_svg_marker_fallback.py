"""Renderer fallback tests for model-authored SVG marker-end connectors."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from server.services.svg_marker_fallback import expand_end_markers, path_end_tangent
from server.services.svg_variant_conversion import _converter_svg


def test_path_end_tangent_handles_orthogonal_connector() -> None:
    assert path_end_tangent("M1190 415V570H500V415") == (500.0, 570.0, 500.0, 415.0)


def test_converter_expands_marker_into_topmost_vector_triangle() -> None:
    source = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 200">'
        '<path d="M20 100H300" fill="none" stroke="#52627A" '
        'stroke-width="3" marker-end="url(#arrow)"/>'
        '<g id="node"><rect x="300" y="60" width="80" height="80"/></g>'
        '</svg>'
    ).encode()

    converted = ET.fromstring(_converter_svg(source))
    children = list(converted)
    layer = children[-1]

    assert layer.attrib["data-renderer-layer"] == "marker-fallback"
    triangle = list(layer)[0]
    assert triangle.tag.rsplit("}", 1)[-1] == "polygon"
    assert triangle.attrib["fill"] == "#52627A"
    assert triangle.attrib["points"].startswith("300.00,100.00")
    path = next(item for item in converted.iter() if item.tag.rsplit("}", 1)[-1] == "path")
    assert "marker-end" not in path.attrib


def test_expand_end_markers_leaves_non_connector_paths_untouched() -> None:
    root = ET.fromstring('<svg><path d="M0 0L10 10" stroke="#000"/></svg>')
    expand_end_markers(root)
    assert len(list(root)) == 1


def test_expand_end_markers_maps_nested_transform_through_clipped_groups() -> None:
    root = ET.fromstring(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 200">'
        '<defs><clipPath id="local-clip"><rect width="50" height="40"/></clipPath></defs>'
        '<g transform="translate(100 50)"><g transform="scale(2)" clip-path="url(#local-clip)">'
        '<path d="M10 20H40" stroke="#123456" stroke-width="2" '
        'marker-end="url(#arrow)"/></g></g></svg>'
    )

    expand_end_markers(root)

    layer = list(root)[-1]
    triangle = list(layer)[0]
    assert triangle.attrib["points"].startswith("180.00,90.00")
    assert triangle.attrib["fill"] == "#123456"
    assert "transform" not in triangle.attrib
    path = next(item for item in root.iter() if item.tag.rsplit("}", 1)[-1] == "path")
    assert "marker-end" not in path.attrib
