"""Pure and read-only policy for selecting a recoverable workflow phase."""

from __future__ import annotations

from typing import Any

import structlog


logger = structlog.get_logger()


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def auto_rebuild_is_due(
    rebuild: dict[str, Any],
    options: dict[str, Any],
    *,
    now: float,
) -> bool:
    retry_limit = min(6, max(1, safe_int(
        rebuild.get("recovery_max_attempts")
        or options.get("auto_rebuild_max_attempts"),
        3,
    )))
    retry_count = max(0, safe_int(rebuild.get("recovery_attempt_count")))
    return bool(
        rebuild.get("recovery_exhausted") is not True
        and retry_count < retry_limit
        and safe_float(rebuild.get("recovery_next_retry_at")) <= now
    )




def _signature_changed(
    engine: Any,
    project_path: str,
    phase_id: str,
    revision: dict[str, Any],
    options: dict[str, Any],
) -> bool | None:
    owner_id = str(revision.get("artifact_owner_id") or phase_id)
    saved_artifact = str(revision.get("artifact_signature") or "")
    saved_runtime = str(revision.get("runtime_signature") or "")
    if saved_runtime and not saved_artifact:
        return None
    changed = False
    if saved_artifact:
        try:
            current = engine._revision_artifact_signature(
                project_path, owner_id, options
            )
        except Exception as exc:
            logger.debug(
                "Workflow recovery artifact signature unavailable",
                project_path=project_path, phase_id=phase_id, error=str(exc),
            )
        else:
            changed = current != saved_artifact
    if saved_runtime:
        try:
            current = engine._revision_runtime_signature(
                project_path, owner_id, options
            )
        except Exception as exc:
            logger.debug(
                "Workflow recovery runtime signature unavailable",
                project_path=project_path, phase_id=phase_id, error=str(exc),
            )
        else:
            changed = changed or current != saved_runtime
    return changed


def _revision_due(
    engine: Any,
    project_path: str,
    phase_id: str,
    phase: dict[str, Any],
    options: dict[str, Any],
    now: float,
) -> bool:
    if phase.get("status") != "awaiting_revision":
        return False
    from .recovery_launch_budget import launch_due
    if not launch_due(phase, now):
        return False
    details = phase.get("details")
    details = details if isinstance(details, dict) else {}
    revision = details.get("revision")
    revision = revision if isinstance(revision, dict) else {}
    gate = revision.get("last_gate")
    gate = gate if isinstance(gate, dict) else {}
    terminal_flags = ("hard_limit", "stopped_for_no_progress", "stopped_for_deterministic_stage", "stopped_for_managed_stage")
    if any(revision.get(flag) or gate.get(flag) for flag in terminal_flags):
        return False  # Only an explicit recovery may reopen an exhausted quality transaction.
    if not engine._is_platform_repair_revision_checkpoint(revision):
        return False
    if engine._is_transport_revision_checkpoint(revision):
        return False  # A failed model operation resumes only after a user action.
    changed = _signature_changed(
        engine, project_path, phase_id, revision, options
    )
    if changed is None:
        return False
    if changed:
        return True
    if not engine._platform_checkpoint_is_auto_recoverable(revision):
        return False
    cycle_limit = min(6, max(1, safe_int(
        options.get("max_research_loop_cycles"), 3
    )))
    recovery_count = max(0, safe_int(
        revision.get("platform_auto_recovery_count")
    ))
    return recovery_count < cycle_limit


def _rebuild_phase(
    phases: dict[str, Any],
    rebuild: Any,
    options: dict[str, Any],
    now: float,
) -> str:
    if not isinstance(rebuild, dict) or not auto_rebuild_is_due(
        rebuild, options, now=now
    ):
        return ""
    for phase_id, phase in phases.items():
        if not isinstance(phase, dict):
            continue
        status = str(phase.get("status") or "pending")
        if status == "awaiting_revision":
            return ""
        if status not in {"accepted", "completed", "skipped"}:
            return str(phase_id)
    return ""


def due_phase(
    *,
    engine: Any,
    project_path: str,
    state: dict[str, Any],
    now: float,
) -> str:
    from ..workflows.interruption_checkpoint import manual_resume_required
    if manual_resume_required(state) or state.get("status") in {"completed", "failed", "cancelled", "interrupted"}:
        return ""
    config = state.get("config")
    config = config if isinstance(config, dict) else {}
    options = config.get("options")
    options = options if isinstance(options, dict) else {}
    if options.get("auto_proceed", True) is False:
        return ""
    if options.get("platform_auto_recovery", True) is False:
        return ""
    phases = state.get("phases")
    phases = phases if isinstance(phases, dict) else {}
    for phase_id, phase in phases.items():
        if isinstance(phase, dict) and _revision_due(
            engine, project_path, str(phase_id), phase, options, now
        ):
            return str(phase_id)
    return _rebuild_phase(
        phases, state.get("auto_rebuild_required"), options, now
    )
