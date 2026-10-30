"""Pure policies used to decide whether persisted workflow phases may resume."""

from __future__ import annotations

import re
from typing import Any, Optional


def phase_requires_revalidation(phase_record: dict[str, Any]) -> bool:
    status = str(phase_record.get("status") or "")
    if status in {"done", "awaiting_revision", "running", "failed"}:
        return True
    details = phase_record.get("details")
    if (
        status in {"failed", "pending"}
        and isinstance(details, dict)
        and isinstance(details.get("timeout_artifact_recovery"), dict)
    ):
        return True
    if status != "pending":
        return False
    execution_attempts = details.get("execution_attempts") if isinstance(details, dict) else None
    if isinstance(execution_attempts, list) and execution_attempts:
        return True
    revision = details.get("revision") if isinstance(details, dict) else None
    if not isinstance(revision, dict):
        return False
    try:
        revision_round = int(revision.get("round") or 0)
    except (TypeError, ValueError):
        revision_round = 0
    return bool(revision_round > 0 or revision.get("history") or revision.get("last_gate"))


def phase_is_durably_terminal(phase_record: Any) -> bool:
    if not isinstance(phase_record, dict):
        return False
    status = str(phase_record.get("status") or "").strip().casefold()
    return status == "accepted"


def training_check_blocks_current_mode(
    assessment: dict[str, Any],
    options: dict[str, Any],
) -> bool:
    """A physical run requires explicit authorization; an absent flag is false."""

    from ..services.training_review_policy import review_blocks
    return review_blocks(assessment, options)


def resumable_phase_ids(
    state: Optional[dict[str, Any]],
    selected_phase_ids: Optional[list[str]] = None,
) -> list[str]:
    if not state:
        return list(selected_phase_ids or [])
    phases = state.get("phases", {})
    registered_ids = list(phases)
    if selected_phase_ids is not None:
        requested = set(selected_phase_ids)
        registered_ids = [phase_id for phase_id in registered_ids if phase_id in requested]
    return [
        phase_id
        for phase_id in registered_ids
        if not phase_is_durably_terminal(phases.get(phase_id, {}))
    ]


def phase_failed_from_timeout(phase_record: dict[str, Any]) -> bool:
    if str(phase_record.get("status") or "") != "failed":
        return False
    return bool(re.search(
        r"(?:TimeoutError|wall-time limit|request timeout|stream stalled)",
        str(phase_record.get("error") or ""),
        re.IGNORECASE,
    ))


def tool_artifact_path(data: dict[str, Any]) -> str:
    """Read the path from current structured tool events only."""
    direct = str(data.get("artifact_path") or "").strip()
    if direct:
        return direct
    raw_args = data.get("args")
    if isinstance(raw_args, dict):
        for key in ("path", "file_path", "target_path"):
            value = str(raw_args.get(key) or "").strip()
            if value:
                return value
    return ""
