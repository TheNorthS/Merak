"""Share dependency invalidation between repair start, recovery and reconciliation."""

from typing import Any


def owner_revision_dependents(host: Any, owner: str, consumer: str, available: set[str]) -> list[str]:
    if owner == "lit" and consumer in {"review", "audit"}:
        return [key for key in ("narrative", "paper", "review", "audit", "compile", "ppt") if key in available]
    return host._dependent_phase_ids(owner, available)


def revalidate_unaffected_owner_phases(host: Any, run: Any, durable: Any) -> None:
    """Freshly validate over-invalidated current receipts; never restore a status blindly."""
    from .artifact_snapshot_ownership import owner_snapshot_view
    saved = durable.load() or {}
    repair = saved.get("active_owner_revision") or {}
    owner, consumer = repair.get("owner_node"), repair.get("consumer_node")
    if owner != "lit" or consumer not in {"review", "audit"}:
        return
    phases = saved.get("phases", {})
    affected = {owner, *owner_revision_dependents(host, owner, consumer, set(phases))}
    definitions = {node.id: node for node in host._get_default_nodes()}
    for key, phase in phases.items():
        details = phase.get("details") or {}
        history = details.get("revoked_acceptances") or []
        snapshot = owner_snapshot_view(key, details.get("artifact_snapshot"))
        if (key in affected or key not in definitions or phase.get("status") != "pending"
                or not history or history[-1].get("owner") != owner or not history[-1].get("verdict_id")
                or not snapshot or host._artifact_snapshot_issues(run.project_path, snapshot)):
            continue
        gate = host._acceptance_gate(definitions[key], run, str(saved.get("config", {}).get("assurance") or "draft"),
                                     "Fresh revalidation of unchanged artifacts outside the active repair scope", require_fresh=False)
        if gate.get("accepted"):
            durable.set_status(key, "done", details={"owner_scope_revalidation": "fresh gate passed"})
            durable.accept(key, gate["verdict_id"], gate["reviewer"], {
                **gate.get("details", {}), "owner_scope_revalidated": {"owner": owner, "consumer": consumer},
            })
