"""Validate, bind, and register a rendered scientific figure result."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .figure_models import FigureResult, FigureType


EDITABLE_RENDER_TYPES = {
    FigureType.FIGURESPEC,
    FigureType.RICH_SVG,
    FigureType.MERMAID,
    FigureType.DRAWIO,
    FigureType.EXCALIDRAW,
}


def bind_rendered_variants(
    metadata: dict[str, Any], output_dir: str, registry: Any, sha256_path: Any,
) -> None:
    """Bind fresh producer variants before candidate validation or registration."""
    paths = dict(metadata.pop("_rendered_variant_paths", {}) or {})
    if not paths:
        return
    root = registry.project_root(output_dir)
    rendered: dict[str, str] = {}
    hashes: dict[str, str] = {}
    for variant, raw_path in paths.items():
        candidate = Path(str(raw_path)).expanduser().resolve()
        if not candidate.is_file() or candidate.stat().st_size == 0:
            continue
        try:
            relative = candidate.relative_to(root).as_posix()
        except ValueError:
            relative = candidate.as_posix()
        rendered[str(variant)] = relative
        hashes[str(variant)] = sha256_path(candidate)
    metadata.update({
        "rendered_variants": rendered,
        "rendered_variant_sha256": hashes,
        "preview_path": rendered.get("png", ""),
        "paper_vector_path": rendered.get("pdf") or rendered.get("svg") or "",
    })


def _existing(path: str | None) -> Path | None:
    candidate = Path(path).expanduser().resolve() if path else None
    return candidate if candidate and candidate.is_file() and candidate.stat().st_size > 0 else None


def _source_only_note(result: FigureResult, output: Path | None, source: Path | None) -> None:
    if output or not source or result.figure_type not in EDITABLE_RENDER_TYPES:
        return
    note = (
        "Editable source persisted, but no faithful renderer was available; "
        "no degraded preview was created."
    )
    result.install_hint = f"{result.install_hint} {note}".strip() if result.install_hint else note


def _register(
    result: FigureResult, description: str, output_dir: str,
    metadata: dict[str, Any], output: Path | None, source: Path | None,
    registry: Any,
) -> None:
    try:
        manifest, _entry = registry.record(
            output_dir=output_dir, figure_type=result.figure_type.value,
            description=description, output_path=str(output) if output else None,
            source_path=str(source) if source else None, metadata=metadata,
        )
        result.manifest_path = str(manifest)
    except Exception as exc:
        result.success = False
        result.error = f"Failed to persist figure manifest: {exc}"


def finalize_figure_result(
    result: FigureResult, description: str, output_dir: str,
    metadata: dict[str, Any], *, sha256_path: Any,
) -> FigureResult:
    from .figure_artifacts import figure_artifact_registry

    value = dict(metadata or {})
    bind_rendered_variants(value, output_dir, figure_artifact_registry, sha256_path)
    result.metadata = value
    output, source = _existing(result.output_path), _existing(result.source_path)
    result.output_path = str(output) if output else None
    result.source_path = str(source) if source else None
    _source_only_note(result, output, source)
    if result.success and not output and not source:
        result.success = False
        result.error = result.error or "Figure backend returned no persistent artifact."
        return result
    if result.success:
        _register(
            result, description, output_dir, value, output, source,
            figure_artifact_registry,
        )
    if result.success and not output and figure_artifact_registry._is_manuscript_asset(value):
        result.success = False
        result.error = result.error or (
            "The editable figure source was saved, but the required faithful paper "
            "renderer produced no PDF, SVG, or PNG output."
        )
    return result
