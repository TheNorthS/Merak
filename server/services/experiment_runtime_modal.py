"""Modal provider orchestration for managed experiment runs."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

from ..utils.atomic_write import atomic_write_text
from .experiment_health import ExperimentHealthMonitor, HealthFinding
from .experiment_runtime_state import (
    ProjectSnapshot,
    RunManifestStore,
    RuntimeOutcome,
    RuntimeSpec,
    utc_now,
)


class _ModalRun:
    def __init__(
        self, executable: str, env: dict[str, str], app_name: str,
        staging: Path, log_path: Path, output_root: Path,
        health: ExperimentHealthMonitor,
    ) -> None:
        self.executable = executable
        self.env = env
        self.app_name = app_name
        self.staging = staging
        self.log_path = log_path
        self.output_root = output_root
        self.health = health
        self.anomalies: list[HealthFinding] = []
        self.started = time.time()
        self.last_visible_event = self.started
        self.result_payload: dict[str, Any] = {}


class ModalRuntimeMixin:
    async def _resume_modal_attempt(
        self, spec: RuntimeSpec, store: RunManifestStore, attempt: int,
        attempt_data: dict[str, Any], on_event: Any,
    ) -> RuntimeOutcome | None:
        executable = shutil.which("modal")
        token_id = os.environ.get("MODAL_TOKEN_ID", "")
        token_secret = os.environ.get("MODAL_TOKEN_SECRET", "")
        provider = dict(attempt_data.get("provider_metadata") or {})
        app_name = str(provider.get("app_name") or "")
        volume = str(provider.get("volume") or spec.modal_volume)
        if not executable or not token_id or not token_secret or not app_name:
            return None
        env = {**os.environ, "MODAL_TOKEN_ID": token_id, "MODAL_TOKEN_SECRET": token_secret}
        attempt_dir = store.root / f"attempt-{attempt:02d}"
        log_path = attempt_dir / "modal.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        output_root = (
            Path(spec.project_path).resolve() / "experiments" / "results" / "remote"
            / spec.run_id / f"attempt-{attempt:02d}"
        )
        output_root.mkdir(parents=True, exist_ok=True)
        context = _ModalRun(
            executable, env, app_name,
            Path(str(provider.get("snapshot_dir") or attempt_dir / "snapshot")),
            log_path, output_root, ExperimentHealthMonitor(spec.health_policy),
        )
        from .experiment_attempt_clock import attempt_started, restore_monitor_health
        context.started = attempt_started(attempt_data)
        restore_monitor_health(context.health, attempt_data)
        context.log_offset = log_path.stat().st_size if log_path.exists() else 0
        context.volume = volume
        await self._emit(on_event, "experiment_reattached", {
            "run_id": spec.run_id, "backend": "modal", "attempt": attempt,
            "app_name": app_name,
        })
        return await self._monitor_resumed_modal(
            spec, store, attempt, on_event, context
        )

    async def _monitor_resumed_modal(
        self, spec: RuntimeSpec, store: RunManifestStore, attempt: int,
        on_event: Any, context: _ModalRun,
    ) -> RuntimeOutcome:
        deadline = context.started + spec.timeout_seconds
        while time.time() < deadline:
            outcome = await self._poll_resumed_modal(
                spec, store, attempt, on_event, context
            )
            if outcome is not None:
                return outcome
            await asyncio.sleep(max(10.0, spec.poll_interval_seconds))
        await self._stop_modal_app(context.executable, context.app_name, context.env)
        await self._recover_resumed_modal(spec, store, attempt, context)
        return await self._finalize_failure(
            spec, store, attempt, "timed_out", None, context.anomalies,
            "Modal reattachment exceeded the configured timeout",
            context.log_path, on_event, health=context.health,
        )

    async def _poll_resumed_modal(
        self, spec: RuntimeSpec, store: RunManifestStore, attempt: int,
        on_event: Any, context: _ModalRun,
    ) -> RuntimeOutcome | None:
        stop_reason = self.stop_reason(spec.run_id)
        if stop_reason:
            await self._stop_modal_app(context.executable, context.app_name, context.env)
            await self._recover_resumed_modal(spec, store, attempt, context)
            return await self._finalize_failure(
                spec, store, attempt, "cancelled", None, context.anomalies,
                stop_reason, context.log_path, on_event, health=context.health,
            )
        remote_root = f"/{spec.run_id}/attempt-{attempt:02d}"
        status_target = store.root / f"attempt-{attempt:02d}" / "remote-status.json"
        status_ready = await self._modal_get_file(
            context.executable, context.volume,
            f"{remote_root}/status.json", status_target, context.env,
        )
        anomaly_stop = await self._ingest_resumed_modal_log(
            spec, store, attempt, on_event, context, remote_root
        )
        if anomaly_stop:
            return await self._finalize_failure(
                spec, store, attempt, "anomaly_stopped", None,
                context.anomalies,
                "Automatic stop policy triggered after Modal reattachment",
                context.log_path, on_event, health=context.health,
            )
        if status_ready and status_target.is_file():
            return await self._finish_resumed_modal(
                spec, store, attempt, on_event, context, status_target
            )
        store.update_attempt(
            attempt, status="monitor", reattached_at=utc_now(),
            health=context.health.snapshot(),
        )
        context.last_visible_event = await self._maybe_emit_runtime_heartbeat(
            on_event, spec=spec, attempt_number=attempt, backend="modal",
            started_at=context.started,
            last_visible_event=context.last_visible_event, health=context.health,
        )
        return None

    async def _ingest_resumed_modal_log(
        self, spec: RuntimeSpec, store: RunManifestStore, attempt: int,
        on_event: Any, context: _ModalRun, remote_root: str,
    ) -> bool:
        target = store.root / f"attempt-{attempt:02d}" / "remote-train.log"
        ready = await self._modal_get_file(
            context.executable, context.volume,
            f"{remote_root}/train.log", target, context.env,
        )
        if not ready or not target.is_file():
            return False
        data = target.read_bytes()
        if len(data) < context.log_offset:
            context.log_offset = 0
        if len(data) <= context.log_offset:
            return False
        chunk = data[context.log_offset:]
        context.log_offset = len(data)
        text = chunk.decode("utf-8", errors="replace")
        with context.log_path.open("a", encoding="utf-8", newline="") as handle:
            handle.write(text)
        findings = context.health.ingest(text)
        context.anomalies.extend(findings)
        await self._publish_log_and_findings(spec, on_event, text, findings, context.health)
        context.last_visible_event = time.time()
        if spec.auto_stop_on_anomaly and context.health.should_stop(findings):
            await self._stop_modal_app(context.executable, context.app_name, context.env)
            await self._recover_resumed_modal(spec, store, attempt, context)
            return True
        return False

    async def _finish_resumed_modal(
        self, spec: RuntimeSpec, store: RunManifestStore, attempt: int,
        on_event: Any, context: _ModalRun, status_path: Path,
    ) -> RuntimeOutcome:
        try:
            status = json.loads(status_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            status = {}
        await self._recover_resumed_modal(spec, store, attempt, context)
        exit_code = int(status.get("exit_code", 1))
        if exit_code == 0:
            return await self._finalize_success(
                spec, store, attempt, exit_code, context.anomalies,
                context.health, context.log_path, str(context.output_root), on_event,
            )
        return await self._finalize_failure(
            spec, store, attempt, "failed", exit_code, context.anomalies,
            str(status.get("error") or f"Modal function exited with {exit_code}"),
            context.log_path, on_event, health=context.health,
        )

    async def _recover_resumed_modal(
        self, spec: RuntimeSpec, store: RunManifestStore,
        attempt: int, context: _ModalRun,
    ) -> None:
        await self._recover_modal_volume(
            context.executable, context.volume, spec.run_id, attempt,
            context.output_root, context.env, store,
        )
    async def _run_modal(
        self, spec: RuntimeSpec, store: RunManifestStore,
        snapshot: dict[str, Any], attempt_number: int, on_event: Any,
    ) -> RuntimeOutcome:
        context, script = self._prepare_modal(
            spec, store, snapshot, attempt_number
        )
        process = await asyncio.create_subprocess_exec(
            context.executable, "run", str(script),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            env=context.env,
        )
        store.update_attempt(attempt_number, status="monitor", pid=process.pid)
        await self._emit(on_event, "experiment_launched", {
            "run_id": spec.run_id, "backend": "modal", "attempt": attempt_number,
            "app_name": context.app_name, "log_path": str(context.log_path),
        })
        try:
            outcome = await self._monitor_modal(
                spec, store, attempt_number, on_event, process, context
            )
            if outcome is not None:
                return outcome
            return await self._finish_modal(
                spec, store, attempt_number, on_event, process, context
            )
        except asyncio.CancelledError:
            await self._detach_or_stop_modal(
                spec, store, attempt_number, process, context
            )
            raise

    def _prepare_modal(
        self, spec: RuntimeSpec, store: RunManifestStore,
        snapshot: dict[str, Any], attempt: int,
    ) -> tuple[_ModalRun, Path]:
        executable = shutil.which("modal")
        if not executable:
            raise RuntimeError("Modal CLI is not installed")
        token_id = os.environ.get("MODAL_TOKEN_ID", "")
        token_secret = os.environ.get("MODAL_TOKEN_SECRET", "")
        if not token_id or not token_secret:
            raise RuntimeError("MODAL_TOKEN_ID and MODAL_TOKEN_SECRET are not configured")
        self._raise_if_stop_requested(spec)
        attempt_dir = store.root / f"attempt-{attempt:02d}"
        staging = attempt_dir / "snapshot"
        ProjectSnapshot(spec, store).materialize(snapshot, staging)
        app_name = self._safe_cloud_name(f"merak-{spec.run_id}-{attempt}")
        script = attempt_dir / "modal_launcher.py"
        output_root = (
            Path(spec.project_path).resolve() / "experiments" / "results" / "remote"
            / spec.run_id / f"attempt-{attempt:02d}"
        )
        output_root.mkdir(parents=True, exist_ok=True)
        atomic_write_text(script, self._build_modal_launcher(spec, staging, app_name, attempt))
        store.update_attempt(attempt, status="launch", provider_metadata={
            "app_name": app_name, "volume": spec.modal_volume,
            "gpu": spec.gpu_type, "snapshot_dir": str(staging),
        })
        env = {**os.environ, "MODAL_TOKEN_ID": token_id, "MODAL_TOKEN_SECRET": token_secret}
        context = _ModalRun(
            executable, env, app_name, staging, attempt_dir / "modal.log",
            output_root, ExperimentHealthMonitor(spec.health_policy),
        )
        return context, script

    async def _monitor_modal(
        self, spec: RuntimeSpec, store: RunManifestStore, attempt: int,
        on_event: Any, process: Any, context: _ModalRun,
    ) -> RuntimeOutcome | None:
        with context.log_path.open("a", encoding="utf-8", newline="") as handle:
            while True:
                outcome = await self._poll_modal_once(
                    spec, store, attempt, on_event, process, context, handle
                )
                if outcome is not None:
                    return outcome
                if process.returncode is not None:
                    return None

    async def _poll_modal_once(
        self, spec: RuntimeSpec, store: RunManifestStore, attempt: int,
        on_event: Any, process: Any, context: _ModalRun, handle: Any,
    ) -> RuntimeOutcome | None:
        stop_reason = self.stop_reason(spec.run_id)
        if stop_reason:
            return await self._stop_and_finalize_modal(
                spec, store, attempt, on_event, process, context,
                "cancelled", stop_reason,
            )
        if time.time() - context.started > spec.timeout_seconds:
            return await self._stop_and_finalize_modal(
                spec, store, attempt, on_event, process, context,
                "timed_out", f"Modal run exceeded {spec.timeout_seconds} seconds",
            )
        raw = await self._read_modal_line(process, spec.poll_interval_seconds)
        if raw:
            return await self._handle_modal_output(
                spec, store, attempt, on_event, process, context, handle, raw
            )
        if process.returncode is None:
            findings = context.health.heartbeat(running=True)
            context.anomalies.extend(findings)
            await self._publish_findings(spec, on_event, findings)
            context.last_visible_event = await self._maybe_emit_runtime_heartbeat(
                on_event, spec=spec, attempt_number=attempt, backend="modal",
                started_at=context.started,
                last_visible_event=context.last_visible_event,
                health=context.health,
            )
        return None

    async def _handle_modal_output(
        self, spec: RuntimeSpec, store: RunManifestStore, attempt: int,
        on_event: Any, process: Any, context: _ModalRun,
        handle: Any, raw: bytes,
    ) -> RuntimeOutcome | None:
        text = raw.decode("utf-8", errors="replace")
        handle.write(text)
        handle.flush()
        if text.startswith("MERAK_GPU:"):
            payload = self._modal_json_payload(text, "MERAK_GPU:")
            await self._emit(on_event, "experiment_resources", {
                "run_id": spec.run_id, "backend": "modal", "attempt": attempt,
                "gpus": payload.get("gpus", []),
            })
            return None
        if text.startswith("MERAK_RESULT:"):
            context.result_payload = self._modal_json_payload(text, "MERAK_RESULT:")
        findings = context.health.ingest(text)
        context.anomalies.extend(findings)
        await self._publish_log_and_findings(
            spec, on_event, text, findings, context.health
        )
        context.last_visible_event = time.time()
        if spec.auto_stop_on_anomaly and context.health.should_stop(findings):
            return await self._stop_and_finalize_modal(
                spec, store, attempt, on_event, process, context,
                "anomaly_stopped", "Automatic stop policy triggered",
            )
        return None

    @staticmethod
    def _modal_json_payload(text: str, prefix: str) -> dict[str, Any]:
        try:
            payload = json.loads(text.split(prefix, 1)[1])
        except (IndexError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    async def _stop_and_finalize_modal(
        self, spec: RuntimeSpec, store: RunManifestStore, attempt: int,
        on_event: Any, process: Any, context: _ModalRun,
        state: str, error: str,
    ) -> RuntimeOutcome:
        await self._stop_modal_process(
            process, context.executable, context.app_name, context.env
        )
        await self._recover_modal_results(spec, store, attempt, context)
        return await self._finalize_failure(
            spec, store, attempt, state, process.returncode,
            context.anomalies, error, context.log_path, on_event,
            health=context.health,
        )

    async def _finish_modal(
        self, spec: RuntimeSpec, store: RunManifestStore, attempt: int,
        on_event: Any, process: Any, context: _ModalRun,
    ) -> RuntimeOutcome:
        exit_code = await process.wait()
        context.anomalies.extend(context.health.flush())
        await self._recover_modal_results(spec, store, attempt, context)
        remote_exit = int(context.result_payload.get("exit_code", exit_code))
        if exit_code != 0 or remote_exit != 0:
            return await self._finalize_failure(
                spec, store, attempt, "failed", remote_exit, context.anomalies,
                str(context.result_payload.get("error") or f"Modal CLI exited with {exit_code}"),
                context.log_path, on_event, health=context.health,
            )
        outcome = await self._finalize_success(
            spec, store, attempt, remote_exit, context.anomalies, context.health,
            context.log_path, str(context.output_root), on_event,
        )
        outcome.metadata.update({
            "app_name": context.app_name, "volume": spec.modal_volume,
            "gpu": spec.gpu_type,
            "runtime_seconds": round(time.time() - context.started, 1),
        })
        return outcome

    async def _recover_modal_results(
        self, spec: RuntimeSpec, store: RunManifestStore,
        attempt: int, context: _ModalRun,
    ) -> None:
        await self._recover_modal_volume(
            context.executable, spec.modal_volume, spec.run_id,
            attempt, context.output_root, context.env, store,
        )

    async def _detach_or_stop_modal(
        self, spec: RuntimeSpec, store: RunManifestStore, attempt: int,
        process: Any, context: _ModalRun,
    ) -> None:
        if self.stop_reason(spec.run_id):
            await self._stop_modal_process(
                process, context.executable, context.app_name, context.env
            )
            return
        store.update_attempt(
            attempt, status="monitor", detached_at=utc_now(),
            provider_metadata={
                "app_name": context.app_name, "volume": spec.modal_volume,
                "gpu": spec.gpu_type, "snapshot_dir": str(context.staging),
            },
        )

    @staticmethod
    async def _read_modal_line(process: Any, timeout: float) -> bytes:
        if not process.stdout:
            return b""
        try:
            return await asyncio.wait_for(process.stdout.readline(), timeout=timeout)
        except asyncio.TimeoutError:
            return b""

    async def _recover_modal_volume(
        self, executable: str, volume: str, run_id: str, attempt: int,
        output_root: Path, env: dict[str, str], store: RunManifestStore,
    ) -> None:
        remote_path = f"/{run_id}/attempt-{attempt:02d}"
        process = await asyncio.create_subprocess_exec(
            executable, "volume", "get", volume, remote_path, str(output_root),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            env=env,
        )
        try:
            output, _ = await asyncio.wait_for(process.communicate(), timeout=300)
        except asyncio.TimeoutError:
            process.kill()
            await process.communicate()
            store.append_event(
                "modal_result_recovery_failed", {"error": "volume get timed out"}
            )
            return
        message = output.decode("utf-8", errors="replace") if output else ""
        store.append_event("modal_result_recovery", {
            "exit_code": process.returncode, "remote_path": remote_path,
            "local_path": str(output_root), "output": message[-1000:],
        })

    @staticmethod
    async def _modal_get_file(
        executable: str, volume: str, remote_path: str,
        local_path: Path, env: dict[str, str],
    ) -> bool:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.unlink(missing_ok=True)
        process = await asyncio.create_subprocess_exec(
            executable, "volume", "get", volume, remote_path, str(local_path),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            env=env,
        )
        try:
            await asyncio.wait_for(process.wait(), timeout=60)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return False
        return process.returncode == 0 and local_path.exists()

    @staticmethod
    async def _stop_modal_app(
        executable: str, app_name: str, env: dict[str, str]
    ) -> None:
        process = await asyncio.create_subprocess_exec(
            executable, "app", "stop", app_name,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            env=env,
        )
        try:
            await asyncio.wait_for(process.wait(), timeout=30)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()

    async def _stop_modal_process(
        self, process: Any, executable: str, app_name: str, env: dict[str, str]
    ) -> None:
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=15)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        await self._stop_modal_app(executable, app_name, env)

    @staticmethod
    def _build_modal_launcher(
        spec: RuntimeSpec, snapshot_dir: Path, app_name: str, attempt_number: int
    ) -> str:
        from .experiment_modal_launcher import build_modal_launcher

        return build_modal_launcher(spec, snapshot_dir, app_name, attempt_number)
