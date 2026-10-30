"""Deterministic FigureSpec validation and same-source variant rendering."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable, Optional

from ..utils.atomic_write import atomic_write_text
from .figure_models import FigureResult, FigureType


AppendReview = Callable[[Path, dict[str, Any]], list[dict[str, Any]]]


def _parse(code: str) -> tuple[dict[str, Any] | None, str, str]:
    if not code.strip():
        return None, "", (
            "FigureSpec generation requires a complete structured JSON spec. "
            "A prose description cannot define publication geometry."
        )
    try:
        payload = json.loads(code)
    except json.JSONDecodeError as exc:
        return None, "", f"FigureSpec source is not valid JSON: {exc}"
    if not isinstance(payload, dict):
        return None, "", "FigureSpec source must be one JSON object."
    normalized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    return payload, normalized, ""


def _review(
    append_review: AppendReview, path: Path, metadata: dict[str, Any],
    status: str, issues: list[str], source_hash: str, render_hash: str = "",
) -> list[dict[str, Any]]:
    return append_review(path, {
        "status": status, "issues": list(dict.fromkeys(issues)),
        "content_sha256": source_hash, "render_sha256": render_hash,
        "reviewed_at": time.time(),
        "review_kind": (
            "enhanced_local_pixels"
            if str(metadata.get("visual_review_policy") or "").casefold()
            == "enhanced_local_pixels_required" else "deterministic_same_render"
        ),
        "checks": [
            "schema_validation", "text_fit", "node_overlap", "canvas_bounds",
            "edge_integrity", "source_mapping", "raster_legibility",
            "contrast_and_visual_differentiation", "canvas_edge_safety",
            "five_second_node_edge_budget", "group_boundary_and_overlap",
            "connector_label_brevity",
        ],
    })


def _validation(
    payload: dict[str, Any], metadata: dict[str, Any], root: Path,
    renderer: Any, registry: Any, verify_mappings: Any,
) -> tuple[list[dict[str, Any]], list[str]]:
    issues = [str(item) for item in renderer.validate_spec(payload)]
    issues.extend(registry.figurespec_layout_issues_payload(payload))
    mappings = [
        dict(item) for item in metadata.get("element_mappings") or []
        if isinstance(item, dict)
    ]
    if str(metadata.get("scientific_role") or "") == "method":
        if not mappings:
            issues.append(
                "method FigureSpec requires element_mappings to project code, "
                "protocol, formula, or experiment-contract sources"
            )
        else:
            scene = {"elements": [
                {"id": str(node.get("id") or "")}
                for node in payload.get("nodes") or []
                if isinstance(node, dict) and str(node.get("id") or "")
            ]}
            issues.extend(verify_mappings(scene, mappings, root))
    return mappings, list(dict.fromkeys(issues))


def _failure(
    error: str, *, source: Path | None = None, code: str = "",
    rounds: list[dict[str, Any]] | None = None,
) -> FigureResult:
    return FigureResult(
        False, FigureType.FIGURESPEC,
        source_path=str(source) if source else None, code=code or None,
        error=error,
        metadata={"visual_review_rounds": rounds} if rounds is not None else None,
    )


def _success(
    source: Path, svg: Path, pdf: Path, png: Path, code: str,
    metadata: dict[str, Any], mappings: list[dict[str, Any]],
    rounds: list[dict[str, Any]], source_hash: str, render_hash: str,
) -> FigureResult:
    symbols = sorted({
        str(item.get("source_symbol") or "").strip()
        for item in mappings if str(item.get("source_symbol") or "").strip()
    })
    return FigureResult(
        True, FigureType.FIGURESPEC, output_path=str(pdf), source_path=str(source),
        code=code, svg_content=svg.read_text(encoding="utf-8"),
        install_hint=f"IDE preview: {png}",
        metadata={
            "generator": "deterministic-figurespec",
            "skill": metadata.get("generator_skill") or metadata.get("skill") or "",
            "generator_skill": metadata.get("generator_skill") or "",
            "skill_invocation_verified": bool(metadata.get("skill_invocation_verified")),
            "renderer": "figurespec-v2", "render_status": "rendered",
            "source_faithful": "deterministic-json-to-svg-same-source",
            "model_authored": metadata.get("producer_kind") != "deterministic",
            "code_symbols": symbols,
            "element_mappings": mappings, "visual_review_rounds": rounds,
            "visual_review_source_sha256": source_hash,
            "visual_review_render_sha256": render_hash,
            "_rendered_variant_paths": {
                "json": str(source), "svg": str(svg),
                "pdf": str(pdf), "png": str(png),
            },
        },
    )


async def generate_figurespec(
    code: str, output_dir: str, artifact_stem: str, metadata: Optional[dict],
    *, load_renderer: Any, convert_variants: Any, append_review: AppendReview,
) -> FigureResult:
    from .excalidraw_renderer import verify_element_mappings
    from .figure_artifacts import figure_artifact_registry

    value = dict(metadata or {})
    payload, normalized, parse_error = _parse(code)
    if payload is None:
        return _failure(parse_error)
    source_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    directory = Path(output_dir).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    root = figure_artifact_registry.project_root(directory)
    review = root / ".merak" / "figure-reviews" / f"{artifact_stem}.json"
    review.parent.mkdir(parents=True, exist_ok=True)
    try:
        renderer = load_renderer()
        mappings, issues = _validation(
            payload, value, root, renderer,
            figure_artifact_registry, verify_element_mappings,
        )
    except Exception as exc:
        rounds = _review(append_review, review, value, "failed", [str(exc)], source_hash)
        return _failure(
            f"FigureSpec renderer validation failed: {exc}", rounds=rounds,
        )
    if issues:
        rounds = _review(append_review, review, value, "failed", issues, source_hash)
        return _failure(
            "FigureSpec visual review failed; revise the same artifact_name and retry: "
            + "; ".join(issues), code=normalized, rounds=rounds,
        )
    source, svg, pdf, png = (
        directory / f"{artifact_stem}{suffix}"
        for suffix in (".json", ".svg", ".pdf", ".png")
    )
    atomic_write_text(source, normalized)
    try:
        atomic_write_text(svg, renderer.render_svg(payload))
    except Exception as exc:
        rounds = _review(
            append_review, review, value, "failed",
            [f"SVG rendering failed: {exc}"], source_hash,
        )
        return _failure(
            f"FigureSpec SVG rendering failed: {exc}",
            source=source, code=normalized, rounds=rounds,
        )
    converted, conversion_error = convert_variants(svg, pdf, png)
    if not converted:
        rounds = _review(
            append_review, review, value, "failed", [conversion_error], source_hash,
        )
        return _failure(
            conversion_error, source=source, code=normalized, rounds=rounds,
        )
    raster_issues = figure_artifact_registry.raster_visual_quality_issues(png)
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    render_hash = hashlib.sha256(png.read_bytes()).hexdigest()
    if raster_issues:
        rounds = _review(
            append_review, review, value, "failed", raster_issues,
            source_hash, render_hash,
        )
        return _failure(
            "FigureSpec render review failed; revise the same artifact_name and retry: "
            + "; ".join(raster_issues), source=source, code=normalized, rounds=rounds,
        )
    rounds = _review(
        append_review, review, value, "passed", [], source_hash, render_hash,
    )
    return _success(
        source, svg, pdf, png, normalized, value, mappings,
        rounds, source_hash, render_hash,
    )
