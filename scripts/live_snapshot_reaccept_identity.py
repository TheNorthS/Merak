"""Pinned identity of an invalidated verification copy before genuine local gates."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from scripts.live_snapshot_resume_validation import (
    ALLOWED_NODES, UPSTREAM, _config_identity, _json, _source_archives,
    scientific_digest, validate_copy_boundary,
)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pinned_source(root: Path, original: Path, run_id: str, report_pin: str, trace_pin: str) -> tuple[dict, dict, dict]:
    if _digest(root / ".merak/LIVE_VERIFICATION_REPORT.json") != report_pin:
        raise ValueError("Original copy verification report differs from its recorded digest")
    source, source_trace = _source_archives(root, original, run_id)
    if _digest(original / f".merak/runs/{run_id}.skills.json") != trace_pin:
        raise ValueError("Original upstream trace differs from its recorded digest")
    report = _json(root / ".merak/LIVE_VERIFICATION_REPORT.json")
    if (report.get("accepted") is not False or report.get("status") != "incomplete"
            or report.get("snapshot_path") != str(root) or report.get("scientific_inputs_unchanged") is not True
            or report.get("original_inputs_unchanged") is not True or report.get("real_model_execution") is not True
            or report.get("original_workflow_resumed") is not False or report.get("training_authorized") is not False
            or report.get("blocked_operations") != []
            or (report.get("source_specialist_snapshot") or {}).get("source_plan_sha256")
            != _digest(original / f".merak/runs/{run_id}.specialists.json")
            or (report.get("upstream_readonly_revalidation") or {}).get("source_run_state_sha256")
            != _digest(original / f".merak/runs/{run_id}.json")):
        raise ValueError("Invalidated copy lacks its authentic previous independent verification")
    return source, source_trace, report


def _trace_identity(root: Path, original: Path, run_id: str, source_trace: dict) -> dict:
    trace = _json(root / f".merak/runs/{run_id}.skills.json")
    provenance = trace.get("snapshot_provenance") or {}
    if (trace.get("schema") != 2 or trace.get("run_id") != run_id
            or Path(str(trace.get("project_path") or "")).resolve() != root
            or provenance.get("source_project") != str(original) or provenance.get("source_run_id") != run_id
            or provenance.get("source_trace_sha256") != _digest(original / f".merak/runs/{run_id}.skills.json")
            or provenance.get("upstream_invocations_rewritten") is not False
            or provenance.get("new_upstream_execution_claimed") is not False):
        raise ValueError("Invalidated copy changed its original execution envelope")
    for node in UPSTREAM:
        expected = (source_trace.get("stages") or {}).get(node)
        if not isinstance(expected, dict) or not expected or (trace.get("stages") or {}).get(node) != expected:
            raise ValueError("Invalidated copy cannot replace upstream model execution evidence")
    if not isinstance((trace.get("stages") or {}).get("figure"), dict) or not trace["stages"]["figure"]:
        raise ValueError("Figure reacceptance requires this copy's actual existing execution evidence")
    return trace


def _invalidated_phases(root: Path, run_id: str, state: dict, source: dict, report: dict) -> None:
    phases = state.get("phases") or {}
    if set(phases) != set(UPSTREAM) | set(ALLOWED_NODES):
        raise ValueError("Invalidated copy changed its pipeline inventory")
    for node in UPSTREAM:
        phase, old = phases[node], source["phases"][node]
        history = (phase.get("details") or {}).get("acceptance_invalidations") or []
        if (report.get("phases", {}).get(node) != "accepted" or old.get("status") != "accepted"
                or phase.get("status") != "done" or phase.get("accepted_at") is not None or not history
                or any(history[-1].get(key) != old.get(key) for key in ("verdict_id", "reviewer", "accepted_at"))):
            raise ValueError("Local reacceptance cannot invent the copied original acceptance history")
    figure = phases["figure"]
    history = (figure.get("details") or {}).get("acceptance_invalidations") or []
    events = [json.loads(line) for line in (root / f".merak/runs/{run_id}.events.jsonl").read_text(encoding="utf-8").splitlines()]
    accepted = [event for event in events if event.get("run_id") == run_id
                and event.get("event") == "node_accepted" and event.get("data", {}).get("node_id") == "figure"]
    if (report.get("phases", {}).get("figure") != "accepted" or figure.get("status") != "done"
            or not history or not accepted
            or any(history[-1].get(key) != accepted[-1]["data"].get(key) for key in ("verdict_id", "reviewer"))):
        raise ValueError("Figure reacceptance must follow its own authentic copy acceptance, not the original project")


def validate_invalidated_copy(root: Path, original: Path, run_id: str, repository: Path,
                              science_pin: str, report_pin: str, trace_pin: str,
                              state_pin: str, inputs: dict[str, str]) -> dict:
    root, original, repository = root.resolve(), original.resolve(), repository.resolve()
    if (root == original or root.parent != repository or not root.name.startswith("live-verification-106-")
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", run_id)
            or any(not re.fullmatch(r"[a-f0-9]{64}", pin) for pin in (science_pin, report_pin, trace_pin, state_pin))
            or not inputs or scientific_digest(inputs) != science_pin):
        raise ValueError("Genuine reacceptance requires the exact isolated copy and independently pinned inputs")
    validate_copy_boundary(root)
    state_path = root / f".merak/runs/{run_id}.json"
    if _digest(state_path) != state_pin:
        raise ValueError("Invalidated copy state changed since independent observation")
    state = _json(state_path)
    source, source_trace, report = _pinned_source(root, original, run_id, report_pin, trace_pin)
    if (state.get("schema") != 1 or state.get("run_id") != run_id or state.get("status") != "incomplete"
            or state.get("input_baseline") != source.get("input_baseline")):
        raise ValueError("Genuine reacceptance cannot change the original run or input baseline")
    _config_identity(state, source, root, original, run_id)
    _trace_identity(root, original, run_id, source_trace)
    _invalidated_phases(root, run_id, state, source, report)
    return {"source_run_id": run_id, "snapshot_path": str(root), "source_project": str(original),
            "science_sha256": science_pin, "previous_report_sha256": report_pin,
            "source_trace_sha256": trace_pin, "source_run_state_sha256": _digest(original / f".merak/runs/{run_id}.json"),
            "state_before_sha256": state_pin, "model_invoked": False}
