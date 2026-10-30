"""Revoke stale acceptance before cross-owner mutations, in one durable transaction."""
import time
from typing import Any


def begin_owner_revision(ctx: Any) -> None:
    owner, consumer = ctx.revision_owner, ctx.node
    if owner.id == consumer.id:
        return
    from .owner_revision_scope import owner_revision_dependents
    available = {node.id for node in ctx.host._get_default_nodes()}
    invalid = {owner.id, *owner_revision_dependents(ctx.host, owner.id, consumer.id, available)}
    def update(state: dict) -> None:
        state["active_owner_revision"] = {"owner_node": owner.id, "consumer_node": consumer.id,
            "stage": "primary", "session_id": "", "input_signature": ctx.scope_signature,
            "started_at": time.time()}
        for key in invalid:
            phase = state.get("phases", {}).get(key)
            if not phase:
                continue
            if phase.get("status") == "accepted":
                history = phase.setdefault("details", {}).setdefault("revoked_acceptances", [])
                history.append({"verdict_id": phase.get("verdict_id"), "at": time.time(), "owner": owner.id})
                del history[:-20]
                phase.update(status="pending", verdict_id="", reviewer="", accepted_at=None)
            if key == owner.id:
                phase["status"] = "running"
                phase.setdefault("details", {})["execution_checkpoint"] = {"schema": 1, "stage": "primary"}
    ctx.run_state.update_state(update)
    from .models import NodeStatus
    for node in ctx.run.nodes:
        if node.id in invalid and node.id != consumer.id:
            node.status = NodeStatus.RUNNING if node.id == owner.id else NodeStatus.IDLE


def update_owner_boundary(state: Any, owner: Any, stage: str) -> None:
    def update(saved: dict) -> None:
        repair = saved.get("active_owner_revision")
        if repair and repair.get("owner_node") == owner.id:
            repair.update(stage=stage, session_id=owner.session_id)
            saved["phases"][owner.id].setdefault("details", {})["execution_checkpoint"] = {
                "schema": 1, "stage": stage, "session_id": owner.session_id,
            }
    state.update_state(update)


def finish_consumer_revision(saved: dict, phase_id: str) -> None:
    """A fresh consumer acceptance ends its prior cross-owner repair transaction."""
    repair = saved.get("active_owner_revision")
    if not isinstance(repair, dict) or repair.get("consumer_node") != phase_id:
        return
    history = saved.setdefault("owner_revision_history", [])
    history.append({**repair, "resolved_at": time.time(), "resolution": "consumer_accepted"})
    del history[:-20]
    saved.pop("active_owner_revision", None)
