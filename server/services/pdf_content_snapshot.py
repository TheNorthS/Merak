"""Fingerprint visible PDF content without volatile document IDs or creation dates."""

import hashlib
import json
from pathlib import Path


def pdf_content_snapshot(path: Path) -> dict:
    import fitz

    digest = hashlib.sha256()
    try:
        with fitz.open(path) as document:
            if not document.page_count or document.needs_pass:
                raise ValueError("PDF is empty or encrypted")
            for page in document:
                raster = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                digest.update(json.dumps([list(page.rect), raster.width, raster.height, page.get_text()],
                    ensure_ascii=False).encode())
                digest.update(raster.samples)
            pages = document.page_count
    except (OSError, RuntimeError, ValueError) as error:
        return {"kind": "pdf_content", "sha256": "", "pages": 0, "error": str(error)}
    return {"kind": "pdf_content", "sha256": digest.hexdigest(), "pages": pages}
