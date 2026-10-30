"""Immutable retry and post-run validation policy."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Optional

from ..utils.atomic_write import atomic_write_json
from .experiment_models import Experiment, ExperimentJob, JobStatus
from .remote_experiment_runtime import ProjectSnapshot, RunManifestStore, RuntimeSpec


def _retry_context(scheduler: Any, experiment: Experiment, job: ExperimentJob) -> dict[str, Any]:
    store = RunManifestStore(experiment.project_path, job.id)
    manifest = store.load()
    attempts = [item for item in manifest.get("attempts") or [] if isinstance(item, dict)]
    previous = attempts[-1] if attempts else {}
    previous_snapshot = str(previous.get("snapshot_hash") or "")
    previous_command = str(previous.get("command_sha256") or "")
    current_command = hashlib.sha256(job.command.encode("utf-8")).hexdigest()
    try:
        current_snapshot = scheduler._current_source_snapshot_hash(experiment, job, store)
    except (OSError, ValueError) as exc:
        current_snapshot, snapshot_error = "", f"{type(exc).__name__}: {exc}"
    else:
        snapshot_error = ""
    anomalies = [item for item in previous.get("anomalies") or [] if isinstance(item, dict)]
    critical = [
        item for item in anomalies
        if str(item.get("severity") or "").casefold() == "critical"
    ]
    return {
        "previous": previous, "previous_snapshot": previous_snapshot,
        "current_snapshot": current_snapshot, "snapshot_error": snapshot_error,
        "previous_command": previous_command, "current_command": current_command,
        "source_changed": bool(previous_snapshot and current_snapshot and previous_snapshot != current_snapshot),
        "command_changed": bool(previous_command and previous_command != current_command),
        "critical": critical,
    }


def _retry_reason(job: ExperimentJob, context: dict[str, Any], budget: int) -> tuple[str, bool]:
    from .experiment_runtime_state import ACTIVE_EXPERIMENT_STATES
    previous = context["previous"]
    platform_failure = bool(
        previous.get("exit_code") is None and not context["critical"]
        and job.status == JobStatus.FAILED
        and previous.get("status") not in ACTIVE_EXPERIMENT_STATES
    )
    if previous.get("status") == "recovery_required":
        reason = "the previous remote attempt requires reconciliation before retry"
    elif context["critical"]:
        reason = "critical runtime anomaly requires an approved scientific/runtime adjustment"
    elif budget <= 0:
        reason = "automatic retry budget exhausted"
    elif context["source_changed"]:
        reason = "execution source changed after the preserved failed attempt"
    elif context["command_changed"]:
        reason = "execution command changed after the preserved failed attempt"
    elif platform_failure:
        reason = "attempt failed before producing an exit code or scientific anomaly"
    elif job.status != JobStatus.FAILED:
        reason = f"job status {job.status.value} is not eligible for automatic retry"
    else:
        reason = "failed scientific process is unchanged and requires diagnosis-driven repair"
    return reason, platform_failure


def _retry_fingerprint(job: ExperimentJob, context: dict[str, Any], reason: str) -> str:
    previous = context["previous"]
    payload = {
        "job_id": job.id, "attempt": int(previous.get("attempt") or 0),
        "previous_snapshot": context["previous_snapshot"],
        "current_snapshot": context["current_snapshot"],
        "previous_command_hash": context["previous_command"],
        "current_command_hash": context["current_command"],
        "exit_code": previous.get("exit_code"),
        "error": str(previous.get("error") or job.error_message or "").strip(),
        "critical_anomalies": context["critical"], "reason": reason,
    }
    return hashlib.sha256(json.dumps(
        payload, ensure_ascii=False, sort_keys=True, default=str,
    ).encode("utf-8")).hexdigest()


class ExperimentRetryMixin:
    async def retry_job(
        self,
        experiment_id: str,
        job_id: str,
        proposal_id: str,
    ) -> dict[str, Any]:
        """Queue a new immutable attempt after one approved adjustment."""
        experiment = self._experiments.get(experiment_id)
        job = self.get_job(job_id)
        if not experiment or not job or job.experiment_id != experiment_id:
            raise KeyError("Experiment job not found")
        if job.status in {JobStatus.RUNNING, JobStatus.QUEUED, JobStatus.RETRYING, JobStatus.STOPPING}:
            raise ValueError("The job is already active")
        if job.retry_count >= job.max_retries:
            raise ValueError("The job has reached its approved retry limit")
        proposals = {item.get("proposal_id"): item for item in self.list_adjustment_proposals(experiment_id, job_id)}
        proposal = proposals.get(proposal_id)
        if not proposal or proposal.get("status") != "approved":
            raise ValueError("A current approved adjustment proposal is required")
        if proposal.get("consumed_at"):
            raise ValueError("This adjustment proposal has already been used for an attempt")
        if job.approved_adjustment_id != proposal_id:
            raise ValueError("The approved adjustment no longer matches the job configuration")

        store = RunManifestStore(experiment.project_path, job.id)
        current_source_hash = self._current_source_snapshot_hash(experiment, job, store)
        expected_source_hash = str((proposal.get("expected") or {}).get("source_snapshot_hash") or "")
        if current_source_hash != expected_source_hash:
            raise ValueError("Project source changed after approval; create and approve a new proposal")
        proposal_path = store.root / "proposals" / f"{proposal_id}.json"
        proposal["consumed_at"] = datetime.utcnow().isoformat() + "Z"
        proposal["retry_number"] = job.retry_count + 1
        atomic_write_json(proposal_path, proposal)
        previous_manifest = store.load()
        next_attempt = int(previous_manifest.get("current_attempt") or 0) + 1

        job.retry_count += 1
        job.status = JobStatus.QUEUED
        job.started_at = None
        job.finished_at = None
        job.exit_code = None
        job.error_message = None
        await self._queue.put((-job.priority - 10, next(self._queue_sequence), job))
        store.append_event("retry_queued", {
            "proposal_id": proposal_id,
            "next_attempt": next_attempt,
            "retry_count": job.retry_count,
        })
        await self._notify_listeners("job_retrying", {
            "experiment_id": experiment_id,
            "job_id": job.id,
            "proposal_id": proposal_id,
            "retry": job.retry_count,
            "next_attempt": next_attempt,
        })
        return {
            "status": "queued",
            "job_id": job.id,
            "proposal_id": proposal_id,
            "next_attempt": next_attempt,
            "retry_count": job.retry_count,
        }

    def automatic_retry_assessment(
        self,
        experiment_id: str,
        job_id: str,
    ) -> dict[str, Any]:
        """Classify whether a failed attempt can be retried without research approval."""
        experiment = self._experiments.get(experiment_id)
        job = self.get_job(job_id)
        if not experiment or not job or job.experiment_id != experiment_id:
            raise KeyError("Experiment job not found")
        context = _retry_context(self, experiment, job)
        previous = context["previous"]
        budget = max(0, int(job.max_retries) - int(job.retry_count))
        reason, platform_failure = _retry_reason(job, context, budget)
        eligible = bool(
            job.status == JobStatus.FAILED
            and not job.pending_adjustment_id
            and budget > 0
            and not context["critical"]
            and (
                context["source_changed"]
                or context["command_changed"]
                or platform_failure
            )
        )
        return {
            "eligible": eligible, "reason": reason,
            "source_changed": context["source_changed"],
            "command_changed": context["command_changed"],
            "platform_launch_failure": platform_failure,
            "retry_budget_remaining": budget,
            "previous_attempt": int(previous.get("attempt") or 0),
            "previous_snapshot_hash": context["previous_snapshot"],
            "current_snapshot_hash": context["current_snapshot"],
            "snapshot_error": context["snapshot_error"],
            "exit_code": previous.get("exit_code"),
            "error": str(previous.get("error") or job.error_message or "").strip(),
            "critical_anomalies": context["critical"],
            "diagnosis_path": str(
                previous.get("diagnosis_path") or job.diagnosis_path or ""
            ),
            "fingerprint": _retry_fingerprint(job, context, reason),
        }

    async def mark_job_output_validation_failed(
        self,
        experiment_id: str,
        job_id: str,
        issues: list[str],
    ) -> dict[str, Any]:
        """Quarantine a zero-exit attempt whose declared evidence is invalid."""

        experiment = self._experiments.get(experiment_id)
        job = self.get_job(job_id)
        if not experiment or not job or job.experiment_id != experiment_id:
            raise KeyError("Experiment job not found")
        if job.status != JobStatus.COMPLETED:
            raise ValueError("Only a completed job can fail post-run validation")
        normalized = list(dict.fromkeys(
            str(item).strip() for item in issues if str(item).strip()
        ))
        if not normalized:
            raise ValueError("Post-run validation requires at least one issue")

        store = RunManifestStore(experiment.project_path, job.id)
        manifest = store.load()
        attempt_number = int(manifest.get("current_attempt") or 0)
        attempt_dir = store.root / f"attempt-{attempt_number:02d}"
        attempt_dir.mkdir(parents=True, exist_ok=True)
        diagnosis_path = attempt_dir / "post-run-validation.json"
        payload = {
            "schema_version": 1,
            "run_id": job.id,
            "attempt": attempt_number,
            "state": "failed_validation",
            "owner": "experiment_output_contract",
            "issues": normalized,
            "retry_contract": {
                "preserve_failed_attempt": True,
                "new_attempt_required": True,
                "automatic_after_source_repair": True,
            },
            "created_at": datetime.utcnow().isoformat() + "Z",
        }
        atomic_write_json(diagnosis_path, payload)
        message = "Post-run evidence validation failed: " + "; ".join(normalized)
        store.update_attempt(
            attempt_number,
            status="failed_validation",
            evidence_eligible=False,
            validation_issues=normalized,
            validation_error=message,
            diagnosis_path=str(diagnosis_path),
        )
        store.update(
            status="failed_validation",
            evidence_eligible=False,
            error=message,
            diagnosis_path=str(diagnosis_path),
        )
        store.append_event("post_run_validation_failed", {
            "attempt": attempt_number,
            "issues": normalized,
            "diagnosis_path": str(diagnosis_path),
        })
        job.status = JobStatus.FAILED
        job.error_message = message
        job.diagnosis_path = str(diagnosis_path)
        await self._notify_listeners("job_output_validation_failed", {
            "experiment_id": experiment_id,
            "job_id": job.id,
            "attempt": attempt_number,
            "issues": normalized,
            "diagnosis_path": str(diagnosis_path),
        })
        return payload

    async def retry_failed_job_automatically(
        self,
        experiment_id: str,
        job_id: str,
        *,
        assessment: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Queue a new immutable attempt for a platform-owned or repaired failure."""

        experiment = self._experiments.get(experiment_id)
        job = self.get_job(job_id)
        if not experiment or not job or job.experiment_id != experiment_id:
            raise KeyError("Experiment job not found")
        assessment = assessment or self.automatic_retry_assessment(
            experiment_id,
            job_id,
        )
        if not assessment.get("eligible"):
            raise ValueError(
                "Failed job is not eligible for automatic retry: "
                + str(assessment.get("reason") or "unknown reason")
            )
        if job.status != JobStatus.FAILED:
            raise ValueError("Only a preserved failed job can be automatically retried")

        store = RunManifestStore(experiment.project_path, job.id)
        previous_manifest = store.load()
        next_attempt = int(previous_manifest.get("current_attempt") or 0) + 1
        job.retry_count += 1
        job.status = JobStatus.QUEUED
        job.started_at = None
        job.finished_at = None
        job.exit_code = None
        job.error_message = None
        job.pending_adjustment_id = None
        job.approved_adjustment_id = None
        await self._queue.put(
            (-job.priority - 10, next(self._queue_sequence), job)
        )
        event_payload = {
            "next_attempt": next_attempt,
            "retry_count": job.retry_count,
            "reason": str(assessment.get("reason") or ""),
            "fingerprint": str(assessment.get("fingerprint") or ""),
            "source_changed": bool(assessment.get("source_changed")),
            "command_changed": bool(assessment.get("command_changed")),
            "platform_launch_failure": bool(
                assessment.get("platform_launch_failure")
            ),
        }
        store.append_event("automatic_retry_queued", event_payload)
        await self._notify_listeners("job_retrying", {
            "experiment_id": experiment_id,
            "job_id": job.id,
            "proposal_id": "",
            "automatic": True,
            **event_payload,
        })
        return {
            "status": "queued",
            "job_id": job.id,
            "automatic": True,
            **event_payload,
        }

    @staticmethod
    def _current_source_snapshot_hash(
        experiment: Experiment,
        job: ExperimentJob,
        store: RunManifestStore,
    ) -> str:
        spec = RuntimeSpec(
            run_id=job.id,
            project_path=experiment.project_path,
            command=job.command,
            include_data=experiment.include_data,
            gpu_required=False,
        )
        return str(ProjectSnapshot(spec, store).build(persist=False)["snapshot_hash"])

