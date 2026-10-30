"""Apply reviewed edits; completed deliveries stay frozen, unfinished work remains resumable."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from ..contracts.registry import artifact_contract_registry, workflow_artifact_contracts
from ..contracts.workflow_nodes import WORKFLOW_NODES
from ..utils.atomic_write import atomic_write_json, atomic_write_text, path_lock


def affected_phases(relative: str) -> list[str]:
    """Resolve canonical owners, then their declared downstream closure."""
    owners = {item.owner for item in artifact_contract_registry.values() if item.path == relative}
    owners.update(node for node, contract in workflow_artifact_contracts.items()
                  if relative in contract.required or relative == contract.primary)
    if not owners:
        prefixes = (
            ("experiments/results/", "exp-run"), ("experiments/", "exp-design"),
            ("paper/", "paper"), ("figures/", "figure"), ("slides/", "ppt"),
            ("literature/", "lit"), ("ideas/", "novelty"),
            ("NARRATIVE_REPORT.md", "narrative"),
        )
        owners = {next((owner for prefix, owner in prefixes if relative.startswith(prefix)), "")}
    while True:
        expanded = owners | {node["id"] for node in WORKFLOW_NODES
                             if owners.intersection(node["depends_on"])}
        if expanded == owners:
            return [node["id"] for node in WORKFLOW_NODES if node["id"] in owners]
        owners = expanded


def _invalidate_run(state: dict, phases: list[str], receipt: dict) -> None:
    """Retain former acceptance as history; edits never start background work."""
    changed = []
    for phase_id in phases:
        phase = state.get("phases", {}).get(phase_id)
        if not phase:
            continue
        if phase.get("status") == "pending" and phase_id != phases[0]:
            continue
        details = phase.setdefault("details", {})
        history = details.setdefault("acceptance_invalidations", [])
        if any(item.get("change_id") == receipt["id"] for item in history):
            continue
        history.append({"verdict_id": phase.get("verdict_id"),
                        "reviewer": phase.get("reviewer"), "accepted_at": phase.get("accepted_at"),
                        "invalidated_at": receipt["created_at"], "change_id": receipt["id"],
                        "reason": f"Reviewed research edit: {receipt['path']}"})
        details["revision"] = {"round": 0, "cycle": 1, "history": [], "waiting": False}
        details.pop("execution_checkpoint", None)
        interrupted = details.pop("interruption", None)
        if interrupted:
            history[-1]["previous_interruption"] = interrupted
        phase.update(status="done" if phase_id == phases[0] else "pending",
                     verdict_id="", reviewer="", accepted_at=None, error="")
        changed.append(phase_id)
    if changed:
        from ..workflows.run_state_support import _clear_run_terminal_fields
        _clear_run_terminal_fields(state)
        state.update(status="incomplete", current_node=changed[0],
                     manual_resume_required=True, finished_at=None)
        state.pop("auto_rebuild_required", None)
        if state.get("interruption", {}).get("node_id") in changed:
            receipt = {**receipt, "previous_interruption": state.pop("interruption")}
        state["research_edit"] = {**receipt, "affected_phases": changed}
        for key in ("completion_class", "submission_ready", "submission_eligible"):
            state.pop(key, None)


def _invalidate_runs(root: Path, phases: list[str], receipt: dict) -> list[str]:
    from ..workflows.run_state import RunState

    runs = []
    for path in sorted((root / ".merak" / "runs").glob("*.json")):
        if "." in path.stem:
            continue
        state = RunState(str(root), path.stem)
        existing = state.load()
        if not existing or not isinstance(existing.get("phases"), dict):
            continue
        if not set(phases).intersection(existing["phases"]):
            continue
        if existing.get('status') == 'completed':
            from .completed_run_revision import record_completed_revision
            record_completed_revision(root, existing, receipt)
            continue
        state.update_state(lambda value: _invalidate_run(value, phases, receipt))
        runs.append(path.stem)
    return runs


def apply_research_change(root: Path, change: Any) -> dict:
    """Compare and swap under the workflow-start lock; retain a change receipt."""
    from ..workflows.workflow_lease import ProjectRunLease

    root = root.resolve()
    target = Path(change.path).resolve()
    relative = target.relative_to(root).as_posix()
    lease = ProjectRunLease(str(root))
    receipt_path = root / ".merak" / "research-edits" / f"{change.id}.json"
    with path_lock(lease.path), path_lock(target):
        if lease.active_claim():
            raise RuntimeError("A workflow is active; pause it before applying this research edit")
        if receipt_path.is_file():
            prior = json.loads(receipt_path.read_text(encoding="utf-8"))
            expected_hash = hashlib.sha256(change.after.encode("utf-8")).hexdigest()
            if prior.get("id") != change.id or prior.get("path") != relative or prior.get("after_sha256") != expected_hash:
                raise ValueError("Change receipt does not match the reviewed proposal")
            if prior.get("status") == "applied":
                return prior
        current = target.read_text(encoding="utf-8") if target.exists() else ""
        if (receipt_path.is_file() and prior.get("status") == "prepared"
                and current == change.after and target.exists()
                and prior.get("after_sha256") == hashlib.sha256(current.encode("utf-8")).hexdigest()):
            prior.update(status="applied", applied_at=time.time(), recovered=True)
            atomic_write_json(receipt_path, prior)
            return prior
        if current != change.before or (change.action == "create" and target.exists()):
            raise ValueError("Change conflict: file changed after this proposal; regenerate against the current file")
        if change.action != "create" and not target.exists():
            raise ValueError("Change conflict: the proposed file was deleted")
        receipt = {"schema_version": 1, "id": change.id, "status": "prepared",
                   "path": relative, "created_at": time.time(),
                   "before_sha256": hashlib.sha256(current.encode("utf-8")).hexdigest(),
                   "after_sha256": hashlib.sha256(change.after.encode("utf-8")).hexdigest(),
                   "affected_phases": affected_phases(relative)}
        from .completed_run_revision import preserve_edit_before
        preserve_edit_before(root, receipt, target.read_bytes() if target.is_file() else None)
        atomic_write_json(receipt_path, receipt)
        receipt["affected_runs"] = _invalidate_runs(root, receipt["affected_phases"], receipt)
        atomic_write_json(receipt_path, receipt)
        atomic_write_text(target, change.after)
        receipt.update(status="applied", applied_at=time.time())
        atomic_write_json(receipt_path, receipt)
        return receipt
