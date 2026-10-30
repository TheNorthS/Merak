"""Durable experiment lifecycle for local, SSH, Vast.ai, and Modal runs.

The runtime owns deterministic infrastructure work. The language model may
prepare code and interpret a diagnosis, but it does not decide whether files
were synchronized, whether a process is alive, or whether results were
successfully recovered.
"""

from __future__ import annotations

import asyncio
import json
import os
import queue
import re
import shlex
import signal
import shutil as shutil
import subprocess
import threading
import time
from pathlib import Path, PurePosixPath
from typing import Any, Awaitable, Callable, Optional

import structlog

from .experiment_health import ExperimentHealthMonitor, HealthFinding
from .experiment_runtime_state import (
    ProjectSnapshot as ProjectSnapshot,
    RunManifestStore as RunManifestStore,
    RuntimeOutcome as RuntimeOutcome,
    RuntimeSpec as RuntimeSpec,
    utc_now as utc_now,
)
from .experiment_runtime_ssh import SSHRuntimeMixin
from .experiment_runtime_local import LocalRuntimeMixin
from .experiment_runtime_vast import VastRuntimeMixin
from .experiment_runtime_modal import ModalRuntimeMixin
from .experiment_runtime_lifecycle import RuntimeLifecycleMixin
from .sftp_service import sftp_service
from .ssh_manager import ssh_manager


logger = structlog.get_logger()
EventCallback = Callable[[str, dict[str, Any]], Awaitable[None] | None]

ACTIVE_STATES = {"precheck", "snapshot", "sync", "launch", "monitor", "healthy", "collect", "stopping"}


class ExperimentStopRequested(RuntimeError):
    """Raised before launch when an operator requests a cooperative stop."""


def _terminate_windows_process_tree(pid: int, *, force: bool) -> bool:
    """Terminate a Windows shell and every child it launched."""

    if pid <= 0:
        return False
    command = ["taskkill", "/PID", str(pid), "/T"]
    if force:
        command.append("/F")
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def _terminate_local_process(process: Any, *, force: bool = False) -> None:
    """Stop a local process without leaving shell-launched children running."""
    owned = getattr(process, "_owned_job", None)
    if owned is not None:
        owned.stop()
        return
    group = getattr(process, "_owned_process_group", None)
    if os.name == "posix" and isinstance(group, int) and group > 0:
        try:
            os.killpg(group, signal.SIGKILL if force else signal.SIGTERM)
        except ProcessLookupError:
            pass
        return

    # A console shell has no reliable graceful tree signal on Windows. Without
    # /F, cmd.exe may exit while Python keeps running and its pipe never closes.
    if os.name == "nt" and _terminate_windows_process_tree(
        int(getattr(process, "pid", 0) or 0),
        force=True,
    ):
        return
    if force:
        process.kill()
    else:
        process.terminate()


class _ThreadedPipe:
    """Expose a blocking ``Popen`` stdout pipe through an async readline API."""

    def __init__(self, stream: Any) -> None:
        self._stream = stream
        self._items: queue.Queue[bytes | None] = queue.Queue()
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()

    def _read(self) -> None:
        try:
            while True:
                line = self._stream.readline()
                if not line:
                    break
                self._items.put(line)
        finally:
            self._items.put(None)

    async def readline(self) -> bytes:
        while True:
            try:
                item = self._items.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.05)
                continue
            return item or b""

    def drain_after_exit(self) -> bytes:
        self._reader.join(timeout=5)
        chunks: list[bytes] = []
        while True:
            try:
                item = self._items.get_nowait()
            except queue.Empty:
                break
            if item:
                chunks.append(item)
        return b"".join(chunks)


class _ThreadedProcess:
    """Small asyncio-compatible adapter for Windows selector event loops."""

    def __init__(self, process: subprocess.Popen[bytes], owned_job: Any = None) -> None:
        self._process = process
        self._owned_job = owned_job
        self.stdout = _ThreadedPipe(process.stdout) if process.stdout else None

    @property
    def pid(self) -> int:
        return int(self._process.pid)

    @property
    def returncode(self) -> Optional[int]:
        return self._process.poll()

    def terminate(self) -> None:
        self._owned_job.stop() if self._owned_job is not None else _terminate_local_process(self._process)

    def kill(self) -> None:
        self._owned_job.stop() if self._owned_job is not None else _terminate_local_process(self._process, force=True)

    async def wait(self) -> int:
        code = int(await asyncio.to_thread(self._process.wait))
        if self._owned_job is not None:
            await asyncio.to_thread(self._owned_job.stop)
        return code

    async def communicate(self) -> tuple[bytes, None]:
        await self.wait()
        output = await asyncio.to_thread(self.stdout.drain_after_exit) if self.stdout else b""
        return output, None


async def _create_local_subprocess_shell(
    command: str,
    *,
    cwd: str,
    env: dict[str, str],
) -> Any:
    """Launch locally even when the active Windows event loop lacks subprocesses."""
    if os.name == "nt":
        from .windows_experiment_process import create_owned_experiment
        launching = asyncio.create_task(asyncio.to_thread(create_owned_experiment, command, cwd=cwd, env=env))
        try:
            process, job = await asyncio.shield(launching)
        except asyncio.CancelledError:
            process, job = await launching
            await asyncio.to_thread(job.stop)
            await asyncio.to_thread(process.wait, timeout=5)
            raise
        return _ThreadedProcess(process, job)
    try:
        process = await asyncio.create_subprocess_shell(
            command,
            cwd=cwd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
        )
        process._owned_process_group = process.pid
        return process
    except NotImplementedError:
        logger.warning(
            "Async subprocesses are unavailable; using threaded local runner",
            platform=os.name,
        )
        process = await asyncio.to_thread(
            subprocess.Popen,
            command,
            cwd=cwd,
            env=env,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        process._owned_process_group = process.pid
        adapter = _ThreadedProcess(process)
        adapter._owned_process_group = process.pid
        return adapter

class ExperimentRuntime(
    RuntimeLifecycleMixin,
    LocalRuntimeMixin,
    ModalRuntimeMixin,
    VastRuntimeMixin,
    SSHRuntimeMixin,
):
    """Execute one immutable source snapshot and preserve every attempt."""

    def __init__(self) -> None:
        self._active: dict[str, asyncio.Task] = {}
        self._stop_requests: dict[str, str] = {}

    async def cancel(self, run_id: str, reason: str = "Stopped by operator") -> bool:
        """Request a cooperative stop so the active backend can collect evidence.

        Cancelling the asyncio task directly can interrupt SFTP result recovery or
        Modal volume collection. Monitor loops observe this request and terminate
        the process group before finalizing the attempt.
        """
        task = self._active.get(run_id)
        if task is None or task.done():
            # Do not poison a future retry with a stop request for a stale UI
            # state or a run that already finalized.
            self._stop_requests.pop(run_id, None)
            return False
        self._stop_requests[run_id] = reason
        return True

    def stop_reason(self, run_id: str) -> str:
        return self._stop_requests.get(run_id, "")

    def _raise_if_stop_requested(self, spec: RuntimeSpec) -> None:
        reason = self.stop_reason(spec.run_id)
        if reason:
            raise ExperimentStopRequested(reason)

    async def _finalize_success(
        self,
        spec: RuntimeSpec,
        store: RunManifestStore,
        attempt_number: int,
        exit_code: int,
        anomalies: list[HealthFinding],
        health: ExperimentHealthMonitor,
        log_path: Path,
        result_path: str,
        on_event: EventCallback | None,
    ) -> RuntimeOutcome:
        return await self._finalize(
            spec, store, attempt_number, "completed", exit_code, anomalies,
            health, log_path, result_path or str(Path(spec.project_path) / "experiments" / "results"),
            "", on_event,
        )

    async def _finalize_failure(
        self,
        spec: RuntimeSpec,
        store: RunManifestStore,
        attempt_number: int,
        state: str,
        exit_code: Optional[int],
        anomalies: list[HealthFinding],
        error: str,
        log_path: Path,
        on_event: EventCallback | None,
        health: ExperimentHealthMonitor | None = None,
    ) -> RuntimeOutcome:
        return await self._finalize(
            spec, store, attempt_number, state, exit_code, anomalies,
            health or ExperimentHealthMonitor(spec.health_policy), log_path, "", error, on_event,
        )

    async def _finalize(
        self, spec: RuntimeSpec, store: RunManifestStore, attempt_number: int,
        state: str, exit_code: Optional[int], anomalies: list[HealthFinding],
        health: ExperimentHealthMonitor, log_path: Path, result_path: str,
        error: str, on_event: EventCallback | None,
        transfers: Optional[dict[str, Any]] = None,
    ) -> RuntimeOutcome:
        from .experiment_runtime_finalization import finalize_runtime

        payload = await finalize_runtime(
            spec=spec, store=store, attempt_number=attempt_number, state=state,
            exit_code=exit_code, anomalies=anomalies, health=health,
            log_path=log_path, result_path=result_path, error=error,
            on_event=on_event, transfers=transfers,
            diagnosis_writer=self._write_diagnosis, emitter=self._emit,
            utc_now=utc_now,
        )
        return RuntimeOutcome(**payload)
    async def _wait_for_vast_ssh(
        self,
        client: Any,
        base_url: str,
        headers: dict[str, str],
        instance_id: int,
        spec: RuntimeSpec,
    ) -> tuple[str, int]:
        deadline = time.time() + min(900, max(120, spec.timeout_seconds // 4))
        last_status = "unknown"
        while time.time() < deadline:
            self._raise_if_stop_requested(spec)
            response = await client.get(f"{base_url}/instances/{instance_id}/", headers=headers)
            if response.is_success:
                payload = response.json()
                if isinstance(payload, dict) and "instances" in payload:
                    instances = payload.get("instances") or []
                    payload = instances[0] if instances else {}
                last_status = str(payload.get("actual_status") or payload.get("status") or "unknown")
                host = str(payload.get("ssh_host") or payload.get("public_ipaddr") or "")
                port = int(payload.get("ssh_port") or payload.get("direct_port_start") or 0)
                if last_status == "running" and host and port:
                    return host, port
                if last_status in {"exited", "error", "offline"}:
                    raise RuntimeError(f"Vast.ai instance entered terminal state: {last_status}")
            await asyncio.sleep(10)
        raise TimeoutError(f"Vast.ai instance did not expose SSH before timeout (last status: {last_status})")

    async def _ensure_ssh_connection(self, server_id: str) -> None:
        connection = ssh_manager._connections.get(server_id)
        if connection and connection.conn and connection.is_alive:
            return
        config = ssh_manager._configs.get(server_id)
        accept_unknown = bool(
            config and server_id.startswith("vast_") and not config.host_key_fingerprint
        )
        await ssh_manager.connect(server_id, accept_unknown_host=accept_unknown)
        if accept_unknown and config:
            config.host_key_fingerprint = ssh_manager.get_host_key_fingerprint(server_id)

    async def _ssh_precheck(self, spec: RuntimeSpec) -> dict[str, Any]:
        command = (
            "command -v bash >/dev/null 2>&1 && "
            "command -v python >/dev/null 2>&1 && "
            "python --version && "
            "printf 'HOME=%s\\n' \"$HOME\" && "
            "df -Pk \"$HOME\" | tail -1"
        )
        stdout, stderr, code = await ssh_manager.execute(spec.server_id, command, timeout=30)
        if code != 0:
            raise RuntimeError(f"Remote precheck failed: {stderr or stdout}")
        gpu = {"available": False, "gpus": []}
        try:
            gpu = await ssh_manager.get_gpu_status(spec.server_id)
        except Exception:
            pass
        if spec.gpu_required and not gpu.get("available"):
            raise RuntimeError("Remote target passed SSH but no usable NVIDIA GPU was detected")
        return {"shell_python": stdout[-2000:], "gpu": gpu, "checked_at": utc_now()}

    async def _resolve_remote_path(self, server_id: str, raw_path: str) -> str:
        if not raw_path.startswith("~"):
            return raw_path
        stdout, stderr, code = await ssh_manager.execute(
            server_id, "printf '%s' \"$HOME\"", timeout=10
        )
        if code != 0 or not stdout.strip():
            raise RuntimeError(f"Unable to resolve remote home: {stderr or stdout}")
        suffix = raw_path[1:].lstrip("/")
        return str(PurePosixPath(stdout.strip()) / suffix) if suffix else stdout.strip()

    @staticmethod
    def _build_remote_wrapper(
        spec: RuntimeSpec,
        workspace: str,
        log_path: str,
        status_path: str,
    ) -> str:
        env_lines = []
        for key, value in sorted(spec.env_vars.items()):
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                raise ValueError(f"Invalid environment variable name: {key}")
            env_lines.append(f"export {key}={shlex.quote(str(value))}")
        exports = "\n".join(env_lines)
        return f'''#!/usr/bin/env bash
set -uo pipefail
mkdir -p {shlex.quote(str(PurePosixPath(log_path).parent))}
cd {shlex.quote(workspace)}
{exports}
set +e
({spec.command}) 2>&1 | tee -a {shlex.quote(log_path)}
rc=${{PIPESTATUS[0]}}
printf '{{"exit_code":%d,"finished_at":"%s"}}\n' "$rc" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > {shlex.quote(status_path)}
exit "$rc"
'''

    @staticmethod
    async def _read_remote_status(server_id: str, status_path: str) -> Optional[dict[str, Any]]:
        if not await sftp_service.exists(server_id, status_path):
            return None
        try:
            content = await sftp_service.read_file(server_id, status_path, max_size=64 * 1024)
            payload = json.loads(content)
            return payload if isinstance(payload, dict) else None
        except (json.JSONDecodeError, OSError):
            return None

    @staticmethod
    async def _remote_process_alive(server_id: str, pid: int) -> bool:
        stdout, _, _ = await ssh_manager.execute(
            server_id, f"kill -0 {int(pid)} >/dev/null 2>&1 && echo ALIVE || echo DEAD", timeout=10
        )
        return "ALIVE" in stdout

    @staticmethod
    async def _safe_stop_ssh(server_id: str, pid: int) -> None:
        await ssh_manager.execute(
            server_id,
            f"kill -TERM -- -{int(pid)} >/dev/null 2>&1 || kill -TERM {int(pid)} >/dev/null 2>&1 || true",
            timeout=10,
        )
        for _ in range(10):
            if not await ExperimentRuntime._remote_process_alive(server_id, pid):
                return
            await asyncio.sleep(1)
        await ssh_manager.execute(
            server_id,
            f"kill -KILL -- -{int(pid)} >/dev/null 2>&1 || kill -KILL {int(pid)} >/dev/null 2>&1 || true",
            timeout=10,
        )

    async def _publish_log_and_findings(
        self,
        spec: RuntimeSpec,
        on_event: EventCallback | None,
        text: str,
        findings: list[HealthFinding],
        health: ExperimentHealthMonitor,
    ) -> None:
        await self._emit(on_event, "experiment_log", {
            "run_id": spec.run_id,
            "backend": spec.normalized_backend(),
            "text": text[-4000:],
            "metrics": health.latest_metrics,
        })
        await self._publish_findings(spec, on_event, findings)

    async def _publish_findings(
        self,
        spec: RuntimeSpec,
        on_event: EventCallback | None,
        findings: list[HealthFinding],
    ) -> None:
        for finding in findings:
            await self._emit(on_event, "experiment_anomaly", {
                "run_id": spec.run_id,
                "backend": spec.normalized_backend(),
                "finding": finding.to_dict(),
                "auto_stop": (
                    spec.auto_stop_on_anomaly and
                    finding.kind in set(spec.health_policy.auto_stop_kinds) and
                    finding.severity == "critical"
                ),
            })

    def _write_diagnosis(
        self, spec: RuntimeSpec, store: RunManifestStore,
        attempt_number: int, state: str, anomalies: list[HealthFinding],
        error: str, log_path: str,
    ) -> Path:
        from .experiment_runtime_diagnostics import write_diagnosis

        return write_diagnosis(
            spec, store, attempt_number, state, anomalies, error, log_path,
            utc_now=utc_now,
        )
    @staticmethod
    def _publish_manifest_copy(
        spec: RuntimeSpec, store: RunManifestStore, manifest: dict[str, Any],
    ) -> None:
        from .experiment_runtime_finalization import publish_manifest_copy

        publish_manifest_copy(spec, store, manifest)
    @staticmethod
    async def _emit(callback: EventCallback | None, event: str, data: dict[str, Any]) -> None:
        if callback is None:
            return
        result = callback(event, data)
        if asyncio.iscoroutine(result):
            await result

    async def _maybe_emit_runtime_heartbeat(
        self,
        callback: EventCallback | None,
        *,
        spec: RuntimeSpec,
        attempt_number: int,
        backend: str,
        started_at: float,
        last_visible_event: float,
        health: ExperimentHealthMonitor,
        phase: str = "monitor",
    ) -> float:
        """Emit bounded liveness evidence while a healthy run has no stdout."""

        now = time.time()
        if now - last_visible_event < 30.0:
            return last_visible_event
        await self._emit(callback, "experiment_heartbeat", {
            "run_id": spec.run_id,
            "backend": backend,
            "attempt": attempt_number,
            "elapsed_seconds": max(0, int(now - started_at)),
            "status": "running",
            "phase": phase,
            "health": health.snapshot(),
        })
        return now

    @staticmethod
    def _safe_cloud_name(value: str) -> str:
        cleaned = re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")
        return cleaned[:63] or "merak-experiment"

    @staticmethod
    def _validate_spec(spec: RuntimeSpec) -> None:
        root = Path(spec.project_path).resolve()
        if not root.is_dir():
            raise NotADirectoryError(root)
        if not spec.run_id or not re.fullmatch(r"[A-Za-z0-9_.-]{1,96}", spec.run_id):
            raise ValueError("run_id must contain only letters, digits, '.', '_' or '-'")
        if not spec.command.strip():
            raise ValueError("Experiment command is empty")
        if spec.timeout_seconds < 30:
            raise ValueError("Experiment timeout must be at least 30 seconds")
        if spec.poll_interval_seconds < 0.5:
            raise ValueError("Poll interval must be at least 0.5 seconds")
        for key in spec.env_vars:
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                raise ValueError(f"Invalid environment variable name: {key}")

    @staticmethod
    def _outcome_from_manifest(manifest: dict[str, Any]) -> RuntimeOutcome:
        return RuntimeOutcome(
            run_id=str(manifest.get("run_id") or ""),
            backend=str(manifest.get("backend") or ""),
            status=str(manifest.get("status") or "unknown"),
            exit_code=manifest.get("exit_code"),
            manifest_path="",
            log_path=str(manifest.get("log_path") or ""),
            result_path=str(manifest.get("result_path") or ""),
            diagnosis_path=str(manifest.get("diagnosis_path") or ""),
            error=str(manifest.get("error") or ""),
            metrics=dict(manifest.get("metrics") or {}),
            anomalies=list(manifest.get("anomalies") or []),
        )


experiment_runtime = ExperimentRuntime()
