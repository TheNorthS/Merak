"""Faithfully convert one SVG source into PDF and PNG variants."""

from __future__ import annotations

import os
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from ..utils.atomic_write import atomic_replace_file
from .svg_marker_fallback import expand_end_markers


def _converter_svg(source: bytes) -> bytes:
    try:
        from .figure_svg_sources import (
            _inline_svg_vector_class_styles, _normalize_svg_marker_viewports,
        )

        normalized = _inline_svg_vector_class_styles(
            _normalize_svg_marker_viewports(source.decode("utf-8")),
        )
        root = ET.fromstring(normalized.encode("utf-8"))
        root.set(
            "style",
            str(root.attrib.get("style") or "").replace(
                "color-scheme: light dark", "color-scheme: light",
            ),
        )
        expand_end_markers(root)
        parents = {
            child: parent for parent in root.iter() for child in list(parent)
        }
        for switch in [
            element for element in root.iter()
            if element.tag.rsplit("}", 1)[-1] == "switch"
        ]:
            fallback = next((
                child for child in list(switch)
                if child.tag.rsplit("}", 1)[-1] == "text"
            ), None)
            parent = parents.get(switch)
            if fallback is None or parent is None:
                continue
            index = list(parent).index(switch)
            switch.remove(fallback)
            parent.remove(switch)
            parent.insert(index, fallback)
        return ET.tostring(root, encoding="utf-8", xml_declaration=True)
    except ET.ParseError:
        return source


def _temporary(target: Path) -> Path:
    return target.with_name(
        f".{target.name}.{os.getpid()}.{threading.get_ident()}."
        f"{time.time_ns()}.merak-part{target.suffix}"
    )


def convert_svg_variants(
    svg_path: str | Path, pdf_path: str | Path, png_path: str | Path,
) -> tuple[bool, str]:
    svg, pdf, png = (
        Path(value).expanduser().resolve()
        for value in (svg_path, pdf_path, png_path)
    )
    temporary_pdf, temporary_png = _temporary(pdf), _temporary(png)
    try:
        import fitz

        svg_document = fitz.open(stream=_converter_svg(svg.read_bytes()), filetype="svg")
        pdf_document = fitz.open("pdf", svg_document.convert_to_pdf())
        pdf_document.save(str(temporary_pdf))
        page = pdf_document[0]
        scale = max(1.5, 1800.0 / max(1.0, page.rect.width))
        page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False).save(str(temporary_png))
        pdf_document.close()
        svg_document.close()
        atomic_replace_file(temporary_pdf, pdf)
        atomic_replace_file(temporary_png, png)
    except Exception as exc:
        temporary_pdf.unlink(missing_ok=True)
        temporary_png.unlink(missing_ok=True)
        return False, f"SVG conversion to PDF/PNG failed: {exc}"
    if not all(path.is_file() and path.stat().st_size > 0 for path in (svg, pdf, png)):
        return False, "SVG conversion did not persist all PDF/PNG variants."
    return True, ""
