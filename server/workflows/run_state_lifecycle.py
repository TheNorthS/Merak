"""Core lifecycle persistence for a workflow run."""

from __future__ import annotations

import copy
import json
import time
from typing import Any, Callable, Optional

from ..utils.atomic_write import atomic_write_json, path_lock
from .run_state_support import (
    PhaseState,
    TERMINAL_PHASE_STATES,
    _clear_run_terminal_fields,
    _merge_state_changes,
    _state_mutation,
)


class RunStateLifecycleMixin:
    @_state_mutation
    def start(
        self,
        phases: list[dict[str, Any]],
        config: dict[str, Any],
        input_baseline: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        existing = self.load()
        if existing:
            existing_phases = existing.setdefault("phases", {})
            for item in phases:
                phase_id = item["id"]
                if phase_id not in existing_phases:
                    existing_phases[phase_id] = PhaseState(
                        id=phase_id,
                        name=item.get("name", phase_id),
                        skill=item.get("skill", ""),
                        execution_kind=item.get("execution_kind", "model_owned"),
                        runtime_service=item.get("runtime_service", ""),
                        policy_required=bool(item.get("policy_required", True)),
                    ).__dict__
                else:
                    existing_phase = existing_phases[phase_id]
                    existing_phase["execution_kind"] = item.get(
                        "execution_kind", existing_phase.get("execution_kind", "model_owned")
                    )
                    existing_phase["runtime_service"] = item.get(
                        "runtime_service", existing_phase.get("runtime_service", "")
                    )
                    existing_phase["policy_required"] = bool(item.get(
                        "policy_required", existing_phase.get("policy_required", True)
                    ))
            _clear_run_terminal_fields(existing)
            existing["status"] = "running"
            existing["config"] = config
            if input_baseline and not existing.get("input_baseline"):
                existing["input_baseline"] = input_baseline
            self.save_state(existing)
            return existing
        now = time.time()
        state = {
            "schema": 1,
            "run_id": self.run_id,
            "status": "running",
            "created_at": now,
            "updated_at": now,
            "config": config,
            "input_baseline": input_baseline or {},
            "phases": {
                item["id"]: PhaseState(
                    id=item["id"],
                    name=item.get("name", item["id"]),
                    skill=item.get("skill", ""),
                    execution_kind=item.get("execution_kind", "model_owned"),
                    runtime_service=item.get("runtime_service", ""),
                    policy_required=bool(item.get("policy_required", True)),
                ).__dict__
                for item in phases
            },
        }
        self.save_state(state)
        return state

    @_state_mutation
    def invalidate_acceptance(self, phase_id: str, reason: str) -> None:
        """Return a stale accepted phase to deterministic revalidation."""
        state = self.load()
        if not state:
            return
        phase = state.get("phases", {}).get(phase_id)
        if not isinstance(phase, dict) or phase.get("status") not in TERMINAL_PHASE_STATES:
            return
        now = time.time()
        previous = {
            "verdict_id": str(phase.get("verdict_id") or ""),
            "reviewer": str(phase.get("reviewer") or ""),
            "accepted_at": phase.get("accepted_at"),
            "invalidated_at": now,
            "reason": str(reason or "accepted artifact changed"),
        }
        details = phase.setdefault("details", {})
        history = details.setdefault("acceptance_invalidations", [])
        previous_revision = details.get("revision")
        if isinstance(previous_revision, dict):
            previous["previous_revision_round"] = int(
                previous_revision.get("round") or 0
            )
            previous["previous_revision_cycle"] = int(
                previous_revision.get("cycle") or 1
            )
        history.append(previous)
        if len(history) > 20:
            del history[:-20]
        # An accepted phase that becomes stale is now solving a different
        # problem against a different scientific input state.  Reusing an
        # exhausted 6/6 counter made deterministic revalidation detect the new
        # issue and then stop without performing even one repair.  Preserve
        # the former cycle in acceptance_invalidations above, while granting
        # this newly invalidated state a fresh bounded revision budget.
        details["revision"] = {
            "round": 0,
            "cycle": max(
                1,
                int(previous_revision.get("cycle") or 1) + 1,
            ) if isinstance(previous_revision, dict) else 1,
            "history": [],
            "waiting": False,
            "prompt_acknowledged": True,
        }
        phase["status"] = "done"
        phase["error"] = ""
        phase["finished_at"] = now
        phase["verdict_id"] = ""
        phase["reviewer"] = ""
        phase["accepted_at"] = None
        _clear_run_terminal_fields(state)
        state["status"] = "running"
        self.save_state(state)

    @_state_mutation
    def reopen_for_upstream_change(
        self,
        phase_id: str,
        *,
        owner_id: str,
        reason: str,
        loop_cycle: int,
    ) -> bool:
        """Reset one dependent phase so it is executed again, not just rechecked."""
        state = self.load()
        if not state:
            return False
        phase = state.get("phases", {}).get(phase_id)
        if not isinstance(phase, dict):
            return False
        now = time.time()
        details = phase.setdefault("details", {})
        history = details.setdefault("research_loop_rebuilds", [])
        previous_revision = details.get("revision")
        history.append({
            "owner_id": str(owner_id),
            "reason": str(reason or "upstream scientific artifact changed"),
            "loop_cycle": max(1, int(loop_cycle)),
            "previous_status": str(phase.get("status") or "pending"),
            "previous_verdict_id": str(phase.get("verdict_id") or ""),
            "previous_reviewer": str(phase.get("reviewer") or ""),
            "previous_revision_round": (
                int(previous_revision.get("round") or 0)
                if isinstance(previous_revision, dict)
                else 0
            ),
            "reopened_at": now,
        })
        if len(history) > 20:
            del history[:-20]
        # A new upstream scientific state grants a fresh bounded repair budget.
        # Keep the old history above for audit, but do not let its exhausted
        # revision counter block the new dependency cycle.
        details["revision"] = {
            "round": 0,
            "cycle": max(1, int(loop_cycle)),
            "history": [],
            "waiting": False,
            "prompt_acknowledged": True,
        }
        for key in (
            "artifact_baseline",
            "artifact_snapshot",
            "risk_audit_bound",
            "artifact_snapshot_bound_at",
            "research_quality",
            "node_risk_audit",
            "execution_evidence",
            "execution_gate_applied",
            "transport_retry",
        ):
            details.pop(key, None)
        phase["status"] = "pending"
        phase["error"] = ""
        phase["started_at"] = None
        phase["finished_at"] = None
        phase["accepted_at"] = None
        phase["verdict_id"] = ""
        phase["reviewer"] = ""
        _clear_run_terminal_fields(state)
        state["status"] = "running"
        self.save_state(state)
        return True

    @_state_mutation
    def refresh_accepted_details(
        self,
        phase_id: str,
        details: dict[str, Any],
        *,
        reason: str,
    ) -> bool:
        """Refresh provenance for an accepted phase without changing its verdict."""
        state = self.load()
        if not state:
            return False
        phase = state.get("phases", {}).get(phase_id)
        if (
            not isinstance(phase, dict)
            or phase.get("status") not in TERMINAL_PHASE_STATES
        ):
            return False
        phase_details = phase.setdefault("details", {})
        phase_details.update(dict(details or {}))
        history = phase_details.setdefault("acceptance_rebindings", [])
        history.append({
            "reason": str(reason or "accepted downstream review"),
            "timestamp": time.time(),
            "verdict_id": str(phase.get("verdict_id") or ""),
            "reviewer": str(phase.get("reviewer") or ""),
        })
        if len(history) > 20:
            del history[:-20]
        self.save_state(state)
        return True

    def _load_disk(self) -> Optional[dict[str, Any]]:
        try:
            raw = self.path.read_text(encoding="utf-8-sig")
        except FileNotFoundError:
            return None
        except (OSError, UnicodeError) as exc:
            raise RuntimeError(f"Workflow run state is unreadable: {self.path}") from exc
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Workflow run state is corrupt: {self.path}") from exc
        if not isinstance(payload, dict):
            raise RuntimeError(f"Workflow run state is corrupt: {self.path}")
        return payload

    def load(self) -> Optional[dict[str, Any]]:
        state = self._load_disk()
        self._thread_snapshot.base = copy.deepcopy(state)
        return state

    def save_state(self, state: dict[str, Any]) -> None:
        with path_lock(self.path):
            self.runs_dir.mkdir(parents=True, exist_ok=True)
            existing = self._load_disk()
            base = getattr(self._thread_snapshot, "base", None)
            merged = (
                _merge_state_changes(base, state, existing)
                if isinstance(base, dict) and isinstance(existing, dict)
                else copy.deepcopy(state)
            )
            previous_rebuild = (
                existing.get("auto_rebuild_required")
                if isinstance(existing, dict)
                and isinstance(existing.get("auto_rebuild_required"), dict)
                else None
            )
            current_rebuild = (
                merged.get("auto_rebuild_required")
                if isinstance(merged.get("auto_rebuild_required"), dict)
                else None
            )
            if (
                previous_rebuild is not None
                and current_rebuild is not None
                and str(previous_rebuild.get("reason") or "")
                == str(current_rebuild.get("reason") or "")
            ):
                # Readiness refresh may reconstruct this marker. Preserve the
                # watchdog budget while the same invalidation is unresolved.
                for key in (
                    "recovery_attempt_count",
                    "recovery_max_attempts",
                    "recovery_last_attempt_at",
                    "recovery_last_phase_id",
                    "recovery_next_retry_at",
                    "recovery_exhausted",
                    "recovery_exhausted_at",
                ):
                    if key not in current_rebuild and key in previous_rebuild:
                        current_rebuild[key] = previous_rebuild[key]
            updated_at = time.time()
            state["updated_at"] = updated_at
            merged["updated_at"] = updated_at
            atomic_write_json(self.path, merged)
            self._thread_snapshot.base = copy.deepcopy(merged)

    def update_state(
        self,
        updater: Callable[[dict[str, Any]], Optional[dict[str, Any]]],
    ) -> Optional[dict[str, Any]]:
        """Run an external state mutation under the same full transaction lock."""

        with path_lock(self.path):
            current = self._load_disk()
            if not isinstance(current, dict):
                return None
            self._thread_snapshot.base = copy.deepcopy(current)
            replacement = updater(current)
            proposed = replacement if isinstance(replacement, dict) else current
            self.save_state(proposed)
            persisted = self._load_disk()
            return copy.deepcopy(persisted) if isinstance(persisted, dict) else None


