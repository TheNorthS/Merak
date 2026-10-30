"""Preserve and restore the strongest unaccepted SVG draft composition."""

from __future__ import annotations

import json
import hashlib
import shutil
from pathlib import Path
from typing import Any

from server.utils.atomic_write import atomic_write_json, atomic_write_text

from .rich_svg_visual_review import REVIEW_POLICY_VERSION


def _snapshot_root(directory: Path) -> Path:
    return directory / "best-composition"


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


_CONTRACT_FILES = (
    "canvas-layout.json", "mechanism-ir.json", "visual-blueprint.json",
)


def _source_sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def _quality_rank(
    *, score: float, verdict: str, issues: list[str], findings: list[Any],
) -> tuple[int, int, int, float]:
    typed_blockers = sum(
        1 for item in findings
        if isinstance(item, dict) and item.get("severity") == "blocker"
    )
    blockers = max(typed_blockers, len(issues))
    accepted = int(verdict == "accept" and not issues and blockers == 0)
    return accepted, -blockers, -len(issues), score


def _draft_identity(manifest: dict[str, Any]) -> str:
    """Identify the brief, excluding candidate-owned blueprint and mappings."""
    payload = {
        "draft_policy_version": manifest.get("draft_policy_version"),
        "canvas_layout_schema": manifest.get("canvas_layout_schema"),
        "authoring_mode": manifest.get("authoring_mode"),
        "production_strategy": manifest.get("production_strategy"),
        "source_bundle_sha256": manifest.get("source_bundle_sha256"),
        "figure_spec_sha256": manifest.get("figure_spec_sha256"),
        "layout_policy_version": manifest.get("layout_policy_version"),
        "storyboard_selected_id": manifest.get("storyboard_selected_id"),
        "storyboard_selected_sha256": manifest.get("storyboard_selected_sha256"),
        "storyboard_candidate_id": manifest.get("storyboard_candidate_id"),
        "storyboard_candidate_sha256": manifest.get("storyboard_candidate_sha256"),
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def matching_best_draft(
    directory: Path, visual_blueprint_sha256: str,
) -> dict[str, Any]:
    """Return a usable best snapshot only for the current source-bound brief."""
    snapshot = _snapshot_root(directory)
    best = _load(snapshot / "best.json")
    manifest = _load(directory / "manifest.json")
    saved_manifest = _load(snapshot / "manifest.json")
    artifact_name = str(manifest.get("artifact_name") or "")
    source = snapshot / f"{artifact_name}.svg"
    if not (
        visual_blueprint_sha256
        and saved_manifest.get("artifact_name") == artifact_name
        and _draft_identity(saved_manifest) == _draft_identity(manifest)
        and best.get("review_policy_version") == REVIEW_POLICY_VERSION
        and source.is_file()
        and best.get("source_sha256") == _source_sha256(source)
    ):
        return {}
    return best


def restore_best_after_local_failure(
    directory: Path, visual_blueprint_sha256: str,
) -> dict[str, Any]:
    """Undo an unreviewable revision without crossing a changed source contract."""
    best = matching_best_draft(directory, visual_blueprint_sha256)
    if best:
        restore_best_draft(directory)
    return best


def preserve_best_draft(
    directory: Path, source: Path, review: dict[str, Any],
    issues: list[str], visual_blueprint_sha256: str,
) -> tuple[bool, float]:
    """Snapshot improving work; restore the previous snapshot on regression."""
    snapshot = _snapshot_root(directory)
    record_path = snapshot / "best.json"
    previous = _load(record_path)
    manifest = _load(directory / "manifest.json")
    previous_score = float(previous.get("score") or 0.0)
    score = float(review.get("score") or 0.0)
    identity = _draft_identity(manifest)
    same_brief = bool(matching_best_draft(directory, visual_blueprint_sha256))
    issues = [str(item) for item in issues if str(item).strip()]
    findings = list(review.get("findings") or [])
    source_sha256 = _source_sha256(source)
    previous_source = snapshot / source.name
    previous_sha256 = str(previous.get("source_sha256") or "") or _source_sha256(
        previous_source
    )
    if same_brief and previous_score:
        previous_rank = _quality_rank(
            score=previous_score,
            verdict=str(previous.get("verdict") or ""),
            issues=[str(item) for item in previous.get("issues") or []],
            findings=list(previous.get("findings") or []),
        )
        candidate_rank = _quality_rank(
            score=score, verdict=str(review.get("verdict") or ""),
            issues=issues, findings=findings,
        )
        if source_sha256 == previous_sha256 and candidate_rank == previous_rank:
            return False, previous_score
        if candidate_rank <= previous_rank:
            restore_best_draft(directory)
            return True, previous_score
    parts = directory / "parts"
    snapshot_parts = snapshot / "parts"
    snapshot_parts.mkdir(parents=True, exist_ok=True)
    for current in snapshot_parts.glob("*.svgfrag"):
        current.unlink()
    if parts.is_dir():
        for current in parts.glob("*.svgfrag"):
            shutil.copy2(current, snapshot_parts / current.name)
    shutil.copy2(source, snapshot / source.name)
    atomic_write_json(snapshot / "manifest.json", manifest)
    for name in _CONTRACT_FILES:
        target = snapshot / name
        target.unlink(missing_ok=True)
        current = directory / name
        if current.is_file():
            shutil.copy2(current, target)
    atomic_write_json(record_path, {
        "schema": 1, "score": score, "verdict": str(review.get("verdict") or ""),
        "review_policy_version": REVIEW_POLICY_VERSION,
        "issues": issues, "findings": findings,
        "checklist": dict(review.get("checklist") or {}),
        "improvement_prompt": str(review.get("improvement_prompt") or ""),
        "source_sha256": source_sha256,
        "visual_blueprint_sha256": visual_blueprint_sha256,
        "draft_identity_sha256": identity,
        "parts": list(manifest.get("parts") or []),
    })
    return False, score


def restore_best_draft(directory: Path) -> None:
    """Restore exact staged fragments and assembled SVG from the best snapshot."""
    snapshot = _snapshot_root(directory)
    best = _load(snapshot / "best.json")
    manifest = _load(snapshot / "manifest.json")
    if not best or not manifest:
        raise ValueError("best draft composition snapshot is missing")
    parts = directory / "parts"
    allowed = {str(name) for name in best.get("parts") or []}
    if allowed:
        parts.mkdir(parents=True, exist_ok=True)
        for current in parts.glob("*.svgfrag"):
            if current.name not in allowed:
                current.unlink()
        for name in allowed:
            shutil.copy2(snapshot / "parts" / name, parts / name)
    artifact_name = str(manifest.get("artifact_name") or "")
    source = snapshot / f"{artifact_name}.svg"
    atomic_write_text(directory / source.name, source.read_text(encoding="utf-8"))
    atomic_write_json(directory / "manifest.json", manifest)
    for name in _CONTRACT_FILES:
        current = directory / name
        saved = snapshot / name
        if saved.is_file():
            shutil.copy2(saved, current)
        else:
            current.unlink(missing_ok=True)
