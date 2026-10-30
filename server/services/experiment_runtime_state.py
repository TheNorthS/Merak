"""Managed experiment specifications, manifests, and source snapshots."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Optional

from ..utils.atomic_write import atomic_write_json, path_lock
from .experiment_health import HealthPolicy

_EXCLUDED_DIRS = {
    ".git", ".hg", ".svn", ".idea", ".vscode", ".merak", "node_modules",
    "dist", "dist-electron", "build", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", ".venv", "venv", "checkpoints", "wandb",
}
_EXCLUDED_RELATIVE_PREFIXES = {
    "experiments/logs", "experiments/results", "experiments/checkpoints",
}
_DATA_DIR_NAMES = {"data", "dataset", "datasets"}
_SENSITIVE_NAMES = {
    ".env", ".env.local", "user_settings.json", "merak_ide.db", "yjs_docs.db",
    "id_rsa", "id_ed25519", "credentials.json", "secrets.json",
}
_SENSITIVE_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".sqlite", ".db"}
ACTIVE_EXPERIMENT_STATES = frozenset({
    "precheck", "snapshot", "sync", "launch", "monitor", "healthy", "collect", "stopping", "recovery_required",
})


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class RuntimeSpec:
    run_id: str
    project_path: str
    command: str
    preflight_command: str = ""
    backend: str = "local"
    server_id: str = ""
    env_vars: dict[str, str] = field(default_factory=dict)
    remote_base_dir: str = "~/.merak/runs"
    timeout_seconds: int = 6 * 3600
    poll_interval_seconds: float = 5.0
    include_data: bool = False
    max_sync_file_bytes: int = 512 * 1024 * 1024
    max_retries: int = 0
    auto_stop_on_anomaly: bool = True
    health_policy: HealthPolicy = field(default_factory=HealthPolicy)
    gpu_required: bool = True
    gpu_type: str = "A100"
    modal_volume: str = "merak-experiment-results"
    modal_image: str = "pytorch/pytorch:2.4.0-cuda12.4-cudnn9-runtime"
    vast_image: str = "pytorch/pytorch:2.4.0-cuda12.4-cudnn9-runtime"
    vast_gpu_ram_mb: int = 16000
    vast_disk_gb: int = 30
    vast_max_hourly_usd: float = 2.0
    max_remote_cost_usd: float = 10.0
    auto_destroy: bool = True
    approved_adjustment_id: str = ""

    def normalized_backend(self) -> str:
        aliases = {
            "remote": "ssh_remote", "ssh": "ssh_remote",
            "vast": "vast_ai", "vastai": "vast_ai",
        }
        return aliases.get(self.backend, self.backend)


@dataclass(slots=True)
class RuntimeOutcome:
    run_id: str
    backend: str
    status: str
    exit_code: Optional[int] = None
    manifest_path: str = ""
    log_path: str = ""
    result_path: str = ""
    diagnosis_path: str = ""
    error: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    anomalies: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def _manifest_mutation(method):
    @wraps(method)
    def locked(self, *args, **kwargs):
        with path_lock(self.path):
            return method(self, *args, **kwargs)

    return locked


class RunManifestStore:
    """Atomic per-run state and append-only event storage."""

    def __init__(self, project_path: str | Path, run_id: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,96}", run_id):
            raise ValueError("Invalid experiment run_id")
        self.project_path = Path(project_path).resolve()
        self.root = self.project_path / ".merak" / "experiments" / run_id
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "run.json"
        self.events_path = self.root / "events.jsonl"

    def load(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Experiment run manifest is unreadable: {self.path}") from exc
        if not isinstance(value, dict):
            raise RuntimeError(f"Experiment run manifest root must be an object: {self.path}")
        return value

    @_manifest_mutation
    def initialize(self, spec: RuntimeSpec) -> dict[str, Any]:
        current = self.load()
        if current:
            return current
        payload = {
            "schema_version": 1, "run_id": spec.run_id,
            "project_path": str(Path(spec.project_path).resolve()),
            "backend": spec.normalized_backend(), "command": spec.command,
            "environment_keys": sorted(spec.env_vars), "status": "pending",
            "created_at": utc_now(), "updated_at": utc_now(),
            "current_attempt": 0, "attempts": [],
            "policy": asdict(spec.health_policy), "anomalies": [],
        }
        self.write(payload)
        return payload

    @_manifest_mutation
    def begin_attempt(
        self, spec: RuntimeSpec, snapshot_hash: str
    ) -> tuple[int, dict[str, Any]]:
        from .experiment_runtime_identity import execution_identity

        payload = self.initialize(spec)
        if payload.get("status") in ACTIVE_EXPERIMENT_STATES:
            from .experiment_runtime_identity import ActiveExperimentConflict
            raise ActiveExperimentConflict("An active experiment attempt already owns this durable run")
        attempts = list(payload.get("attempts") or [])
        number = len(attempts) + 1
        command_hash = hashlib.sha256(spec.command.encode("utf-8")).hexdigest()
        attempt = {
            "attempt": number, "status": "precheck", "evidence_eligible": False,
            "started_at": utc_now(), "finished_at": None,
            "snapshot_hash": snapshot_hash, "command": spec.command,
            "command_sha256": command_hash,
            "execution_identity": execution_identity(spec),
            "approved_adjustment_id": spec.approved_adjustment_id,
            "remote": {}, "anomalies": [], "transfers": {},
        }
        attempts.append(attempt)
        payload.update({
            "status": "precheck", "evidence_eligible": False,
            "current_attempt": number, "attempts": attempts,
            "snapshot_hash": snapshot_hash,
            "command": spec.command, "command_sha256": command_hash,
            "approved_adjustment_id": spec.approved_adjustment_id,
        })
        self.write(payload)
        self.append_event("attempt_started", {"attempt": number, "snapshot_hash": snapshot_hash})
        return number, payload

    @_manifest_mutation
    def update(self, **changes: Any) -> dict[str, Any]:
        payload = self.load()
        if not payload:
            raise RuntimeError(
                f"Experiment run manifest is missing; initialize before update: {self.path}"
            )
        payload.update(changes)
        self.write(payload)
        return payload

    @_manifest_mutation
    def update_attempt(self, attempt_number: int, **changes: Any) -> dict[str, Any]:
        payload = self.load()
        if not payload:
            raise RuntimeError(
                f"Experiment run manifest is missing; initialize before update: {self.path}"
            )
        attempts = list(payload.get("attempts") or [])
        matched = False
        for attempt in attempts:
            if int(attempt.get("attempt") or 0) == attempt_number:
                attempt.update(changes)
                matched = True
                break
        if not matched:
            raise KeyError(f"Experiment attempt {attempt_number} is absent from {self.path}")
        payload["attempts"] = attempts
        if "status" in changes:
            payload["status"] = changes["status"]
        self.write(payload)
        return payload

    def append_event(self, event: str, data: dict[str, Any]) -> None:
        record = {"timestamp": utc_now(), "event": event, **data}
        with path_lock(self.events_path):
            with self.events_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
                handle.flush()
                os.fsync(handle.fileno())

    def write(self, payload: dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            raise TypeError("Experiment run manifest payload must be an object")
        if self.path.exists():
            self.load()
        payload["updated_at"] = utc_now()
        atomic_write_json(self.path, payload, default=str)


class ProjectSnapshot:
    """Content-addressed source snapshot with explicit exclusion reasons."""

    def __init__(self, spec: RuntimeSpec, store: RunManifestStore) -> None:
        self.spec = spec
        self.store = store

    def build(self, *, persist: bool = True) -> dict[str, Any]:
        root = Path(self.spec.project_path).resolve()
        if not root.is_dir():
            raise NotADirectoryError(root)
        files, excluded, digest = [], [], hashlib.sha256()
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(root).as_posix()
            reason = self._exclusion_reason(relative, path)
            if reason:
                excluded.append({"path": relative, "reason": reason})
                continue
            file_hash, size = self._hash(path), path.stat().st_size
            files.append({"path": relative, "size": size, "sha256": file_hash})
            digest.update(relative.encode("utf-8") + b"\0" + file_hash.encode("ascii") + b"\n")
        payload = {
            "schema_version": 1, "project_path": str(root), "created_at": utc_now(),
            "snapshot_hash": digest.hexdigest(), "file_count": len(files),
            "total_bytes": sum(item["size"] for item in files),
            "files": files, "excluded": excluded,
        }
        if persist:
            atomic_write_json(self.store.root / "snapshot.json", payload)
        return payload

    def materialize(self, snapshot: dict[str, Any], target: Path) -> Path:
        source_root = Path(self.spec.project_path).resolve()
        target.mkdir(parents=True, exist_ok=True)
        for item in snapshot.get("files", []):
            source = source_root / Path(item["path"])
            destination = target / Path(item["path"])
            if (not source.resolve().is_relative_to(source_root)
                    or not destination.resolve().is_relative_to(target.resolve())
                    or self._hash(source) != item["sha256"]):
                raise ValueError(f"Source changed since experiment snapshot: {item['path']}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            if self._hash(destination) != item["sha256"]:
                raise ValueError(f"Source changed while materializing experiment snapshot: {item['path']}")
        return target

    def _exclusion_reason(self, relative: str, path: Path) -> str:
        parts = {part.lower() for part in Path(relative).parts}
        if parts & _EXCLUDED_DIRS:
            return "generated_or_local_directory"
        normalized = relative.lower()
        if normalized in {'manifest.md', 'paper/publication_style.json'}:
            return 'runtime_publication_metadata'
        if any(normalized == prefix or normalized.startswith(prefix + "/")
               for prefix in _EXCLUDED_RELATIVE_PREFIXES):
            return "previous_experiment_artifact"
        if not self.spec.include_data and parts & _DATA_DIR_NAMES:
            return "dataset_sync_disabled"
        if path.name.lower() in _SENSITIVE_NAMES or path.suffix.lower() in _SENSITIVE_SUFFIXES:
            return "sensitive_local_file"
        if path.stat().st_size > self.spec.max_sync_file_bytes:
            return "file_exceeds_sync_limit"
        return ""

    @staticmethod
    def _hash(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
