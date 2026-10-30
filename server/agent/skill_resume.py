"""Reuse interrupted delegate transcripts only within the same run and stage contract."""
from __future__ import annotations

from contextvars import ContextVar
import hashlib
import json
from typing import Any


workflow_scope: ContextVar[tuple[str, str]] = ContextVar("workflow_scope", default=("", ""))


def delegate_identity(loaded: Any, parent: str, contract: str, scope: Any, *, input_fingerprint: str = "") -> dict:
    run_id, node_id = workflow_scope.get()
    parts = [loaded.name, parent, contract, scope]
    if input_fingerprint:
        parts.append(input_fingerprint)
    signature = json.dumps(parts, sort_keys=True)
    return {"workflow_run_id": run_id, "workflow_node_id": node_id,
            "resume_key": hashlib.sha256(signature.encode()).hexdigest()}


def restore_delegate(engine: Any, loaded: Any, prompt: str, identity: dict) -> Any:
    if not identity["workflow_run_id"]:
        return None
    directory = loaded.root / ".merak/skill-invocations"
    candidates = sorted(directory.glob(f"*_{loaded.name}.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in candidates:
        try:
            trace = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if any(trace.get(key) != value for key, value in identity.items()):
            continue
        if trace.get("status") not in {"failed", "cancelled", "running"}:
            return None
        if trace.get("skill_sha256") != hashlib.sha256(loaded.source_bytes).hexdigest():
            return None
        from ..workflows.primary_session_resume import restore_primary_session
        return restore_primary_session(engine, str(trace.get("session_id") or ""),
                                       str(loaded.root), system_prompt=prompt)
    return None
