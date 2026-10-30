"""Read-only readiness checks for managed manuscript-review artifacts."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def _identity_issues(
    state: dict[str, Any],
    *,
    run_id: str,
    evidence_mode: str,
    current_hash: str,
    require_threshold: bool = True,
) -> tuple[list[str], str, str, list[str]]:
    issues: list[str] = []
    if state.get("managed_by") != "cross_model_review_loop":
        issues.append("review state was not produced by the managed review loop")
    if str(state.get("run_id") or "") != run_id:
        issues.append("review state belongs to a different workflow run")
    if str(state.get("evidence_mode") or "").casefold() != evidence_mode:
        issues.append("review evidence mode does not match the workflow")
    if state.get("policy_loaded") is not True:
        issues.append("review skill policy was not recorded as loaded")
    expected_hash = str(state.get("source_bundle_sha256") or "")
    if not expected_hash:
        issues.append("review state is missing its source bundle hash")
    elif expected_hash != current_hash:
        issues.append("independent review is stale relative to current sources")
    executor = str(state.get("executor_model") or "").strip()
    reviewer = str(state.get("reviewer_model") or "").strip()
    if not executor or not reviewer:
        issues.append("review state is missing executor/reviewer model identity")
    sessions = [
        str(item).strip() for item in state.get("reviewer_session_ids") or []
        if str(item).strip()
    ]
    if not sessions:
        issues.append("independent review has no durable reviewer session")
    if state.get("fallback_reason"):
        issues.append("independent review completed through a fallback path")
    if state.get("is_complete") is not True:
        issues.append("independent review loop is not complete")
    if require_threshold and state.get("threshold_met") is not True:
        issues.append("independent review did not meet its acceptance threshold")
    return issues, executor, reviewer, sessions


def _visual_issues(round_record: dict[str, Any]) -> list[str]:
    visual = round_record.get("visual_review")
    visual = visual if isinstance(visual, dict) else {}
    required = {
        "pdf_path", "figure_quality", "caption_alignment", "page_layout",
        "table_formatting", "visual_consistency",
    }
    if required.issubset(visual) and all(
        str(visual.get(key) or "").strip() for key in required
    ):
        return []
    return ["independent review is missing the compiled-PDF visual/layout attestation"]


def _final_snapshot_issues(
    root: Path,
    state: dict[str, Any],
    final_round: dict[str, Any],
    current_hash: str,
) -> tuple[list[str], str]:
    issues: list[str] = []
    snapshots = [item for item in state.get("pdf_snapshots") or [] if isinstance(item, dict)]
    try:
        round_number = int(state.get("current_round") or final_round.get("round") or 0)
    except (TypeError, ValueError):
        round_number = 0
    snapshot = next((
        item for item in reversed(snapshots)
        if str(item.get("round") or "").isdigit()
        and int(item.get("round") or 0) == round_number
    ), None)
    if snapshot is None:
        return ["managed review has no final compiled PDF snapshot"], ""
    raw_snapshot = str(snapshot.get("snapshot_path") or "")
    snapshot_path = (root / raw_snapshot).resolve()
    layout_path = (root / str(snapshot.get("layout_report_path") or "")).resolve()
    try:
        snapshot_path.relative_to(root)
        layout_path.relative_to(root)
    except ValueError:
        return ["managed review PDF snapshot path leaves the project"], ""
    if not snapshot_path.is_file() or snapshot_path.stat().st_size <= 0:
        issues.append("managed review final PDF snapshot is missing or invalid")
    elif snapshot_path.read_bytes()[:5] != b"%PDF-":
        issues.append("managed review final PDF snapshot is missing or invalid")
    elif str(snapshot.get("pdf_sha256") or "") != _sha256(snapshot_path):
        issues.append("managed review final PDF snapshot hash does not match")
    if not layout_path.is_file():
        issues.append("managed review final PDF layout report is missing")
    if str(snapshot.get("source_bundle_sha256") or "") != current_hash:
        issues.append("managed review final PDF snapshot is stale")
    return issues, raw_snapshot


def review_readiness_issues(
    root: Path,
    state: dict[str, Any],
    *,
    run_id: str,
    evidence_mode: str,
    require_threshold: bool = True,
) -> tuple[list[str], dict[str, Any]]:
    from ..workflows.review_audit import review_source_bundle

    current_hash, source_paths = review_source_bundle(root)
    issues, executor, reviewer, sessions = _identity_issues(
        state, run_id=run_id, evidence_mode=evidence_mode, current_hash=current_hash,
        require_threshold=require_threshold,
    )
    rounds = [item for item in state.get("rounds") or [] if isinstance(item, dict)]
    final_round = rounds[-1] if rounds else {}
    issues.extend(_visual_issues(final_round))
    snapshot_issues, snapshot_path = _final_snapshot_issues(
        root, state, final_round, current_hash
    )
    issues.extend(snapshot_issues)
    return issues, {
        "source_bundle_sha256": current_hash,
        "source_count": len(source_paths),
        "reviewer_session_ids": sessions,
        "executor_model": executor,
        "reviewer_model": reviewer,
        "final_pdf_snapshot": snapshot_path,
        "visual_review_complete": not any(
            "visual/layout attestation" in issue for issue in issues
        ),
    }
