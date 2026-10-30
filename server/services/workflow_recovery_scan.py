"""One-pass scheduling for the background workflow recovery watchdog."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog


logger = structlog.get_logger()


@dataclass(frozen=True)
class RecoveryCandidate:
    project_path: str
    project_key: str
    run_id: str
    phase_id: str
    state_path: Path
    state: dict[str, Any]

    @property
    def key(self) -> tuple[str, str]:
        return self.project_key, self.run_id


def _state_paths(project_path: str) -> list[Path]:
    runs_dir = Path(project_path) / ".merak" / "runs"
    if not runs_dir.is_dir():
        return []
    try:
        return sorted(
            runs_dir.glob("*.json"),
            key=lambda item: item.stat().st_mtime_ns,
            reverse=True,
        )
    except OSError:
        return []


def _refresh_completed(
    engine: Any,
    project_path: str,
    run_id: str,
    state: dict[str, Any],
) -> dict[str, Any]:
    if str(state.get("status") or "") != "completed":
        return state
    refresh = getattr(engine, "get_persisted_run_state", None)
    if not callable(refresh):
        return state
    try:
        return refresh(project_path, run_id) or state
    except Exception as exc:
        logger.debug(
            "Completed workflow readiness refresh failed",
            project_path=project_path, run_id=run_id, error=str(exc),
        )
        return state


def _candidate(
    watchdog: Any,
    engine: Any,
    project_key: str,
    project_path: str,
    now: float,
) -> RecoveryCandidate | None:
    if engine._active_run_for_project(project_path):
        return None
    state_paths = _state_paths(project_path)
    if not state_paths:
        observed_at = watchdog._observed_at.get(project_key, 0.0)
        if observed_at <= 0.0 or now - observed_at >= 300.0:
            watchdog._projects.pop(project_key, None)
            watchdog._observed_at.pop(project_key, None)
            watchdog._registry_changed = True
        return None
    state_path = watchdog._selected_state_path(project_path, state_paths)
    if state_path is None:
        return None
    state = watchdog._read_json_object(state_path)
    if not state:
        return None
    run_id = str(state.get("run_id") or state_path.stem)
    if any((phase.get("details") or {}).get("manifest_delivery", {}).get("status") in {"pending", "failed"}
           for phase in (state.get("phases") or {}).values() if isinstance(phase, dict)):
        from types import SimpleNamespace
        from ..workflows.acceptance_manifest import deliver_acceptance_manifests
        deliver_acceptance_manifests(engine, SimpleNamespace(project_path=project_path, id=run_id))
    if str(state.get("status") or "") == "cancelled":
        return None
    state = _refresh_completed(engine, project_path, run_id, state)
    if str(state.get("status") or "") == "completed" and not isinstance(
        state.get("auto_rebuild_required"), dict
    ):
        return None
    phase_id = watchdog._due_phase(
        engine=engine, project_path=project_path, state=state, now=now
    )
    key = (project_key, run_id)
    if not phase_id or key in watchdog._inflight:
        return None
    if now - watchdog._last_attempt_at.get(key, 0.0) < 30.0:
        return None
    if not watchdog._acquire_recovery_lease(project_path, run_id, now=now):
        return None
    return RecoveryCandidate(
        project_path, project_key, run_id, phase_id, state_path, state
    )


def _is_rebuild_attempt(candidate: RecoveryCandidate) -> bool:
    rebuild = candidate.state.get("auto_rebuild_required")
    phases = candidate.state.get("phases")
    phases = phases if isinstance(phases, dict) else {}
    phase = phases.get(candidate.phase_id)
    return bool(
        isinstance(rebuild, dict)
        and isinstance(phase, dict)
        and str(phase.get("status") or "") != "awaiting_revision"
    )


async def _resume(
    watchdog: Any,
    engine: Any,
    candidate: RecoveryCandidate,
    now: float,
) -> dict[str, str] | None:
    from .recovery_launch_budget import begin_launch, finish_launch
    if _is_rebuild_attempt(candidate) and not watchdog._record_auto_rebuild_attempt(
        candidate.state_path, phase_id=candidate.phase_id, now=now
    ):
        watchdog._release_recovery_lease(candidate.key)
        return None
    if not _is_rebuild_attempt(candidate) and not begin_launch(candidate.state_path, candidate.phase_id, now):
        watchdog._release_recovery_lease(candidate.key)
        return None
    watchdog._inflight.add(candidate.key)
    watchdog._last_attempt_at[candidate.key] = now
    resume_started = False
    try:
        await engine.resume_persisted_run(
            run_id=candidate.run_id,
            project_path=candidate.project_path,
            resume_source="watchdog",
        )
        resume_started = True
        finish_launch(candidate.state_path, candidate.phase_id, succeeded=True)
        logger.info(
            "Workflow recovery watchdog resumed run",
            project_path=candidate.project_path,
            run_id=candidate.run_id,
            phase_id=candidate.phase_id,
        )
        return {
            "project_path": candidate.project_path,
            "run_id": candidate.run_id,
            "phase_id": candidate.phase_id,
        }
    except ValueError as exc:
        finish_launch(candidate.state_path, candidate.phase_id, succeeded=False, error=str(exc))
        logger.info(
            "Workflow recovery candidate no longer resumable",
            project_path=candidate.project_path,
            run_id=candidate.run_id,
            error=str(exc),
        )
    except Exception as exc:
        finish_launch(candidate.state_path, candidate.phase_id, succeeded=False, error=str(exc))
        logger.warning(
            "Workflow recovery watchdog could not resume run",
            project_path=candidate.project_path,
            run_id=candidate.run_id,
            error=str(exc),
        )
    finally:
        watchdog._inflight.discard(candidate.key)
        if not resume_started:
            watchdog._release_recovery_lease(candidate.key)
    return None


async def scan_recoveries(watchdog: Any, engine: Any = None) -> list[dict[str, str]]:
    if engine is None:
        from ..workflows.engine import workflow_engine
        engine = workflow_engine
    now = time.time()
    watchdog._maintain_recovery_leases(engine, now=now)
    watchdog._registry_changed = False
    started: list[dict[str, str]] = []
    for project_key, project_path in list(watchdog._projects.items()):
        candidate = _candidate(
            watchdog, engine, project_key, project_path, now
        )
        if candidate is None:
            continue
        result = await _resume(watchdog, engine, candidate, now)
        if result:
            started.append(result)
    if watchdog._registry_changed:
        watchdog._save_registry()
    return started
