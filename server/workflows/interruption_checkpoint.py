"""Durable execution boundaries and manual continuation after any interruption.

The checkpoint records orchestration progress, never fabricates research output.
Accepted phases and stage-specific receipts remain owned by their validators.
"""
from __future__ import annotations

import time
from typing import Any

from .run_state import RunState


def mark_boundary(run: Any, node: Any, stage: str, *, result: str = "") -> None:
    def update(state: dict) -> None:
        phase = state.get("phases", {}).get(node.id)
        if not phase or phase.get("status") == "accepted":
            return
        details = phase.setdefault("details", {})
        previous = details.get("execution_checkpoint", {})
        details["execution_checkpoint"] = {
            "schema": 1, "stage": stage, "updated_at": time.time(),
            "session_id": str(getattr(node, "session_id", "") or previous.get("session_id", "")),
            "result": result or previous.get("result", ""),
        }
    RunState(run.project_path, run.id).update_state(update)


def record_interruption(run: Any, node: Any, reason: str, *, kind: str) -> dict:
    record: dict = {}
    def update(state: dict) -> None:
        repair = state.get("active_owner_revision") or {}
        owner_phase = state.get("phases", {}).get(repair.get("owner_node"), {})
        if (getattr(node, "id", "") not in {repair.get("owner_node"), repair.get("consumer_node")}
                or owner_phase.get("status") == "accepted"):
            repair = {}
        owner_id = repair.get("owner_node") or getattr(node, "id", "")
        owner = next((item for item in run.nodes if item.id == owner_id), node)
        phase = state.get("phases", {}).get(owner_id, {})
        checkpoint = phase.get("details", {}).get("execution_checkpoint", {})
        record.update({"schema": 1, "node_id": owner_id,
                       "consumer_node": repair.get("consumer_node") or getattr(node, "id", ""),
                       "owner_node": owner_id, "input_signature": repair.get("input_signature", ""),
                       "substage": repair.get("substage", ""), "delegate_session_id": repair.get("delegate_session_id", ""),
                       "stage": repair.get("stage") or checkpoint.get("stage", "primary"),
                       "session_id": str(getattr(owner, "session_id", "") or checkpoint.get("session_id", "")),
                       "kind": kind, "reason": reason, "interrupted_at": time.time(),
                       "manual_resume_required": True})
        state["interruption"] = dict(record)
        if phase and phase.get("status") != "accepted":
            phase.setdefault("details", {})["interruption"] = dict(record)
            if owner_id != getattr(node, "id", ""):
                phase.update(status="pending", error=reason, verdict_id="", reviewer="", accepted_at=None)
                from .models import NodeStatus
                owner.status = NodeStatus.IDLE
    RunState(run.project_path, run.id).update_state(update)
    return record


def manual_resume_required(state: dict) -> bool:
    return bool(state.get("manual_resume_required")
                or state.get("interruption", {}).get("manual_resume_required"))


def acknowledge_manual_resume(durable: RunState) -> None:
    def update(state: dict) -> None:
        state.pop("manual_resume_required", None)
        record = state.get("interruption")
        if isinstance(record, dict):
            record["manual_resume_required"] = False
            record["resumed_at"] = time.time()
        # Keep phase checkpoints until acceptance, for same-process and restart recovery.
    durable.update_state(update)


def resume_execution_stage(phase: dict) -> str:
    details = phase.get("details") or {}
    checkpoint = details.get("execution_checkpoint") or {}
    if phase.get("status") != "accepted" and (details.get("interruption") or phase.get("status") == "running"):
        return str(checkpoint.get("stage") or "primary")
    return ""
