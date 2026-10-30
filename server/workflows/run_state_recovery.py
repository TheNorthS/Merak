"""Platform recovery and reconciliation transitions for run state."""

from __future__ import annotations

import time
from typing import Any

from .run_state_support import _clear_run_terminal_fields, _state_mutation


_STOP_FLAGS = (
    "hard_limit", "stopped_for_no_progress", "stopped_for_deterministic_stage",
    "stopped_for_managed_stage", "transport_exhausted",
)


def _reset_platform_cycle(
    revision: dict[str, Any], runtime_signature: str,
) -> None:
    revision["round"] = 0
    revision["cycle"] = max(1, int(revision.get("cycle") or 1) + 1)
    revision["waiting"] = False
    revision["runtime_signature"] = str(runtime_signature or "")
    revision["intervention_kind"] = "platform_repair"
    revision["requires_human_decision"] = False
    for key in _STOP_FLAGS:
        revision[key] = False
    last_gate = revision.get("last_gate")
    if isinstance(last_gate, dict):
        for key in _STOP_FLAGS:
            last_gate[key] = False
    for key in (
        "artifact_signature", "active_owner_id", "owner_rounds", "waiting_since",
        "prompt_acknowledged", "prompt_acknowledged_at",
    ):
        revision.pop(key, None)


class RunStateRecoveryMixin:
    @_state_mutation
    def start_platform_recovery_cycle(
        self,
        phase_id: str,
        *,
        runtime_signature: str,
        reason: str,
    ) -> int:
        """Reopen a platform-owned checkpoint without losing its audit trail.

        Scientific revision rounds remain bounded inside each cycle.  This
        counter bounds fresh platform recovery cycles across recursive engine
        execution and backend restarts, so auto-proceed cannot become an
        unbounded model-cost loop.
        """
        state = self.load()
        if not state:
            return 0
        phase = state.get("phases", {}).get(phase_id)
        if not isinstance(phase, dict):
            return 0
        revision = phase.setdefault("details", {}).setdefault(
            "revision", {"round": 0, "cycle": 1, "history": []}
        )
        recovery_count = max(
            0,
            int(revision.get("platform_auto_recovery_count") or 0),
        ) + 1
        recoveries = revision.setdefault("platform_auto_recoveries", [])
        recoveries.append({
            "count": recovery_count,
            "previous_round": int(revision.get("round") or 0),
            "previous_cycle": int(revision.get("cycle") or 1),
            "reason": str(reason or "platform-owned checkpoint recovery"),
            "runtime_signature": str(runtime_signature or ""),
            "timestamp": time.time(),
        })
        if len(recoveries) > 20:
            del recoveries[:-20]
        revision["platform_auto_recovery_count"] = recovery_count
        revision["round"] = 0
        revision["cycle"] = max(1, int(revision.get("cycle") or 1) + 1)
        revision["waiting"] = False
        revision["runtime_signature"] = str(runtime_signature or "")
        revision["intervention_kind"] = "platform_repair"
        revision["requires_human_decision"] = False
        revision.pop("artifact_signature", None)
        revision.pop("active_owner_id", None)
        revision.pop("owner_rounds", None)
        revision.pop("waiting_since", None)
        revision.pop("prompt_acknowledged", None)
        revision.pop("prompt_acknowledged_at", None)
        phase["status"] = "done"
        phase["error"] = ""
        phase["finished_at"] = time.time()
        _clear_run_terminal_fields(state)
        state["status"] = "running"
        self.save_state(state)
        return recovery_count

    @_state_mutation
    def reopen_platform_repair_checkpoint(
        self,
        phase_id: str,
        *,
        runtime_signature: str,
        reason: str,
    ) -> None:
        """Start one fresh bounded cycle after an explicit workflow resume.

        Automatic platform recovery has its own cross-restart budget. Once that
        budget is exhausted, a later Resume action must still be able to test a
        repaired validator/runtime without requiring a meaningless artifact
        edit. This preserves the previous gate history and automatic recovery
        count while resetting only the active revision cycle.
        """
        state = self.load()
        if not state:
            return
        phase = state.get("phases", {}).get(phase_id)
        if not isinstance(phase, dict):
            return
        revision = phase.setdefault("details", {}).setdefault(
            "revision", {"round": 0, "cycle": 1, "history": []}
        )
        resumes = revision.setdefault("platform_checkpoint_resumes", [])
        resumes.append({
            "previous_round": int(revision.get("round") or 0),
            "previous_cycle": int(revision.get("cycle") or 1),
            "reason": str(reason or "platform-owned checkpoint resumed"),
            "runtime_signature": str(runtime_signature or ""),
            "timestamp": time.time(),
        })
        if len(resumes) > 20:
            del resumes[:-20]
        _reset_platform_cycle(revision, runtime_signature)
        if phase_id in {"review", "audit"}:
            # A managed consumer cannot repair a stale REVIEW_STATE/AUDIT_STATE
            # by merely revalidating it.  Explicit platform resume must force
            # one new hash-bound verdict after its upstream paper/evidence
            # bundle has changed.
            revision["consumer_refresh_required"] = True
            revision["consumer_refresh_owner_id"] = phase_id
        phase["status"] = "done"
        phase["error"] = ""
        phase["finished_at"] = time.time()
        _clear_run_terminal_fields(state)
        state["status"] = "running"
        self.save_state(state)

    @_state_mutation
    def begin_reconciliation_transaction(
        self,
        *,
        owner_id: str,
        artifact_signature: str,
        reason: str,
        invalidated_phase_ids: list[str],
        maximum_transactions: int,
    ) -> dict[str, Any]:
        """Persist and deduplicate cross-node scientific rebuild transactions."""
        state = self.load()
        if not state:
            return {"started": False, "missing_state": True, "count": 0}
        transactions = state.setdefault("reconciliation_transactions", [])
        owner_transactions = [
            item
            for item in transactions
            if isinstance(item, dict)
            and str(item.get("owner_id") or "") == str(owner_id)
        ]
        latest_owner = owner_transactions[-1] if owner_transactions else {}
        if (
            latest_owner
            and str(latest_owner.get("artifact_signature") or "")
            == str(artifact_signature or "")
        ):
            return {
                "started": False,
                "duplicate": True,
                "count": len(transactions),
                "transaction": latest_owner,
            }
        limit = max(1, int(maximum_transactions or 1))
        if len(transactions) >= limit:
            return {
                "started": False,
                "exhausted": True,
                "count": len(transactions),
            }
        transaction = {
            "id": f"reconcile-{len(transactions) + 1}",
            "owner_id": str(owner_id),
            "artifact_signature": str(artifact_signature or ""),
            "reason": str(reason or "upstream scientific artifact changed")[:2000],
            "invalidated_phase_ids": [
                str(item)
                for item in invalidated_phase_ids
                if str(item).strip()
            ],
            "started_at": time.time(),
        }
        transactions.append(transaction)
        if len(transactions) > 20:
            del transactions[:-20]
        state["research_loop_cycle"] = len(transactions)
        self.save_state(state)
        return {
            "started": True,
            "duplicate": False,
            "exhausted": False,
            "count": len(transactions),
            "transaction": transaction,
        }

    @_state_mutation
    def reset_for_reexecution(self, phase_id: str, *, reason: str) -> None:
        """Discard one phase's retry state when its generated verdict must be rebuilt."""
        state = self.load()
        if not state:
            return
        phase = state.get("phases", {}).get(phase_id)
        if not isinstance(phase, dict):
            return
        details = phase.setdefault("details", {})
        revision = details.get("revision")
        resets = details.setdefault("reexecution_resets", [])
        resets.append({
            "previous_status": str(phase.get("status") or ""),
            "previous_revision_round": (
                int(revision.get("round") or 0)
                if isinstance(revision, dict)
                else 0
            ),
            "previous_revision_cycle": (
                int(revision.get("cycle") or 1)
                if isinstance(revision, dict)
                else 1
            ),
            "reason": str(reason or "generated verdict requires reexecution"),
            "timestamp": time.time(),
        })
        if len(resets) > 20:
            del resets[:-20]
        details.pop("revision", None)
        details.pop("artifact_snapshot", None)
        details.pop("risk_audit_bound", None)
        details.pop("artifact_snapshot_bound_at", None)
        phase["status"] = "pending"
        phase["error"] = ""
        phase["verdict_id"] = ""
        phase["reviewer"] = ""
        phase["accepted_at"] = None
        phase["started_at"] = None
        phase["finished_at"] = None
        _clear_run_terminal_fields(state)
        state["status"] = "running"
        self.save_state(state)

    @_state_mutation
    def acknowledge_revision_checkpoint(self, phase_id: str) -> None:
        """Remember that the current hard-limit prompt was seen without waiving its gate."""
        state = self.load()
        if not state:
            return
        phase = state.get("phases", {}).get(phase_id, {})
        if phase.get("status") != "awaiting_revision":
            raise ValueError(f"Phase is not awaiting revision: {phase_id}")
        revision = phase.setdefault("details", {}).setdefault("revision", {})
        revision["prompt_acknowledged"] = True
        revision["prompt_acknowledged_at"] = time.time()
        self.save_state(state)

    def revision_state(self, phase_id: str) -> dict[str, Any]:
        state = self.load() or {}
        phase = state.get("phases", {}).get(phase_id, {})
        revision = phase.get("details", {}).get("revision", {})
        return dict(revision) if isinstance(revision, dict) else {}

    def human_checkpoint_consumed(self, phase_id: str) -> bool:
        state = self.load() or {}
        phase = state.get("phases", {}).get(phase_id, {})
        checkpoint = phase.get("details", {}).get("human_checkpoint", {})
        return bool(checkpoint.get("consumed")) if isinstance(checkpoint, dict) else False

    @_state_mutation
    def consume_human_checkpoint(
        self,
        phase_id: str,
        *,
        resolution: str,
        feedback_supplied: bool,
    ) -> None:
        """Persist a once-per-run/node checkpoint decision across retries and resumes."""
        state = self.load()
        if not state:
            return
        phase = state.setdefault("phases", {}).setdefault(phase_id, {"id": phase_id})
        phase.setdefault("details", {})["human_checkpoint"] = {
            "consumed": True,
            "resolution": str(resolution or "continued"),
            "feedback_supplied": bool(feedback_supplied),
            "consumed_at": time.time(),
        }
        self.save_state(state)

