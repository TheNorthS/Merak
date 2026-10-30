"""Validated layout-storyboard submission for one scientific figure."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from server.utils.atomic_write import atomic_write_json
from server.services.figure_storyboard_connections import validate_storyboard_connections


_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{1,79}$")
_TOPOLOGIES = {
    "linear", "parallel", "hierarchical", "radial", "matrix",
    "timeline", "spatial", "causal", "logical", "hybrid",
}
LAYOUT_POLICY_VERSION = 5


def _text(value: Any, field: str, *, minimum: int = 3, maximum: int = 500) -> str:
    normalized = " ".join(str(value or "").split())
    if len(normalized) < minimum or len(normalized) > maximum:
        raise ValueError(f"{field} must contain {minimum}–{maximum} characters")
    return normalized


def _candidate(value: Any) -> dict[str, Any]:
    candidate = dict(value) if isinstance(value, dict) else {}
    identity = str(candidate.get("id") or "").strip()
    if not _IDENTIFIER.fullmatch(identity):
        raise ValueError("storyboard candidate id must be stable snake_case")
    topology = str(candidate.get("topology") or "").strip().casefold()
    if topology not in _TOPOLOGIES:
        raise ValueError(f"storyboard candidate {identity} has unsupported topology")
    regions = [dict(item) for item in candidate.get("regions") or [] if isinstance(item, dict)]
    if not 2 <= len(regions) <= 8:
        raise ValueError(f"storyboard candidate {identity} requires 2–8 regions")
    region_ids = [str(item.get("id") or "").strip() for item in regions]
    if any(not _IDENTIFIER.fullmatch(item) for item in region_ids) or len(region_ids) != len(set(region_ids)):
        raise ValueError(f"storyboard candidate {identity} region ids are invalid or duplicated")
    normalized_regions = [{
        "id": region_id,
        "purpose": _text(region.get("purpose"), f"{identity}.{region_id}.purpose"),
        "visual_grammar": _text(
            region.get("visual_grammar"), f"{identity}.{region_id}.visual_grammar",
        ),
        "relative_weight": max(1, min(5, int(region.get("relative_weight") or 1))),
    } for region_id, region in zip(region_ids, regions)]
    reading_order = [str(item) for item in candidate.get("reading_order") or []]
    if set(reading_order) != set(region_ids) or len(reading_order) != len(region_ids):
        raise ValueError(f"storyboard candidate {identity} reading_order must cover every region once")
    connections = validate_storyboard_connections(
        candidate.get("connections"), region_ids, reading_order,
    )
    return {
        "id": identity, "topology": topology,
        "focal_message": _text(candidate.get("focal_message"), f"{identity}.focal_message", minimum=12),
        "regions": normalized_regions, "reading_order": reading_order,
        "connections": connections,
        "strengths": [_text(item, f"{identity}.strength", maximum=180) for item in candidate.get("strengths") or []][:4],
        "risks": [_text(item, f"{identity}.risk", maximum=180) for item in candidate.get("risks") or []][:4],
    }


def _storyboard_path(project_path: str, artifact_name: str) -> tuple[Path, Path]:
    root = Path(project_path).expanduser().resolve()
    if not root.is_dir() or not _IDENTIFIER.fullmatch(artifact_name):
        raise ValueError("storyboard project or artifact_name is invalid")
    path = root / ".merak" / "figure-storyboards" / f"{artifact_name}.json"
    return root, path


def begin_figure_storyboard(
    artifact_name: str, project_path: str = "",
    semantic_projection_sha256: str = "",
) -> str:
    """Start one three-candidate layout competition with a small tool call."""
    root, path = _storyboard_path(project_path, artifact_name)
    binding = str(semantic_projection_sha256 or "").strip()
    if not binding and path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            existing = {}
        if existing.get("layout_policy_version") == LAYOUT_POLICY_VERSION:
            binding = str(existing.get("semantic_projection_sha256") or "").strip()
    if binding and not re.fullmatch(r"[0-9a-f]{64}", binding):
        raise ValueError("semantic_projection_sha256 must be a lowercase SHA-256 digest")
    atomic_write_json(path, {
        "schema": 1, "layout_policy_version": LAYOUT_POLICY_VERSION,
        "semantic_projection_sha256": binding,
        "artifact_name": artifact_name, "candidates": [],
        "selected_id": "", "selection_reason": "",
    })
    return json.dumps({
        "status": "started", "artifact_name": artifact_name,
        "storyboard_path": str(path.relative_to(root)),
    })


def add_figure_storyboard_candidate(
    artifact_name: str, candidate: dict[str, Any], project_path: str = "",
) -> str:
    """Append one validated layout candidate without resending its siblings."""
    _root, path = _storyboard_path(project_path, artifact_name)
    if not path.is_file():
        raise ValueError("storyboard competition has not been started")
    payload = json.loads(path.read_text(encoding="utf-8"))
    candidates = [dict(item) for item in payload.get("candidates") or []]
    if len(candidates) >= 3:
        raise ValueError("storyboard already contains three candidates")
    normalized = _candidate(candidate)
    if normalized["id"] in {str(item.get("id")) for item in candidates}:
        raise ValueError(f"storyboard candidate {normalized['id']!r} already exists")
    candidates.append(normalized)
    payload["candidates"] = candidates
    atomic_write_json(path, payload)
    return json.dumps({
        "status": "candidate_added", "artifact_name": artifact_name,
        "candidate_id": normalized["id"], "candidate_count": len(candidates),
    })


def select_figure_storyboard(
    artifact_name: str, selected_id: str, selection_reason: str,
    project_path: str = "",
) -> str:
    """Select one of exactly three previously submitted layout candidates."""
    root, path = _storyboard_path(project_path, artifact_name)
    if not path.is_file():
        raise ValueError("storyboard competition has not been started")
    payload = json.loads(path.read_text(encoding="utf-8"))
    normalized = [_candidate(item) for item in payload.get("candidates") or []]
    if len(normalized) != 3 or len({item["id"] for item in normalized}) != 3:
        raise ValueError("storyboard requires exactly three unique layout candidates")
    selected = str(selected_id or "").strip()
    if selected not in {item["id"] for item in normalized}:
        raise ValueError("selected_id must reference one candidate")
    payload["candidates"] = normalized
    payload["selected_id"] = selected
    payload["selection_reason"] = _text(
        selection_reason, "selection_reason", minimum=1,
    )
    atomic_write_json(path, payload)
    return json.dumps({
        "status": "accepted", "artifact_name": artifact_name,
        "selected_id": selected, "storyboard_path": str(path.relative_to(root)),
    })


def submit_figure_storyboard(
    artifact_name: str, candidates: list[dict[str, Any]], selected_id: str,
    selection_reason: str, project_path: str = "",
    semantic_projection_sha256: str = "",
) -> str:
    """Test/programmatic convenience wrapper; model workflows use small calls."""
    begin_figure_storyboard(
        artifact_name, project_path,
        semantic_projection_sha256=semantic_projection_sha256,
    )
    for candidate in candidates:
        add_figure_storyboard_candidate(artifact_name, candidate, project_path)
    return select_figure_storyboard(
        artifact_name, selected_id, selection_reason, project_path,
    )


def load_selected_storyboard(
    project_path: str | Path, artifact_name: str,
    expected_projection_sha256: str = "",
) -> dict[str, Any]:
    """Read and revalidate one selected storyboard for workflow orchestration."""
    root = Path(project_path).expanduser().resolve()
    path = root / ".merak" / "figure-storyboards" / f"{artifact_name}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"figure storyboard is missing or invalid: {path}") from error
    if payload.get("layout_policy_version") != LAYOUT_POLICY_VERSION:
        raise ValueError(f"figure storyboard policy is stale: {path}")
    expected = str(expected_projection_sha256 or "").strip()
    if expected and payload.get("semantic_projection_sha256") != expected:
        raise ValueError(f"figure storyboard semantic projection is stale: {path}")
    candidates = [_candidate(item) for item in payload.get("candidates") or []]
    if len(candidates) != 3 or payload.get("selected_id") not in {item["id"] for item in candidates}:
        raise ValueError(f"figure storyboard contract is incomplete: {path}")
    return {**payload, "candidates": candidates, "path": str(path)}
