"""Durable attempt contracts; static validation never grants independent acceptance.

This layer records execution boundaries, not scientific policies or model claims.
An unfinished record is evidence of an unknown outcome, never permission to replay.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import Any

from .write_scope import normalize_allowed_write_paths
from ..utils.atomic_write import atomic_write_json


def fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def attempt_directory(root: Path, run_id: str) -> Path:
    root = root.resolve()
    path = root / ".merak/harness" / fingerprint(run_id)
    if path.resolve() != path:
        raise ValueError("Harness storage cannot redirect outside its canonical location")
    return path


def target_digests(root: Path, targets: list[str]) -> dict[str, str]:
    paths = normalize_allowed_write_paths(root, targets) or []
    return {relative: hashlib.sha256((root / relative).read_bytes()).hexdigest()
            if (root / relative).is_file() else "missing" for relative in paths}


class ExecutionAttempt:
    """Persist intent before invocation and validation before acceptance side effects."""

    def __init__(self, root: Path, run_id: str, contract: dict[str, Any]):
        self.root = root.resolve()
        self.path = attempt_directory(self.root, run_id) / f"{uuid.uuid4().hex}.json"
        # Copy caller-owned data so later scope expansion cannot rewrite intent.
        self.record = {"schema": 1, "attempt_id": self.path.stem, "run_id": run_id,
                       "contract": json.loads(json.dumps(contract)), "status": "running",
                       "started_at": time.time(), "before": target_digests(self.root, contract["targets"])}
        self._save(self.record)

    def _save(self, record: dict[str, Any]) -> None:
        atomic_write_json(self.path, record)
        self.record = record

    def finish(self, report: dict[str, Any], output: str, snapshot: str, *, exhausted: bool = False) -> None:
        if self.record["status"] != "running":
            raise RuntimeError("Harness attempt already finished")
        after = target_digests(self.root, self.record["contract"]["targets"])
        self._save({**self.record, "status": "awaiting_review" if report.get("passed") is True else "validation_failed",
                    "finished_at": time.time(), "after": after,
                    "changed_targets": [path for path in after if after[path] != self.record["before"][path]],
                    "validation": report, "snapshot_sha256": snapshot,
                    "output_sha256": hashlib.sha256(output.encode()).hexdigest(),
                    "model_budget_exhausted": exhausted})

    def interrupt(self, error: BaseException) -> None:
        # Error text can contain credentials. Preserve the type, not raw provider output.
        self._save({**self.record, "status": "interrupted", "finished_at": time.time(),
                    "error_type": type(error).__name__, "outcome_requires_reconciliation": True})


def record_independent_review(
    root: Path, run_id: str, node_id: str, snapshot: str, assessment: dict, *, blocking: bool,
) -> None:
    """Bind only matching pending snapshots; changed candidates are superseded, not passed."""
    for path in sorted(attempt_directory(root, run_id).glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("schema") != 1 or record.get("run_id") != run_id:
            raise ValueError("Invalid harness attempt identity or schema")
        if record.get("status") != "awaiting_review" or record["contract"]["node_id"] != node_id:
            continue
        matching = record["snapshot_sha256"] == snapshot
        atomic_write_json(path, {**record, "status": (
            "review_blocked" if blocking else "review_passed") if matching else "superseded",
            "reviewed_at": time.time(), "review_snapshot_sha256": snapshot,
            "review_sha256": fingerprint(assessment),
            "review_finding_ids": [item.get("id") for item in assessment.get("findings", [])] if matching else []})


def pending_review(root: Path, run_id: str, node_id: str, snapshot: str) -> bool:
    """A newly checked owner rebuttal needs adjudication even when source bytes are unchanged."""
    for path in attempt_directory(root, run_id).glob("*.json"):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("schema") != 1 or record.get("run_id") != run_id:
            raise ValueError("Invalid harness attempt identity or schema")
        if (record.get("status") == "awaiting_review" and record["contract"]["node_id"] == node_id
                and record.get("snapshot_sha256") == snapshot):
            return True
    return False
