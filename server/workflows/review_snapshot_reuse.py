"""Preserve genuinely reviewed source/PDF/page pixels at a no-edit handoff.

Only an existing current, independently reviewed snapshot can produce a numbered
copy without recompiling. Any missing/stale proof returns to the print producer;
this service never grants review acceptance or re-signs model provenance.
"""

from __future__ import annotations

import hashlib
import shutil
import time
from pathlib import Path
from typing import Any

from ..services.paper_pdf_quality import validate_persisted_pdf_quality
from .review_audit import review_source_bundle
from .review_visual_artifact_evidence import (
    ReviewVisualContext, resolve_project_file, validate_reviewed_pixels, validate_snapshot,
)


def preserve_reviewed_snapshot(state: Any, request: Any, paper: Path) -> dict[str, Any] | None:
    """Copy an unchanged fully bound snapshot; never touch the current manuscript/PDF."""
    if request.original or not state.rounds or paper.name != "main.tex":
        return None
    root = Path(request.project_path).resolve()
    current_pdf = paper.with_suffix(".pdf")
    last = state.rounds[-1]
    visual = dict(last.visual_review)
    reviewed = next((dict(item) for item in reversed(state.pdf_snapshots)
                     if item.get("snapshot_path") == last.pdf_snapshot), None)
    source_hash, source_paths = review_source_bundle(root)
    if (reviewed is None or not last.has_complete_visual_review()
            or state.source_bundle_sha256 != source_hash
            or visual.get("_source_bundle_sha256") != source_hash
            or not current_pdf.is_file()
            or reviewed.get("pdf_sha256") != hashlib.sha256(current_pdf.read_bytes()).hexdigest()
            or visual.get("_pdf_sha256") != reviewed.get("pdf_sha256")
            or validate_persisted_pdf_quality(root)):
        return None
    context = ReviewVisualContext(root, {}, {}, visual, source_hash, source_paths, reviewed, reviewed)
    hashes = validate_snapshot(context, reviewed, "reviewed")
    validate_reviewed_pixels(context, hashes, hashes)
    if context.issues or not hashes.bundle or not hashes.content or not _complete_page_inventory(root, reviewed):
        return None
    original = resolve_project_file(root, reviewed["snapshot_path"])
    if original is None:
        return None
    destination = paper.parent / f"{paper.stem}_round{request.round_number}.pdf"
    if original != destination:
        shutil.copy2(original, destination)
    return {**reviewed, "round": request.round_number, "kind": "review_round",
            "reason": request.reason, "compiled_at": time.time(),
            "snapshot_path": destination.relative_to(root).as_posix(),
            "preserved_reviewed_snapshot": last.pdf_snapshot}


def _complete_page_inventory(root: Path, record: dict[str, Any]) -> bool:
    """A self-declared aggregate hash cannot substitute for actual full page coverage."""
    import fitz

    snapshot = resolve_project_file(root, record.get("snapshot_path"))
    if snapshot is None:
        return False
    try:
        with fitz.open(snapshot) as document:
            pages = len(document)
    except (OSError, RuntimeError, ValueError):
        return False
    return bool(pages > 0 and type(record.get("pages")) is int and record["pages"] == pages
                and len(record.get("page_preview_paths") or []) == pages
                and record.get("contact_sheet_paths"))
