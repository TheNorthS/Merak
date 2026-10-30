"""Strict source-evidence selection and specialist relocation for an isolated copy.

No workflow state, source contract, invocation bytes, or acceptance status is
rewritten. Existing model evidence remains source-run evidence; only copied
specialist-plan path metadata may point at an identical archived local trace.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path

from server.utils.atomic_write import atomic_write_bytes, atomic_write_json


_ROOT_METADATA = frozenset({
    "NARRATIVE_BUILD.json", "PAPER_PLAN_BUILD.json", "RESEARCH_WORKFLOW_CONTRACT.json",
    "research_strategy.json", "NODE_RISK_AUDIT.json", "WORKFLOW_RISK_SNAPSHOT.json",
    "NARRATIVE_RECONCILIATION.json",
})


def additional_input_files(original: Path, run_id: str) -> list[Path]:
    """Select evidence omitted by paper/figure inventories, never active leases or keys."""
    original = original.resolve()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", run_id):
        raise ValueError("Snapshot input selection requires a stable run identifier")
    files = []
    for directory, extensions in (
        (".merak/skill-invocations", {".json"}), ("experiments/specialists", {".md", ".json"}),
        ("review-stage", {".md", ".json", ".txt", ".png", ".pdf"}),
        ("audit-results", {".json", ".md"}),
    ):
        files.extend(path for path in (original / directory).rglob("*")
                     if path.is_file() and path.suffix.casefold() in extensions)
    files.extend(original / f".merak/runs/{run_id}{suffix}" for suffix in (".json", ".skills.json", ".specialists.json"))
    files.extend(original / ".merak" / name for name in _ROOT_METADATA)
    result = sorted({path for path in files if path.is_file()})
    for path in result:
        if not path.resolve().is_relative_to(original) or path.stat().st_size > 20 * 1024 * 1024:
            raise ValueError("Additional snapshot input escapes its source project or exceeds the local bound")
    return result


def safe_selected_input_files(original: Path, candidates: list[Path]) -> list[Path]:
    """Filter existing inventories without carrying keys, databases or execution leases."""
    original = original.resolve()
    rejected_names = {".env", "user_settings.json", "active-workflow.json", "workflow_recovery_projects.json"}
    rejected_parts = {"recovery-leases", "agent-sessions", "node_modules", ".git"}
    result = []
    for raw in candidates:
        path = raw.resolve()
        if not path.is_relative_to(original):
            raise ValueError("Selected snapshot input escapes its source project")
        relative = path.relative_to(original)
        if (path.name.casefold() in rejected_names or path.suffix.casefold() in {".db", ".sqlite", ".sqlite3", ".key", ".pem"}
                or rejected_parts.intersection(relative.parts)):
            continue
        if path.is_file():
            result.append(path)
    return sorted(set(result))


def _relocated_trace(root: Path, original: Path, entry: dict, archives: dict[Path, bytes]) -> str:
    source = Path(str(entry.get("invocation_trace") or "")).resolve()
    trace_root = original / ".merak/skill-invocations"
    if not source.is_relative_to(trace_root) or not source.is_file():
        raise ValueError("Specialist source invocation trace is missing or belongs to a different project")
    relative = source.relative_to(original)
    copied = root / relative
    source_bytes = source.read_bytes()
    if not copied.is_file() or copied.read_bytes() != source_bytes:
        raise ValueError("Copied specialist invocation bytes differ from the immutable source evidence")
    payload = json.loads(source_bytes.decode("utf-8-sig"))
    if (not isinstance(payload, dict) or payload.get("status") != "completed"
            or payload.get("session_id") != entry.get("session_id")
            or str(payload.get("skill") or "").lstrip("/") != str(entry.get("skill") or "").lstrip("/")):
        raise ValueError("Specialist source invocation identity does not match its declared completed evidence")
    archive = root / ".merak/snapshot-source-traces/specialist-invocations" / relative.name
    archives[archive] = source_bytes
    return str(copied)


def relocate_specialist_plan_same_run(root: Path, original: Path, run_id: str) -> dict:
    """Archive exact source evidence and change only copied invocation-path metadata."""
    root, original = root.resolve(), original.resolve()
    if root == original or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", run_id):
        raise ValueError("Specialist relocation requires a distinct copy and a stable source run identifier")
    relative = f".merak/runs/{run_id}.specialists.json"
    source_path, copied_path = original / relative, root / relative
    source = source_path.read_bytes()
    if copied_path.read_bytes() != source:
        raise ValueError("Copied specialist plan differs from its immutable source bytes")
    payload = json.loads(source.decode("utf-8-sig"))
    if (not isinstance(payload, dict) or payload.get("schema") != 1 or payload.get("run_id") != run_id
            or not isinstance(payload.get("subnodes"), list)
            or any(not isinstance(entry, dict) for entry in payload["subnodes"])):
        raise ValueError("Specialist source plan has a different run identity or unsupported schema")
    if payload.get("project_path") and Path(str(payload["project_path"])).resolve() != original:
        raise ValueError("Specialist source plan belongs to a different project")
    clone = copy.deepcopy(payload)
    archives = {root / f".merak/snapshot-source-traces/{run_id}.specialists.original.json": source}
    relocated = 0
    for entry in clone["subnodes"]:
        if entry.get("status") != "completed" and not entry.get("invocation_trace"):
            continue
        entry["invocation_trace"] = _relocated_trace(root, original, entry, archives)
        relocated += 1
    if payload.get("project_path"):
        clone["project_path"] = str(root)
    digest = hashlib.sha256(source).hexdigest()
    clone["snapshot_provenance"] = {"source_project": str(original), "source_run_id": run_id,
                                    "source_plan_sha256": digest, "new_model_session_claimed": False,
                                    "invocation_records_rewritten": False}
    for path, content in archives.items():
        if path.exists() and path.read_bytes() != content:
            raise ValueError("Specialist source archive contains different evidence bytes")
    for path, content in archives.items():
        atomic_write_bytes(path, content)
    atomic_write_json(copied_path, clone)
    return {"metadata_relocated_for_snapshot": True, "source_plan_sha256": digest,
            "source_archive_unchanged": all(path.read_bytes() == content for path, content in archives.items()),
            "source_original_plan_unchanged": source_path.read_bytes() == source,
            "relocated_evidence_count": relocated, "new_model_session_claimed": False,
            "invocation_records_rewritten": False}
