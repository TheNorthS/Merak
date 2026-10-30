"""Exact synchronous capability for the trusted current skill-trace writer.

Delegation keeps its model/scientific owner context. Only the production trace
repository's deterministic commit is allowed to update current runtime proof;
no model file tool, other run, lifecycle state or scientific file inherits it.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
import re
from unittest.mock import patch


_TRUSTED_SKILL_TRACE: ContextVar[tuple[Path, str] | None] = ContextVar(
    "full_benchmark_trusted_skill_trace", default=None,
)


def trusted_runtime_record_target(target: Path) -> bool:
    """The audit guard must match the exact canonical target and current run ID."""
    capability = _TRUSTED_SKILL_TRACE.get()
    return bool(capability and target == capability[0]
                and target.name == capability[1] + ".skills.json")


@contextmanager
def trusted_benchmark_runtime_records(root: Path, run_id: str):
    """Wrap only the real synchronous trace commit, not model callbacks or tools."""
    from server.services.skill_execution_trace import SkillExecutionTrace

    root = root.resolve(strict=True)
    if not re.fullmatch(r"[a-f0-9]{12}", run_id):
        raise ValueError("Trusted benchmark trace capability requires an exact hexadecimal run ID")
    target = root / f".merak/runs/{run_id}.skills.json"
    original = SkillExecutionTrace._write_payload

    def owned_commit(path, payload, actual_run_id, stages, registry_total, *, include_digest=False):
        if (Path(path).resolve() != target or actual_run_id != run_id
                or Path(path).is_symlink()
                or payload.get("run_id") != run_id or payload.get("schema") != 2
                or Path(str(payload.get("project_path") or "")).resolve() != root):
            raise PermissionError("Trusted benchmark trace commit differs from its exact existing runtime owner")
        token = _TRUSTED_SKILL_TRACE.set((target, run_id))
        try:
            return original(path, payload, actual_run_id, stages, registry_total, include_digest=include_digest)
        finally:
            _TRUSTED_SKILL_TRACE.reset(token)

    with patch.object(SkillExecutionTrace, "_write_payload", staticmethod(owned_commit)):
        yield
