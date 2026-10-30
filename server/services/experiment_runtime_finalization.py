"""Finalize managed experiment attempts and bind runtime-owned evidence."""

from __future__ import annotations

import json
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from ..utils.atomic_write import atomic_write_json


async def finalize_runtime(
    *,
    spec: Any,
    store: Any,
    attempt_number: int,
    state: str,
    exit_code: Optional[int],
    anomalies: list[Any],
    health: Any,
    log_path: Path,
    result_path: str,
    error: str,
    on_event: Any,
    transfers: Optional[dict[str, Any]],
    diagnosis_writer: Callable[..., Path],
    emitter: Callable[[Any, str, dict[str, Any]], Awaitable[None]],
    utc_now: Callable[[], str],
) -> dict[str, Any]:
    from .execution_provenance import execution_provenance_service

    anomaly_payload = [item.to_dict() for item in anomalies]
    started_epoch = _attempt_started_epoch(store.load(), attempt_number)
    published_log = _publish_log(spec, attempt_number, log_path)
    result_artifacts = {
        relative: facts
        for relative, facts in execution_provenance_service.result_artifacts(
            spec.project_path
        ).items()
        if float(facts.get("mtime") or 0) >= started_epoch - 2.0
    }
    config_hashes = _config_hashes(store.root / "snapshot.json")
    diagnosis_path = ""
    if state != "completed" or anomaly_payload:
        diagnosis_path = str(diagnosis_writer(
            spec, store, attempt_number, state, anomalies, error, str(log_path)
        ))
    fields = _final_fields(
        state, exit_code, error, anomaly_payload, health, result_path,
        log_path, published_log, transfers, result_artifacts, config_hashes,
        started_epoch, diagnosis_path, utc_now,
    )
    store.update_attempt(attempt_number, **fields)
    manifest = store.update(**_manifest_fields(fields))
    store.append_event("finished", {
        "attempt": attempt_number, "status": state,
        "exit_code": exit_code, "error": error,
    })
    publish_manifest_copy(spec, store, manifest)
    await emitter(on_event, "experiment_finished", {
        "run_id": spec.run_id, "backend": spec.normalized_backend(),
        "attempt": attempt_number, "status": state, "exit_code": exit_code,
        "manifest_path": str(store.path), "result_path": result_path,
        "diagnosis_path": diagnosis_path,
    })
    return {
        "run_id": spec.run_id, "backend": spec.normalized_backend(),
        "status": state, "exit_code": exit_code,
        "manifest_path": str(store.path), "log_path": str(log_path),
        "result_path": result_path, "diagnosis_path": diagnosis_path,
        "error": error, "metrics": health.latest_metrics,
        "anomalies": anomaly_payload,
    }


def _attempt_started_epoch(manifest: dict[str, Any], attempt: int) -> float:
    current = next(
        (item for item in manifest.get("attempts") or []
         if int(item.get("attempt") or 0) == attempt),
        {},
    )
    try:
        return datetime.fromisoformat(str(current.get("started_at") or "")).timestamp()
    except ValueError:
        return time.time()


def _publish_log(spec: Any, attempt: int, log_path: Path) -> str:
    if not log_path.is_file():
        return ""
    target = (
        Path(spec.project_path).resolve() / "experiments" / "logs" / "managed"
        / spec.run_id / f"attempt-{attempt:02d}.log"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(log_path, target)
    return str(target)


def _config_hashes(snapshot_path: Path) -> dict[str, str]:
    try:
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        str(item.get("path") or ""): str(item.get("sha256") or "")
        for item in payload.get("files") or []
        if isinstance(item, dict)
        and str(item.get("path") or "").startswith("experiments/configs/")
        and item.get("sha256")
    }


def _final_fields(
    state: str, exit_code: Optional[int], error: str,
    anomalies: list[dict[str, Any]], health: Any, result_path: str,
    log_path: Path, published_log: str, transfers: Optional[dict[str, Any]],
    result_artifacts: dict[str, Any], config_hashes: dict[str, str],
    started_epoch: float, diagnosis_path: str, utc_now: Callable[[], str],
) -> dict[str, Any]:
    return {
        "status": state, "evidence_eligible": state == "completed",
        "exit_code": exit_code, "finished_at": utc_now(), "error": error,
        "anomalies": anomalies, "metrics": health.latest_metrics,
        "health": health.snapshot(), "diagnosis_path": diagnosis_path,
        "result_path": result_path, "local_log_path": str(log_path),
        "published_log_path": published_log, "transfers": transfers or {},
        "result_artifacts": result_artifacts, "config_hashes": config_hashes,
        "artifact_window_started_at_epoch": started_epoch,
    }


def _manifest_fields(fields: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value for key, value in fields.items()
        if key not in {"finished_at", "health", "local_log_path", "transfers"}
    } | {"log_path": fields["local_log_path"]}


def publish_manifest_copy(spec: Any, store: Any, manifest: dict[str, Any]) -> None:
    target = (
        Path(spec.project_path).resolve() / "experiments" / "results" / "remote"
        / spec.run_id / "run_manifest.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(target, manifest)
