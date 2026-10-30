"""Verify the exact bounded image packet sent to the native reviewer API."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .review_audit import REVIEW_NATIVE_IMAGE_LIMIT
from .review_visual_artifact_evidence import ReviewVisualContext, resolve_project_file
from .review_visual_trace_evidence import NativeReviewTrace


@dataclass
class SnapshotImages:
    allowed: dict[str, tuple[Path, str]] = field(default_factory=dict)
    previews: set[str] = field(default_factory=set)
    contacts: set[str] = field(default_factory=set)


@dataclass
class ReviewAttachmentPacket:
    declared: bool
    identities: list[str] = field(default_factory=list)
    hashes: dict[str, str] = field(default_factory=dict)
    bundle_sha256: str = ""


def _snapshot_images(context: ReviewVisualContext) -> SnapshotImages:
    snapshot = context.reviewed_snapshot or {}
    images = SnapshotImages()
    previews = list(snapshot.get("page_preview_paths") or [])
    contacts = list(snapshot.get("contact_sheet_paths") or [])
    for value, identities in [
        *((value, images.previews) for value in previews),
        *((value, images.contacts) for value in contacts),
    ]:
        path = resolve_project_file(context.root, value)
        if path is None or not path.is_file() or path.stat().st_size <= 0:
            continue
        identity = path.relative_to(context.root).as_posix()
        images.allowed[identity] = (path, hashlib.sha256(path.read_bytes()).hexdigest())
        identities.add(identity)
    return images


def _packet_values(context: ReviewVisualContext) -> tuple[bool, list[Any]]:
    raw = context.visual.get("_review_image_paths")
    declared = isinstance(raw, list) or bool(str(raw or "").strip())
    if isinstance(raw, list):
        return declared, list(raw)
    if str(raw or "").strip():
        try:
            values = json.loads(str(raw))
        except (TypeError, json.JSONDecodeError):
            values = None
        if isinstance(values, list):
            return declared, list(values)
        context.issues.append("review image attachment packet is not a JSON path list")
        return declared, []
    snapshot = context.reviewed_snapshot or {}
    return declared, [
        *list(snapshot.get("page_preview_paths") or []),
        *list(snapshot.get("contact_sheet_paths") or []),
    ]


def _validate_membership(
    context: ReviewVisualContext,
    images: SnapshotImages,
    declared: bool,
    values: list[Any],
) -> ReviewAttachmentPacket:
    packet = ReviewAttachmentPacket(declared)
    for value in values:
        path = resolve_project_file(context.root, value)
        if path is None or not path.is_file() or path.stat().st_size <= 0:
            context.issues.append(
                f"review image attachment is missing or unsafe: {value}"
            )
            continue
        identity = path.relative_to(context.root).as_posix()
        if identity not in images.allowed:
            context.issues.append(
                f"review image attachment is not part of the reviewed PDF snapshot: {identity}"
            )
            continue
        if identity in packet.hashes:
            context.issues.append(
                f"review image attachment packet contains a duplicate: {identity}"
            )
            continue
        packet.identities.append(identity)
        packet.hashes[identity] = images.allowed[identity][1]
    if not packet.hashes:
        context.issues.append("native reviewer image attachment packet is empty")
    if declared and len(packet.identities) > REVIEW_NATIVE_IMAGE_LIMIT:
        context.issues.append(
            f"native reviewer image attachment packet exceeds the bounded limit of {REVIEW_NATIVE_IMAGE_LIMIT}"
        )
    return packet


def _validate_coverage(
    context: ReviewVisualContext,
    images: SnapshotImages,
    packet: ReviewAttachmentPacket,
) -> None:
    if not images.contacts:
        context.issues.append(
            "reviewed PDF snapshot has no full-document contact-sheet coverage"
        )
    else:
        missing = sorted(images.contacts.difference(packet.identities))
        if missing:
            context.issues.append(
                "native reviewer packet omits contact sheets required for whole-paper coverage: "
                + ", ".join(missing)
            )
    try:
        pages = int((context.reviewed_snapshot or {}).get("pages") or 0)
    except (TypeError, ValueError):
        pages = 0
    if pages <= 0 or len(images.previews) < pages:
        context.issues.append(
            "rendered contact-sheet evidence does not cover every PDF page"
        )


def _validate_packet_binding(
    context: ReviewVisualContext,
    trace: NativeReviewTrace,
    packet: ReviewAttachmentPacket,
) -> None:
    digest = hashlib.sha256()
    for identity in packet.identities:
        digest.update(identity.encode("utf-8", errors="replace"))
        digest.update(b"::")
        digest.update(bytes.fromhex(packet.hashes[identity]))
        digest.update(b"\n")
    packet.bundle_sha256 = digest.hexdigest() if packet.identities else ""
    if (
        packet.declared
        and str(context.visual.get("_review_image_bundle_sha256") or "").casefold()
        != packet.bundle_sha256
    ):
        context.issues.append(
            "review image attachment packet hash does not match its files"
        )
    raw_hashes = trace.meta.get("image_sha256")
    raw_hashes = raw_hashes if isinstance(raw_hashes, dict) else {}
    traced = {
        str(key).replace("\\", "/"): str(value).casefold()
        for key, value in raw_hashes.items()
    }
    if traced != packet.hashes:
        context.issues.append(
            "native reviewer image attachments do not match the declared review packet"
        )
    paths = [
        str(value).replace("\\", "/") for value in trace.meta.get("image_paths") or []
    ]
    if packet.declared and paths != packet.identities:
        context.issues.append(
            "native reviewer trace image path order does not match the declared review packet"
        )
    _validate_request_binding(context, trace, packet, paths)


def _validate_request_binding(
    context: ReviewVisualContext,
    trace: NativeReviewTrace,
    packet: ReviewAttachmentPacket,
    paths: list[str],
) -> None:
    material = [
        trace.invocation,
        trace.purpose,
        str(trace.meta.get("prompt_sha256") or ""),
        str(trace.meta.get("schema_sha256") or ""),
        str(trace.meta.get("reviewer_route_sha256") or ""),
        *(f"{identity}:{packet.hashes.get(identity, '')}" for identity in paths),
    ]
    expected = hashlib.sha256("\x00".join(material).encode("utf-8")).hexdigest()
    if str(trace.meta.get("request_sha256") or "").casefold() != expected:
        context.issues.append(
            "native visual-review API request is not hash-bound to its model route, prompt, schema, and image packet"
        )


def validate_review_attachments(
    context: ReviewVisualContext,
    trace: NativeReviewTrace,
) -> ReviewAttachmentPacket:
    images = _snapshot_images(context)
    declared, values = _packet_values(context)
    packet = _validate_membership(context, images, declared, values)
    _validate_coverage(context, images, packet)
    _validate_packet_binding(context, trace, packet)
    return packet
