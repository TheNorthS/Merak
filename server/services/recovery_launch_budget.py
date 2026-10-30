"""Persist bounded recovery-launch attempts before invoking the workflow engine."""
import hashlib
import json
from pathlib import Path

from ..utils.atomic_write import atomic_write_json, path_lock


def checkpoint_key(revision: dict) -> str:
    fields = ("cycle", "round", "transport_retry_count", "artifact_signature", "runtime_signature")
    return hashlib.sha256(json.dumps({key: revision.get(key) for key in fields}, sort_keys=True).encode()).hexdigest()


def launch_due(phase: dict, now: float) -> bool:
    details = phase.get("details") or {}
    budget = details.get("recovery_launch") or {}
    if budget.get("checkpoint_key") != checkpoint_key(details.get("revision") or {}):
        return True
    return not budget.get("exhausted") and float(budget.get("next_retry_at") or 0) <= now


def begin_launch(path: Path, phase_id: str, now: float) -> bool:
    with path_lock(path):
        state = json.loads(path.read_text(encoding="utf-8-sig"))
        phase = state["phases"][phase_id]
        if state.get("status") == "cancelled" or phase.get("status") != "awaiting_revision" or not launch_due(phase, now):
            return False
        details = phase.setdefault("details", {})
        revision = details.get("revision") or {}
        key = checkpoint_key(revision)
        budget = details.get("recovery_launch") or {}
        count = int(budget.get("attempts") or 0) if budget.get("checkpoint_key") == key else 0
        options = (state.get("config") or {}).get("options") or {}
        limit = min(12, max(1, int(revision.get("max_transport_checkpoint_retries")
                                 or options.get("model_transport_checkpoint_max_retries") or 4)))
        if count >= limit:
            return False
        count += 1
        details["recovery_launch"] = {"checkpoint_key": key, "attempts": count, "limit": limit,
                                      "exhausted": count >= limit, "started_at": now,
                                      "next_retry_at": now + min(3600, 30 * 2 ** (count - 1)), "status": "starting"}
        atomic_write_json(path, state)
    return True


def finish_launch(path: Path, phase_id: str, *, succeeded: bool, error: str = "") -> None:
    with path_lock(path):
        state = json.loads(path.read_text(encoding="utf-8-sig"))
        details = state.get("phases", {}).get(phase_id, {}).get("details", {})
        budget = details.get("recovery_launch")
        if not budget:
            return
        if succeeded:
            details.pop("recovery_launch", None)
        else:
            budget.update(status="failed", error=error[:1000])
        atomic_write_json(path, state)
