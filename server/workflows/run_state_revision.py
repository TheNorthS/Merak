"""Revision gate state and targeted-repair checkpoints."""

from __future__ import annotations

import time
from typing import Any

from .run_state_support import _clean_string_list, _clear_run_terminal_fields, _state_mutation


def _gate_issues(gate: dict[str, Any]) -> list[str]:
    issues = [
        str(item).strip()[:1000]
        for item in list(gate.get("issues") or [])[:30]
        if str(item).strip()
    ]
    if issues:
        return issues
    fallback = str(gate.get("summary") or gate.get("reason") or "").strip()
    return [fallback[:1000]] if fallback else [
        "质量门未通过，但校验器没有返回结构化问题；请查看对应节点的质量报告。"
    ]


def _repair_scope(gate: dict[str, Any]) -> dict[str, list[str]]:
    scope = gate.get("repair_scope")
    if not isinstance(scope, dict):
        return {}
    return {
        "finding_ids": _clean_string_list(scope.get("finding_ids")),
        "target_files": _clean_string_list(scope.get("target_files")),
        "asset_ids": _clean_string_list(scope.get("asset_ids")),
    }


def _revision_progress(gate: dict[str, Any]) -> dict[str, Any]:
    progress = gate.get("revision_progress")
    return dict(progress) if isinstance(progress, dict) else {}


def _clear_stale_transport(revision: dict[str, Any], gate: dict[str, Any]) -> None:
    categories = {"transport", "network", "provider_transport", "model_transport"}
    category = str(gate.get("error_category") or "").strip().casefold()
    if gate.get("transport_exhausted") is True or category in categories:
        return
    for key in (
        "transport_exhausted", "max_transport_attempts", "error_type",
        "error_category", "retryable", "transport_retry_count", "next_retry_at",
        "retry_delay_seconds", "max_transport_checkpoint_retries",
    ):
        revision.pop(key, None)


def _last_gate(gate: dict[str, Any]) -> dict[str, Any]:
    decision = gate.get("decision_brief")
    components = gate.get("component_statuses")
    return {
        "reason": str(gate.get("reason") or ""),
        "summary": str(gate.get("summary") or "")[:4000],
        "score": gate.get("score"), "threshold": gate.get("threshold"),
        "issues": _gate_issues(gate), "report_path": str(gate.get("report_path") or ""),
        "decision_brief": dict(decision or {}) if isinstance(decision, dict) else {},
        "component_statuses": dict(components or {}) if isinstance(components, dict) else {},
        "intervention_kind": str(gate.get("intervention_kind") or "platform_repair"),
        "requires_human_decision": bool(gate.get("requires_human_decision", False)),
        "hard_limit": bool(gate.get("hard_limit", False)),
        "stopped_for_no_progress": bool(gate.get("stopped_for_no_progress", False)),
        "stopped_for_deterministic_stage": bool(gate.get("stopped_for_deterministic_stage", False)),
        "stopped_for_managed_stage": bool(gate.get("stopped_for_managed_stage", False)),
        "error_type": str(gate.get("error_type") or ""),
        "error_category": str(gate.get("error_category") or ""),
        "retryable": bool(gate.get("retryable", False)),
        "transport_retry_count": max(0, int(gate.get("transport_retry_count") or 0)),
        "next_retry_at": float(gate.get("next_retry_at") or 0.0),
        "retry_delay_seconds": float(gate.get("retry_delay_seconds") or 0.0),
        "max_transport_checkpoint_retries": max(
            0, int(gate.get("max_transport_checkpoint_retries") or 0),
        ),
        "repair_scope": _repair_scope(gate),
        "revision_progress": _revision_progress(gate),
    }


def _apply_stop_fields(revision: dict[str, Any], gate: dict[str, Any]) -> None:
    for key in (
        "hard_limit", "stopped_for_no_progress", "stopped_for_deterministic_stage",
        "stopped_for_managed_stage",
    ):
        revision[key] = bool(gate.get(key, False))
    for key in (
        "transport_exhausted", "max_transport_attempts", "intervention_kind",
        "requires_human_decision", "error_type", "error_category", "retryable",
        "transport_retry_count", "next_retry_at", "retry_delay_seconds",
        "max_transport_checkpoint_retries",
    ):
        if key in gate:
            revision[key] = gate[key]


class RunStateRevisionMixin:
    @_state_mutation
    def record_revision_gate(
        self,
        phase_id: str,
        *,
        round_number: int,
        cycle: int,
        gate: dict[str, Any],
        owner_id: str = "",
        owner_rounds: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        """Append one quality-gate observation without turning it into a failure."""
        state = self.load()
        if not state:
            return {}
        phase = state.setdefault("phases", {}).setdefault(phase_id, {"id": phase_id})
        details = phase.setdefault("details", {})
        revision = details.setdefault("revision", {"round": 0, "cycle": 1, "history": []})
        clean_owner_id = str(owner_id or "").strip()
        if clean_owner_id:
            revision["round"] = int(round_number)
            revision["active_owner_id"] = clean_owner_id
        else:
            revision["round"] = max(int(revision.get("round") or 0), int(round_number))
        if owner_rounds is not None:
            revision["owner_rounds"] = {
                str(key): max(0, int(value))
                for key, value in owner_rounds.items()
                if str(key).strip()
            }
        revision["cycle"] = max(1, int(cycle))
        revision["waiting"] = False
        revision.pop("waiting_since", None)
        history = revision.setdefault("history", [])
        history.append({
            "gate_attempt": len(history) + 1,
            "round": int(round_number),
            "owner_id": clean_owner_id,
            "cycle": int(cycle),
            "accepted": bool(gate.get("accepted")),
            "reason": str(gate.get("reason") or ""),
            "summary": str(gate.get("summary") or "")[:4000],
            "score": gate.get("score"),
            "threshold": gate.get("threshold"),
            "issues": _gate_issues(gate),
            "report_path": str(gate.get("report_path") or ""),
            "timestamp": time.time(),
            # Keep the structured repair identity with the durable history.
            # The UI/event stream is not a reliable source after a process
            # restart, and dropping this data makes a resumed no-progress
            # checkpoint look like a fresh finding.
            "repair_scope": _repair_scope(gate),
            "revision_progress": _revision_progress(gate),
        })
        # Bound disk growth while retaining enough history for forensic review.
        if len(history) > 200:
            revision["history"] = history[-200:]
        self.save_state(state)
        return revision

    @_state_mutation
    def require_consumer_refresh(
        self,
        phase_id: str,
        *,
        owner_id: str,
        reason: str,
    ) -> None:
        """Persist that a managed consumer must regenerate its verdict.

        Review and audit findings are snapshots of their upstream source
        bundle.  Once an upstream owner is repaired, reusing that snapshot can
        route the same obsolete finding back to the owner indefinitely.  Keep
        this marker durable so a backend restart cannot lose the required
        reviewer/auditor refresh.
        """
        state = self.load()
        if not state:
            return
        phase = state.setdefault("phases", {}).setdefault(
            phase_id,
            {"id": phase_id},
        )
        revision = phase.setdefault("details", {}).setdefault(
            "revision",
            {"round": 0, "cycle": 1, "history": []},
        )
        revision["consumer_refresh_required"] = True
        revision["consumer_refresh_owner_id"] = str(owner_id or "")
        revision["consumer_refresh_reason"] = str(reason or "")[:2000]
        revision["consumer_refresh_requested_at"] = time.time()
        _clear_run_terminal_fields(state)
        state["status"] = "running"
        self.save_state(state)

    @_state_mutation
    def clear_consumer_refresh(self, phase_id: str) -> None:
        """Clear a durable consumer-refresh marker after fresh execution."""
        state = self.load()
        if not state:
            return
        phase = state.get("phases", {}).get(phase_id)
        if not isinstance(phase, dict):
            return
        details = phase.get("details")
        revision = details.get("revision") if isinstance(details, dict) else None
        if not isinstance(revision, dict):
            return
        for key in (
            "consumer_refresh_required",
            "consumer_refresh_owner_id",
            "consumer_refresh_reason",
            "consumer_refresh_requested_at",
        ):
            revision.pop(key, None)
        revision["consumer_refreshed_at"] = time.time()
        self.save_state(state)

    @_state_mutation
    def set_revision_waiting(
        self,
        phase_id: str,
        *,
        round_number: int,
        cycle: int,
        gate: dict[str, Any],
        artifact_signature: str = "",
        artifact_owner_id: str = "",
        runtime_signature: str = "",
        owner_rounds: dict[str, int] | None = None,
    ) -> None:
        """Persist a resumable research-revision checkpoint."""
        state = self.load()
        if not state:
            return
        phase = state.setdefault("phases", {}).setdefault(phase_id, {"id": phase_id})
        phase["status"] = "awaiting_revision"
        phase["finished_at"] = time.time()
        phase.pop("error", None)
        revision = phase.setdefault("details", {}).setdefault(
            "revision", {"round": 0, "cycle": 1, "history": []}
        )
        _clear_stale_transport(revision, gate)
        revision.update({
            "round": int(round_number),
            "cycle": int(cycle),
            "waiting": True,
            "waiting_since": time.time(),
            "prompt_acknowledged": False,
            "artifact_signature": str(artifact_signature or ""),
            "artifact_owner_id": str(artifact_owner_id or phase_id),
            "runtime_signature": str(runtime_signature or ""),
            "last_gate": _last_gate(gate),
        })
        clean_owner_id = str(artifact_owner_id or phase_id)
        revision["active_owner_id"] = clean_owner_id
        if owner_rounds is not None:
            revision["owner_rounds"] = {
                str(key): max(0, int(value))
                for key, value in owner_rounds.items()
                if str(key).strip()
            }
        _apply_stop_fields(revision, gate)
        _clear_run_terminal_fields(state)
        state["status"] = "running"
        self.save_state(state)

    @_state_mutation
    def reset_revision_for_runtime_change(
        self,
        phase_id: str,
        *,
        runtime_signature: str,
        reason: str,
    ) -> None:
        """Reopen a blocked node when the engine gains new remediation ability."""
        state = self.load()
        if not state:
            return
        phase = state.get("phases", {}).get(phase_id)
        if not isinstance(phase, dict):
            return
        revision = phase.setdefault("details", {}).setdefault(
            "revision", {"round": 0, "cycle": 1, "history": []}
        )
        resets = revision.setdefault("runtime_resets", [])
        resets.append({
            "previous_runtime_signature": str(
                revision.get("runtime_signature") or ""
            ),
            "runtime_signature": str(runtime_signature or ""),
            "reason": str(reason or "runtime capability changed"),
            "timestamp": time.time(),
        })
        if len(resets) > 20:
            del resets[:-20]
        revision["round"] = 0
        revision["cycle"] = max(1, int(revision.get("cycle") or 1) + 1)
        revision["waiting"] = False
        revision["runtime_signature"] = str(runtime_signature or "")
        revision["progress_history_start"] = len(revision.get("history") or [])
        revision.pop("artifact_signature", None)
        revision.pop("active_owner_id", None)
        revision.pop("owner_rounds", None)
        revision.pop("waiting_since", None)
        revision.pop("prompt_acknowledged", None)
        revision.pop("prompt_acknowledged_at", None)
        # The previous gate's semantic-progress counters belong to the old
        # runtime capability. Keeping them makes an upgraded deterministic
        # repair stop immediately as if its new first attempt were the third
        # unchanged attempt from the prior implementation.
        for key in (
            "last_gate",
            "repair_scope",
            "revision_progress",
            "stopped_for_no_progress",
            "stopped_for_deterministic_stage",
            "stopped_for_managed_stage",
            "hard_limit",
            "transport_exhausted",
        ):
            revision.pop(key, None)
        phase["status"] = "done"
        phase["error"] = ""
        phase["finished_at"] = time.time()
        _clear_run_terminal_fields(state)
        state["status"] = "running"
        self.save_state(state)
