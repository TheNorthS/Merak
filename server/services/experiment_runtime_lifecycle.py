"""Top-level managed experiment lifecycle and safe attempt reattachment."""

from __future__ import annotations

import asyncio
import hashlib
import os
import traceback
from dataclasses import dataclass, replace
from typing import Any

from ..utils.atomic_write import atomic_write_json, atomic_write_text
from .experiment_runtime_identity import (
    ActiveExperimentConflict, active_attempt_matches, execution_identity, validate_cached_artifacts,
)
from .experiment_runtime_state import (
    ACTIVE_EXPERIMENT_STATES,
    ProjectSnapshot,
    RunManifestStore,
    RuntimeOutcome,
    RuntimeSpec,
    utc_now,
)
from .ssh_manager import SSHServerConfig, ssh_manager

ACTIVE_STATES = ACTIVE_EXPERIMENT_STATES


@dataclass
class _ResumeBinding:
    spec: RuntimeSpec
    client: Any = None
    base_url: str = ""
    headers: dict[str, str] | None = None
    instance_id: int = 0
    ephemeral_server_id: str = ""


class RuntimeLifecycleMixin:
    async def run(self, spec: RuntimeSpec, on_event: Any = None) -> RuntimeOutcome:
        self._validate_spec(spec)
        from .scientific_execution_readiness import require_scientific_execution_ready
        require_scientific_execution_ready(spec.project_path)
        active = self._active.get(spec.run_id)
        if active is not None and not active.done():
            raise ActiveExperimentConflict("This experiment already has an active monitor")
        store = RunManifestStore(spec.project_path, spec.run_id)
        snapshot = ProjectSnapshot(spec, store).build(persist=False)
        previous = store.initialize(spec)
        cached = self._cached_outcome(spec, store, snapshot, previous)
        if cached is not None:
            return cached
        if previous.get("status") in ACTIVE_STATES:
            active_attempt_matches(spec, previous, snapshot["snapshot_hash"])
            return await self._resume_or_fail(spec, store, previous, on_event)
        attempt, _ = store.begin_attempt(spec, snapshot["snapshot_hash"])
        atomic_write_json(store.root / "snapshot.json", snapshot)
        store.update(snapshot_hash=snapshot["snapshot_hash"])
        task = asyncio.current_task()
        if task:
            self._active[spec.run_id] = task
        try:
            await self._emit(on_event, "experiment_phase", {
                "run_id": spec.run_id, "backend": spec.normalized_backend(),
                "phase": "precheck", "attempt": attempt,
            })
            return await self._execute_backend(
                spec, store, snapshot, attempt, on_event
            )
        except asyncio.CancelledError:
            self._record_cancel_or_detach(spec, store, attempt)
            raise
        except self._stop_exception_type() as exc:
            return await self._finalize_operator_stop(
                spec, store, attempt, on_event, exc
            )
        except Exception as exc:
            return await self._finalize_runtime_exception(
                spec, store, attempt, on_event, exc
            )
        finally:
            self._active.pop(spec.run_id, None)
            self._stop_requests.pop(spec.run_id, None)

    def _cached_outcome(
        self, spec: RuntimeSpec, store: RunManifestStore,
        snapshot: dict[str, Any], previous: dict[str, Any],
    ) -> RuntimeOutcome | None:
        attempts = list(previous.get("attempts") or [])
        prior = attempts[-1] if attempts else {}
        command_hash = hashlib.sha256(spec.command.encode("utf-8")).hexdigest()
        matches = bool(
            previous.get("status") == "completed"
            and previous.get("snapshot_hash") == snapshot["snapshot_hash"]
            and prior.get("command_sha256") == command_hash
            and prior.get("execution_identity") == execution_identity(spec)
            and str(prior.get("approved_adjustment_id") or "")
            == str(spec.approved_adjustment_id or "")
        )
        if not matches:
            if previous.get("status") == "completed":
                raise ValueError(
                    "Completed experiment inputs changed; implicit re-execution is prohibited. "
                    "Preserve its results and use an explicitly authorized new execution identity."
                )
            return None
        validate_cached_artifacts(spec, previous)
        outcome = self._outcome_from_manifest(store.load())
        outcome.manifest_path = str(store.path)
        return outcome

    async def _resume_or_fail(
        self, spec: RuntimeSpec, store: RunManifestStore,
        previous: dict[str, Any], on_event: Any,
    ) -> RuntimeOutcome:
        task = asyncio.current_task()
        if task:
            self._active[spec.run_id] = task
        try:
            resumed = await self._resume_active_attempt(
                spec, store, previous, on_event
            )
        except asyncio.CancelledError:
            self._record_cancel_or_detach(spec, store, int(previous.get("current_attempt") or 0))
            raise
        finally:
            self._active.pop(spec.run_id, None)
            self._stop_requests.pop(spec.run_id, None)
        if resumed is not None:
            return resumed
        attempt = int(previous.get("current_attempt") or 0)
        message = (
            "MERAK restarted while this backend was active and could not safely "
            "reattach; a duplicate run was not launched."
        )
        diagnosis = self._write_diagnosis(
            spec, store, attempt, "failed", [], message,
            str(previous.get("log_path") or ""),
        )
        store.update_attempt(
            attempt, status="recovery_required",
            error="active run could not be safely reattached",
            diagnosis_path=str(diagnosis),
        )
        return RuntimeOutcome(
            run_id=spec.run_id, backend=spec.normalized_backend(), status="failed",
            manifest_path=str(store.path), diagnosis_path=str(diagnosis),
            error="Active run could not be safely reattached; no duplicate was launched",
        )

    async def _execute_backend(
        self, spec: RuntimeSpec, store: RunManifestStore,
        snapshot: dict[str, Any], attempt: int, on_event: Any,
    ) -> RuntimeOutcome:
        backend = spec.normalized_backend()
        if backend == "local":
            return await self._run_local(spec, store, attempt, on_event)
        if backend == "ssh_remote":
            return await self._run_ssh(spec, store, snapshot, attempt, on_event)
        if backend == "vast_ai":
            return await self._run_vast(spec, store, snapshot, attempt, on_event)
        if backend == "modal":
            return await self._run_modal(spec, store, snapshot, attempt, on_event)
        raise ValueError(f"Unsupported experiment backend: {backend}")

    def _record_cancel_or_detach(
        self, spec: RuntimeSpec, store: RunManifestStore, attempt: int
    ) -> None:
        if spec.run_id in self._stop_requests or spec.normalized_backend() == "local":
            store.update_attempt(attempt, status="cancelled", finished_at=utc_now())
            store.append_event("cancelled", {"attempt": attempt})
        else:
            store.update_attempt(attempt, status="monitor", detached_at=utc_now())
            store.append_event("monitor_detached", {
                "attempt": attempt,
                "reason": "MERAK process stopped without an explicit experiment cancellation",
            })

    async def _finalize_operator_stop(
        self, spec: RuntimeSpec, store: RunManifestStore,
        attempt: int, on_event: Any, exc: Exception,
    ) -> RuntimeOutcome:
        log_path = store.root / f"attempt-{attempt:02d}" / "operator-stop.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(log_path, str(exc) + "\n")
        return await self._finalize_failure(
            spec, store, attempt, "cancelled", None, [],
            str(exc), log_path, on_event,
        )

    async def _finalize_runtime_exception(
        self, spec: RuntimeSpec, store: RunManifestStore,
        attempt: int, on_event: Any, exc: Exception,
    ) -> RuntimeOutcome:
        error = str(exc).strip()
        error = f"{type(exc).__name__}: {error}" if error else type(exc).__name__
        attempt_dir = store.root / f"attempt-{attempt:02d}"
        attempt_dir.mkdir(parents=True, exist_ok=True)
        error_log = attempt_dir / "runtime-error.log"
        atomic_write_text(error_log, traceback.format_exc())
        diagnosis = self._write_diagnosis(
            spec, store, attempt, "failed", [], error, str(error_log)
        )
        fields = {
            "status": "failed", "error": error,
            "log_path": str(error_log), "diagnosis_path": str(diagnosis),
        }
        store.update_attempt(
            attempt, finished_at=utc_now(), exception_type=type(exc).__name__,
            local_log_path=str(error_log), **fields,
        )
        store.update(**fields)
        store.append_event("failed", {"attempt": attempt, "error": error})
        await self._emit(on_event, "experiment_failed", {
            "run_id": spec.run_id, "backend": spec.normalized_backend(),
            "attempt": attempt, "error": error, "log_path": str(error_log),
            "diagnosis_path": str(diagnosis),
        })
        return RuntimeOutcome(
            run_id=spec.run_id, backend=spec.normalized_backend(), status="failed",
            manifest_path=str(store.path), log_path=str(error_log),
            diagnosis_path=str(diagnosis), error=error,
        )

    @staticmethod
    def _stop_exception_type() -> type[Exception]:
        from .remote_experiment_runtime import ExperimentStopRequested

        return ExperimentStopRequested

    async def _resume_active_attempt(
        self, spec: RuntimeSpec, store: RunManifestStore,
        manifest: dict[str, Any], on_event: Any,
    ) -> RuntimeOutcome | None:
        backend = spec.normalized_backend()
        attempt_number = int(manifest.get("current_attempt") or 0)
        attempts = list(manifest.get("attempts") or [])
        attempt = next(
            (item for item in attempts if int(item.get("attempt") or 0) == attempt_number), {}
        )
        if backend == "modal" and attempt_number:
            return await self._resume_modal_attempt(
                spec, store, attempt_number, attempt, on_event
            )
        remote = dict(attempt.get("remote") or {})
        pid = int(attempt.get("pid") or 0)
        if not attempt_number or not pid or not remote:
            return None
        binding = await self._prepare_resume_binding(spec, attempt)
        if binding is None:
            return None
        await self._emit(on_event, "experiment_reattached", {
            "run_id": spec.run_id, "backend": backend,
            "attempt": attempt_number, "pid": pid,
        })
        preserve = True
        try:
            await self._ensure_ssh_connection(binding.spec.server_id)
            outcome = await self._monitor_ssh_process(
                binding.spec, store, attempt_number, pid,
                str(remote.get("workspace") or ""),
                str(remote.get("log_path") or ""),
                str(remote.get("status_path") or ""), on_event,
            )
            preserve = False
            return outcome
        except asyncio.CancelledError:
            preserve = not bool(self.stop_reason(spec.run_id))
            raise
        finally:
            await self._cleanup_resume_binding(spec, binding, preserve=preserve)

    async def _prepare_resume_binding(
        self, spec: RuntimeSpec, attempt: dict[str, Any]
    ) -> _ResumeBinding | None:
        backend = spec.normalized_backend()
        remote = dict(attempt.get("remote") or {})
        if backend == "ssh_remote":
            server_id = spec.server_id or str(remote.get("server_id") or "")
            if not server_id or server_id not in ssh_manager._configs:
                return None
            return _ResumeBinding(replace(spec, server_id=server_id))
        if backend != "vast_ai":
            return None
        provider = dict(attempt.get("provider_metadata") or {})
        instance_id = int(provider.get("instance_id") or 0)
        api_key = os.environ.get("VASTAI_API_KEY", "")
        if not instance_id or not api_key:
            return None
        try:
            import httpx
        except ImportError:
            return None
        base_url = "https://console.vast.ai/api/v0"
        headers = {"Accept": "application/json", "Authorization": f"Bearer {api_key}"}
        client = httpx.AsyncClient(timeout=60, follow_redirects=True)
        try:
            host, port = await self._wait_for_vast_ssh(
                client, base_url, headers, instance_id, spec
            )
        except Exception:
            await client.aclose()
            return None
        server_id = f"vast_{instance_id}_{spec.run_id}_resume"
        ssh_manager.add_server(SSHServerConfig(
            id=server_id, name=f"Vast.ai {instance_id} (resumed)",
            host=host, port=port, username="root", work_dir="/workspace",
            gpu_count=1, gpu_type=str(provider.get("gpu") or ""),
        ))
        return _ResumeBinding(
            replace(spec, server_id=server_id), client, base_url, headers,
            instance_id, server_id,
        )

    @staticmethod
    async def _cleanup_resume_binding(
        original_spec: RuntimeSpec, binding: _ResumeBinding, *, preserve: bool = False,
    ) -> None:
        if binding.ephemeral_server_id:
            try:
                await ssh_manager.disconnect(binding.ephemeral_server_id)
            finally:
                ssh_manager._configs.pop(binding.ephemeral_server_id, None)
        if binding.client is None:
            return
        try:
            if original_spec.auto_destroy and not preserve:
                response = await binding.client.delete(
                    f"{binding.base_url}/instances/{binding.instance_id}/",
                    headers=binding.headers,
                )
                if not response.is_success:
                    raise RuntimeError(
                        "Vast.ai resumed instance cleanup failed: "
                        f"HTTP {response.status_code}; instance {binding.instance_id}"
                    )
        finally:
            await binding.client.aclose()
