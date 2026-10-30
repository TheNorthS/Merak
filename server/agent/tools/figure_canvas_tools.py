"""Hybrid canvas tools: deterministic global geometry, model-authored local glyphs."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from server.agent.tools.figure_draft_tools import (
    append_figure_svg_fragment,
    begin_figure_svg_draft,
    finalize_figure_svg_draft,
    replace_figure_svg_fragment,
)
from server.agent.tools.figure_storyboard_tools import load_selected_storyboard
from server.services.figure_canvas_layout import canvas_layout, opening_svg, region_header_svg
from server.services.figure_mechanism_ir import (
    MECHANISM_CANVAS_SCHEMA,
    validate_mechanism_ir,
)
from server.services.figure_mechanism_requirements import (
    required_mechanism_labels, validate_required_mechanisms,
)
from server.services.figure_mechanism_layout import (
    mechanism_connection_labels_svg, mechanism_connections_svg,
    mechanism_frames_svg, mechanism_layout, mechanism_runtime_glyph_svg,
)
from server.utils.atomic_write import atomic_write_json


def _context(
    project_path: str, artifact_name: str,
) -> tuple[Path, Path, dict[str, Any]]:
    root = Path(project_path).expanduser().resolve()
    storyboard = load_selected_storyboard(root, artifact_name)
    selected = next(
        item for item in storyboard["candidates"]
        if item["id"] == storyboard["selected_id"]
    )
    directory = root / ".merak" / "figure-drafts" / artifact_name
    return root, directory, canvas_layout(selected)


def _fallback_score(
    candidate: dict[str, Any], visual_scores: dict[str, Any],
) -> float:
    try:
        return float(visual_scores.get(str(candidate["id"]), float("-inf")))
    except (TypeError, ValueError):
        return float("-inf")


def _select_mechanism_layout(
    storyboard: dict[str, Any], selected_canvas: dict[str, Any],
    mechanism_ir: dict[str, Any],
) -> tuple[dict[str, Any], str, str]:
    selected_id = str(storyboard["selected_id"])
    selected = next(
        item for item in storyboard["candidates"] if item["id"] == selected_id
    )
    review = storyboard.get("visual_review")
    scores = (
        review.get("scores")
        if isinstance(review, dict) and isinstance(review.get("scores"), dict)
        else {}
    )
    alternatives = [
        item for item in storyboard["candidates"] if item["id"] != selected_id
    ]
    alternatives.sort(key=lambda item: _fallback_score(item, scores), reverse=True)
    expected_regions = {str(item["id"]) for item in selected_canvas["regions"]}
    selected_error: ValueError | None = None
    for candidate in [selected, *alternatives]:
        candidate_canvas = canvas_layout(candidate)
        if {str(item["id"]) for item in candidate_canvas["regions"]} != expected_regions:
            continue
        try:
            layout = mechanism_layout(candidate_canvas, mechanism_ir)
        except ValueError as error:
            if candidate["id"] == selected_id:
                selected_error = error
            continue
        candidate_id = str(candidate["id"])
        layout["storyboard_selected_id"] = selected_id
        layout["storyboard_candidate_id"] = candidate_id
        if candidate_id != selected_id:
            layout["layout_fallback"] = {
                "from": selected_id, "to": candidate_id,
                "reason": str(selected_error or "selected layout lacks mechanism capacity"),
            }
        return layout, selected_id, candidate_id
    if selected_error is not None:
        raise selected_error
    raise ValueError("no storyboard candidate can place the mechanism primitives")


def _start_canvas_draft(
    root: Path, artifact_name: str, layout: dict[str, Any], candidate_id: str,
) -> list[str]:
    begin_figure_svg_draft(
        artifact_name, opening_svg(layout, artifact_name), str(root),
        storyboard_candidate_id=candidate_id,
    )
    renderers = (
        ("mechanism_connections", mechanism_connections_svg),
        ("canvas_region_headers", region_header_svg),
        ("mechanism_frames", mechanism_frames_svg),
        ("mechanism_connection_labels", mechanism_connection_labels_svg),
    )
    for fragment_id, render in renderers:
        append_figure_svg_fragment(
            artifact_name, fragment_id, render(layout), str(root),
        )
    runtime_primitives = []
    for item in layout["primitive_boxes"]:
        if not item.get("runtime_type"):
            continue
        append_figure_svg_fragment(
            artifact_name, item["id"],
            mechanism_runtime_glyph_svg(layout, item["id"]), str(root),
        )
        runtime_primitives.append(item["id"])
    return runtime_primitives


def _persist_canvas_contract(
    directory: Path, layout: dict[str, Any], mechanism_ir: dict[str, Any],
) -> None:
    atomic_write_json(directory / "canvas-layout.json", layout)
    atomic_write_json(directory / "mechanism-ir.json", mechanism_ir)
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["canvas_layout_schema"] = MECHANISM_CANVAS_SCHEMA
    atomic_write_json(manifest_path, manifest)


def _prepared_canvas_payload(
    root: Path, directory: Path, artifact_name: str, layout: dict[str, Any],
    mechanism_ir: dict[str, Any], required_labels: list[str],
    selected_id: str, candidate_id: str, runtime_primitives: list[str],
) -> dict[str, Any]:
    runtime_ids = set(runtime_primitives)
    return {
        "status": "prepared", "artifact_name": artifact_name,
        "canvas_path": str((directory / "canvas-layout.json").relative_to(root)),
        "minimum_font_units": layout["minimum_font_units"],
        "regions": layout["regions"],
        "primitives": [{
            "id": item["id"], "region_id": item["region_id"],
            "visual_form": item["visual_form"], "public_label": item["public_label"],
            "glyph_width": item["glyph_width"], "glyph_height": item["glyph_height"],
        } for item in layout["primitive_boxes"] if item["id"] not in runtime_ids],
        "runtime_primitives": runtime_primitives,
        "flows": mechanism_ir["flows"],
        "required_mechanism_labels": required_labels,
        "storyboard_selected_id": selected_id,
        "storyboard_candidate_id": candidate_id,
        "layout_fallback": layout.get("layout_fallback"),
        "instruction": (
            "Author each primitive as vector geometry only in local coordinates "
            "0..glyph_width and 0..glyph_height. Do not add text, titles, panels, "
            "markers, ports, connectors, or runtime glyphs. The runtime owns every "
            "label, subitem, object box, scientific relation, and typed synthesis/readout."
        ),
    }


def prepare_figure_svg_canvas(
    artifact_name: str, mechanism_ir: dict[str, Any], project_path: str = "",
) -> str:
    """Start object-level deterministic geometry from a typed scientific mechanism."""
    root, directory, canvas = _context(project_path, artifact_name)
    regions = {str(item["id"]) for item in canvas["regions"]}
    normalized_ir = validate_mechanism_ir(mechanism_ir, regions)
    required_labels = required_mechanism_labels(root, artifact_name)
    validate_required_mechanisms(normalized_ir, required_labels)
    storyboard = load_selected_storyboard(root, artifact_name)
    layout, selected_id, candidate_id = _select_mechanism_layout(
        storyboard, canvas, normalized_ir,
    )
    runtime_primitives = _start_canvas_draft(
        root, artifact_name, layout, candidate_id,
    )
    _persist_canvas_contract(directory, layout, normalized_ir)
    payload = _prepared_canvas_payload(
        root, directory, artifact_name, layout, normalized_ir, required_labels,
        selected_id, candidate_id, runtime_primitives,
    )
    return json.dumps(payload, ensure_ascii=False)


def _primitive_content(fragment: str) -> list[ET.Element]:
    value = str(fragment or "").strip()
    if not value or "<svg" in value or "</svg>" in value:
        raise ValueError("region_svg must contain local SVG children, not an SVG root")
    if "<style" in value or "!important" in value:
        raise ValueError("region_svg cannot contain global styles")
    try:
        wrapper = ET.fromstring('<g xmlns="http://www.w3.org/2000/svg">' + value + "</g>")
    except ET.ParseError as error:
        raise ValueError(f"region_svg is malformed: {error}") from error
    if not list(wrapper):
        raise ValueError("region_svg must contain visible scientific geometry")
    for element in wrapper.iter():
        tag = element.tag.rsplit("}", 1)[-1].casefold()
        if tag in {"text", "tspan", "textpath"}:
            raise ValueError("primitive_svg cannot contain text; runtime owns publication labels")
        if tag == "marker":
            raise ValueError("primitive_svg cannot contain markers; runtime owns arrowheads")
        for raw_name, raw_value in element.attrib.items():
            name = raw_name.rsplit("}", 1)[-1].casefold()
            value = str(raw_value).casefold()
            if name in {"marker", "marker-start", "marker-mid", "marker-end"} or "marker-" in value:
                raise ValueError("primitive_svg cannot contain markers; runtime owns arrowheads")
            if name in {"data-connector", "data-port", "data-from", "data-to"}:
                raise ValueError(
                    "primitive_svg cannot contain connectors or ports; runtime owns relations"
                )
            if name in {"id", "class", "role", "data-role"}:
                tokens = {
                    token for token in value.replace("_", "-").split("-") if token
                }
                if tokens & {
                    "connector", "connection", "arrow", "arrowhead", "port",
                    "edge", "flow", "link", "relation",
                }:
                    raise ValueError(
                        "primitive_svg cannot contain connectors or ports; runtime owns relations"
                    )
    return list(wrapper)


def _wrapped_primitive(
    primitive_id: str, primitive_svg: str, box: dict[str, Any],
) -> str:
    children = _primitive_content(primitive_svg)
    inner = "".join(ET.tostring(item, encoding="unicode") for item in children)
    return (
        f'<g id="{primitive_id}" clip-path="url(#primitive-clip-{primitive_id})">'
        f'<g transform="translate({box["glyph_x"]} {box["glyph_y"]})">'
        f'{inner}</g></g>'
    )


def _primitive_box(layout: dict[str, Any], primitive_id: str) -> dict[str, Any]:
    try:
        return next(item for item in layout["primitive_boxes"] if item["id"] == primitive_id)
    except StopIteration as error:
        raise ValueError(f"primitive_id is not declared by mechanism_ir: {primitive_id}") from error


def append_figure_canvas_primitive(
    artifact_name: str, primitive_id: str, primitive_svg: str,
    project_path: str = "",
) -> str:
    """Place one text-free domain glyph inside its runtime-owned object box."""
    root, directory, _canvas = _context(project_path, artifact_name)
    layout = json.loads((directory / "canvas-layout.json").read_text(encoding="utf-8"))
    box = _primitive_box(layout, primitive_id)
    return append_figure_svg_fragment(
        artifact_name, primitive_id,
        _wrapped_primitive(primitive_id, primitive_svg, box),
        str(root),
    )


def replace_figure_canvas_primitive(
    artifact_name: str, primitive_id: str, primitive_svg: str,
    project_path: str = "",
) -> str:
    """Repair one domain glyph without changing runtime scientific geometry."""
    root, directory, _canvas = _context(project_path, artifact_name)
    layout = json.loads((directory / "canvas-layout.json").read_text(encoding="utf-8"))
    box = _primitive_box(layout, primitive_id)
    return replace_figure_svg_fragment(
        artifact_name, primitive_id,
        _wrapped_primitive(primitive_id, primitive_svg, box),
        str(root),
    )


def refresh_figure_canvas_runtime(
    artifact_name: str, project_path: str = "",
) -> str:
    """Refresh code-owned labels and routes without regenerating model glyphs."""
    root, directory, _canvas = _context(project_path, artifact_name)
    layout = json.loads((directory / "canvas-layout.json").read_text(encoding="utf-8"))
    replacements = {
        "mechanism_connections": mechanism_connections_svg(layout),
        "canvas_region_headers": region_header_svg(layout),
        "mechanism_frames": mechanism_frames_svg(layout),
        "mechanism_connection_labels": mechanism_connection_labels_svg(layout),
    }
    for item in layout["primitive_boxes"]:
        if item.get("runtime_type"):
            replacements[item["id"]] = mechanism_runtime_glyph_svg(
                layout, item["id"],
            )
    for fragment_id, fragment in replacements.items():
        replace_figure_svg_fragment(
            artifact_name, fragment_id, fragment, str(root),
        )
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["canvas_layout_schema"] = MECHANISM_CANVAS_SCHEMA
    atomic_write_json(manifest_path, manifest)
    finalized = json.loads(finalize_figure_svg_draft(artifact_name, str(root)))
    return json.dumps({
        **finalized, "status": "runtime_layers_refreshed",
        "artifact_name": artifact_name,
        "refreshed_fragments": list(replacements),
    }, ensure_ascii=False)


def finalize_figure_svg_canvas(
    artifact_name: str, project_path: str = "",
) -> str:
    """Require every selected storyboard region before assembling the hybrid SVG."""
    root, directory, _canvas = _context(project_path, artifact_name)
    layout = json.loads((directory / "canvas-layout.json").read_text(encoding="utf-8"))
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    present = {
        str(name).split("_", 1)[-1].removesuffix(".svgfrag")
        for name in manifest.get("parts") or []
    }
    missing = [item["id"] for item in layout["primitive_boxes"] if item["id"] not in present]
    if missing:
        raise ValueError("canvas primitives are missing: " + ", ".join(missing))
    return finalize_figure_svg_draft(artifact_name, str(root))
