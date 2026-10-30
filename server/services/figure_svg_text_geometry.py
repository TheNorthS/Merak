"""Rendered PDF text geometry diagnostics for model-authored SVG figures."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _spans(page: Any, fitz: Any) -> list[tuple[str, Any, int, int]]:
    spans = []
    for block_index, block in enumerate(page.get_text("dict").get("blocks") or []):
        for line_index, line in enumerate(block.get("lines") or []):
            for span in line.get("spans") or []:
                label = " ".join(str(span.get("text") or "").split())
                if label:
                    spans.append((
                        label, fitz.Rect(span["bbox"]), block_index, line_index,
                    ))
    return spans


def rendered_svg_text_geometry(pdf_path: str | Path) -> list[dict[str, object]]:
    """Report severe text collisions and clipped labels in the actual PDF variant."""
    import fitz

    document = fitz.open(str(pdf_path))
    findings: list[dict[str, object]] = []
    try:
        for page_number, page in enumerate(document):
            spans = _spans(page, fitz)
            safe = fitz.Rect(2, 2, page.rect.width - 2, page.rect.height - 2)
            for label, bounds, _block, _line in spans:
                if not safe.contains(bounds):
                    findings.append({
                        "kind": "clipped_text", "page": page_number + 1,
                        "labels": [label[:100]],
                        "bbox": [round(value, 1) for value in bounds],
                    })
            for index, (left_label, left, left_block, left_line) in enumerate(spans):
                for right_label, right, right_block, right_line in spans[index + 1:]:
                    # One SVG <text> element may become several PDF spans when
                    # subscripts, superscripts, or font fallbacks are present.
                    # Those spans intentionally share geometry and must be
                    # treated as one text line, not as colliding labels.
                    if left_block == right_block and left_line == right_line:
                        continue
                    overlap = (left & right).get_area()
                    smaller = min(left.get_area(), right.get_area())
                    if smaller <= 0 or overlap / smaller < 0.12:
                        continue
                    findings.append({
                        "kind": "text_collision", "page": page_number + 1,
                        "labels": [left_label[:100], right_label[:100]],
                        "overlap_fraction": round(overlap / smaller, 2),
                    })
    finally:
        document.close()
    return findings[:16]
