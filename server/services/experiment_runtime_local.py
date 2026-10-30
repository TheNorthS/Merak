"""Local-process provider for the managed experiment runtime."""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any

from ..utils.atomic_write import atomic_write_bytes
from .experiment_health import ExperimentHealthMonitor, HealthFinding
from .experiment_runtime_state import RunManifestStore, RuntimeOutcome, RuntimeSpec


class _LocalMonitor:
    def __init__(self, spec: RuntimeSpec, log_path: Path) -> None:
        self.health = ExperimentHealthMonitor(spec.health_policy)
        self.anomalies: list[HealthFinding] = []
        self.started = time.time()
        self.last_visible_event = self.started
        self.log_path = log_path


class LocalRuntimeMixin:
    async def _run_local(
        self,
        spec: RuntimeSpec,
        store: RunManifestStore,
        attempt_number: int,
        on_event: Any,
    ) -> RuntimeOutcome:
        root = Path(spec.project_path).resolve()
        attempt_dir = store.root / f"attempt-{attempt_number:02d}"
        attempt_dir.mkdir(parents=True, exist_ok=True)
        monitor = _LocalMonitor(spec, attempt_dir / "train.log")
        self._raise_if_stop_requested(spec)
        await self._run_local_preflight(
            spec, store, attempt_number, on_event, root, attempt_dir, monitor
        )
        process = await self._launch_local_process(
            spec, store, attempt_number, on_event, root, monitor.log_path
        )
        try:
            outcome = await self._monitor_local_process(
                spec, store, attempt_number, on_event, process, monitor
            )
            if outcome is not None:
                return outcome
            return await self._finish_local_process(
                spec, store, attempt_number, on_event, process, monitor
            )
        except asyncio.CancelledError:
            await self._stop_local_process(process, timeout=10)
            raise

    async def _run_local_preflight(
        self,
        spec: RuntimeSpec,
        store: RunManifestStore,
        attempt: int,
        on_event: Any,
        root: Path,
        attempt_dir: Path,
        monitor: _LocalMonitor,
    ) -> None:
        if not spec.preflight_command:
            return
        log_path = attempt_dir / "preflight.log"
        started = time.time()
        deadline = started + min(600, max(30, spec.timeout_seconds // 4))
        process = await self._create_local_process(
            spec.preflight_command, cwd=str(root), env={**os.environ, **spec.env_vars}
        )
        communication = asyncio.create_task(process.communicate())
        await self._emit(on_event, "experiment_phase", {
            "run_id": spec.run_id, "backend": "local", "phase": "preflight",
            "attempt": attempt,
        })
        output = await self._wait_local_preflight(
            spec, attempt, on_event, process, communication,
            deadline, started, monitor, log_path,
        )
        atomic_write_bytes(log_path, output or b"")
        await self._emit(on_event, "experiment_preflight", {
            "run_id": spec.run_id, "backend": "local",
            "success": process.returncode == 0, "log_path": str(log_path),
        })
        if process.returncode != 0:
            tail = (output or b"").decode("utf-8", errors="replace")[-1000:]
            raise RuntimeError(
                f"Local experiment preflight failed with code {process.returncode}: {tail}"
            )
        self._raise_if_stop_requested(spec)

    async def _wait_local_preflight(
        self,
        spec: RuntimeSpec,
        attempt: int,
        on_event: Any,
        process: Any,
        communication: asyncio.Task[Any],
        deadline: float,
        started: float,
        monitor: _LocalMonitor,
        log_path: Path,
    ) -> bytes:
        try:
            while True:
                remaining = deadline - time.time()
                if remaining <= 0:
                    raise asyncio.TimeoutError
                try:
                    output, _ = await asyncio.wait_for(
                        asyncio.shield(communication), timeout=min(1.0, remaining)
                    )
                    return output or b""
                except asyncio.TimeoutError:
                    if time.time() >= deadline:
                        raise
                    monitor.last_visible_event = await self._maybe_emit_runtime_heartbeat(
                        on_event, spec=spec, attempt_number=attempt, backend="local",
                        started_at=started, last_visible_event=monitor.last_visible_event,
                        health=monitor.health, phase="preflight",
                    )
                    if self.stop_reason(spec.run_id):
                        await asyncio.to_thread(self._terminate_local, process)
                        output, _ = await asyncio.wait_for(asyncio.shield(communication), timeout=10)
                        atomic_write_bytes(log_path, output or b"")
                        self._raise_if_stop_requested(spec)
        except asyncio.TimeoutError:
            await asyncio.to_thread(self._terminate_local, process, force=True)
            output, _ = await asyncio.wait_for(asyncio.shield(communication), timeout=10)
            atomic_write_bytes(log_path, output or b"")
            raise RuntimeError("Local experiment preflight timed out")
        except asyncio.CancelledError:
            await asyncio.to_thread(self._terminate_local, process, force=True)
            output, _ = await asyncio.wait_for(asyncio.shield(communication), timeout=10)
            atomic_write_bytes(log_path, output or b"")
            raise

    async def _launch_local_process(
        self,
        spec: RuntimeSpec,
        store: RunManifestStore,
        attempt: int,
        on_event: Any,
        root: Path,
        log_path: Path,
    ) -> Any:
        store.update_attempt(attempt, status="launch", local_log_path=str(log_path))
        await self._emit(on_event, "experiment_phase", {
            "run_id": spec.run_id, "backend": "local",
            "phase": "launch", "attempt": attempt,
        })
        process = await self._create_local_process(
            spec.command, cwd=str(root), env={**os.environ, **spec.env_vars}
        )
        store.update_attempt(attempt, status="monitor", pid=process.pid)
        return process

    async def _monitor_local_process(
        self,
        spec: RuntimeSpec,
        store: RunManifestStore,
        attempt: int,
        on_event: Any,
        process: Any,
        monitor: _LocalMonitor,
    ) -> RuntimeOutcome | None:
        with monitor.log_path.open("a", encoding="utf-8", newline="") as handle:
            while True:
                outcome = await self._poll_local_once(
                    spec, store, attempt, on_event, process, monitor, handle
                )
                if outcome is not None:
                    return outcome
                if process.returncode is not None:
                    return None
                await asyncio.sleep(0)

    async def _poll_local_once(
        self,
        spec: RuntimeSpec,
        store: RunManifestStore,
        attempt: int,
        on_event: Any,
        process: Any,
        monitor: _LocalMonitor,
        handle: Any,
    ) -> RuntimeOutcome | None:
        stop_reason = self.stop_reason(spec.run_id)
        if stop_reason:
            remaining = await self._stop_local_process(process, timeout=15)
            self._ingest_local_bytes(remaining, handle, monitor)
            return await self._finalize_failure(
                spec, store, attempt, "cancelled", process.returncode,
                monitor.anomalies, stop_reason, monitor.log_path, on_event,
                health=monitor.health,
            )
        if time.time() - monitor.started > spec.timeout_seconds:
            await self._stop_local_process(process, timeout=15)
            return await self._finalize_failure(
                spec, store, attempt, "timed_out", None, monitor.anomalies,
                f"Experiment exceeded {spec.timeout_seconds} seconds",
                monitor.log_path, on_event, health=monitor.health,
            )
        raw = await self._read_local_line(process, spec.poll_interval_seconds)
        if raw:
            return await self._handle_local_output(
                spec, store, attempt, on_event, process, monitor, handle, raw
            )
        if process.returncode is None:
            await self._local_heartbeat(spec, attempt, on_event, monitor)
        return None

    async def _handle_local_output(
        self,
        spec: RuntimeSpec,
        store: RunManifestStore,
        attempt: int,
        on_event: Any,
        process: Any,
        monitor: _LocalMonitor,
        handle: Any,
        raw: bytes,
    ) -> RuntimeOutcome | None:
        text = raw.decode("utf-8", errors="replace")
        handle.write(text)
        handle.flush()
        findings = monitor.health.ingest(text)
        monitor.anomalies.extend(findings)
        await self._publish_log_and_findings(
            spec, on_event, text, findings, monitor.health
        )
        monitor.last_visible_event = time.time()
        if not spec.auto_stop_on_anomaly or not monitor.health.should_stop(findings):
            return None
        await self._stop_local_process(process, timeout=15)
        return await self._finalize_failure(
            spec, store, attempt, "anomaly_stopped", process.returncode,
            monitor.anomalies, "Automatic stop policy triggered",
            monitor.log_path, on_event, health=monitor.health,
        )

    async def _local_heartbeat(
        self,
        spec: RuntimeSpec,
        attempt: int,
        on_event: Any,
        monitor: _LocalMonitor,
    ) -> None:
        findings = monitor.health.heartbeat(running=True)
        monitor.anomalies.extend(findings)
        await self._publish_findings(spec, on_event, findings)
        monitor.last_visible_event = await self._maybe_emit_runtime_heartbeat(
            on_event, spec=spec, attempt_number=attempt, backend="local",
            started_at=monitor.started, last_visible_event=monitor.last_visible_event,
            health=monitor.health,
        )

    async def _finish_local_process(
        self,
        spec: RuntimeSpec,
        store: RunManifestStore,
        attempt: int,
        on_event: Any,
        process: Any,
        monitor: _LocalMonitor,
    ) -> RuntimeOutcome:
        remaining, _ = await asyncio.wait_for(process.communicate(), timeout=10)
        if remaining:
            with monitor.log_path.open("a", encoding="utf-8", newline="") as handle:
                outcome = await self._handle_local_output(
                    spec, store, attempt, on_event, process, monitor, handle, remaining)
            if outcome is not None:
                return outcome
        exit_code = await process.wait()
        monitor.anomalies.extend(monitor.health.flush())
        if exit_code != 0:
            return await self._finalize_failure(
                spec, store, attempt, "failed", exit_code, monitor.anomalies,
                f"Local process exited with code {exit_code}",
                monitor.log_path, on_event, health=monitor.health,
            )
        return await self._finalize_success(
            spec, store, attempt, exit_code, monitor.anomalies,
            monitor.health, monitor.log_path, "", on_event,
        )

    @staticmethod
    async def _read_local_line(process: Any, timeout: float) -> bytes:
        if not process.stdout:
            return b""
        try:
            return await asyncio.wait_for(process.stdout.readline(), timeout=timeout)
        except asyncio.TimeoutError:
            return b""

    @staticmethod
    def _ingest_local_bytes(raw: bytes, handle: Any, monitor: _LocalMonitor) -> None:
        if not raw:
            return
        text = raw.decode("utf-8", errors="replace")
        handle.write(text)
        handle.flush()
        monitor.anomalies.extend(monitor.health.ingest(text))

    @staticmethod
    async def _create_local_process(command: str, *, cwd: str, env: dict[str, str]) -> Any:
        from . import remote_experiment_runtime

        return await remote_experiment_runtime._create_local_subprocess_shell(
            command, cwd=cwd, env=env
        )

    @staticmethod
    def _terminate_local(process: Any, *, force: bool = False) -> None:
        from .remote_experiment_runtime import _terminate_local_process

        _terminate_local_process(process, force=force)

    async def _stop_local_process(self, process: Any, *, timeout: int) -> bytes:
        if (process.returncode is not None and getattr(process, "_owned_job", None) is None
                and getattr(process, "_owned_process_group", None) is None):
            return b""
        await asyncio.to_thread(self._terminate_local, process)
        try:
            remaining, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            await asyncio.to_thread(self._terminate_local, process, force=True)
            remaining, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
        return remaining or b""
