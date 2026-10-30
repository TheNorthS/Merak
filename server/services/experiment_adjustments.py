"""Approval-gated scientific runtime adjustment proposals."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from typing import Any, Optional

from ..utils.atomic_write import atomic_write_json, path_lock
from .experiment_models import Experiment, ExperimentJob, JobStatus
from .remote_experiment_runtime import RunManifestStore


def _proposed_command(
    experiment: Experiment, job: ExperimentJob,
    batch_size: Optional[int], command: str,
) -> str:
    proposed = command.strip()
    if batch_size is None or proposed:
        return proposed
    if "{batch_size}" not in experiment.command_template:
        raise ValueError("The experiment command template does not expose {batch_size}")
    return experiment.command_template.format(
        seed=job.seed, batch_size=batch_size, work_dir=experiment.work_dir,
    )


def _change_labels(
    job: ExperimentJob, batch_size: Optional[int], proposed_command: str,
) -> list[str]:
    labels: list[str] = []
    if batch_size is not None:
        labels.append(f"Batch size: {job.batch_size or 'unspecified'} -> {batch_size}")
    if proposed_command and proposed_command != job.command:
        labels.append("Training command will change for the next immutable attempt")
    return labels or [
        "No runtime parameter changes; approval records a diagnosed source/infrastructure adjustment"
    ]


def _decision_brief(
    job: ExperimentJob, source: str, summary: str, rationale: str,
    batch_size: Optional[int], command: str, proposed_command: str,
) -> dict[str, Any]:
    return {
        "trigger": "runtime_health_monitor" if source == "health_monitor" else "researcher_proposed_adjustment",
        "problem": summary.strip(), "evidence": rationale.strip(),
        "proposed_action": _change_labels(job, batch_size, proposed_command),
        "research_impact": (
            "The scientific hypothesis and model definition remain unchanged; only execution memory pressure changes."
            if batch_size is not None and not command.strip()
            else "Review whether the command/source change alters the model, data split, objective, or comparison budget."
        ),
        "risks": [
            "A changed effective batch size can alter optimization and must be recorded in the result artifact.",
            "Approval creates a new immutable attempt; prior failed evidence is retained.",
            "Reject if the change weakens the selected idea or changes the locked evaluation protocol.",
        ],
        "approval_question": "Does this minimal change fix the diagnosed problem without changing the research claim?",
    }


def _proposal_payload(
    experiment_id: str, job: ExperimentJob, store: RunManifestStore,
    source: str, summary: str, rationale: str, batch_size: Optional[int],
    proposed_command: str, source_snapshot_hash: str, decision_brief: dict[str, Any],
) -> dict[str, Any]:
    manifest = store.load()
    return {
        "schema_version": 1, "proposal_id": uuid.uuid4().hex[:16],
        "experiment_id": experiment_id, "job_id": job.id, "runtime_run_id": job.id,
        "attempt": int(manifest.get("current_attempt") or 0), "source": source,
        "status": "pending", "summary": summary.strip(), "rationale": rationale.strip(),
        "changes": {"batch_size": batch_size, "command": proposed_command},
        "decision_brief": decision_brief,
        "expected": {
            "batch_size": job.batch_size,
            "command_sha256": hashlib.sha256(job.command.encode("utf-8")).hexdigest(),
            "snapshot_hash": str(manifest.get("snapshot_hash") or ""),
            "source_snapshot_hash": source_snapshot_hash,
        },
        "diagnosis_path": job.diagnosis_path or "",
        "created_at": datetime.utcnow().isoformat() + "Z",
    }


class ExperimentAdjustmentMixin:
    async def create_adjustment_proposal(
        self,
        experiment_id: str,
        job_id: str,
        *,
        summary: str,
        rationale: str,
        batch_size: Optional[int] = None,
        command: str = "",
        source: str = "operator",
    ) -> dict[str, Any]:
        """Persist a runtime/config adjustment without applying it."""
        experiment = self._experiments.get(experiment_id)
        job = self.get_job(job_id)
        if not experiment or not job or job.experiment_id != experiment_id:
            raise KeyError("Experiment job not found")
        if source != "health_monitor" and job.status in {
            JobStatus.RUNNING, JobStatus.QUEUED, JobStatus.RETRYING, JobStatus.STOPPING,
        }:
            raise ValueError("Stop and diagnose the active attempt before proposing an adjustment")
        if not summary.strip() or not rationale.strip():
            raise ValueError("Adjustment summary and rationale are required")
        if batch_size is not None and batch_size < 1:
            raise ValueError("batch_size must be at least 1")

        proposed_command = _proposed_command(experiment, job, batch_size, command)
        store = RunManifestStore(experiment.project_path, job.id)
        decision_brief = _decision_brief(
            job, source, summary, rationale, batch_size, command, proposed_command,
        )
        proposal = _proposal_payload(
            experiment_id, job, store, source, summary, rationale, batch_size,
            proposed_command,
            self._current_source_snapshot_hash(experiment, job, store),
            decision_brief,
        )
        proposal_id = str(proposal["proposal_id"])
        proposal_dir = store.root / "proposals"
        proposal_dir.mkdir(parents=True, exist_ok=True)
        path = proposal_dir / f"{proposal_id}.json"
        atomic_write_json(path, proposal)
        store.append_event("adjustment_proposed", {
            "attempt": proposal["attempt"],
            "proposal_id": proposal_id,
            "source": source,
        })
        job.pending_adjustment_id = proposal_id
        job.status = JobStatus.AWAITING_APPROVAL
        await self._notify_listeners("experiment_adjustment_proposed", {
            "experiment_id": experiment_id,
            "job_id": job.id,
            "proposal_id": proposal_id,
            "summary": proposal["summary"],
            "rationale": proposal["rationale"],
            "changes": proposal["changes"],
            "decision_brief": decision_brief,
            "diagnosis_path": proposal["diagnosis_path"],
            "proposal_path": str(path),
        })
        return proposal

    def list_adjustment_proposals(self, experiment_id: str, job_id: str) -> list[dict[str, Any]]:
        experiment = self._experiments.get(experiment_id)
        job = self.get_job(job_id)
        if not experiment or not job or job.experiment_id != experiment_id:
            raise KeyError("Experiment job not found")
        proposal_dir = RunManifestStore(experiment.project_path, job.id).root / "proposals"
        proposals: list[dict[str, Any]] = []
        for path in sorted(proposal_dir.glob("*.json")) if proposal_dir.is_dir() else []:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict):
                payload["proposal_path"] = str(path)
                proposals.append(payload)
        return proposals

    async def resolve_adjustment_proposal(
        self,
        experiment_id: str,
        job_id: str,
        proposal_id: str,
        *,
        approved: bool,
        note: str = "",
    ) -> dict[str, Any]:
        experiment = self._experiments.get(experiment_id)
        job = self.get_job(job_id)
        if not experiment or not job or job.experiment_id != experiment_id:
            raise KeyError("Experiment job not found")
        path = RunManifestStore(experiment.project_path, job.id).root / "proposals" / f"{proposal_id}.json"
        if not path.is_file():
            raise KeyError("Adjustment proposal not found")
        with path_lock(path):
            try:
                proposal = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise RuntimeError(
                    f"Adjustment proposal is unreadable; refusing resolution: {path}"
                ) from exc
            if not isinstance(proposal, dict):
                raise RuntimeError(
                    f"Adjustment proposal root must be an object: {path}"
                )
            if proposal.get("status") != "pending":
                raise ValueError(f"Adjustment proposal is already {proposal.get('status')}")
            expected = dict(proposal.get("expected") or {})
            current_command_hash = hashlib.sha256(job.command.encode("utf-8")).hexdigest()
            store = RunManifestStore(experiment.project_path, job.id)
            current_source_hash = self._current_source_snapshot_hash(experiment, job, store)
            if (
                expected.get("command_sha256") != current_command_hash
                or expected.get("batch_size") != job.batch_size
                or expected.get("source_snapshot_hash") != current_source_hash
            ):
                proposal.update({
                    "status": "stale",
                    "resolved_at": datetime.utcnow().isoformat() + "Z",
                    "resolution_note": "Job configuration changed after this proposal was created.",
                })
                atomic_write_json(path, proposal)
                raise ValueError("Adjustment proposal is stale because the job configuration changed")

            proposal.update({
                "status": "approved" if approved else "rejected",
                "resolved_at": datetime.utcnow().isoformat() + "Z",
                "resolution_note": note.strip(),
            })
            if approved:
                changes = dict(proposal.get("changes") or {})
                if changes.get("batch_size") is not None:
                    job.batch_size = int(changes["batch_size"])
                if str(changes.get("command") or "").strip():
                    job.command = str(changes["command"]).strip()
                job.approved_adjustment_id = proposal_id
            job.pending_adjustment_id = None
            job.status = JobStatus.READY_TO_RETRY if approved else JobStatus.FAILED
            atomic_write_json(path, proposal)
        store.append_event("adjustment_resolved", {
            "proposal_id": proposal_id,
            "approved": approved,
            "note": note.strip(),
        })
        await self._notify_listeners("experiment_adjustment_resolved", {
            "experiment_id": experiment_id,
            "job_id": job.id,
            "proposal_id": proposal_id,
            "approved": approved,
        })
        return proposal

