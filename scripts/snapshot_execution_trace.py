"""Explicit, auditable project-envelope relocation for isolated verification copies.

This is a test-copy operation, not a production migration. Source run identity,
stages, invocation bytes and upstream sessions remain unchanged. Only the outer
project binding is relocated after its original identity is strictly checked.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from server.utils.atomic_write import atomic_write_bytes, atomic_write_json


def clone_execution_envelope(root: Path, original_project: Path, run_id: str) -> dict:
    """Relocate an exact copied trace and archive its immutable source bytes."""
    root, original_project = root.resolve(), original_project.resolve()
    if root == original_project or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", run_id):
        raise ValueError("Execution snapshot requires a distinct copy and a stable run identifier")
    relative = f".merak/runs/{run_id}.skills.json"
    source_path, copied_path = original_project / relative, root / relative
    source = source_path.read_bytes()
    if copied_path.read_bytes() != source:
        raise ValueError("Copied execution trace is not identical to the source trace")
    payload = json.loads(source.decode("utf-8-sig"))
    if (not isinstance(payload, dict) or payload.get("schema") != 2
            or payload.get("run_id") != run_id or not isinstance(payload.get("stages"), dict)):
        raise ValueError("Source execution trace has a different run identity or unsupported schema")
    if not payload.get("project_path") or Path(str(payload["project_path"])).resolve() != original_project:
        raise ValueError("Source execution trace belongs to a different project")
    digest = hashlib.sha256(source).hexdigest()
    archive_relative = f".merak/snapshot-source-traces/{run_id}.skills.original.json"
    archive = root / archive_relative
    if archive.exists() and archive.read_bytes() != source:
        raise ValueError("Source execution archive already exists with different bytes")
    atomic_write_bytes(archive, source)
    payload["project_path"] = str(root)
    payload["snapshot_provenance"] = {
        "source_project": str(original_project), "source_run_id": run_id,
        "source_trace_sha256": digest, "source_trace_archive": archive_relative,
        "upstream_invocations_rewritten": False, "new_upstream_execution_claimed": False,
    }
    atomic_write_json(copied_path, payload)
    return {"metadata_relocated_for_snapshot": True, "source_trace_sha256": digest,
            "source_trace_archive": archive_relative, "upstream_invocations_rewritten": False,
            "new_upstream_execution_claimed": False}


def archived_execution_source_unchanged(root: Path, relocation: dict) -> bool:
    path = (root.resolve() / str(relocation.get("source_trace_archive") or "")).resolve()
    return path.is_relative_to(root.resolve()) and path.is_file() and (
        hashlib.sha256(path.read_bytes()).hexdigest() == relocation.get("source_trace_sha256")
    )
