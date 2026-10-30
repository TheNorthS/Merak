"""Reuse accepted upstream execution evidence for targeted node runs.

A single-node desktop run must not rerun the entire pipeline merely to recreate
model/runtime provenance. Reuse is allowed only when the current deterministic
gate rejects solely for current-run execution trace, a prior phase was accepted
with verified execution evidence, and its recorded artifact snapshot is still
byte/semantic-current.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol
from .artifact_snapshot_ownership import owner_snapshot_view


class DependencyReuseHost(Protocol):
    def _artifact_snapshot_issues(
        self, project_path: str, snapshot: Any,
    ) -> list[str]: ...


def execution_trace_only_failure(gate: dict[str, Any]) -> bool:
    details = gate.get("details")
    details = details if isinstance(details, dict) else {}
    issues = [str(item) for item in details.get("issues") or [] if str(item)]
    if not issues:
        summary = str(gate.get("summary") or gate.get("reason") or "")
        issues = [summary] if summary else []
    return bool(issues) and all(
        "missing verified current-run" in item and "execution" in item
        for item in issues
    )


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _primary_snapshot(
    project_root: Path, phase: dict[str, Any], snapshot: dict[str, Any],
) -> dict[str, Any]:
    raw = str(phase.get("artifact") or "").strip()
    if not raw:
        return {}
    artifact = Path(raw).expanduser()
    artifact = artifact if artifact.is_absolute() else project_root / artifact
    try:
        relative = artifact.resolve().relative_to(project_root).as_posix()
    except (OSError, ValueError):
        return {}
    return {
        key: value for key, value in snapshot.items()
        if key == relative or key.startswith(relative.rstrip("/") + "/")
    }


def reusable_dependency_evidence(
    host: DependencyReuseHost,
    project_path: str,
    current_run_id: str,
    dependency_id: str,
    input_baseline_id: str = "",
) -> dict[str, Any] | None:
    runs = Path(project_path).expanduser().resolve() / ".merak" / "runs"
    if not runs.is_dir():
        return None
    candidates = sorted(
        (path for path in runs.glob("*.json") if path.stem != current_run_id),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )
    for path in candidates:
        state = _load(path)
        phase = (state.get("phases") or {}).get(dependency_id)
        if not isinstance(phase, dict) or phase.get("status") != "accepted":
            continue
        details = phase.get("details")
        details = details if isinstance(details, dict) else {}
        evidence = details.get("execution_evidence")
        if not isinstance(evidence, dict) or evidence.get("accepted") is not True:
            continue
        recorded_input = str(details.get("input_baseline_snapshot_id") or "")
        if input_baseline_id and recorded_input and recorded_input != input_baseline_id:
            continue
        snapshot = owner_snapshot_view(dependency_id, details.get("artifact_snapshot"))
        primary = _primary_snapshot(Path(project_path).resolve(), phase, snapshot)
        if not isinstance(snapshot, dict) or not primary or host._artifact_snapshot_issues(
            project_path, primary,
        ):
            continue
        return {
            "run_id": str(state.get("run_id") or path.stem),
            "phase_id": dependency_id,
            "verdict_id": str(phase.get("verdict_id") or ""),
            "reviewer": str(phase.get("reviewer") or ""),
            "execution_evidence": evidence,
        }
    return None
