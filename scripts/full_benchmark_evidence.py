"""Import unchanged prior owner evidence; never create new accepted phases.

The source run/stages/invocations keep their original identities and are archived
byte-for-byte. Only known absolute artifact/trace envelope paths may relocate to
the content-identical copy. Every reused owner still runs its current real gate.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from server.utils.atomic_write import atomic_write_bytes, atomic_write_json


SOURCE_NODES = ("lit", "idea", "novelty")


def _json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("Prior source ownership evidence must be a canonical object")
    return value


def _copied_path(root: Path, original: Path, raw: str) -> str:
    path = Path(raw)
    source = path.resolve() if path.is_absolute() else (original / path).resolve()
    if not source.is_relative_to(original):
        raise ValueError("Prior owner artifact path belongs to a foreign original project")
    copied = root / source.relative_to(original)
    if not source.is_file() or not copied.is_file() or source.read_bytes() != copied.read_bytes():
        raise ValueError("A reused owner artifact is not byte-identical to its source")
    return str(copied)


def archive_source_history(root: Path, original: Path, run_id: str) -> dict[str, Any]:
    """All-fresh execution archives history without installing reusable old phases."""
    root, original = root.resolve(), original.resolve()
    if root == original or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", run_id):
        raise ValueError("Historical source archive needs a distinct project and stable source identity")
    hashes = {}
    for label, suffix in (("run", ".json"), ("skills", ".skills.json")):
        path = original / f".merak/runs/{run_id}{suffix}"
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8-sig"))
        if (not isinstance(payload, dict) or payload.get("run_id") != run_id
                or label == "run" and payload.get("status") != "cancelled"):
            raise ValueError("Historical source evidence is not the exact stopped source run")
        atomic_write_bytes(root / f".merak/source-evidence/{run_id}.{label}.original.json", raw)
        hashes[label] = hashlib.sha256(raw).hexdigest()
    for path in sorted((original / ".merak/skill-invocations").glob("*.json")):
        atomic_write_bytes(root / ".merak/source-evidence/invocations" / path.name, path.read_bytes())
    return {"source_run_id": run_id, "source_run_sha256": hashes["run"], "source_trace_sha256": hashes["skills"],
            "source_nodes": [], "historical_only": True, "new_accepted_phases_created": False,
            "reusable_prior_run_installed": False}


def import_source_owner_evidence(root: Path, original: Path, run_id: str) -> dict[str, Any]:
    """Copy exact source proof; relocate only declared artifact/outer trace paths."""
    root, original = root.resolve(), original.resolve()
    if root == original or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", run_id):
        raise ValueError("Source import needs a distinct owned copy and stable source run identifier")
    source_path = original / f".merak/runs/{run_id}.json"
    trace_path = original / f".merak/runs/{run_id}.skills.json"
    source, trace = _json(source_path), _json(trace_path)
    if (source.get("schema") != 1 or source.get("run_id") != run_id or source.get("status") != "cancelled"
            or trace.get("schema") != 2 or trace.get("run_id") != run_id
            or Path(str(trace.get("project_path") or "")).resolve() != original):
        raise ValueError("Only an explicitly stopped original run with genuine source traces can be reused")
    imported = copy.deepcopy(source)
    for node_id in SOURCE_NODES:
        phase = imported.get("phases", {}).get(node_id)
        stage = trace.get("stages", {}).get(node_id)
        if (not isinstance(phase, dict) or phase.get("status") != "accepted" or not phase.get("accepted_at")
                or not phase.get("verdict_id") or not phase.get("reviewer") or not isinstance(stage, dict)
                or stage.get("node_id") != node_id or stage.get("run_id") != run_id):
            raise ValueError("Prior owner has no genuine accepted source-run identity: " + node_id)
        phase["artifact"] = _copied_path(root, original, str(phase.get("artifact") or ""))
        evidence = (phase.get("details") or {}).get("execution_evidence")
        if not isinstance(evidence, dict) or evidence.get("accepted") is not True or evidence.get("issues"):
            raise ValueError("Prior owner has no passing source execution evidence: " + node_id)
        evidence["trace_path"] = str(root / f".merak/runs/{run_id}.skills.json")
    archive_root = root / ".merak/source-evidence"
    for label, path in (("run", source_path), ("skills", trace_path)):
        atomic_write_bytes(archive_root / f"{run_id}.{label}.original.json", path.read_bytes())
    for path in sorted((original / ".merak/skill-invocations").glob("*.json")):
        relative = path.relative_to(original)
        copied = root / relative
        if copied.exists() and copied.read_bytes() != path.read_bytes():
            raise ValueError("Imported raw invocation already has a different identity")
        atomic_write_bytes(copied, path.read_bytes())
        atomic_write_bytes(archive_root / "invocations" / path.name, path.read_bytes())
    current_trace = {**trace, "project_path": str(root), "snapshot_provenance": {
        "source_project": str(original), "source_run_id": run_id,
        "source_trace_sha256": hashlib.sha256(trace_path.read_bytes()).hexdigest(),
        "source_trace_archive": f".merak/source-evidence/{run_id}.skills.original.json",
        "upstream_invocations_rewritten": False, "new_upstream_execution_claimed": False}}
    atomic_write_json(root / f".merak/runs/{run_id}.skills.json", current_trace)
    atomic_write_json(root / f".merak/runs/{run_id}.json", imported)
    return {"source_run_id": run_id, "source_run_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
            "source_trace_sha256": hashlib.sha256(trace_path.read_bytes()).hexdigest(),
            "source_nodes": list(SOURCE_NODES), "new_accepted_phases_created": False}


def check_source_owners(host: Any, root: Path, source_run_id: str, nodes: tuple[str, ...]) -> dict[str, Any]:
    """Every owner must pass complete current acceptance and original-run execution."""
    if not nodes:
        return {}
    from server.workflows.artifact_snapshot_ownership import owner_snapshot_view
    from server.workflows.models import WorkflowRun

    state = _json(root / f".merak/runs/{source_run_id}.json")
    definitions = host._get_default_nodes()
    run = WorkflowRun(id=source_run_id, project_path=str(root), nodes=definitions,
                      options=dict((state.get("config") or {}).get("options") or {}),
                      input_baseline=state.get("input_baseline") or {})
    gates = {}
    for identity in nodes:
        phase = state["phases"][identity]
        snapshot = owner_snapshot_view(identity, (phase.get("details") or {}).get("artifact_snapshot"))
        if not snapshot or host._artifact_snapshot_issues(str(root), snapshot):
            raise ValueError("Prior source owner inputs changed; a real owner must run again: " + identity)
        node = next(node for node in definitions if node.id == identity)
        gate = host._acceptance_gate(node, run, str(state["config"].get("assurance") or "draft"), "", require_fresh=False)
        evidence = (gate.get("details") or {}).get("execution_evidence") or {}
        if gate.get("accepted") is not True or evidence.get("accepted") is not True or evidence.get("issues"):
            raise ValueError("Current source owner gate or archived execution is invalid: " + identity)
        gates[identity] = {"verdict_id": gate.get("verdict_id"), "reviewer": gate.get("reviewer"),
                           "source_run_id": source_run_id, "execution_evidence": evidence}
    return gates
