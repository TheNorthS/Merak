"""Durable background recovery for platform-owned workflow checkpoints."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Optional

import structlog

from ..utils.atomic_write import atomic_write_json, path_lock
from .settings_storage import settings_storage_path
from .workflow_recovery_policy import (
    auto_rebuild_is_due,
    due_phase,
    safe_float,
    safe_int,
)
from .workflow_recovery_scan import scan_recoveries


logger = structlog.get_logger()


class WorkflowRecoveryWatchdog:
    """Wake due platform checkpoints without making scientific decisions.

    The watchdog only schedules the existing workflow engine. Acceptance remains
    owned by the node gate and reviewer. Project paths are remembered locally so
    a backend restart during an unattended run does not lose the recovery target.
    """

    def __init__(
        self,
        *,
        poll_interval_seconds: float = 10.0,
        registry_path: Optional[Path] = None,
        lease_ttl_seconds: float = 600.0,
    ) -> None:
        self.poll_interval_seconds = max(1.0, float(poll_interval_seconds))
        self.registry_path = registry_path or settings_storage_path(".merak/workflow_recovery_projects.json")
        self._projects: dict[str, str] = {}
        self._observed_at: dict[str, float] = {}
        self._task: Optional[asyncio.Task] = None
        self._inflight: set[tuple[str, str]] = set()
        self._last_attempt_at: dict[tuple[str, str], float] = {}
        self.lease_ttl_seconds = max(60.0, float(lease_ttl_seconds))
        self._held_leases: dict[tuple[str, str], dict[str, Any]] = {}
        self._registry_changed = False

    @staticmethod
    def _project_key(project_path: str | Path) -> str:
        return str(Path(project_path).expanduser().resolve()).replace(
            "\\", "/"
        ).casefold()

    def observe_project(self, project_path: str | Path) -> None:
        """Register a project that may contain resumable workflow state."""
        raw = str(project_path or "").strip()
        if not raw:
            return
        path = Path(raw).expanduser().resolve()
        key = self._project_key(path)
        normalized = str(path)
        if self._projects.get(key) == normalized:
            self._observed_at[key] = time.time()
            return
        previous = self._projects.get(key)
        self._projects[key] = normalized
        try:
            self._save_registry()
        except OSError:
            if previous is None:
                self._projects.pop(key, None)
            else:
                self._projects[key] = previous
            raise
        self._observed_at[key] = time.time()

    def _load_registry(self) -> None:
        try:
            payload = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        entries = payload.get("projects") if isinstance(payload, dict) else []
        if not isinstance(entries, list):
            return
        for entry in entries:
            raw = str(entry or "").strip()
            if not raw:
                continue
            path = Path(raw).expanduser().resolve()
            key = self._project_key(path)
            self._projects[key] = str(path)
            self._observed_at.setdefault(key, 0.0)

    def _save_registry(self) -> None:
        try:
            self.registry_path.parent.mkdir(parents=True, exist_ok=True)
            with path_lock(self.registry_path):
                payload = {
                    "schema": 1,
                    "projects": sorted(self._projects.values()),
                    "updated_at": time.time(),
                }
                atomic_write_json(self.registry_path, payload)
        except OSError as exc:
            logger.warning(
                "Workflow recovery registry could not be saved",
                error=str(exc),
            )
            raise

    @staticmethod
    def _lease_run_key(run_id: str) -> str:
        return hashlib.sha256(str(run_id).encode("utf-8")).hexdigest()[:24]

    def _lease_dir(self, project_path: str | Path) -> Path:
        return Path(project_path) / ".merak" / "recovery-leases"

    @staticmethod
    def _read_json_object(path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
        atomic_write_json(path, payload)

    def _lease_path(self, project_path: str, run_id: str) -> Path:
        return self._lease_dir(project_path) / f"{self._lease_run_key(run_id)}.lock"

    @staticmethod
    def _try_lock_fd(fd: int) -> bool:
        try:
            if os.fstat(fd).st_size == 0:
                return False
            os.lseek(fd, 0, os.SEEK_SET)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False

    @staticmethod
    def _unlock_fd(fd: int) -> None:
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass

    @staticmethod
    def _write_lease_fd(fd: int, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        previous_size = os.fstat(fd).st_size
        os.lseek(fd, 0, os.SEEK_SET)
        offset = 0
        while offset < len(encoded):
            offset += os.write(fd, encoded[offset:])
        remaining = max(0, previous_size - len(encoded))
        while remaining:
            written = os.write(fd, b" " * min(remaining, 4096))
            remaining -= written
        os.fsync(fd)

    def _acquire_recovery_lease(
        self,
        project_path: str,
        run_id: str,
        *,
        now: float,
    ) -> bool:
        key = (self._project_key(project_path), str(run_id))
        held = self._held_leases.get(key)
        if held:
            return self._renew_recovery_lease(key, now=now)
        lease_dir = self._lease_dir(project_path)
        try:
            lease_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return False
        token = uuid.uuid4().hex
        path = self._lease_path(project_path, run_id)
        created = False
        try:
            fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
            created = True
        except FileExistsError:
            try:
                fd = os.open(path, os.O_RDWR)
            except OSError:
                return False
        except OSError:
            return False
        if created:
            try:
                os.write(fd, b" ")
                os.fsync(fd)
            except OSError:
                os.close(fd)
                return False
        if not self._try_lock_fd(fd):
            os.close(fd)
            return False
        payload = {
            "schema": 1,
            "project_key": key[0],
            "run_id": str(run_id),
            "token": token,
            "pid": os.getpid(),
            "acquired_at": now,
            "heartbeat_at": now,
            "expires_at": now + self.lease_ttl_seconds,
        }
        try:
            self._write_lease_fd(fd, payload)
        except OSError:
            self._unlock_fd(fd)
            os.close(fd)
            return False
        self._held_leases[key] = {
            **payload,
            "path": str(path),
            "project_path": str(project_path),
            "fd": fd,
        }
        return True

    def _renew_recovery_lease(
        self,
        key: tuple[str, str],
        *,
        now: float,
    ) -> bool:
        held = self._held_leases.get(key)
        if not held:
            return False
        fd = self._safe_int(held.get("fd"), -1)
        if fd < 0:
            return False
        payload = {
            key_name: value
            for key_name, value in held.items()
            if key_name not in {"path", "project_path", "fd"}
        }
        payload["heartbeat_at"] = now
        payload["expires_at"] = now + self.lease_ttl_seconds
        try:
            self._write_lease_fd(fd, payload)
        except OSError:
            return False
        held.update(payload)
        return True

    def _release_recovery_lease(self, key: tuple[str, str]) -> None:
        held = self._held_leases.pop(key, None)
        if not held:
            return
        fd = self._safe_int(held.get("fd"), -1)
        if fd < 0:
            return
        try:
            payload = {
                key_name: value
                for key_name, value in held.items()
                if key_name not in {"path", "project_path", "fd"}
            }
            payload["released_at"] = time.time()
            payload["expires_at"] = 0.0
            self._write_lease_fd(fd, payload)
        except OSError:
            pass
        finally:
            self._unlock_fd(fd)
            os.close(fd)

    def _maintain_recovery_leases(self, engine: Any, *, now: float) -> None:
        for key, held in list(self._held_leases.items()):
            project_path = str(held.get("project_path") or "")
            active_run_id = engine._active_run_for_project(project_path)
            if str(active_run_id or "") == key[1]:
                self._renew_recovery_lease(key, now=now)
            else:
                self._release_recovery_lease(key)

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._load_registry()
        self._task = asyncio.create_task(
            self._run(),
            name="merak-workflow-recovery-watchdog",
        )

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        for key in list(self._held_leases):
            self._release_recovery_lease(key)

    async def _run(self) -> None:
        while True:
            try:
                await self.scan_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "Workflow recovery watchdog scan failed",
                    error=str(exc),
                )
            await asyncio.sleep(self.poll_interval_seconds)

    _safe_int = staticmethod(safe_int)
    _safe_float = staticmethod(safe_float)

    @staticmethod
    def _auto_rebuild_is_due(
        rebuild: dict[str, Any],
        options: dict[str, Any],
        *,
        now: float,
    ) -> bool:
        return auto_rebuild_is_due(rebuild, options, now=now)

    def _record_auto_rebuild_attempt(
        self,
        state_path: Path,
        *,
        phase_id: str,
        now: float,
    ) -> bool:
        with path_lock(state_path):
            return self._record_auto_rebuild_attempt_locked(
                state_path,
                phase_id=phase_id,
                now=now,
            )

    def _record_auto_rebuild_attempt_locked(
        self,
        state_path: Path,
        *,
        phase_id: str,
        now: float,
    ) -> bool:
        state = self._read_json_object(state_path)
        rebuild = state.get("auto_rebuild_required")
        if not isinstance(rebuild, dict):
            return False
        config = state.get("config") if isinstance(state.get("config"), dict) else {}
        options = config.get("options") if isinstance(config.get("options"), dict) else {}
        if not self._auto_rebuild_is_due(rebuild, options, now=now):
            return False
        retry_limit = min(
            6,
            max(
                1,
                self._safe_int(
                    rebuild.get("recovery_max_attempts")
                    or options.get("auto_rebuild_max_attempts"),
                    3,
                ),
            ),
        )
        retry_count = max(
            0,
            self._safe_int(rebuild.get("recovery_attempt_count")),
        ) + 1
        base_delay = min(
            3600.0,
            max(
                5.0,
                self._safe_float(
                    options.get("auto_rebuild_retry_delay_seconds"),
                    30.0,
                ),
            ),
        )
        delay = min(3600.0, base_delay * (2 ** max(0, retry_count - 1)))
        rebuild.update({
            "recovery_attempt_count": retry_count,
            "recovery_max_attempts": retry_limit,
            "recovery_last_attempt_at": now,
            "recovery_last_phase_id": str(phase_id),
            "recovery_next_retry_at": now + delay,
            "recovery_exhausted": retry_count >= retry_limit,
        })
        if rebuild["recovery_exhausted"]:
            rebuild["recovery_exhausted_at"] = now
        state["updated_at"] = now
        try:
            self._atomic_write_json(state_path, state)
        except OSError as exc:
            logger.warning(
                "Workflow auto-rebuild budget could not be persisted",
                state_path=str(state_path),
                error=str(exc),
            )
            return False
        return True

    @staticmethod
    def _due_phase(
        *,
        engine: Any,
        project_path: str,
        state: dict[str, Any],
        now: float,
    ) -> str:
        return due_phase(
            engine=engine,
            project_path=project_path,
            state=state,
            now=now,
        )

    def _selected_state_path(
        self,
        project_path: str,
        state_paths: list[Path],
    ) -> Optional[Path]:
        """Select the newest canonical workflow state, ignoring run sidecars.

        The runs directory also contains ``*.skills.json`` and agent-session
        JSON files.  Those files are often newer than the durable workflow
        checkpoint and previously caused the watchdog to inspect a sidecar,
        conclude that no recovery was due, and leave the real run stalled.
        """
        # Only `.merak/runs/<run_id>.json` records are passed here. Sidecars and
        # UI hints cannot authorize unattended recovery.
        selected, newest = None, -1
        ambiguous = False
        for path in state_paths:
            state = self._read_json_object(path)
            if (
                str(state.get("run_id") or "").strip()
                and isinstance(state.get("phases"), dict)
                and isinstance(state.get("config"), dict)
            ):
                try:
                    modified = path.stat().st_mtime_ns
                except OSError:
                    return None
                if modified > newest:
                    selected, newest, ambiguous = path, modified, False
                elif modified == newest:
                    ambiguous = True
        # Equal timestamps cannot prove which run is current. Never use directory
        # enumeration order or a UI session hint to authorize automatic execution.
        return None if ambiguous else selected

    async def scan_once(self, engine: Any = None) -> list[dict[str, str]]:
        return await scan_recoveries(self, engine)



workflow_recovery_watchdog = WorkflowRecoveryWatchdog()
