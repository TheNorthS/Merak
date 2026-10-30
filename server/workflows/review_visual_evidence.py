"""Aggregate native visual review proof without rendering or model invocation."""

from __future__ import annotations

from typing import Any

from .review_visual_artifact_evidence import (
    SnapshotHashes,
    prepare_visual_context,
    validate_reviewed_pixels,
    validate_snapshot,
)
from .review_visual_attachment_evidence import (
    ReviewAttachmentPacket,
    validate_review_attachments,
)
from .review_visual_trace_evidence import (
    NativeReviewTrace,
    read_native_trace,
    validate_native_trace,
)


def review_visual_evidence_gate(
    project_path: str,
    state_data: dict[str, Any],
    structured_rounds: list[dict[str, Any]],
) -> dict[str, Any]:
    managed = state_data.get("managed_by") == "cross_model_review_loop"
    if not managed:
        return {"required": False, "verified": True, "issues": []}
    context = prepare_visual_context(project_path, state_data, structured_rounds)
    reviewed, final = SnapshotHashes(), SnapshotHashes()
    trace = NativeReviewTrace(None, {}, "", "", "", 0)
    packet = ReviewAttachmentPacket(False)
    try:
        reviewed = validate_snapshot(context, context.reviewed_snapshot, "reviewed")
        final = validate_snapshot(context, context.final_snapshot, "final")
        validate_reviewed_pixels(context, reviewed, final)
        trace = read_native_trace(context)
        validate_native_trace(context, trace)
        packet = validate_review_attachments(context, trace)
    except (OSError, UnicodeError) as error:
        context.issues.append(
            f"native visual-review evidence became unreadable during verification: {type(error).__name__}: {error}"
        )
    return {
        "required": True,
        "verified": not context.issues,
        "issues": list(dict.fromkeys(context.issues)),
        "transport": str(context.visual.get("_review_transport") or ""),
        "reviewed_snapshot": str(context.last_round.get("pdf_snapshot") or ""),
        "final_snapshot": str(
            (context.final_snapshot or {}).get("snapshot_path") or ""
        ),
        "current_source_bundle_sha256": context.source_hash,
        "reviewed_visual_content_sha256": reviewed.content,
        "final_visual_content_sha256": final.content,
        "review_trace_path": str(trace.path or ""),
        "review_image_paths": packet.identities,
        "review_image_bundle_sha256": packet.bundle_sha256,
        "review_response_sha256": trace.response_sha256,
    }
