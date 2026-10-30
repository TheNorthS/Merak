"""Verify native reviewer API traces against frozen source and response bytes."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..services.api_visual_review_invocation import (
    API_IMAGE_ATTACHMENT_MODE,
    API_VISUAL_REVIEW_TRANSPORT,
    TRACE_SCHEMA_VERSION,
)
from ..services.api_visual_review_schemas import REVIEW_SCHEMA
from .review_visual_artifact_evidence import (
    VISUAL_FIELDS,
    ReviewVisualContext,
    resolve_project_file,
)


@dataclass
class NativeReviewTrace:
    path: Path | None
    meta: dict[str, Any]
    invocation: str
    model: str
    purpose: str
    response_chars: int
    response_sha256: str = ""


@dataclass(frozen=True)
class TraceFiles:
    prompt: bytes = b""
    schema: bytes = b""
    response: str = ""


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _integer(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def read_native_trace(context: ReviewVisualContext) -> NativeReviewTrace:
    path = resolve_project_file(context.root, context.visual.get("_review_trace_path"))
    meta: dict[str, Any] = {}
    if path is None or not path.is_dir():
        context.issues.append("native visual-review trace directory is missing")
    elif tuple(
        part.casefold() for part in path.relative_to(context.root).parts[:2]
    ) != (".merak", "model-api-reviewer"):
        context.issues.append(
            "native visual-review trace is outside its managed directory"
        )
        path = None
    else:
        meta_path = resolve_project_file(context.root, path / "meta.json")
        try:
            if meta_path is None:
                raise ValueError("unsafe trace metadata path")
            payload = json.loads(meta_path.read_text(encoding="utf-8-sig"))
            if not isinstance(payload, dict):
                raise ValueError("trace metadata root must be an object")
            meta = payload
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            context.issues.append(
                "native visual-review trace metadata is missing or invalid"
            )
    trace = NativeReviewTrace(
        path,
        meta,
        str(meta.get("invocation_id") or ""),
        str(context.visual.get("_review_model_identity") or ""),
        f"review-round-{_integer(context.last_round.get('round'))}",
        _integer(meta.get("response_chars")),
    )
    _validate_trace_identity(context, trace)
    _validate_execution_policy(context, trace)
    return trace


def _validate_trace_identity(
    context: ReviewVisualContext, trace: NativeReviewTrace
) -> None:
    if (
        not trace.invocation.startswith("model-api:")
        or str(context.visual.get("_review_invocation_id") or "") != trace.invocation
    ):
        context.issues.append("native visual-review invocation id is not trace-bound")
    if (
        not trace.model
        or str(trace.meta.get("model_identity") or "") != trace.model
        or str(context.state.get("reviewer_model") or "") != trace.model
    ):
        context.issues.append("native visual-review model identity is not trace-bound")


def _validate_execution_policy(
    context: ReviewVisualContext, trace: NativeReviewTrace
) -> None:
    meta = trace.meta
    expected = {
        "purpose": trace.purpose,
        "image_attachment_mode": API_IMAGE_ATTACHMENT_MODE,
        "transport": API_VISUAL_REVIEW_TRANSPORT,
        "evidence_transport": "frozen-prompt-bundle-v1",
        "tool_policy": "model-output-only",
    }
    valid = (
        type(meta.get("schema_version")) is int
        and meta["schema_version"] == TRACE_SCHEMA_VERSION
        and meta.get("success") is True
        and not str(meta.get("failure_kind") or "").strip()
        and trace.response_chars > 0
        and all(str(meta.get(key) or "") == value for key, value in expected.items())
    )
    if not valid:
        context.issues.append("native visual-review execution policy is not verified")


def _read_trace_files(
    context: ReviewVisualContext, trace: NativeReviewTrace
) -> TraceFiles:
    if trace.path is None or not trace.path.is_dir():
        return TraceFiles()
    paths = [
        resolve_project_file(context.root, trace.path / name)
        for name in (
            "prompt.txt",
            "output.schema.json",
            "response.txt",
        )
    ]
    try:
        if any(path is None or path.parent != trace.path for path in paths):
            raise ValueError("unsafe trace artifact path")
        prompt, schema, response = paths
        return TraceFiles(
            prompt.read_bytes(),
            schema.read_bytes(),
            response.read_text(
                encoding="utf-8-sig",
                errors="strict",
            ).strip(),
        )
    except (OSError, UnicodeError, ValueError):
        context.issues.append(
            "native visual-review trace prompt/schema/response files are missing or unreadable"
        )
        return TraceFiles()


def _validate_file_hashes(
    context: ReviewVisualContext, trace: NativeReviewTrace, files: TraceFiles
) -> None:
    prompt_hash = hashlib.sha256(files.prompt).hexdigest() if files.prompt else ""
    schema_hash = hashlib.sha256(files.schema).hexdigest() if files.schema else ""
    trace.response_sha256 = hashlib.sha256(files.response.encode("utf-8")).hexdigest()
    if (
        not prompt_hash
        or str(trace.meta.get("prompt_sha256") or "").casefold() != prompt_hash
    ):
        context.issues.append(
            "native visual-review prompt hash does not match prompt.txt"
        )
    if (
        not schema_hash
        or str(trace.meta.get("schema_sha256") or "").casefold() != schema_hash
    ):
        context.issues.append(
            "native visual-review schema hash does not match output.schema.json"
        )
    if (
        str(trace.meta.get("response_sha256") or "").casefold() != trace.response_sha256
        or str(context.visual.get("_review_response_sha256") or "").casefold()
        != trace.response_sha256
    ):
        context.issues.append(
            "native visual-review response is not hash-bound to the final structured round"
        )
    if trace.response_chars != len(files.response):
        context.issues.append(
            "native visual-review response length does not match response.txt"
        )


def _validate_route(context: ReviewVisualContext, trace: NativeReviewTrace) -> None:
    route = _mapping(trace.meta.get("reviewer_route"))
    route_hash = hashlib.sha256(
        json.dumps(
            route,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    valid = (
        bool(route)
        and str(trace.meta.get("reviewer_route_sha256") or "").casefold() == route_hash
        and str(route.get("transport") or "") == API_VISUAL_REVIEW_TRANSPORT
        and str(route.get("model_identity") or "") == trace.model
        and route.get("same_model_allowed") is True
        and str(route.get("session_isolation") or "") == "fresh_context"
    )
    if not valid:
        context.issues.append(
            "native visual-review API route is not session-isolated or hash-bound"
        )


def _validate_packet_file(
    context: ReviewVisualContext,
    trace: NativeReviewTrace,
    files: TraceFiles,
) -> None:
    packet_meta = _mapping(trace.meta.get("evidence_packet"))
    path = resolve_project_file(context.root, trace.meta.get("evidence_packet_path"))
    if (
        path is None
        or not path.is_file()
        or trace.path is None
        or path.parent != trace.path
    ):
        context.issues.append(
            "native visual-review frozen evidence packet is missing from its trace directory"
        )
        return
    try:
        packet_bytes = path.read_bytes()
    except OSError:
        packet_bytes = b""
    if (
        not packet_bytes
        or str(packet_meta.get("sha256") or "").casefold()
        != hashlib.sha256(packet_bytes).hexdigest()
        or packet_bytes not in files.prompt
    ):
        context.issues.append(
            "native visual-review frozen evidence packet is not hash-bound into prompt.txt"
        )


def _validate_packet_sources(
    context: ReviewVisualContext, trace: NativeReviewTrace
) -> None:
    packet = _mapping(trace.meta.get("evidence_packet"))
    expected = {
        path.relative_to(context.root).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in context.source_paths
    }
    declared = {
        str(key).replace("\\", "/"): str(value).casefold()
        for key, value in _mapping(packet.get("file_sha256")).items()
    }
    paths = sorted(str(item).replace("\\", "/") for item in packet.get("paths") or [])
    valid = (
        str(packet.get("mode") or "") == "frozen-prompt-bundle-v1"
        and str(packet.get("source_bundle_sha256") or "").casefold()
        == context.source_hash
        and declared == expected
        and paths == sorted(expected)
        and not packet.get("truncated_paths")
    )
    if not valid:
        context.issues.append(
            "native visual-review evidence packet is incomplete or stale for the current manuscript source bundle"
        )


def _validate_response(context: ReviewVisualContext, files: TraceFiles) -> None:
    try:
        schema = json.loads(files.schema.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError):
        schema = {}
    from .draft_delivery import DRAFT, draft_schema
    expected_schema = draft_schema(REVIEW_SCHEMA) if context.state.get("delivery_goal") == DRAFT else REVIEW_SCHEMA
    if schema != expected_schema:
        context.issues.append(
            "native visual-review output schema is not the managed review contract"
        )
    try:
        decoded = json.loads(files.response)
    except json.JSONDecodeError:
        decoded = {}
    if not isinstance(decoded, dict):
        context.issues.append("native visual-review response is not a JSON object")
        decoded = {}
    response_visual = _mapping(decoded.get("visual_review"))
    try:
        mismatch = float(decoded.get("score")) != float(context.last_round.get("score"))
    except (TypeError, ValueError):
        mismatch = True
    mismatch = (
        mismatch
        or (context.state.get("delivery_goal") == DRAFT and decoded.get("draft_blockers") != context.last_round.get("draft_blockers"))
        or str(decoded.get("verdict") or "")
        != str(context.last_round.get("verdict") or "")
        or any(
            list(decoded.get(key) or []) != list(context.last_round.get(key) or [])
            for key in ("strengths", "weaknesses", "action_items")
        )
        or any(
            str(response_visual.get(key) or "") != str(context.visual.get(key) or "")
            for key in VISUAL_FIELDS
        )
    )
    if mismatch:
        context.issues.append(
            "native visual-review trace response does not match the final structured review round"
        )


def validate_native_trace(
    context: ReviewVisualContext, trace: NativeReviewTrace
) -> None:
    if trace.path is None or not trace.path.is_dir():
        return
    files = _read_trace_files(context, trace)
    _validate_file_hashes(context, trace, files)
    _validate_route(context, trace)
    _validate_packet_file(context, trace, files)
    _validate_packet_sources(context, trace)
    _validate_response(context, files)
