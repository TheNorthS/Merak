"""A genuine local reinspection cannot invent lost source or copy acceptance."""

from __future__ import annotations

import copy
import hashlib
import json

import pytest

from scripts.live_snapshot_reaccept_identity import validate_invalidated_copy
from server.tests.test_live_snapshot_resume_validation import evidence, RUN_ID


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def invalidated(evidence):
    root = evidence["root"]
    path = root / f".merak/runs/{RUN_ID}.json"
    state = json.loads(path.read_text())
    report_path = root / ".merak/LIVE_VERIFICATION_REPORT.json"
    report = json.loads(report_path.read_text())
    report["phases"]["figure"] = "accepted"
    evidence["report"] = _write(report_path, report)
    for node in ("lit", "idea", "novelty", "exp-design", "exp-run", "results"):
        phase = state["phases"][node]
        previous = {key: phase.get(key) for key in ("verdict_id", "reviewer", "accepted_at")}
        phase.update({"status": "done", "verdict_id": "", "reviewer": "", "accepted_at": None})
        phase["details"] = {"acceptance_invalidations": [previous]}
    figure = state["phases"]["figure"]
    figure.update({"status": "done", "accepted_at": None, "details": {"acceptance_invalidations": [{
        "verdict_id": "copy-figure-verdict", "reviewer": "copy-local-gate", "accepted_at": 150,
    }]}})
    event = {"run_id": RUN_ID, "event": "node_accepted", "data": {
        "node_id": "figure", "verdict_id": "copy-figure-verdict", "reviewer": "copy-local-gate",
    }}
    (root / f".merak/runs/{RUN_ID}.events.jsonl").write_text(json.dumps(event) + "\n", encoding="utf-8")
    trace_path = root / f".merak/runs/{RUN_ID}.skills.json"
    trace = json.loads(trace_path.read_text())
    trace["stages"]["figure"] = {"execution_kind": "runtime_owned", "completed_operations": ["actual-figure"]}
    _write(trace_path, trace)
    evidence["state"] = _write(path, state)
    return evidence


def _validate(value):
    return validate_invalidated_copy(value["root"], value["original"], RUN_ID, value["repository"],
        value["scientific"], value["report"], value["trace"], value["state"], value["inputs"])


def test_invalidated_source_and_actual_copy_figure_can_be_checked_without_status_changes(invalidated):
    state = invalidated["root"] / f".merak/runs/{RUN_ID}.json"
    before = state.read_bytes()
    identity = _validate(invalidated)
    assert identity["state_before_sha256"] == invalidated["state"]
    assert state.read_bytes() == before


@pytest.mark.parametrize("mutation", ["state_pin", "source_history", "figure_history", "figure_trace", "science"])
def test_unproved_or_changed_acceptance_is_refused(invalidated, mutation):
    value = copy.copy(invalidated)
    if mutation == "state_pin":
        value["state"] = "a" * 64
    elif mutation == "science":
        value["inputs"] = {**value["inputs"], "experiments/new.csv": "b" * 64}
    elif mutation == "figure_trace":
        path = value["root"] / f".merak/runs/{RUN_ID}.skills.json"
        trace = json.loads(path.read_text())
        trace["stages"].pop("figure")
        _write(path, trace)
    else:
        path = value["root"] / f".merak/runs/{RUN_ID}.json"
        state = json.loads(path.read_text())
        node = "results" if mutation == "source_history" else "figure"
        state["phases"][node]["details"]["acceptance_invalidations"][-1]["verdict_id"] = "invented"
        value["state"] = _write(path, state)
    with pytest.raises(ValueError):
        _validate(value)
