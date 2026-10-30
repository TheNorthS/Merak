"""Render an authored Excalidraw scene without ambiguous packaged dependencies."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Any

from ..utils.atomic_write import atomic_write_json
from .process_runner import run_process


class ExcalidrawSceneError(ValueError):
    """Raised when a model-authored scene cannot be rendered faithfully."""


def _renderer_command() -> tuple[str, Path]:
    if getattr(sys, "frozen", False):
        raise ExcalidrawSceneError(
            "Excalidraw rendering is unavailable in the packaged backend: "
            "the Rough.js renderer is not embedded. Choose a supported figure "
            "backend; installing system Node.js will not repair this package."
        )
    renderer = Path(__file__).resolve().parents[2] / "scripts" / "render-excalidraw.cjs"
    if not renderer.is_file():
        raise ExcalidrawSceneError(f"Bundled Excalidraw renderer is missing: {renderer}")
    node = shutil.which("node")
    if not node:
        raise ExcalidrawSceneError("Node.js is required for the source Rough.js renderer.")
    return node, renderer


async def render_scene(
    scene: dict[str, Any],
    *,
    source_path: str | Path,
    svg_path: str | Path,
    pdf_path: str | Path,
    png_path: str | Path,
) -> dict[str, Any]:
    """Render variants from one scene or fail before writing when unsupported."""
    node, renderer = _renderer_command()
    source = Path(source_path).expanduser().resolve()
    svg = Path(svg_path).expanduser().resolve()
    pdf = Path(pdf_path).expanduser().resolve()
    png = Path(png_path).expanduser().resolve()
    source.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(source, scene)

    try:
        process = await run_process(
            [node, str(renderer), str(source), str(svg)],
            timeout=30,
        )
    except TimeoutError as exc:
        raise ExcalidrawSceneError(
            "Rough.js Excalidraw rendering timed out after 30 seconds."
        ) from exc
    stdout = process.stdout or b""
    stderr = process.stderr or b""
    if process.returncode != 0 or not svg.is_file() or svg.stat().st_size == 0:
        detail = (stderr or stdout).decode("utf-8", errors="replace")[:1200]
        raise ExcalidrawSceneError(f"Rough.js Excalidraw rendering failed: {detail}")

    try:
        import fitz

        svg_document = fitz.open(str(svg))
        pdf_bytes = svg_document.convert_to_pdf()
        pdf_document = fitz.open("pdf", pdf_bytes)
        pdf_document.save(str(pdf))
        page = pdf_document[0]
        scale = max(1.5, 1800.0 / max(1.0, page.rect.width))
        pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        pixmap.save(str(png))
        width, height = pixmap.width, pixmap.height
        pdf_document.close()
        svg_document.close()
    except Exception as exc:
        raise ExcalidrawSceneError(f"SVG conversion to PDF/PNG failed: {exc}") from exc

    for path in (source, svg, pdf, png):
        if not path.is_file() or path.stat().st_size == 0:
            raise ExcalidrawSceneError(f"Renderer did not persist required artifact: {path}")
    return {
        "source": str(source),
        "svg": str(svg),
        "pdf": str(pdf),
        "png": str(png),
        "width": width,
        "height": height,
    }
