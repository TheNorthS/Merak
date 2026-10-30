"""Read-only identity checks for the PDF pages inspected by a native reviewer."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..services.api_visual_review_invocation import API_VISUAL_REVIEW_TRANSPORT
from .review_audit import review_source_bundle


VISUAL_FIELDS = {
    "pdf_path",
    "figure_quality",
    "caption_alignment",
    "page_layout",
    "table_formatting",
    "visual_consistency",
}


@dataclass
class ReviewVisualContext:
    root: Path
    state: dict[str, Any]
    last_round: dict[str, Any]
    visual: dict[str, Any]
    source_hash: str
    source_paths: list[Path]
    reviewed_snapshot: dict[str, Any] | None
    final_snapshot: dict[str, Any] | None
    issues: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SnapshotHashes:
    bundle: str = ""
    content: str = ""


def resolve_project_file(root: Path, raw_value: Any) -> Path | None:
    if not str(raw_value or "").strip():
        return None
    candidate = Path(str(raw_value)).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        candidate = candidate.resolve()
        candidate.relative_to(root)
    except (OSError, ValueError):
        return None
    return candidate


def prepare_visual_context(
    project_path: str,
    state: dict[str, Any],
    rounds: list[dict[str, Any]],
) -> ReviewVisualContext:
    root = Path(project_path).expanduser().resolve()
    last_round = rounds[-1] if rounds else {}
    visual = last_round.get("visual_review")
    visual = dict(visual) if isinstance(visual, dict) else {}
    source_hash, source_paths = review_source_bundle(root)
    snapshots = [
        dict(item)
        for item in state.get("pdf_snapshots") or []
        if isinstance(item, dict)
    ]
    try:
        current_round = int(state.get("current_round") or last_round.get("round") or 0)
    except (TypeError, ValueError):
        current_round = 0
    reviewed_path = resolve_project_file(root, last_round.get("pdf_snapshot"))
    reviewed = next(
        (
            item
            for item in reversed(snapshots)
            if reviewed_path is not None
            and resolve_project_file(root, item.get("snapshot_path")) == reviewed_path
        ),
        None,
    )
    final = next(
        (
            item
            for item in reversed(snapshots)
            if str(item.get("round") or "") == str(current_round)
            and str(item.get("kind") or "") == "review_round"
        ),
        None,
    )
    context = ReviewVisualContext(
        root, state, last_round, visual, source_hash, source_paths, reviewed, final
    )
    _validate_context_identity(context)
    return context


def _validate_context_identity(context: ReviewVisualContext) -> None:
    missing = sorted(
        key for key in VISUAL_FIELDS if not str(context.visual.get(key) or "").strip()
    )
    if missing:
        context.issues.append(
            "last review round lacks visual fields: " + ", ".join(missing)
        )
    if (
        str(context.visual.get("_review_transport") or "")
        != API_VISUAL_REVIEW_TRANSPORT
    ):
        context.issues.append(
            "last review did not use the native visual reviewer transport"
        )
    if context.visual.get("_coordinator_verified") != "true":
        context.issues.append("last visual review was not coordinator-verified")
    if not context.source_hash:
        context.issues.append("current review source bundle is empty")
    if str(context.state.get("source_bundle_sha256") or "") != context.source_hash:
        context.issues.append(
            "REVIEW_STATE source bundle is stale for the current paper"
        )
    if str(context.visual.get("_source_bundle_sha256") or "") != context.source_hash:
        context.issues.append(
            "visual review is stale for the current paper source bundle"
        )
    if context.reviewed_snapshot is None:
        context.issues.append("reviewed immutable PDF snapshot is missing from state")
    if context.final_snapshot is None:
        context.issues.append("final numbered PDF snapshot is missing from state")


def _page_hashes(
    context: ReviewVisualContext,
    record: dict[str, Any],
    label: str,
) -> SnapshotHashes:
    values = [
        *list(record.get("page_preview_paths") or []),
        *list(record.get("contact_sheet_paths") or []),
    ]
    if not values:
        context.issues.append(f"{label} snapshot has no rendered page images")
        return SnapshotHashes()
    bundle, content = hashlib.sha256(), hashlib.sha256()
    inspected = 0
    for value in values:
        path = resolve_project_file(context.root, value)
        if path is None or not path.is_file() or path.stat().st_size <= 0:
            context.issues.append(f"{label} snapshot page image is missing: {value}")
            continue
        digest = hashlib.sha256(path.read_bytes()).digest()
        bundle.update(
            path.relative_to(context.root).as_posix().encode("utf-8", errors="replace")
        )
        bundle.update(b"::")
        bundle.update(digest)
        bundle.update(b"\n")
        content.update(digest)
        content.update(b"\n")
        inspected += 1
    return (
        SnapshotHashes(bundle.hexdigest(), content.hexdigest())
        if inspected == len(values)
        else SnapshotHashes()
    )


def _pdf_snapshot_issues(
    context: ReviewVisualContext, record: dict[str, Any], label: str
) -> None:
    path = resolve_project_file(context.root, record.get("snapshot_path"))
    if (
        path is None
        or not path.is_file()
        or path.stat().st_size <= 0
        or path.read_bytes()[:5] != b"%PDF-"
    ):
        context.issues.append(f"{label} PDF snapshot is missing or invalid")
    elif (
        str(record.get("pdf_sha256") or "")
        != hashlib.sha256(path.read_bytes()).hexdigest()
    ):
        context.issues.append(f"{label} PDF snapshot hash does not match its file")
    layout = resolve_project_file(context.root, record.get("layout_report_path"))
    if layout is None or not layout.is_file():
        context.issues.append(f"{label} layout report is missing")
    else:
        try:
            report = json.loads(layout.read_text(encoding="utf-8-sig"))
            if not isinstance(report, dict):
                raise ValueError("layout report root must be an object")
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            report = {}
            context.issues.append(f"{label} layout report is invalid")
        report_hash = str(report.get("pdf_sha256") or "")
        if report_hash and report_hash != str(record.get("pdf_sha256") or ""):
            context.issues.append(f"{label} layout report is stale for its PDF")
    if str(record.get("source_bundle_sha256") or "") != context.source_hash:
        context.issues.append(
            f"{label} snapshot is stale for the current source bundle"
        )


def validate_snapshot(
    context: ReviewVisualContext,
    record: dict[str, Any] | None,
    label: str,
) -> SnapshotHashes:
    if record is None:
        return SnapshotHashes()
    hashes = _page_hashes(context, record, label)
    if not hashes.bundle:
        return hashes
    if str(record.get("visual_bundle_sha256") or "") != hashes.bundle:
        context.issues.append(f"{label} visual bundle hash does not match its files")
    if str(record.get("visual_content_sha256") or "") != hashes.content:
        context.issues.append(f"{label} visual content hash does not match its files")
    _pdf_snapshot_issues(context, record, label)
    return hashes


def validate_reviewed_pixels(
    context: ReviewVisualContext,
    reviewed: SnapshotHashes,
    final: SnapshotHashes,
) -> None:
    if reviewed.bundle and reviewed.bundle != str(
        context.visual.get("_visual_bundle_sha256") or ""
    ):
        context.issues.append(
            "visual review is not bound to the reviewed page-image bundle"
        )
    expected = str(context.visual.get("_visual_content_sha256") or "")
    if reviewed.content and reviewed.content != expected:
        context.issues.append("visual review is not bound to the reviewed page pixels")
    if final.content and final.content != expected:
        context.issues.append(
            "final PDF page pixels changed after visual review; a fresh visual review is required"
        )
