"""SSH provider execution for the managed experiment runtime."""

from __future__ import annotations

import asyncio
import shlex
import shutil
import time
from pathlib import Path, PurePosixPath
from typing import Any, Awaitable, Callable, Optional

from ..utils.atomic_write import atomic_write_text
from .experiment_health import ExperimentHealthMonitor, HealthFinding
from .experiment_runtime_state import ProjectSnapshot, RunManifestStore, RuntimeOutcome, RuntimeSpec, utc_now
from .sftp_service import sftp_service
from .ssh_manager import ssh_manager

EventCallback = Callable[[str, dict[str, Any]], Awaitable[None] | None]


class _MonitorState:
    def __init__(self, store: RunManifestStore, spec: RuntimeSpec, attempt: int) -> None:
        from .experiment_attempt_clock import attempt_record, attempt_started, restore_monitor_health
        saved = attempt_record(store, attempt)
        self.health = ExperimentHealthMonitor(spec.health_policy)
        restore_monitor_health(self.health, saved)
        self.anomalies: list[HealthFinding] = []
        self.log_offset = max(0, int(saved.get("log_offset") or 0))
        self.started = attempt_started(saved)
        self.last_visible_event = time.time()
        self.last_gpu_check = 0.0
        self.gpu_values: list[int] = []
        self.local_log = store.root / f"attempt-{attempt:02d}" / "train.log"
        self.local_log.parent.mkdir(parents=True, exist_ok=True)


class SSHRuntimeMixin:
    async def _run_ssh(
        self, spec: RuntimeSpec, store: RunManifestStore,
        snapshot: dict[str, Any], attempt_number: int,
        on_event: EventCallback | None,
    ) -> RuntimeOutcome:
        if not spec.server_id:
            raise ValueError("SSH experiment requires server_id")
        await self._ensure_ssh_connection(spec.server_id)
        precheck = await self._ssh_precheck(spec)
        store.update_attempt(attempt_number, precheck=precheck)
        self._raise_if_stop_requested(spec)
        remote = await self._sync_ssh_workspace(
            spec, store, snapshot, attempt_number, on_event
        )
        await self._run_ssh_preflight(spec, store, attempt_number, on_event, remote)
        pid = await self._launch_ssh_wrapper(
            spec, store, attempt_number, on_event, remote
        )
        return await self._monitor_ssh_process(
            spec, store, attempt_number, pid, remote["workspace"],
            remote["log"], remote["status"], on_event,
        )

    async def _sync_ssh_workspace(
        self, spec: RuntimeSpec, store: RunManifestStore,
        snapshot: dict[str, Any], attempt: int,
        on_event: EventCallback | None,
    ) -> dict[str, str]:
        remote_base = await self._resolve_remote_path(spec.server_id, spec.remote_base_dir)
        run_dir = str(PurePosixPath(remote_base) / spec.run_id / f"attempt-{attempt:02d}")
        remote = {
            "run": run_dir,
            "workspace": str(PurePosixPath(run_dir) / "workspace"),
            "log": str(PurePosixPath(run_dir) / "train.log"),
            "status": str(PurePosixPath(run_dir) / "status.json"),
            "wrapper": str(PurePosixPath(run_dir) / "run.sh"),
        }
        store.update_attempt(attempt, status="sync", remote={
            "server_id": spec.server_id, "run_dir": remote["run"],
            "workspace": remote["workspace"], "log_path": remote["log"],
            "status_path": remote["status"],
        })
        await self._emit(on_event, "experiment_phase", {
            "run_id": spec.run_id, "backend": spec.normalized_backend(),
            "phase": "sync", "attempt": attempt, "remote_dir": remote["run"],
        })
        staging = ProjectSnapshot(spec, store).materialize(
            snapshot, store.root / f"attempt-{attempt:02d}" / "snapshot"
        )
        transfer = await sftp_service.upload_directory(
            spec.server_id, str(staging), remote["workspace"],
            relative_paths=[item["path"] for item in snapshot.get("files", [])],
            verify=True,
        )
        store.update_attempt(attempt, transfers={"upload": transfer})
        store.append_event("sync_completed", {
            "attempt": attempt, "file_count": transfer["file_count"],
            "bytes": transfer["bytes"], "verified": transfer["verified"],
        })
        self._raise_if_stop_requested(spec)
        return remote

    async def _run_ssh_preflight(
        self, spec: RuntimeSpec, store: RunManifestStore, attempt: int,
        on_event: EventCallback | None, remote: dict[str, str],
    ) -> None:
        if not spec.preflight_command:
            return
        command = f"cd {shlex.quote(remote['workspace'])} && ({spec.preflight_command})"
        stdout, stderr, code = await ssh_manager.execute(
            spec.server_id, command,
            timeout=min(600, max(30, spec.timeout_seconds // 4)),
        )
        log_path = store.root / f"attempt-{attempt:02d}" / "preflight.log"
        atomic_write_text(log_path, stdout + (f"\\n[stderr]\\n{stderr}" if stderr else ""))
        store.update_attempt(attempt, preflight={
            "command": spec.preflight_command, "exit_code": code,
            "log_path": str(log_path),
        })
        await self._emit(on_event, "experiment_preflight", {
            "run_id": spec.run_id, "backend": spec.normalized_backend(),
            "attempt": attempt, "success": code == 0, "log_path": str(log_path),
        })
        if code != 0:
            raise RuntimeError(
                f"Remote experiment preflight failed with code {code}: {(stderr or stdout)[-1000:]}"
            )
        self._raise_if_stop_requested(spec)

    async def _launch_ssh_wrapper(
        self, spec: RuntimeSpec, store: RunManifestStore, attempt: int,
        on_event: EventCallback | None, remote: dict[str, str],
    ) -> int:
        local_wrapper = store.root / f"attempt-{attempt:02d}" / "run.sh"
        local_wrapper.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(
            local_wrapper,
            self._build_remote_wrapper(
                spec, remote["workspace"], remote["log"], remote["status"]
            ),
        )
        await sftp_service.upload_file(spec.server_id, local_wrapper, remote["wrapper"])
        await ssh_manager.execute(
            spec.server_id, f"chmod 700 {shlex.quote(remote['wrapper'])}", timeout=15
        )
        store.update_attempt(attempt, status="launch")
        launcher_log = str(PurePosixPath(remote["run"]) / "launcher.log")
        command = (
            f"mkdir -p {shlex.quote(remote['run'])} && "
            f"nohup setsid bash {shlex.quote(remote['wrapper'])} "
            f"> {shlex.quote(launcher_log)} 2>&1 < /dev/null & echo $!"
        )
        stdout, stderr, code = await ssh_manager.execute(spec.server_id, command, timeout=20)
        if code != 0 or not stdout.strip().splitlines():
            raise RuntimeError(f"Remote launch failed: {stderr or stdout}")
        pid_text = stdout.strip().splitlines()[-1].strip()
        if not pid_text.isdigit():
            raise RuntimeError(f"Remote launch returned an invalid PID: {pid_text}")
        pid = int(pid_text)
        store.update_attempt(attempt, status="monitor", pid=pid)
        store.append_event("launched", {"attempt": attempt, "pid": pid})
        await self._emit(on_event, "experiment_launched", {
            "run_id": spec.run_id, "backend": spec.normalized_backend(),
            "attempt": attempt, "pid": pid, "log_path": remote["log"],
        })
        return pid
    async def _monitor_ssh_process(
        self,
        spec: RuntimeSpec,
        store: RunManifestStore,
        attempt_number: int,
        pid: int,
        remote_workspace: str,
        remote_log: str,
        remote_status: str,
        on_event: EventCallback | None,
    ) -> RuntimeOutcome:
        monitor = _MonitorState(store, spec, attempt_number)
        try:
            with monitor.local_log.open("a", encoding="utf-8", newline="") as local_handle:
                while True:
                    outcome = await self._poll_ssh_once(
                        spec, store, attempt_number, pid, remote_workspace,
                        remote_log, remote_status, on_event, monitor, local_handle,
                    )
                    if outcome is not None:
                        return outcome
                    await asyncio.sleep(spec.poll_interval_seconds)
        except asyncio.CancelledError:
            if self.stop_reason(spec.run_id):
                await self._safe_stop_ssh(spec.server_id, pid)
            else:
                store.update_attempt(
                    attempt_number, status="monitor", detached_at=utc_now(),
                    health=monitor.health.snapshot(), log_offset=monitor.log_offset,
                )
            raise

    async def _poll_ssh_once(
        self, spec: RuntimeSpec, store: RunManifestStore, attempt: int, pid: int,
        workspace: str, remote_log: str, remote_status: str,
        on_event: EventCallback | None, monitor: _MonitorState,
        local_handle: Any,
    ) -> RuntimeOutcome | None:
        now = time.time()
        stop_state = await self._ssh_stop_outcome(
            spec, store, attempt, pid, workspace, remote_log, on_event, monitor, now
        )
        if stop_state is not None:
            return stop_state
        log_stop = await self._ingest_ssh_log(
            spec, store, attempt, pid, workspace, remote_log,
            on_event, monitor, local_handle, now,
        )
        if log_stop is not None:
            return log_stop
        await self._refresh_ssh_gpu(spec, attempt, on_event, monitor, now)
        status = await self._read_remote_status(spec.server_id, remote_status)
        if status is not None:
            return await self._finish_ssh_status(
                spec, store, attempt, workspace, remote_log,
                on_event, monitor, local_handle, status,
            )
        return await self._ssh_heartbeat(
            spec, store, attempt, pid, workspace, remote_log,
            on_event, monitor, now,
        )

    async def _ssh_stop_outcome(
        self, spec: RuntimeSpec, store: RunManifestStore, attempt: int, pid: int,
        workspace: str, remote_log: str, on_event: EventCallback | None,
        monitor: _MonitorState, now: float,
    ) -> RuntimeOutcome | None:
        reason = self.stop_reason(spec.run_id)
        if reason:
            await self._safe_stop_ssh(spec.server_id, pid)
            return await self._collect_and_finalize_ssh(
                spec, store, attempt, "cancelled", None, monitor.anomalies,
                monitor.health, monitor.local_log, workspace, remote_log, reason, on_event,
            )
        if now - monitor.started <= spec.timeout_seconds:
            return None
        await self._safe_stop_ssh(spec.server_id, pid)
        return await self._collect_and_finalize_ssh(
            spec, store, attempt, "timed_out", None, monitor.anomalies,
            monitor.health, monitor.local_log, workspace, remote_log,
            f"Experiment exceeded {spec.timeout_seconds} seconds", on_event,
        )

    async def _ingest_ssh_log(
        self, spec: RuntimeSpec, store: RunManifestStore, attempt: int, pid: int,
        workspace: str, remote_log: str, on_event: EventCallback | None,
        monitor: _MonitorState, local_handle: Any, now: float,
    ) -> RuntimeOutcome | None:
        chunk, monitor.log_offset = await sftp_service.read_bytes(
            spec.server_id, remote_log, monitor.log_offset, max_bytes=1024 * 1024
        )
        if not chunk:
            return None
        text = chunk.decode("utf-8", errors="replace")
        local_handle.write(text)
        local_handle.flush()
        findings = monitor.health.ingest(text, now)
        monitor.anomalies.extend(findings)
        await self._publish_log_and_findings(spec, on_event, text, findings, monitor.health)
        monitor.last_visible_event = time.time()
        if not spec.auto_stop_on_anomaly or not monitor.health.should_stop(findings):
            return None
        store.update_attempt(attempt, status="stopping")
        await self._safe_stop_ssh(spec.server_id, pid)
        return await self._collect_and_finalize_ssh(
            spec, store, attempt, "anomaly_stopped", None, monitor.anomalies,
            monitor.health, monitor.local_log, workspace, remote_log,
            "Automatic stop policy triggered", on_event,
        )

    async def _refresh_ssh_gpu(
        self, spec: RuntimeSpec, attempt: int, on_event: EventCallback | None,
        monitor: _MonitorState, now: float,
    ) -> None:
        if now - monitor.last_gpu_check < max(15.0, spec.poll_interval_seconds):
            return
        monitor.last_gpu_check = now
        try:
            gpu = await ssh_manager.get_gpu_status(spec.server_id)
            monitor.gpu_values = [
                int(item["utilization_percent"]) for item in gpu.get("gpus", [])
            ]
            await self._emit(on_event, "experiment_resources", {
                "run_id": spec.run_id, "backend": spec.normalized_backend(),
                "attempt": attempt, "gpus": gpu.get("gpus", []),
            })
        except Exception:
            monitor.gpu_values = []

    async def _finish_ssh_status(
        self, spec: RuntimeSpec, store: RunManifestStore, attempt: int,
        workspace: str, remote_log: str, on_event: EventCallback | None,
        monitor: _MonitorState, local_handle: Any, status: dict[str, Any],
    ) -> RuntimeOutcome:
        exit_code = int(status.get("exit_code", 1))
        chunk, monitor.log_offset = await sftp_service.read_bytes(
            spec.server_id, remote_log, monitor.log_offset, max_bytes=4 * 1024 * 1024
        )
        if chunk:
            text = chunk.decode("utf-8", errors="replace")
            local_handle.write(text)
            local_handle.flush()
            findings = monitor.health.ingest(text)
            monitor.anomalies.extend(findings)
            await self._publish_log_and_findings(spec, on_event, text, findings, monitor.health)
        monitor.anomalies.extend(monitor.health.flush())
        state = "completed" if exit_code == 0 else "failed"
        error = "" if exit_code == 0 else f"Remote process exited with code {exit_code}"
        return await self._collect_and_finalize_ssh(
            spec, store, attempt, state, exit_code, monitor.anomalies,
            monitor.health, monitor.local_log, workspace, remote_log, error, on_event,
        )

    async def _ssh_heartbeat(
        self, spec: RuntimeSpec, store: RunManifestStore, attempt: int, pid: int,
        workspace: str, remote_log: str, on_event: EventCallback | None,
        monitor: _MonitorState, now: float,
    ) -> RuntimeOutcome | None:
        running = await self._remote_process_alive(spec.server_id, pid)
        findings = monitor.health.heartbeat(
            running=running, gpu_utilization=monitor.gpu_values, now=now
        )
        monitor.anomalies.extend(findings)
        await self._publish_findings(spec, on_event, findings)
        if spec.auto_stop_on_anomaly and monitor.health.should_stop(findings):
            await self._safe_stop_ssh(spec.server_id, pid)
            return await self._collect_and_finalize_ssh(
                spec, store, attempt, "anomaly_stopped", None, monitor.anomalies,
                monitor.health, monitor.local_log, workspace, remote_log,
                "Remote process stalled while GPUs were idle", on_event,
            )
        if not running:
            return await self._collect_and_finalize_ssh(
                spec, store, attempt, "failed", None, monitor.anomalies,
                monitor.health, monitor.local_log, workspace, remote_log,
                "Remote process disappeared without writing status.json", on_event,
            )
        store.update_attempt(
            attempt, status="healthy", health=monitor.health.snapshot(),
            log_offset=monitor.log_offset,
        )
        monitor.last_visible_event = await self._maybe_emit_runtime_heartbeat(
            on_event, spec=spec, attempt_number=attempt,
            backend=spec.normalized_backend(), started_at=monitor.started,
            last_visible_event=monitor.last_visible_event, health=monitor.health,
        )
        return None

    async def _collect_and_finalize_ssh(
        self,
        spec: RuntimeSpec,
        store: RunManifestStore,
        attempt_number: int,
        state: str,
        exit_code: Optional[int],
        anomalies: list[HealthFinding],
        health: ExperimentHealthMonitor,
        local_log: Path,
        remote_workspace: str,
        remote_log: str,
        error: str,
        on_event: EventCallback | None,
    ) -> RuntimeOutcome:
        store.update_attempt(attempt_number, status="collect")
        await self._emit(on_event, "experiment_phase", {
            "run_id": spec.run_id, "backend": spec.normalized_backend(), "phase": "collect",
            "attempt": attempt_number,
        })
        result_root = (
            Path(spec.project_path).resolve() / "experiments" / "results" / "remote" /
            spec.run_id / f"attempt-{attempt_number:02d}"
        )
        log_root = (
            Path(spec.project_path).resolve() / "experiments" / "logs" / "remote" /
            spec.run_id / f"attempt-{attempt_number:02d}"
        )
        transfers, collection_errors = await self._collect_ssh_artifacts(
            spec, remote_workspace, remote_log, result_root, log_root, local_log
        )
        if collection_errors:
            anomalies.append(HealthFinding(
                kind="artifact_collection_failed",
                severity="critical",
                message="One or more remote artifact directories could not be recovered and verified.",
                evidence={"errors": collection_errors},
            ))
            if state == "completed":
                state = "failed"
                collection_error = "; ".join(collection_errors)
                error = f"Artifact collection failed after remote process success: {collection_error}"
        if state == "completed" and transfers["results"].get("file_count", 0) == 0:
            anomalies.append(HealthFinding(
                kind="missing_result_artifacts",
                severity="warning",
                message="The process exited successfully but produced no files under experiments/results.",
                evidence={"remote_workspace": remote_workspace},
            ))
        return await self._finalize(
            spec, store, attempt_number, state, exit_code, anomalies, health,
            local_log, str(result_root), error, on_event, transfers=transfers,
        )

    @staticmethod
    async def _collect_ssh_artifacts(
        spec: RuntimeSpec, remote_workspace: str, remote_log: str,
        result_root: Path, log_root: Path, local_log: Path,
    ) -> tuple[dict[str, Any], list[str]]:
        transfers: dict[str, Any] = {}
        errors: list[str] = []
        for key, remote, local in (
            ("results", str(PurePosixPath(remote_workspace) / "experiments" / "results"), result_root),
            ("logs", str(PurePosixPath(remote_workspace) / "experiments" / "logs"), log_root),
        ):
            try:
                transfers[key] = await sftp_service.download_directory(
                    spec.server_id, remote, local, verify=True
                )
            except Exception as exc:
                errors.append(f"{key}: {exc}")
                transfers[key] = {
                    "status": "error", "error": str(exc), "verified": False,
                }
        copied_log = log_root / "remote_train.log"
        copied_log.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(local_log, copied_log)
        try:
            transfers["remote_train_log"] = await sftp_service.download_file(
                spec.server_id, remote_log, log_root / "train.log"
            )
        except Exception as exc:
            transfers["remote_train_log"] = {"status": "error", "error": str(exc)}
        return transfers, errors
