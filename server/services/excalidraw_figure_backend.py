"""Validate and render one source-grounded Excalidraw scientific scene."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable, Optional

from .excalidraw_scene_rendering import render_scene

from .figure_models import FigureResult, FigureType


AppendReview = Callable[[Path, dict[str, Any]], list[dict[str, Any]]]


def _save_review(
    append_review: AppendReview, path: Path, status: str,
    issues: list[str], content_sha256: str,
) -> list[dict[str, Any]]:
    return append_review(path, {
        "status": status, "issues": list(dict.fromkeys(issues)),
        "content_sha256": content_sha256, "reviewed_at": time.time(),
        "checks": [
            "text_fit", "shape_overlap", "connector_routing",
            "canvas_occupancy", "source_mapping", "raster_legibility",
        ],
    })


def _scene_and_digest(code: str, normalize_scene: Any) -> tuple[dict[str, Any], str]:
    scene = normalize_scene(code)
    normalized = json.dumps(scene, ensure_ascii=False, sort_keys=True)
    return scene, hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _source_mapping_issues(
    scene: dict[str, Any], metadata: dict[str, Any], project_root: Path,
    enforce_mappings: bool, verify_mappings: Any,
) -> tuple[list[dict[str, Any]], list[str]]:
    mappings = [
        dict(item) for item in metadata.get("element_mappings") or []
        if isinstance(item, dict)
    ]
    issues: list[str] = []
    if enforce_mappings and str(metadata.get("scientific_role") or "") == "method":
        if not mappings:
            issues.append(
                "method architecture requires element_mappings to real code, protocol, "
                "formula, or experiment-contract sources"
            )
        else:
            issues.extend(verify_mappings(scene, mappings, project_root))
    return mappings, issues


def _validation_issues(
    scene: dict[str, Any], metadata: dict[str, Any], project_root: Path,
    enforce_mappings: bool, layout_issues: Any, scene_text: Any,
    verify_mappings: Any,
) -> tuple[list[dict[str, Any]], list[str]]:
    issues = list(layout_issues(scene))
    labels = [
        " ".join(line.casefold().split())
        for line in scene_text(scene).splitlines() if line.strip()
    ]
    generic = {
        "input", "data", "model", "method", "process", "output", "result",
        "input data", "model architecture", "proposed method",
    }
    if labels and all(label in generic for label in labels):
        issues.append("scene uses only generic Input/Model/Output-style labels")
    mappings, mapping_issues = _source_mapping_issues(
        scene, metadata, project_root, enforce_mappings, verify_mappings,
    )
    issues.extend(mapping_issues)
    return mappings, list(dict.fromkeys(issues))


def _failed(
    error: str, *, source: Path | None = None, scene: dict[str, Any] | None = None,
    rounds: list[dict[str, Any]] | None = None,
) -> FigureResult:
    return FigureResult(
        False, FigureType.EXCALIDRAW,
        source_path=str(source) if source and source.exists() else None,
        code=json.dumps(scene, ensure_ascii=False, indent=2) if scene else None,
        error=error,
        metadata={"visual_review_rounds": rounds} if rounds is not None else None,
    )


def _provenance(
    metadata: dict[str, Any], mappings: list[dict[str, Any]],
) -> tuple[list[str], list[str]]:
    symbols = sorted({
        str(item.get("source_symbol") or "").strip()
        for item in mappings if str(item.get("source_symbol") or "").strip()
    })
    artifacts = sorted({
        *(
            str(item).strip() for item in metadata.get("source_data") or []
            if str(item).strip()
        ),
        *(
            str(item.get("source_path") or "").strip()
            for item in mappings if str(item.get("source_path") or "").strip()
        ),
    })
    return symbols, artifacts


async def generate_excalidraw(
    code: str, output_dir: str, artifact_stem: str, metadata: Optional[dict],
    *, enforce_mappings: bool, append_review: AppendReview,
) -> FigureResult:
    from .excalidraw_renderer import (
        ExcalidrawSceneError, normalize_scene,
        scene_layout_issues, scene_text, verify_element_mappings,
    )
    from .figure_artifacts import figure_artifact_registry

    value = dict(metadata or {})
    directory = Path(output_dir).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    root = figure_artifact_registry.project_root(directory)
    review = root / ".merak" / "figure-reviews" / f"{artifact_stem}.json"
    review.parent.mkdir(parents=True, exist_ok=True)
    if not code.strip():
        return _failed(
            "Excalidraw generation requires complete scene JSON authored from project artifacts; "
            "a prose description cannot define scientific geometry."
        )
    try:
        scene, digest = _scene_and_digest(code, normalize_scene)
    except ExcalidrawSceneError as exc:
        digest = hashlib.sha256(code.encode("utf-8", errors="replace")).hexdigest()
        _save_review(append_review, review, "failed", [str(exc)], digest)
        return _failed(f"Excalidraw visual review failed: {exc}")
    mappings, issues = _validation_issues(
        scene, value, root, enforce_mappings,
        scene_layout_issues, scene_text, verify_element_mappings,
    )
    if issues:
        rounds = _save_review(append_review, review, "failed", issues, digest)
        return _failed(
            "Excalidraw visual review failed; revise the same artifact_name and retry: "
            + "; ".join(issues), scene=scene, rounds=rounds,
        )
    source, svg, pdf, png = (
        directory / f"{artifact_stem}{suffix}"
        for suffix in (".excalidraw", ".svg", ".pdf", ".png")
    )
    try:
        rendered = await render_scene(
            scene, source_path=source, svg_path=svg, pdf_path=pdf, png_path=png)
        raster_issues = figure_artifact_registry.raster_layout_issues(png)
        if rendered["width"] < 1000 or rendered["height"] < 450:
            raster_issues.append(
                f"raster preview is too small ({rendered['width']}x{rendered['height']})"
            )
        if raster_issues:
            rounds = _save_review(append_review, review, "failed", raster_issues, digest)
            return _failed(
                "Excalidraw render review failed; revise the same artifact_name and retry: "
                + "; ".join(raster_issues), source=source, scene=scene, rounds=rounds,
            )
    except ExcalidrawSceneError as exc:
        rounds = _save_review(append_review, review, "failed", [str(exc)], digest)
        return _failed(str(exc), source=source, rounds=rounds)
    rounds = _save_review(append_review, review, "passed", [], digest)
    symbols, artifacts = _provenance(value, mappings)
    return FigureResult(
        True, FigureType.EXCALIDRAW, output_path=str(pdf), source_path=str(source),
        code=json.dumps(scene, ensure_ascii=False, indent=2),
        install_hint=f"IDE preview: {png}",
        metadata={
            "generator": "model-excalidraw",
            "skill": value.get("generator_skill") or value.get("skill") or "",
            "generator_skill": value.get("generator_skill") or "",
            "skill_invocation_verified": bool(value.get("skill_invocation_verified")),
            "renderer": "roughjs-excalidraw", "model_authored": True,
            "render_status": "rendered",
            "source_faithful": "same-scene-geometry-style-and-labels",
            "code_symbols": symbols, "source_artifacts": artifacts,
            "element_mappings": mappings, "visual_review_rounds": rounds,
            "_rendered_variant_paths": {
                "excalidraw": str(source), "svg": str(svg),
                "pdf": str(pdf), "png": str(png),
            },
        },
    )
