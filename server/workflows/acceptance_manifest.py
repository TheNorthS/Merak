"""A derived human-readable manifest cannot revoke a committed scientific verdict."""
from .run_state import RunState


def acceptance_details(gate: dict, node_id: str) -> dict:
    return {**gate.get("details", {}), "manifest_delivery": {
        "node_id": node_id, "verdict_id": gate["verdict_id"],
        "summary": gate.get("summary", ""), "status": "pending",
    }}


def deliver_acceptance_manifests(host, run) -> list[dict]:
    state = RunState(run.project_path, run.id)
    pending = (state.load() or {}).get("phases", {})
    failures = []
    for node_id, phase in pending.items():
        delivery = (phase.get("details") or {}).get("manifest_delivery") or {}
        if phase.get("status") != "accepted" or delivery.get("status") not in {"pending", "failed"}:
            continue
        try:
            host._append_manifest(run.project_path, run.id, node_id, delivery["verdict_id"], "accepted", delivery["summary"])
        except (OSError, UnicodeError) as error:
            updated = {**delivery, "status": "failed", "error": str(error)[:1000]}
            failures.append(updated)
        else:
            updated = {**delivery, "status": "delivered", "error": ""}
        try:
            state.refresh_accepted_details(node_id, {"manifest_delivery": updated}, reason="derived manifest delivery")
        except OSError as error:
            # The pending outbox was committed with acceptance. Replay is safe
            # even if acknowledgement persistence fails after manifest delivery.
            failures.append({**delivery, "error": str(error), "status": "pending"})
    return failures
