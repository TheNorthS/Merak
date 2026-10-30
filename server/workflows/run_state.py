"""Durable workflow run-state with accepted gates.

This mirrors the original MERAK contract: a phase is only terminal after it is
accepted by a context-isolated reviewer or deterministic verifier. A plain `done`
state means the executor produced artifacts, but those artifacts must be
re-validated on resume before downstream phases can trust them.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Optional


from .run_state_support import (
    PhaseState as PhaseState,
    TERMINAL_PHASE_STATES,
    _clear_run_terminal_fields,
    _state_mutation,
)


from .workflow_lease import ProjectRunLease as ProjectRunLease
from .run_state_lifecycle import RunStateLifecycleMixin
from .run_state_resume import RunStateResumeMixin
from .run_state_revision import RunStateRevisionMixin
from .run_state_recovery import RunStateRecoveryMixin


class RunState(
    RunStateLifecycleMixin,
    RunStateResumeMixin,
    RunStateRevisionMixin,
    RunStateRecoveryMixin,
):
    """Project-local run-state persisted under `.merak/runs/`."""

    def __init__(self, project_path: str, run_id: str):
        self.project_path = Path(project_path or ".").expanduser().resolve()
        self.run_id = run_id
        self.runs_dir = self.project_path / ".merak" / "runs"
        self.path = self.runs_dir / f"{run_id}.json"
        self._thread_snapshot = threading.local()

    @_state_mutation
    def accept(self, phase_id: str, verdict_id: str, reviewer: str, details: Optional[dict[str, Any]] = None) -> None:
        if not verdict_id or not reviewer:
            raise ValueError("accept requires non-empty verdict_id and reviewer")
        state = self.load()
        if not state:
            return
        phase = state.setdefault("phases", {}).setdefault(phase_id, {"id": phase_id})
        if phase.get("status") not in {"done", "accepted"}:
            raise ValueError("accept requires the phase to be done first")
        phase["status"] = "accepted"
        phase["error"] = ""
        phase["verdict_id"] = verdict_id
        phase["reviewer"] = reviewer
        phase["accepted_at"] = time.time()
        phase["finished_at"] = phase.get("finished_at") or phase["accepted_at"]
        revision = phase.get("details", {}).get("revision")
        if isinstance(revision, dict):
            # A resolved phase must not remain visually resumable after a later
            # successful validation. Keep its history for auditability, but
            # clear transient stop flags that would otherwise resurrect an old
            # timeout/error prompt after restart.
            revision["waiting"] = False
            revision.pop("waiting_since", None)
            revision["transport_exhausted"] = False
            revision["hard_limit"] = False
            revision["stopped_for_no_progress"] = False
            revision["stopped_for_deterministic_stage"] = False
            revision["stopped_for_managed_stage"] = False
            revision["prompt_acknowledged"] = True
            revision["resolved_at"] = phase["accepted_at"]
            revision["resolved_verdict_id"] = verdict_id
            revision["resolved_reviewer"] = reviewer
            previous_gate = (
                revision.get("last_gate")
                if isinstance(revision.get("last_gate"), dict)
                else {}
            )
            accepted_gate = {
                "accepted": True,
                "reason": "",
                "summary": f"节点已通过 {reviewer} 验收。",
                "score": None,
                "threshold": None,
                "issues": [],
                "report_path": str(previous_gate.get("report_path") or ""),
                "verdict_id": verdict_id,
                "resolved_at": phase["accepted_at"],
            }
            revision["last_gate"] = accepted_gate
            history = revision.setdefault("history", [])
            if not history or not bool(history[-1].get("accepted")):
                history.append({
                    "gate_attempt": len(history) + 1,
                    "round": int(revision.get("round") or 0),
                    "cycle": int(revision.get("cycle") or 1),
                    **accepted_gate,
                    "timestamp": phase["accepted_at"],
                })
                if len(history) > 200:
                    del history[:-200]
        if details:
            phase.setdefault("details", {}).update(details)
        from .owner_revision_transaction import finish_consumer_revision
        finish_consumer_revision(state, phase_id)
        from .report_revision_store import close_reports
        close_reports(state, phase_id)
        self.save_state(state)

    def resume_point(self, selected_phase_ids: list[str]) -> Optional[str]:
        state = self.load()
        if not state:
            return selected_phase_ids[0] if selected_phase_ids else None
        phases = state.get("phases", {})
        for phase_id in selected_phase_ids:
            status = phases.get(phase_id, {}).get("status", "pending")
            if status not in TERMINAL_PHASE_STATES:
                return phase_id
        return None

    @staticmethod
    def resumable_phase_ids_from_state(
        state: Optional[dict[str, Any]],
        selected_phase_ids: Optional[list[str]] = None,
    ) -> list[str]:
        """Return registered phases that still require execution or validation."""
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
            if str(phases.get(phase_id, {}).get("status", "pending")) not in TERMINAL_PHASE_STATES
        ]

    def resumable_phase_ids(self, selected_phase_ids: Optional[list[str]] = None) -> list[str]:
        return self.resumable_phase_ids_from_state(self.load(), selected_phase_ids)

    def accepted_phase_ids(self) -> list[str]:
        state = self.load()
        if not state:
            return []
        return [
            phase_id
            for phase_id, phase in state.get("phases", {}).items()
            if phase.get("status") == "accepted"
        ]

    @_state_mutation
    def set_run_status(self, status: str) -> None:
        if status not in {"running", "incomplete", "failed", "cancelled"}:
            raise ValueError(f"invalid run status: {status}")
        state = self.load()
        if not state:
            return
        _clear_run_terminal_fields(state)
        state["status"] = status
        if status != "running":
            state["finished_at"] = time.time()
        self.save_state(state)

    @_state_mutation
    def complete(
        self,
        completion: Optional[dict[str, Any]] = None,
    ) -> bool:
        state = self.load()
        if not state:
            return False
        if self.resumable_phase_ids_from_state(state):
            state["status"] = "incomplete"
            state["finished_at"] = time.time()
            self.save_state(state)
            return False
        state["status"] = "completed"
        if isinstance(completion, dict):
            state["completion"] = dict(completion)
            state["execution_completed"] = bool(
                completion.get("execution_completed")
            )
            state["submission_ready"] = bool(
                completion.get("submission_ready")
            )
            state["completion_class"] = str(
                completion.get("completion_class") or ""
            )
        state.pop("auto_rebuild_required", None)
        state["finished_at"] = time.time()
        self.save_state(state)
        return True


