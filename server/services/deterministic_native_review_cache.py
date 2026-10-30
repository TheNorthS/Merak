"""Reuse a deterministic figure rejection only with intact native-image evidence.

The cache never accepts a figure. It only reports the same producer defect when
the typed input, loaded producer/reviewer code, candidate pixels, and independent
review trace still identify the rejected candidate.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..utils.atomic_write import atomic_write_json
from .rich_svg_visual_review import (
    PROTOCOL, REVIEW_POLICY_VERSION, _brief_sha256, review_gate_issues,
)


_NATIVE_ERROR = "Rich SVG native-image review failed;"
_ALIGNMENT_ERROR = "Candidate scientific alignment failed:"
_REVIEW_KEYS = ("status", "content_sha256", "render_sha256", "issues")
_ARCHIVE_KEYS = ("score", "verdict", "issues", "findings", "checklist")


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def _alignment_sources(root: Path) -> dict[str, str]:
    """Bind external scientific contracts used by candidate alignment."""
    return {
        name: _sha256(root / name) if (root / name).is_file() else "missing"
        for name in ("ideas/SELECTED_IDEA.json", "figures/FIGURE_SPECS.json")
    }


def _direct_child(value: Any, directory: Path) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        path = Path(value).resolve()
        return path if path.parent == directory.resolve() and path.is_dir() else None
    except (OSError, ValueError):
        return None


def _attested_trace(
    root: Path, *, path: Any, invocation_id: Any,
    model_identity: Any, image_sha256: str,
) -> bool:
    if not invocation_id or not model_identity or not image_sha256:
        return False
    trace = _direct_child(
        path, root / ".merak" / "model-api-reviewer",
    )
    if trace is None:
        return False
    meta = _load(trace / "meta.json")
    image_hashes = meta.get("image_sha256")
    if not isinstance(image_hashes, dict):
        return False
    expected = (
        meta.get("success") is True
        and meta.get("invocation_id") == invocation_id
        and meta.get("model_identity") == model_identity
        and meta.get("image_attachment_mode") == "api-native-image-content"
        and image_sha256 in image_hashes.values()
    )
    return bool(expected and all(
        _sha256(trace / filename) == meta.get(field)
        for filename, field in (
            ("prompt.txt", "prompt_sha256"),
            ("output.schema.json", "schema_sha256"),
            ("response.txt", "response_sha256"),
        )
    ))


def _trace_is_current(root: Path, review: dict[str, Any]) -> bool:
    image_sha256 = str(review.get("image_sha256") or "")
    if not _attested_trace(
        root, path=review.get("review_trace_path"),
        invocation_id=review.get("review_invocation_id"),
        model_identity=review.get("review_model_identity"),
        image_sha256=image_sha256,
    ):
        return False
    if "blind_readback" not in review:
        return True
    return _attested_trace(
        root, path=review.get("blind_readback_trace_path"),
        invocation_id=review.get("blind_readback_invocation_id"),
        model_identity=review.get("blind_readback_model_identity"),
        image_sha256=image_sha256,
    )


def _archive_is_current(
    root: Path, asset_id: str, review: dict[str, Any],
) -> bool:
    candidate = _direct_child(
        review.get("candidate_path"),
        root / ".merak" / "figure-candidates" / asset_id,
    )
    if candidate is None:
        return False
    record = _load(candidate / "review.json")
    archived = record.get("review")
    if not isinstance(archived, dict):
        return False
    return bool(
        record.get("protocol") == PROTOCOL
        and record.get("artifact_id") == asset_id
        and record.get("source_sha256") == review.get("source_sha256")
        and record.get("trace_path") == review.get("review_trace_path")
        and all(archived.get(key) == review.get(key) for key in _ARCHIVE_KEYS)
        and _sha256(candidate / f"{asset_id}.svg") == review.get("source_sha256")
        and _sha256(candidate / f"{asset_id}.png") == review.get("image_sha256")
        and bool(_sha256(candidate / f"{asset_id}.pdf"))
    )


def _review_is_cacheable(
    root: Path, asset_id: str, error: str, review: dict[str, Any],
    local_round: dict[str, Any],
) -> bool:
    refused = error.startswith(_NATIVE_ERROR) and review.get("verdict") in {
        "refine", "accept",
    }
    alignment = error.startswith(_ALIGNMENT_ERROR) and review.get("verdict") == "accept"
    if not (refused or alignment):
        return False
    if (
        review.get("protocol") != PROTOCOL
        or review.get("review_backend") != "independent-model-api-native-vision-v1"
        or review.get("review_policy_version") != REVIEW_POLICY_VERSION
        or not review.get("review_invocation_id")
        or not review.get("review_model_identity")
        or not review.get("source_sha256")
        or not review.get("image_sha256")
        or not review.get("brief_sha256")
    ):
        return False
    if not _trace_is_current(root, review) or not _archive_is_current(root, asset_id, review):
        return False
    if (
        local_round.get("status") != ("failed" if refused else "passed")
        or local_round.get("content_sha256") != review.get("source_sha256")
        or local_round.get("render_sha256") != review.get("image_sha256")
    ):
        return False
    if refused:
        issues = local_round.get("issues")
        return bool(
            isinstance(issues, list) and issues
            and all(isinstance(issue, str) and issue in error for issue in issues)
            and review_gate_issues(review)
        )
    return not review_gate_issues(review) and local_round.get("issues") == []


def cacheable_record(
    *, root: Path, asset_id: str, input_hash: str, svg_hash: str,
    error: str, result: Any, persisted_round: dict[str, Any],
) -> dict[str, Any] | None:
    """Capture a failed review only after verifying its immutable evidence."""
    metadata = result.metadata if isinstance(result.metadata, dict) else {}
    review = metadata.get("independent_visual_review")
    rounds = metadata.get("visual_review_rounds")
    if not isinstance(review, dict) or not isinstance(rounds, list) or not rounds:
        return None
    local = rounds[-1]
    if not isinstance(local, dict) or any(
        local.get(key) != persisted_round.get(key) for key in _REVIEW_KEYS
    ):
        return None
    code = result.code
    if (
        not isinstance(code, str)
        or hashlib.sha256(code.encode("utf-8")).hexdigest() != review.get("source_sha256")
        or _brief_sha256(metadata) != review.get("brief_sha256")
        or not _review_is_cacheable(root, asset_id, error, review, local)
    ):
        return None
    return {
        "schema": 2, "kind": "verified_native_review_rejection",
        "asset_id": asset_id, "project_root": str(root.resolve()),
        "producer_input_sha256": input_hash, "candidate_svg_sha256": svg_hash,
        "error_signature": hashlib.sha256(error.encode("utf-8")).hexdigest(),
        "error": error, "review": review,
        "local_review": {key: local.get(key) for key in _REVIEW_KEYS},
        "alignment_sources": _alignment_sources(root)
        if error.startswith(_ALIGNMENT_ERROR) else {},
    }


def record_failure(path: Path, record: dict[str, Any]) -> None:
    atomic_write_json(path, record)


def cached_failure(
    record: dict[str, Any], *, figures_root: Path, asset_id: str,
    input_hash: str, svg_hash: str, persisted_round: dict[str, Any],
) -> str:
    """Return the prior error only while every attested input remains current."""
    if record.get("schema") != 2 or record.get("kind") != "verified_native_review_rejection":
        return ""
    error = record.get("error")
    review = record.get("review")
    local = record.get("local_review")
    if not isinstance(error, str) or not isinstance(review, dict) or not isinstance(local, dict):
        return ""
    expected = {
        "asset_id": asset_id, "project_root": str(figures_root.parent.resolve()),
        "producer_input_sha256": input_hash, "candidate_svg_sha256": svg_hash,
        "error_signature": hashlib.sha256(error.encode("utf-8")).hexdigest(),
    }
    if any(record.get(key) != value for key, value in expected.items()):
        return ""
    if any(local.get(key) != persisted_round.get(key) for key in _REVIEW_KEYS):
        return ""
    if error.startswith(_ALIGNMENT_ERROR) and record.get("alignment_sources") != _alignment_sources(
        figures_root.parent,
    ):
        return ""
    return error if _review_is_cacheable(figures_root.parent, asset_id, error, review, local) else ""
