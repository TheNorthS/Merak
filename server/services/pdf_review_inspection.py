"""Bounded PDF raster and layout inspection for manuscript review."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import structlog


logger = structlog.get_logger()


def _base_report(source: Path) -> dict[str, object]:
    return {
        "schema": 1, "pdf_path": str(source),
        "pdf_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "pages": [], "page_count": 0, "renderer": "",
        "rendered_page_previews": [], "contact_sheet_paths": [],
        "document_findings": [],
    }


def _text_geometry(
    page: Any, fitz: Any,
) -> tuple[list[tuple[Any, str]], list[tuple[Any, str, int]], list[float]]:
    blocks: list[tuple[Any, str]] = []
    line_boxes: list[tuple[Any, str, int]] = []
    font_sizes: list[float] = []
    for block_index, block in enumerate(page.get_text("dict").get("blocks", [])):
        if int(block.get("type", 0)) != 0:
            continue
        lines: list[str] = []
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            text = "".join(str(span.get("text") or "") for span in spans).strip()
            if text:
                lines.append(text)
                line_boxes.extend(_visible_span_boxes(line, text, block_index, fitz))
            font_sizes.extend(
                float(span.get("size") or 0) for span in spans
                if float(span.get("size") or 0) > 0
            )
        text = " ".join(lines).strip()
        if text:
            blocks.append((fitz.Rect(block.get("bbox") or (0, 0, 0, 0)), text))
    return blocks, line_boxes, font_sizes


def _visible_span_boxes(line: dict[str, Any], text: str, owner: int, fitz: Any) -> list[tuple[Any, str, int]]:
    """Test occupied span geometry, not the whitespace envelope of an equation.

    Fraction numerators and neighboring normal text may share a broad line
    envelope with a denominator even when no glyphs collide. Keeping each
    non-blank span separately removes that envelope false positive without
    exempting either mathematics or other text from actual collision checks.
    """
    spans = [span for span in line.get("spans", []) if str(span.get("text") or "").strip()]
    if spans and all(span.get("bbox") and len(span["bbox"]) == 4 for span in spans):
        return [(fitz.Rect(span["bbox"]), str(span["text"]).strip(), owner) for span in spans]
    return [(fitz.Rect(line.get("bbox") or (0, 0, 0, 0)), text, owner)]


def _image_geometry(page: Any) -> list[Any]:
    rectangles: list[Any] = []
    for image in page.get_images(full=True):
        try:
            rectangles.extend(page.get_image_rects(image[0]))
        except Exception:
            continue
    return rectangles


def _content_margins(
    fitz: Any, width: float, height: float,
    text_blocks: list[tuple[Any, str]], image_rects: list[Any],
) -> dict[str, float]:
    rectangles = [rect for rect, _text in text_blocks if not rect.is_empty]
    rectangles.extend(rect for rect in image_rects if not rect.is_empty)
    content = None
    for rectangle in rectangles:
        content = fitz.Rect(rectangle) if content is None else content | rectangle
    if content is None:
        return {side: round(value, 1) for side, value in {
            "left": width, "top": height, "right": width, "bottom": height,
        }.items()}
    return {
        "left": round(max(0.0, float(content.x0)), 1),
        "top": round(max(0.0, float(content.y0)), 1),
        "right": round(max(0.0, width - float(content.x1)), 1),
        "bottom": round(max(0.0, height - float(content.y1)), 1),
    }


def _overlap_pairs(lines: list[tuple[Any, str, int]], *, page: Any = None) -> int:
    count = 0
    ordered = sorted(lines, key=lambda item: item[0].y0)
    for index, (left, _text, owner) in enumerate(ordered):
        for next_index in range(index + 1, len(ordered)):
            right, _right_text, other_owner = ordered[next_index]
            # Positive-area intersection requires overlap on both axes. The
            # remaining boxes start below this one once the y bound is reached.
            if right.y0 >= left.y1:
                break
            if owner == other_owner or right.x0 >= left.x1 or right.x1 <= left.x0:
                continue
            intersection = left & right
            if intersection.is_empty:
                continue
            smaller = min(max(1.0, float(left.get_area())), max(1.0, float(right.get_area())))
            if float(intersection.get_area()) / smaller >= 0.15:
                from .pdf_overlap_pixels import visible_vertical_gap
                if page is not None and visible_vertical_gap(page, left, right):
                    continue
                count += 1
    return count


def _layout_findings(
    height: float, blocks: list[tuple[Any, str]], fonts: list[float],
    images: list[Any], margins: dict[str, float], overlaps: int,
) -> tuple[str, list[str]]:
    ordered = sorted(blocks, key=lambda item: (float(item[0].y0), float(item[0].x0)))
    full_text = " ".join(text for _rect, text in ordered)
    findings: list[str] = []
    if len(full_text.strip()) < 10 and not images:
        findings.append("page appears blank or nearly blank")
    if fonts and min(fonts) < 5.5:
        findings.append(f"very small text detected ({min(fonts):.1f} pt)")
    near_edges = [side for side, value in margins.items() if value < 12.0]
    if near_edges:
        findings.append("content approaches the physical page edge: " + ", ".join(near_edges))
    if overlaps:
        findings.append(f"{overlaps} possible overlapping text-block pair(s)")
    if ordered and _possible_orphan(ordered[-1], height):
        findings.append("possible orphaned heading or short block near page bottom")
    return full_text, findings


def _possible_orphan(last_block: tuple[Any, str], height: float) -> bool:
    rectangle, text = last_block
    last_line = text.splitlines()[-1].strip()
    likely_heading = bool(
        last_line and len(last_line) <= 120
        and last_line[-1:].lower() not in {".", ",", ";", ":"}
        and not re.fullmatch(r"\d+", last_line)
    )
    return likely_heading and 0.75 * height <= float(rectangle.y0) <= 0.93 * height


def _inspect_page(page: Any, index: int, previews: Path, fitz: Any) -> dict[str, object]:
    from .publication_pdf_fonts import minimum_readable_font_pt, readable_font_findings
    width, height = float(page.rect.width), float(page.rect.height)
    blocks, lines, fonts = _text_geometry(page, fitz)
    images = _image_geometry(page)
    margins = _content_margins(fitz, width, height, blocks, images)
    full_text, findings = _layout_findings(
        height, blocks, fonts, images, margins, _overlap_pairs(lines, page=page),
    )
    preview_path = previews / f"page_{index + 1:03d}.png"
    page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False).save(str(preview_path))
    sorted_fonts = sorted(fonts)
    median_font = sorted_fonts[len(sorted_fonts) // 2] if sorted_fonts else 0.0
    return {
        "page": index + 1, "width_pt": round(width, 1), "height_pt": round(height, 1),
        "visible_text_chars": len(full_text), "text_blocks": len(blocks),
        "image_instances": len(images), "drawing_objects": len(page.get_drawings()),
        "minimum_font_pt": round(min(fonts), 1) if fonts else 0.0,
        'minimum_readable_font_pt': minimum_readable_font_pt(page),
        'readable_font_findings': readable_font_findings(page),
        "median_font_pt": round(median_font, 1), "content_margins_pt": margins,
        "top_text": full_text[:240], "bottom_text": full_text[-240:],
        "possible_layout_findings": findings, "preview_path": str(preview_path),
    }


def _contact_sheets(preview_paths: list[str], previews: Path) -> list[str]:
    from PIL import Image, ImageDraw, ImageOps

    paths: list[str] = []
    for sheet_index, start in enumerate(range(0, len(preview_paths), 20), start=1):
        batch = preview_paths[start:start + 20]
        cell_width, cell_height, columns = 260, 360, 4
        rows = (len(batch) + columns - 1) // columns
        sheet = Image.new("RGB", (columns * cell_width, rows * cell_height), "white")
        draw = ImageDraw.Draw(sheet)
        for offset, path in enumerate(batch):
            with Image.open(path) as page_image:
                thumbnail = ImageOps.contain(
                    page_image.convert("RGB"), (cell_width - 20, cell_height - 35),
                )
            x, y = (offset % columns) * cell_width, (offset // columns) * cell_height
            sheet.paste(thumbnail, (x + (cell_width - thumbnail.width) // 2, y + 22))
            draw.text((x + 8, y + 5), f"Page {start + offset + 1}", fill="black")
        contact_path = previews / f"contact_sheet_{sheet_index:03d}.png"
        sheet.save(contact_path)
        paths.append(str(contact_path))
    return paths


def _pymupdf_report(
    source: Path, previews: Path, page_limit: int, report: dict[str, object],
) -> dict[str, object]:
    import fitz

    document = fitz.open(str(source))
    count = len(document)
    pages = [_inspect_page(document[index], index, previews, fitz) for index in range(min(count, page_limit))]
    document.close()
    preview_paths = [str(page["preview_path"]) for page in pages]
    sizes = {(page["width_pt"], page["height_pt"]) for page in pages}
    report.update({
        "renderer": "pymupdf", "page_count": count, "pages": pages,
        "rendered_page_previews": preview_paths, "page_size_consistent": len(sizes) <= 1,
    })
    findings = report["document_findings"]
    if count > page_limit:
        findings.append(f"only the first {page_limit} of {count} pages were rasterized for the bounded visual review")
    if len(sizes) > 1:
        findings.append("inconsistent physical page sizes detected")
    if preview_paths:
        try:
            report["contact_sheet_paths"] = _contact_sheets(preview_paths, previews)
        except Exception as exc:
            findings.append(f"contact-sheet generation failed: {type(exc).__name__}")
    return report


def _pypdf_report(source: Path, page_limit: int, report: dict[str, object]) -> dict[str, object]:
    from pypdf import PdfReader

    reader = PdfReader(str(source))
    pages: list[dict[str, object]] = []
    sizes: set[tuple[float, float]] = set()
    for index, page in enumerate(reader.pages[:page_limit]):
        width, height = float(page.mediabox.width), float(page.mediabox.height)
        sizes.add((round(width, 1), round(height, 1)))
        text = page.extract_text() or ""
        pages.append({
            "page": index + 1, "width_pt": round(width, 1), "height_pt": round(height, 1),
            "visible_text_chars": len(text), "top_text": text[:240], "bottom_text": text[-240:],
            "possible_layout_findings": [
                "page rasterization unavailable; reviewer must open the PDF directly"
            ],
        })
    report.update({
        "renderer": "pypdf-layout-only", "page_count": len(reader.pages),
        "pages": pages, "page_size_consistent": len(sizes) <= 1,
    })
    report["document_findings"].append(
        "rendered previews unavailable; only PDF text and page geometry were extracted"
    )
    return report


def inspect_pdf_for_review(
    pdf_path: str | Path, *, preview_dir: str | Path, max_pages: int = 40,
) -> dict[str, object]:
    source = Path(pdf_path).expanduser().resolve()
    previews = Path(preview_dir).expanduser().resolve()
    if not source.is_file() or source.stat().st_size <= 0 or source.read_bytes()[:5] != b"%PDF-":
        raise ValueError(f"Invalid compiled PDF for review: {source}")
    previews.mkdir(parents=True, exist_ok=True)
    report = _base_report(source)
    try:
        return _pymupdf_report(source, previews, max(1, int(max_pages)), report)
    except Exception as exc:
        logger.warning(
            "PyMuPDF review rendering failed; falling back to pypdf",
            path=str(source), error=str(exc),
        )
        return _pypdf_report(source, max(1, int(max_pages)), report)
