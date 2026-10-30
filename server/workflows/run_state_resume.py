"""Resume lease and phase-status transitions for durable run state."""

from __future__ import annotations

import copy
import time
import uuid
from typing import Any, Optional

from ..utils.atomic_write import path_lock
from .run_state_support import _clear_run_terminal_fields, _state_mutation
from .workflow_lease import _effective_lease_expiry


class RunStateResumeMixin:
    def claim_resume(
        self,
        *,
        owner_id: str,
        expected_status: str = "",
        source: str = "explicit",
        lease_seconds: float = 86400.0,
    ) -> str:
        """Compare-and-set a durable lease before a process resumes this run."""

        with path_lock(self.path):
            current = self._load_disk()
            if not isinstance(current, dict):
                return ""
            if str(current.get("status") or "") == "cancelled" and source != "explicit":
                return ""
            if expected_status and str(current.get("status") or "") != expected_status:
                return ""
            now = time.time()
            existing = current.get("resume_claim")
            existing_expires_at = _effective_lease_expiry(existing)
            if (
                isinstance(existing, dict)
                and str(existing.get("token") or "")
                and existing_expires_at > now
            ):
                return ""
            base = copy.deepcopy(current)
            token = uuid.uuid4().hex
            current["resume_claim"] = {
                "token": token,
                "owner_id": str(owner_id),
                "source": str(source or "explicit"),
                "claimed_at": now,
                "renewed_at": now,
                "expires_at": now + max(60.0, float(lease_seconds)),
                "previous_status": str(current.get("status") or ""),
            }
            self._thread_snapshot.base = base
            self.save_state(current)
            return token

    def renew_resume_claim(
        self,
        token: str,
        *,
        lease_seconds: float = 86400.0,
    ) -> bool:
        with path_lock(self.path):
            current = self._load_disk()
            if not isinstance(current, dict):
                return False
            claim = current.get("resume_claim")
            if not isinstance(claim, dict) or claim.get("token") != token:
                return False
            base = copy.deepcopy(current)
            now = time.time()
            claim["renewed_at"] = now
            claim["expires_at"] = now + max(60.0, float(lease_seconds))
            self._thread_snapshot.base = base
            self.save_state(current)
            return True

    def release_resume_claim(self, token: str) -> bool:
        with path_lock(self.path):
            current = self._load_disk()
            if not isinstance(current, dict):
                return False
            claim = current.get("resume_claim")
            if not isinstance(claim, dict) or claim.get("token") != token:
                return False
            base = copy.deepcopy(current)
            current.pop("resume_claim", None)
            self._thread_snapshot.base = base
            self.save_state(current)
            return True

    @_state_mutation
    def record_transport_retry(
        self,
        phase_id: str,
        retry: dict[str, Any],
    ) -> None:
        """Persist transport diagnostics without changing phase lifecycle state."""
        state = self.load()
        if not state:
            return
        phase = state.get("phases", {}).get(phase_id)
        if not isinstance(phase, dict):
            return
        details = phase.get("details")
        if not isinstance(details, dict):
            details = {}
            phase["details"] = details
        details["transport_retry"] = copy.deepcopy(retry)
        self.save_state(state)

    @_state_mutation
    def set_status(
        self,
        phase_id: str,
        status: str,
        *,
        artifact: str = "",
        error: str = "",
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        if status == "accepted":
            raise ValueError("accepted may only be written with accept()")
        if status not in {"pending", "running", "done", "awaiting_revision", "skipped", "failed"}:
            raise ValueError(f"invalid phase status: {status}")
        state = self.load()
        if not state:
            return
        phase = state.setdefault("phases", {}).setdefault(phase_id, {"id": phase_id})
        previous_status = str(phase.get("status") or "pending")
        previous_started_at = phase.get("started_at")
        previous_finished_at = phase.get("finished_at")
        previous_error = str(phase.get("error") or "")
        previous_verdict_id = str(phase.get("verdict_id") or "")
        previous_reviewer = str(phase.get("reviewer") or "")
        previous_summary = str(
            (phase.get("details") or {}).get("summary") or ""
        ) if isinstance(phase.get("details"), dict) else ""
        phase["status"] = status
        phase["verdict_id"] = ""
        phase["reviewer"] = ""
        phase["accepted_at"] = None
        if status in {"pending", "running"} and isinstance(
            phase.get("details"), dict
        ):
            phase["details"].pop("summary", None)
        if artifact:
            phase["artifact"] = artifact
        if error:
            phase["error"] = error
        elif status in {"pending", "running", "done", "awaiting_revision"}:
            phase["error"] = ""
        if details:
            phase.setdefault("details", {}).update(details)
        now = time.time()
        if status == "pending":
            phase["started_at"] = None
            phase["finished_at"] = None
        if status == "running":
            if previous_status != "running" and previous_started_at:
                attempts = phase.setdefault("details", {}).setdefault("execution_attempts", [])
                attempts.append({
                    "status": previous_status,
                    "started_at": previous_started_at,
                    "finished_at": previous_finished_at,
                    "error": previous_error,
                    "verdict_id": previous_verdict_id,
                    "reviewer": previous_reviewer,
                    "summary": previous_summary,
                })
                if len(attempts) > 20:
                    del attempts[:-20]
            if previous_status != "running" or not previous_started_at:
                phase["started_at"] = now
            phase["finished_at"] = None
        if status in {"done", "awaiting_revision", "accepted", "skipped", "failed"}:
            phase["finished_at"] = now
        _clear_run_terminal_fields(state)
        state["status"] = "running" if status not in {"failed"} else "failed"
        self.save_state(state)

