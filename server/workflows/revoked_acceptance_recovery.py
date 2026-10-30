"""Freshly reaccept unchanged revoked outputs before retrying downstream infrastructure."""

from typing import Any


def revalidate_unchanged_revoked_outputs(host: Any, run: Any, durable: Any) -> None:
    from .artifact_snapshot_ownership import owner_snapshot_view

    definitions = {node.id: node for node in host._get_default_nodes()}
    initial = durable.load() or {}
    for key in initial.get("phases", {}):
        saved = durable.load() or {}
        phase = saved.get("phases", {}).get(key, {})
        details = phase.get("details") or {}
        history = details.get("revoked_acceptances") or []
        definition = definitions.get(key)
        snapshot = owner_snapshot_view(key, details.get("artifact_snapshot"))
        active = saved.get("active_owner_revision") or {}
        if (not definition or phase.get("status") != "pending" or not history or not snapshot
                or not history[-1].get("verdict_id") or active and active.get("owner_node") != key):
            continue
        if any(not host._phase_is_durably_terminal(saved.get("phases", {}).get(dep, {}))
               for dep in definition.depends_on):
            continue
        if host._artifact_snapshot_issues(run.project_path, snapshot):
            continue
        gate = host._acceptance_gate(definition, run, str(saved.get("config", {}).get("assurance") or "draft"),
            "Revalidate unchanged revoked outputs after the prior repair transaction ended", require_fresh=False)
        if gate.get("accepted"):
            durable.set_status(key, "done")
            durable.accept(key, gate["verdict_id"], gate["reviewer"], gate.get("details") or {})
            if active.get("owner_node") == key:
                def end_revalidated_repair(current: dict) -> None:
                    current.pop("active_owner_revision", None)
                durable.update_state(end_revalidated_repair)
