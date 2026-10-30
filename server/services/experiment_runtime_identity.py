"""Bind cached and active experiments to their complete execution specification."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from dataclasses import asdict
from typing import Any

from .experiment_runtime_state import RuntimeSpec


class ActiveExperimentConflict(RuntimeError):
    """An existing attempt must be reconciled before changed work can start."""


def validate_cached_artifacts(spec: RuntimeSpec, manifest: dict[str, Any]) -> None:
    """Stale results require an explicit repair, never implicit scientific re-execution."""
    root = Path(spec.project_path).resolve()
    records = manifest.get("result_artifacts")
    if manifest.get("evidence_eligible") is False or not isinstance(records, dict) or not records:
        raise ValueError("Completed experiment has no reusable validated result artifacts")
    for relative, facts in records.items():
        path = (root / relative).resolve()
        if (not path.is_relative_to(root) or not path.is_file()
                or hashlib.sha256(path.read_bytes()).hexdigest() != facts.get("sha256")):
            raise ValueError(f"Completed experiment artifact changed or is missing: {relative}")


def execution_identity(spec: RuntimeSpec) -> str:
    """Hash execution inputs without persisting environment values or credentials."""
    payload = asdict(spec)
    for field in ("run_id", "project_path", "poll_interval_seconds"):
        payload.pop(field, None)
    payload["backend"] = spec.normalized_backend()
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def active_attempt_matches(
    spec: RuntimeSpec, previous: dict[str, Any], snapshot_hash: str,
) -> None:
    """Refuse ambiguous reattachment and preserve the previous task's evidence."""
    attempts = previous.get("attempts") or []
    number = int(previous.get("current_attempt") or 0)
    attempt = next((item for item in attempts if item.get("attempt") == number), {})
    if (previous.get("snapshot_hash") != snapshot_hash
            or attempt.get("execution_identity") != execution_identity(spec)):
        raise ActiveExperimentConflict(
            "An experiment attempt is still active with different or unverified "
            "source/configuration. Its task and snapshot were preserved; restore "
            "the original execution inputs to reconnect, or explicitly stop and "
            "reconcile that task before starting a changed experiment."
        )
