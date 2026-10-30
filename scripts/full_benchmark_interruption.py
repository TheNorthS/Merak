"""Truthful evidence for an operator-stopped private benchmark continuation.

This module only reads evidence and constructs/validates receipt objects. It
does not cancel processes, change lifecycle state, write files, or grant any
scientific/workflow acceptance. Unknown in-memory blocked-operation history is
never converted into an empty successful observation.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any

from scripts.full_benchmark_scope import numerical_fingerprint, scientific_method_identity, tree_hashes


EVENT = "workflow_cancelled"
REASON = "confirmed_scientific_projection_defect"


def object_sha256(value: Any) -> str:
    """Hash a canonical observation without rewriting its source artifact."""
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("Operator interruption evidence must be an object")
    return value


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _owned(root: Path, relative: str, run_id: str, name: str) -> Path:
    path = root / relative
    if (not isinstance(relative, str) or "\\" in relative or Path(relative).is_absolute()
            or ".." in Path(relative).parts or path.resolve().relative_to(root).as_posix() != relative
            or not relative.startswith(f".merak/benchmark-continuations/{run_id}/")
            or path.name != name or path.is_symlink() or not path.is_file() or path.stat().st_nlink > 1):
        raise ValueError("Operator interruption evidence leaves its exact current-run archive")
    return path


def _event(root: Path, run_id: str, event_sha256: str) -> dict:
    records = [json.loads(line) for line in (root / f".merak/runs/{run_id}.events.jsonl").read_text(
        encoding="utf-8-sig").splitlines() if line.strip()]
    if not records or object_sha256(records[-1]) != event_sha256:
        raise ValueError("Operator interruption is not the current exact terminal journal event")
    record, data = records[-1], records[-1].get("data") or {}
    if (record.get("schema") != 1 or record.get("run_id") != run_id or record.get("event") != EVENT
            or data.get("accepted") is not False or data.get("operator_interruption") is not True
            or data.get("reason") != REASON or data.get("blocked_operations") is not None
            or data.get("blocked_operations_observability") != "unknown"):
        raise ValueError("Operator stop journal cannot assert success or complete memory observability")
    return record


def _frozen_observations(root: Path, source: Path, original: Path, reference: Path) -> dict:
    from scripts.full_benchmark_continuation_scope import frozen_inputs

    return {"frozen_inputs_sha256": object_sha256(frozen_inputs(root)),
        "scientific_method_sha256": object_sha256(scientific_method_identity(root)),
        "numerical_bundle_sha256": object_sha256(numerical_fingerprint(root)),
        "source_current_tree_sha256": object_sha256(tree_hashes(source)),
        "original_current_tree_sha256": object_sha256(tree_hashes(original)),
        "reference_current_tree_sha256": object_sha256(tree_hashes(reference))}


def _authority_binding(original: Path, reference: Path, context: dict) -> dict:
    from server.services.frozen_benchmark_authority import historical_inputs_digest, benchmark_inventory_digest

    binding = {name: context[name] for name in ("historical_inputs_pin", "benchmark_inventory_pin", "settings")}
    if (historical_inputs_digest(original, binding["settings"]) != binding["historical_inputs_pin"]
            or benchmark_inventory_digest(reference) != binding["benchmark_inventory_pin"]):
        raise ValueError("Operator interruption cannot replace independently pinned benchmark authority")
    return binding


def _stop_observation(value: dict) -> dict:
    required = {"terminated_worker_pid", "confirmed_inactive_pids", "observed_at"}
    if (not isinstance(value, dict) or set(value) != required
            or type(value["terminated_worker_pid"]) is not int or value["terminated_worker_pid"] <= 0
            or not isinstance(value["confirmed_inactive_pids"], list) or not value["confirmed_inactive_pids"]
            or any(type(pid) is not int or pid <= 0 for pid in value["confirmed_inactive_pids"])
            or len(set(value["confirmed_inactive_pids"])) != len(value["confirmed_inactive_pids"])
            or value["terminated_worker_pid"] not in value["confirmed_inactive_pids"]
            or not isinstance(value["observed_at"], (float, int)) or value["observed_at"] <= 0):
        raise ValueError("Operator interruption requires the exact observed inactive owned-process chain")
    return value


def build_operator_interruption(root: Path, source: Path, original: Path, reference: Path,
                                run_id: str, previous_report_archive: str, event_sha256: str,
                                authority_context: dict, stop_observation: dict) -> dict:
    """Construct a non-accepting receipt after native cancellation and lease release.

    The caller must independently observe its owned processes have stopped and
    perform the existing native state transitions first. Process observation is
    explicitly recorded, not synthesized or replaced by lifecycle acceptance.
    """
    from scripts.full_benchmark_continuation_scope import (
        validate_stopped_run, _validate_source_archive, _validate_implementation_source,
    )

    state = validate_stopped_run(root, run_id)
    if state.get("status") != "cancelled" or state.get("resume_claim"):
        raise ValueError("Operator interruption requires cancelled state and a released resume claim")
    previous = _owned(root, previous_report_archive, run_id, "report.previous.json")
    report = _json(previous)
    if (report.get("run_id") != run_id or report.get("accepted") is not False
            or report.get("real_model_execution") is not True or report.get("training_authorized") is not False
            or report.get("original_workflow_resumed") is not False):
        raise ValueError("Operator interruption requires its genuine preceding non-training report")
    record = _event(root, run_id, event_sha256)
    observation = _stop_observation(stop_observation)
    state_sha = _hash(root / f".merak/runs/{run_id}.json")
    trace_sha = _hash(root / f".merak/runs/{run_id}.skills.json")
    if (record["timestamp"] < observation["observed_at"]
            or record["data"].get("stop_observation") != observation
            or record["data"].get("state_sha256") != state_sha
            or record["data"].get("trace_sha256") != trace_sha):
        raise ValueError("Operator stop journal must follow the observed worker shutdown")
    _validate_source_archive(root, original, str((report.get("source_evidence") or {}).get("source_run_id") or ""), report)
    _validate_implementation_source(root, source)
    return {"schema": 1, "kind": "operator_interrupted_full_benchmark", "run_id": run_id,
        "project_path": str(root), "accepted": False, "workflow_acceptance_granted": False,
        "scientific_execution_performed": False, "reason": REASON,
        "blocked_operations": None, "blocked_operations_observability": "unknown",
        "original_tree_change_observability": "unknown", "pinned_scientific_inputs_verified": True,
        "state_sha256": state_sha, "trace_sha256": trace_sha,
        "previous_report_archive": previous_report_archive, "previous_report_sha256": _hash(previous),
        "journal_event_sha256": event_sha256, "stop_observation": observation,
        "source_evidence": report["source_evidence"],
        "authority_binding": _authority_binding(original, reference, authority_context),
        "observations": _frozen_observations(root, source, original, reference)}


def operator_interruption_report(root: Path, receipt: dict, receipt_relative: str, receipt_pin: str) -> dict:
    """Construct a truthful stopped report; no current gate or acceptance is invented."""
    state = _json(root / f".merak/runs/{receipt['run_id']}.json")
    from scripts.full_benchmark_scope import PIPELINE_NODES

    return {"run_id": receipt["run_id"], "status": "cancelled", "continuation": True,
        "accepted": False, "issues": ["Private verification worker stopped for confirmed scientific projection repair."],
        "phases": {name: phase.get("status") for name, phase in state["phases"].items()},
        "logical_pipeline_nodes": list(PIPELINE_NODES), "source_owner_reuse": {},
        "source_evidence": receipt["source_evidence"], "training_authorized": False,
        "real_model_execution": True, "original_workflow_resumed": False, "snapshot_path": str(root),
        "originals_unchanged": None, "original_tree_change_observability": "unknown",
        "pinned_scientific_inputs_verified": True, "raw_numerical_and_semantic_bundle_unchanged": True,
        "blocked_operations": None, "blocked_operations_observability": "unknown",
        "operator_interruption": {"receipt_path": receipt_relative, "receipt_sha256": receipt_pin}}


def validate_operator_interruption(root: Path, source: Path, original: Path, reference: Path,
                                   run_id: str, report: dict, receipt_pin: str) -> dict:
    """A pinned truthful interruption permits revalidation, never acceptance."""
    if not re.fullmatch(r"[a-f0-9]{64}", receipt_pin):
        raise ValueError("Explicit observed operator-interruption receipt SHA-256 is required")
    binding = report.get("operator_interruption") or {}
    path = _owned(root, binding.get("receipt_path", ""), run_id, "operator-interruption.json")
    if binding.get("receipt_sha256") != receipt_pin or _hash(path) != receipt_pin:
        raise ValueError("Observed operator-interruption receipt changed")
    receipt = _json(path)
    authority = receipt.get("authority_binding") or {}
    expected = build_operator_interruption(root, source, original, reference, run_id,
        receipt.get("previous_report_archive", ""), receipt.get("journal_event_sha256", ""),
        authority, receipt.get("stop_observation") or {})
    if receipt != expected:
        raise ValueError("Operator interruption receipt no longer matches exact stopped evidence")
    expected_report = operator_interruption_report(root, receipt, binding["receipt_path"], receipt_pin)
    if report != expected_report:
        raise ValueError("Operator interruption report asserts unsupported status or observability")
    return {"operator_interruption_receipt_sha256": receipt_pin,
        "prior_blocked_operations_observability": "unknown", "prior_workflow_acceptance_granted": False,
        "interruption_history": {"receipt_path": binding["receipt_path"], "receipt_sha256": receipt_pin, "original_tree_change_observability": "unknown",
            "blocked_operations_observability": "unknown", "pinned_scientific_inputs_verified": True,
            "workflow_acceptance_granted": False}}


def validate_interruption_history(root: Path, run_id: str, history: dict) -> dict:
    """Later normal continuations must not erase previously unknown observations."""
    if not isinstance(history, dict):
        raise ValueError("Operator interruption history must remain explicitly unknown")
    path = _owned(root, history.get("receipt_path", ""), run_id, "operator-interruption.json")
    pin = history.get("receipt_sha256") or ""
    if not re.fullmatch(r"[a-f0-9]{64}", pin) or _hash(path) != pin:
        raise ValueError("Historical operator-interruption receipt changed")
    receipt = _json(path)
    expected = {"receipt_path": history["receipt_path"], "receipt_sha256": pin,
        "original_tree_change_observability": "unknown", "blocked_operations_observability": "unknown",
        "pinned_scientific_inputs_verified": True, "workflow_acceptance_granted": False}
    if (history != expected or receipt.get("schema") != 1 or receipt.get("run_id") != run_id
            or receipt.get("project_path") != str(root) or receipt.get("accepted") is not False
            or receipt.get("kind") != "operator_interrupted_full_benchmark"
            or receipt.get("workflow_acceptance_granted") is not False
            or receipt.get("original_tree_change_observability") != "unknown"
            or receipt.get("blocked_operations_observability") != "unknown"):
        raise ValueError("Historical interruption cannot become successful complete observability")
    return expected
