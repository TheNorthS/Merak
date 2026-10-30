"""Explicit read-only recovery proof for a naturally failed private prevalidation.

Unknown historical blocked attempts stay unknown. Exact stopped observations
permit only a new guarded native continuation, never historical/current quality
acceptance, status repair, cancellation or automatic persisted-format migration.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from scripts.full_benchmark_continuation_scope import (
    _json, _validate_implementation_source, _validate_source_archive,
    file_sha256, validate_project_roots, validate_stopped_run,
)
from scripts.full_benchmark_failure_launch import validate_launch_observation
from scripts.full_benchmark_interruption import _authority_binding, _frozen_observations
from scripts.full_benchmark_scope import PIPELINE_NODES


def _owned(root: Path, path: Path, run_id: str, *, archive: bool = False) -> Path:
    absolute, resolved = path.absolute(), path.resolve(strict=True)
    prefix = f".merak/benchmark-continuations/{run_id}/" if archive else f".merak/benchmark-natural-failures/{run_id}/"
    name = "report.previous.json" if archive else "natural-failure.json"
    if (absolute != resolved or not resolved.is_relative_to(root) or resolved.is_symlink()
            or resolved.stat().st_nlink > 1 or not resolved.is_file()
            or not resolved.relative_to(root).as_posix().startswith(prefix) or resolved.name != name):
        raise ValueError("Natural failure evidence leaves its exact private-run archive")
    return resolved


def _failed_report(root: Path, run_id: str, state: dict, previous: dict) -> dict:
    report = _json(root / "FULL_BENCHMARK_REPORT.json")
    phases = {name: item.get("status") for name, item in state["phases"].items()}
    boundaries = ("originals_unchanged", "current_continuation_roots_unchanged",
                  "raw_numerical_and_semantic_bundle_unchanged", "frozen_scientific_inputs_unchanged")
    if (state.get("status") != "incomplete" or report.get("status") != "incomplete"
            or report.get("run_id") != run_id or report.get("accepted") is not False
            or report.get("training_authorized") is not False or report.get("real_model_execution") is not True
            or report.get("original_workflow_resumed") is not False or report.get("source_owner_reuse") != {}
            or report.get("logical_pipeline_nodes") != list(PIPELINE_NODES)
            or Path(str(report.get("snapshot_path") or "")).resolve() != root
            or report.get("blocked_operations") is not None or report.get("operator_interruption")
            or report.get("current_gates") or any(report.get(name) is not True for name in boundaries)
            or report.get("originals_unchanged_scope") != "current_continuation_only"
            or report.get("phases") != phases or previous.get("phases") != phases
            or report.get("source_evidence") != previous.get("source_evidence")
            or report.get("interruption_history", {}) != previous.get("interruption_history", {})
            or report.get("natural_failure_history", {}) != previous.get("natural_failure_history", {})):
        raise ValueError("Natural prevalidation failure lacks exact unchanged non-accepting boundary proof")
    issues = report.get("issues")
    qa = report.get("manual_qa_directed_revision") or {}
    if (not isinstance(issues, list) or len(issues) != 1 or not isinstance(issues[0], str)
            or not issues[0].startswith("ValueError: ") or not issues[0].removeprefix("ValueError: ").strip()
            or qa.get("producer_invocation_observed") is True
            or qa.get("quality_acceptance_granted_by_receipt") is True or report.get("failure_observation")):
        raise ValueError("Natural failure is not the independently observed pre-worker validation error")
    if (previous.get("run_id") != run_id or previous.get("accepted") is not False
            or previous.get("blocked_operations") != [] or previous.get("originals_unchanged") is not True
            or previous.get("training_authorized") is not False or previous.get("real_model_execution") is not True):
        raise ValueError("Natural failure needs its genuine prior admitted report archive")
    return report


def build_natural_failure(root: Path, source: Path, original: Path, reference: Path,
                          run_id: str, archive: Path, authority_context: dict,
                          launch_observation: dict, *, repository: Path) -> dict[str, Any]:
    """Construct current evidence without writing files or reconstructing lost memory."""
    validate_project_roots(root, source, original, reference, repository)
    state = validate_stopped_run(root, run_id)
    previous_path = _owned(root, archive, run_id, archive=True)
    previous = _json(previous_path)
    report = _failed_report(root, run_id, state, previous)
    trace_pin = file_sha256(root / f".merak/runs/{run_id}.skills.json")
    launch = validate_launch_observation(launch_observation, repository.resolve(strict=True),
        run_id, file_sha256(previous_path), trace_pin)
    _validate_source_archive(root, original, str(report["source_evidence"].get("source_run_id") or ""), report)
    _validate_implementation_source(root, source)
    if report.get("interruption_history"):
        from scripts.full_benchmark_interruption import validate_interruption_history

        validate_interruption_history(root, run_id, report["interruption_history"])
    return {"schema": 1, "kind": "natural_prevalidation_failure", "run_id": run_id,
        "project_path": str(root), "accepted": False, "workflow_acceptance_granted": False,
        "scientific_execution_authorized": False, "blocked_operations": None,
        "blocked_operations_observability": "unknown", "past_quality_established": False,
        "permission_scope": "fresh_guarded_same_run_continuation_only",
        "reported_error": report["issues"][0], "report_sha256": file_sha256(root / "FULL_BENCHMARK_REPORT.json"),
        "state_sha256": file_sha256(root / f".merak/runs/{run_id}.json"), "trace_sha256": trace_pin,
        "previous_report_archive": previous_path.relative_to(root).as_posix(),
        "previous_report_sha256": file_sha256(previous_path), "launch_observation": launch,
        "source_evidence": report["source_evidence"], "interruption_history": report.get("interruption_history", {}),
        "previous_natural_failure_history": report.get("natural_failure_history", {}),
        "authority_binding": _authority_binding(original, reference, authority_context),
        "observations": _frozen_observations(root, source, original, reference)}


def natural_failure_history(root: Path, run_id: str, path: Path, pin: str) -> dict:
    """Historical uncertainty is immutable even after a later fully observed run."""
    owned = _owned(root, path, run_id)
    if not re.fullmatch(r"[a-f0-9]{64}", pin) or file_sha256(owned) != pin:
        raise ValueError("Natural failure receipt changed")
    receipt = _json(owned)
    if (type(receipt.get("schema")) is not int or receipt.get("schema") != 1
            or receipt.get("kind") != "natural_prevalidation_failure"
            or receipt.get("run_id") != run_id or receipt.get("project_path") != str(root)
            or receipt.get("accepted") is not False or receipt.get("workflow_acceptance_granted") is not False
            or receipt.get("blocked_operations") is not None or receipt.get("blocked_operations_observability") != "unknown"
            or receipt.get("past_quality_established") is not False
            or receipt.get("permission_scope") != "fresh_guarded_same_run_continuation_only"):
        raise ValueError("Natural failure history cannot assert acceptance or known past operations")
    return {"receipt_path": owned.relative_to(root).as_posix(), "receipt_sha256": pin,
            "blocked_operations": None, "blocked_operations_observability": "unknown",
            "workflow_acceptance_granted": False, "past_quality_established": False}


def validate_natural_failure(root: Path, source: Path, original: Path, reference: Path,
                             run_id: str, path: Path, pin: str, *, repository: Path) -> dict:
    """An explicit exact receipt permits fresh guard entry, never retrospective repair."""
    history = natural_failure_history(root, run_id, path, pin)
    receipt = _json(root / history["receipt_path"])
    expected = build_natural_failure(root, source, original, reference, run_id,
        root / receipt["previous_report_archive"], receipt["authority_binding"],
        receipt["launch_observation"], repository=repository)
    if receipt != expected:
        raise ValueError("Natural failure receipt no longer matches its exact stopped observations")
    return {"natural_failure_receipt_sha256": pin, "natural_failure_history": history,
            "prior_blocked_operations_observability": "unknown", "prior_workflow_acceptance_granted": False}


def validate_natural_failure_history(root: Path, run_id: str, report: dict) -> dict:
    """Ordinary observed reports may not silently erase prior unknown failures."""
    history = report.get("natural_failure_history")
    prior = (report.get("continuation_identity") or {}).get("natural_failure_receipt_sha256")
    if prior and not history:
        raise ValueError("Natural failure historical observability cannot disappear")
    if not history:
        return {}
    if not isinstance(history, dict):
        raise ValueError("Natural failure history must be the exact pinned observation object")
    expected = natural_failure_history(root, run_id, root / str(history.get("receipt_path") or ""),
                                      str(history.get("receipt_sha256") or ""))
    if history != expected or prior and prior != expected["receipt_sha256"]:
        raise ValueError("Natural failure historical observability changed")
    return {"natural_failure_history": expected, "natural_failure_receipt_sha256": expected["receipt_sha256"],
            "prior_blocked_operations_observability": "unknown", "prior_workflow_acceptance_granted": False}
