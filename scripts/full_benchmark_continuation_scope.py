"""Read-only admission for continuing one already authorized benchmark copy.

Independent source pins and genuine stopped-run evidence must match before
providers or any continuation-side writes are allowed. This module never
changes lifecycle status, acceptance, scientific values, or research inputs.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import time
from typing import Any

from scripts.full_benchmark_scope import (
    FROZEN_DIRECTORIES, FROZEN_FILES, FROZEN_WORKFLOW_INPUTS, PIPELINE_NODES,
    numerical_fingerprint, scientific_method_identity, tree_hashes,
)


def file_sha256(path: Path) -> str:
    """Bind the exact observed report/state bytes, not a reconstructed object."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("Benchmark continuation evidence must be an object: " + path.name)
    return payload


def _unlinked_root(path: Path) -> Path:
    """Reject junctions, symbolic links and hard links before trusting ownership."""
    absolute = path.absolute()
    resolved = absolute.resolve(strict=True)
    if absolute != resolved or not resolved.is_dir():
        raise ValueError("Benchmark continuation requires an existing unlinked directory")
    for candidate in (absolute, *absolute.rglob("*")):
        if candidate.is_symlink() or getattr(candidate.lstat(), "st_file_attributes", 0) & 0x400:
            raise ValueError("Benchmark continuation rejects linked directories or files")
    tree_hashes(resolved)
    return resolved


def validate_project_roots(copy: Path, source: Path, original: Path,
                           reference: Path, repository: Path) -> tuple[Path, ...]:
    """Only the named independent copy can be resumed; every source is read-only."""
    repository = repository.resolve(strict=True)
    roots = tuple(_unlinked_root(path) for path in (copy, source, original, reference))
    root, implementation, _, _ = roots
    if (root.parent != repository or not root.name.startswith("full-benchmark-verification-")
            or implementation.parent != repository or not implementation.name.startswith("protocol-implementation-")
            or len(set(roots)) != 4):
        raise ValueError("Continuation requires four distinct, explicitly owned benchmark roots")
    return roots


def validate_stopped_run(root: Path, run_id: str) -> dict[str, Any]:
    """Reject active/foreign runs before provider setup; native resume still claims atomically."""
    from server.workflows.workflow_lease import ProjectRunLease, _effective_lease_expiry

    if not re.fullmatch(r"[a-f0-9]{12}", run_id):
        raise ValueError("Continuation requires its exact hexadecimal runtime run ID")
    state = _json(root / f".merak/runs/{run_id}.json")
    if (state.get("schema") != 1 or state.get("run_id") != run_id
            or state.get("status") not in {"incomplete", "failed", "cancelled"}
            or set(state.get("phases") or {}) != set(PIPELINE_NODES)):
        raise ValueError("Only the same stopped complete-inventory benchmark run may continue")
    lease = ProjectRunLease(str(root))
    fresh_marker = lease.marker_path.is_file() and time.time() - lease.marker_path.stat().st_mtime < lease.MARKER_STALE_GRACE_SECONDS
    if (_effective_lease_expiry(state.get("resume_claim")) > time.time()
            or lease.active_claim() or fresh_marker):
        raise ValueError("Benchmark copy already has an active workflow/resume claim")
    trace = _json(root / f".merak/runs/{run_id}.skills.json")
    if (trace.get("schema") != 2 or trace.get("run_id") != run_id
            or Path(str(trace.get("project_path") or "")).resolve() != root):
        raise ValueError("Current benchmark execution trace belongs to another run or project")
    config = state.get("config") or {}
    options = config.get("options") or {}
    baseline = state.get("input_baseline") or {}
    paths = [str(entry.get("path") or "") for entry in baseline.get("entries") or []]
    if (options.get("run_experiment") is not False
            or options.get("non_experiment_evidence_mode") != "synthetic_preview"
            or options.get("platform_auto_recovery") is not False
            or options.get("deterministic_source_repair") is not False
            or options.get("input_files") not in [list(FROZEN_WORKFLOW_INPUTS), paths]
            or not baseline or baseline.get("run_id") != run_id):
        raise ValueError("Stopped run does not preserve the explicitly authorized non-training scope")
    from server.services.workflow_inputs import workflow_input_service

    issues = workflow_input_service.validate_snapshot(str(root), baseline)
    if issues:
        raise ValueError("Frozen benchmark inputs changed: " + "; ".join(issues))
    return state


def _validate_source_archive(root: Path, original: Path, source_run_id: str,
                             report: dict[str, Any]) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", source_run_id):
        raise ValueError("Historical source run ID is invalid")
    evidence = report.get("source_evidence") or {}
    for label, suffix, pin_name in (("run", ".json", "source_run_sha256"),
                                     ("skills", ".skills.json", "source_trace_sha256")):
        path = original / f".merak/runs/{source_run_id}{suffix}"
        archive = root / f".merak/source-evidence/{source_run_id}.{label}.original.json"
        payload = _json(path)
        if (archive.read_bytes() != path.read_bytes() or evidence.get(pin_name) != file_sha256(path)
                or payload.get("run_id") != source_run_id
                or label == "run" and payload.get("status") != "cancelled"):
            raise ValueError("Historical stopped-source evidence changed")
    if (evidence.get("source_run_id") != source_run_id or evidence.get("historical_only") is not True
            or evidence.get("reusable_prior_run_installed") is not False):
        raise ValueError("Continuation requires genuine all-owner benchmark history")


def frozen_inputs(root: Path) -> dict[str, str]:
    """Bind immutable source/plan bytes and archives throughout continuation."""
    hashes = tree_hashes(root)
    return {name: digest for name, digest in hashes.items()
            if name in {*FROZEN_FILES, "ideas/SELECTED_IDEA.json"}
            or any(name.startswith(directory + "/") for directory in FROZEN_DIRECTORIES)}


def _validate_implementation_source(root: Path, source: Path) -> None:
    current, baseline = frozen_inputs(root), frozen_inputs(source)
    for name in set(current) | set(baseline):
        if name.startswith(".merak/source-evidence/") or name == "experiments/RUN_SPEC.json":
            continue
        if current.get(name) != baseline.get(name):
            raise ValueError("Frozen benchmark implementation/source bytes changed: " + name)
    copied, original = _json(root / "experiments/RUN_SPEC.json"), _json(source / "experiments/RUN_SPEC.json")
    from scripts.full_benchmark_preparation import stage_target_declarations

    targets = copied.pop("implementation_stage_targets", None)
    original.pop("implementation_stage_targets", None)
    if copied != original or targets != stage_target_declarations():
        raise ValueError("Current RUN_SPEC differs from its frozen science or actual stage mapping")
    if (numerical_fingerprint(root) != numerical_fingerprint(source)
            or scientific_method_identity(root) != scientific_method_identity(source)):
        raise ValueError("Benchmark continuation cannot accept changed numbers or scientific hypotheses")


def _interruption_history(root: Path, run_id: str, report: dict) -> dict:
    """Retain genuine earlier unknown observations, without promoting them."""
    history = report.get("interruption_history")
    prior_pin = (report.get("continuation_identity") or {}).get("operator_interruption_receipt_sha256")
    if prior_pin and not history:
        raise ValueError("Prior operator interruption observability cannot disappear")
    if not history:
        return {}
    from scripts.full_benchmark_interruption import validate_interruption_history

    result = {"interruption_history": validate_interruption_history(root, run_id, history),
        "operator_interruption_receipt_sha256": history["receipt_sha256"],
        "prior_blocked_operations_observability": "unknown", "prior_workflow_acceptance_granted": False}
    if prior_pin and prior_pin != history["receipt_sha256"]:
        raise ValueError("Prior operator interruption receipt identity changed")
    return result


def validate_continuation_identity(root: Path, source: Path, original: Path, run_id: str,
                                   source_run_id: str, report_pin: str,
                                   state_pin: str, trace_pin: str, *, reference: Path | None = None,
                                   operator_interruption_pin: str = "",
                                   natural_failure_receipt: Path | None = None,
                                   natural_failure_pin: str = "") -> dict[str, Any]:
    """Require exact observed proof and preserved inputs; never manufacture accepted phases."""
    if not re.fullmatch(r"[a-f0-9]{12}", run_id):
        raise ValueError("Continuation requires its exact hexadecimal runtime run ID")
    names = ("FULL_BENCHMARK_REPORT.json", f".merak/runs/{run_id}.json", f".merak/runs/{run_id}.skills.json")
    for name, pin in zip(names, (report_pin, state_pin, trace_pin)):
        if not re.fullmatch(r"[a-f0-9]{64}", pin) or file_sha256(root / name) != pin:
            raise ValueError("Observed benchmark continuation proof changed: " + name)
    state = validate_stopped_run(root, run_id)
    report = _json(root / names[0])
    interruption = {}
    if (bool(natural_failure_receipt) != bool(natural_failure_pin)
            or operator_interruption_pin and natural_failure_pin):
        raise ValueError("Natural failure needs its explicit receipt path/pin and cannot impersonate cancellation")
    if operator_interruption_pin:
        from scripts.full_benchmark_interruption import validate_operator_interruption

        if reference is None or state.get("status") != "cancelled":
            raise ValueError("Operator-interruption continuation requires its exact cancelled copy and reference")
        interruption = validate_operator_interruption(root, source, original, reference,
            run_id, report, operator_interruption_pin)
    elif natural_failure_pin:
        from scripts.full_benchmark_natural_failure import validate_natural_failure

        if reference is None:
            raise ValueError("Natural failure recovery requires its exact frozen reference")
        interruption = {**_interruption_history(root, run_id, report), **validate_natural_failure(
            root, source, original, reference, run_id, natural_failure_receipt, natural_failure_pin,
            repository=root.parent)}
    else:
        if report.get("operator_interruption") or report.get("blocked_operations") != [] or report.get("originals_unchanged") is not True:
            raise ValueError("Ordinary benchmark reports require complete successful boundary observability")
        from scripts.full_benchmark_natural_failure import validate_natural_failure_history

        observation = report.get("failure_observation") or {}
        if (observation.get("safety_violation") is True or report.get("shutdown_error")
                or observation.get("failure_boundary") == "shutdown"):
            raise ValueError("Failed safety or shutdown observations require explicit producer diagnosis")
        interruption = {**_interruption_history(root, run_id, report),
                        **validate_natural_failure_history(root, run_id, report)}
    if (report.get("run_id") != run_id or report.get("status") != state.get("status")
            or report.get("accepted") is not False or report.get("real_model_execution") is not True
            or report.get("training_authorized") is not False or report.get("original_workflow_resumed") is not False
            or report.get("raw_numerical_and_semantic_bundle_unchanged") is not True
            or report.get("source_owner_reuse") != {}
            or report.get("logical_pipeline_nodes") != list(PIPELINE_NODES)
            or Path(str(report.get("snapshot_path") or "")).resolve() != root
            or report.get("phases") != {name: phase.get("status") for name, phase in state["phases"].items()}):
        raise ValueError("Previous real-model benchmark report does not attest this stopped copy")
    _validate_source_archive(root, original, source_run_id, report)
    _validate_implementation_source(root, source)
    return {"state": state, "previous_report": report, "previous_report_sha256": report_pin,
            "previous_state_sha256": state_pin, "previous_trace_sha256": trace_pin, **interruption}
