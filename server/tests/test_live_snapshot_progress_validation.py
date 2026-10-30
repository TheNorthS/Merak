"""Legitimate downstream work must not bypass pinned upstream/scientific owners."""

import copy
import hashlib
import json
import time

import pytest

from scripts import live_snapshot_progress_validation as progress
from server.tests.test_live_snapshot_reaccept_receipt import local_receipt
from server.tests.test_live_snapshot_reaccept_identity import invalidated
from server.tests.test_live_snapshot_resume_validation import evidence, RUN_ID


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return _sha(path)


@pytest.fixture
def advanced(local_receipt, monkeypatch):
    value = copy.deepcopy(local_receipt)
    root, repository = value["root"], value["repository"]
    monkeypatch.setattr(progress, "REPOSITORY", repository)
    receipt = value["receipt"]
    old_call = root / ".merak/skill-invocations/source.json"
    receipt["frozen_inputs_sha256"][old_call.relative_to(root).as_posix()] = _sha(old_call)
    value["receipt_pin"] = _write(root / ".merak/LOCAL_REACCEPT_REPORT.json", receipt)
    state = value["copied"]
    state["status"] = "running"
    state["phases"]["paper"].update(status="running", details={"current_stage": "consistency"})
    value["state_pin"] = _write(root / f".merak/runs/{RUN_ID}.json", state)
    trace = json.loads((root / f".merak/runs/{RUN_ID}.skills.json").read_text())
    trace["stages"]["paper"] = {"selected": ["domain-paper-write"], "node_id": "paper"}
    value["current_trace_pin"] = _write(root / f".merak/runs/{RUN_ID}.skills.json", trace)
    source = repository / "merak-skills/domain-paper-write/SKILL.md"
    source.parent.mkdir(parents=True)
    source.write_text("Current bounded paper author fixture policy\n")
    call = {"schema": 1, "id": "new-paper", "skill": "domain-paper-write", "session_id": "new-session",
            "parent_context": "skill-chain:workflow-staged-paper", "project_path": str(root),
            "bounded_invocation": True, "policy_loaded": True, "status": "running",
            "skill_source": str(source), "skill_sha256": _sha(source), "skill_bytes": source.stat().st_size}
    _write(root / ".merak/skill-invocations/new-paper.json", call)
    _write(root / ".merak/agent-sessions/new-session.json", {"schema": 2, "session_id": "new-session",
        "context_key": "skill-chain:workflow-staged-paper>domain-paper-write", "tool_policy": "workflow_artifacts",
        "workflow_node_id": ""})
    (root / "paper/sections/02_related_work.tex").write_text("Legitimate bounded author revision\n")
    _write(root / ".merak/active-workflow.json", {"schema": 1, "run_id": RUN_ID, "expires_at": time.time() - 10})
    return value


def _validate(value):
    return progress.validate_authorized_progress(value["root"], value["original"], RUN_ID,
        value["receipt_pin"], value["state_pin"], value["current_trace_pin"], value["science_pin"],
        value["trace"], value["report"])


def test_pinned_author_progress_uses_full_historical_gates_not_current_equals_old_state(advanced):
    root = advanced["root"]
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    identity = _validate(advanced)
    assert identity["current_state_sha256"] == advanced["state_pin"]
    assert identity["current_state_sha256"] != advanced["receipt"]["state_after_sha256"]
    assert identity["authorized_new_model_sessions"] == ["new-session"]
    assert identity["workflow_or_model_invoked_by_validation"] is False
    assert all(path.read_bytes() == content for path, content in before.items())


@pytest.mark.parametrize("pin", ["state_pin", "current_trace_pin", "receipt_pin", "science_pin", "trace", "report"])
def test_every_observed_and_historical_pin_is_required(advanced, pin):
    advanced[pin] = "0" * 64
    with pytest.raises(ValueError):
        _validate(advanced)


@pytest.mark.parametrize("defect", ["phase_identity", "phase_details", "source_trace", "source_archive", "source_call",
                                     "science", "unregistered_node", "model_source", "session", "active_lease", "false_old_gate"])
def test_changed_or_out_of_scope_progress_is_refused_even_with_current_pins(advanced, defect):
    root = advanced["root"]
    state_path, trace_path = root / f".merak/runs/{RUN_ID}.json", root / f".merak/runs/{RUN_ID}.skills.json"
    if defect in {"phase_identity", "phase_details"}:
        state = json.loads(state_path.read_text())
        if defect == "phase_identity":
            state["phases"]["lit"]["accepted_at"] += 1
        else:
            state["phases"]["lit"]["details"]["invented_scientific_support"] = True
        advanced["state_pin"] = _write(state_path, state)
    elif defect in {"source_trace", "unregistered_node"}:
        trace = json.loads(trace_path.read_text())
        trace["stages"]["lit" if defect == "source_trace" else "new-unapproved-node"] = {"invented": True}
        advanced["current_trace_pin"] = _write(trace_path, trace)
    elif defect == "source_archive":
        (root / f".merak/snapshot-source-traces/{RUN_ID}.skills.original.json").write_text("altered archive")
    elif defect == "source_call":
        (root / ".merak/skill-invocations/source.json").write_text("rewritten original invocation")
    elif defect == "science":
        (root / "experiments/frozen.csv").write_text("altered scientific input")
    elif defect == "model_source":
        (advanced["repository"] / "merak-skills/domain-paper-write/SKILL.md").write_text("changed current policy")
    elif defect == "session":
        _write(root / ".merak/agent-sessions/new-session.json", {"schema": 2, "session_id": "foreign"})
    elif defect == "active_lease":
        _write(root / ".merak/active-workflow.json", {"run_id": RUN_ID, "expires_at": time.time() + 600})
    else:
        receipt = copy.deepcopy(advanced["receipt"])
        receipt["gates"]["results"]["details"]["execution_evidence"]["accepted"] = False
        advanced["receipt_pin"] = _write(root / ".merak/LOCAL_REACCEPT_REPORT.json", receipt)
    with pytest.raises(ValueError):
        _validate(advanced)


def test_only_semantically_identical_risk_cache_rebinds_are_permitted(advanced):
    root = advanced["root"]
    old = {"schema": 1, "node_id": "lit", "generated_at": 100, "blocking": False, "findings": [],
           "report_path": ".merak/quality/lit-risk.json", "status": "clear"}
    advanced["receipt"]["accepted_phases"]["lit"]["details"]["node_risk_audit"] = old
    advanced["receipt_pin"] = _write(root / ".merak/LOCAL_REACCEPT_REPORT.json", advanced["receipt"])
    path = root / f".merak/runs/{RUN_ID}.json"
    state = json.loads(path.read_text())
    phase = state["phases"]["lit"]
    phase["details"]["node_risk_audit"] = {key: value for key, value in old.items() if key != "report_path"}
    phase["details"]["node_risk_audit"]["generated_at"] = 200
    phase["details"]["acceptance_rebindings"] = [{"reason": "refreshed accepted-phase risk audit cache",
        "timestamp": 200, "verdict_id": phase["verdict_id"], "reviewer": phase["reviewer"]}]
    advanced["state_pin"] = _write(path, state)
    assert _validate(advanced)["upstream_acceptance_unchanged"]
    phase["details"]["node_risk_audit"]["blocking"] = True
    advanced["state_pin"] = _write(path, state)
    with pytest.raises(ValueError, match="risk verdict"):
        _validate(advanced)


def _new_accepted_figure(value):
    from server.services.workflow_inputs import artifact_state

    root = value["root"]
    plan = root / "figures/SCIENTIFIC_ASSET_PLAN.json"
    plan.write_text('{"schema":2,"derived_plan":"before authorized progress"}')
    receipt = value["receipt"]
    receipt["frozen_inputs_sha256"][plan.relative_to(root).as_posix()] = _sha(plan)
    value["receipt_pin"] = _write(root / ".merak/LOCAL_REACCEPT_REPORT.json", receipt)
    plan.write_text('{"schema":2,"derived_plan":"new actually accepted figure plan"}')
    spec = root / "figures/FIGURE_SPECS.json"
    spec.write_text('{"schema":4,"figures":[]}')
    manifest = root / "figures/FIGURE_MANIFEST.json"
    _write(manifest, {"schema": 1, "figures": []})
    state_path, trace_path = root / f".merak/runs/{RUN_ID}.json", root / f".merak/runs/{RUN_ID}.skills.json"
    state = json.loads(state_path.read_text())
    phase = state["phases"]["figure"]
    phase.update(status="accepted", accepted_at=2000, verdict_id="actual-progress-figure",
                 reviewer="deterministic:figure-manifest", execution_kind="runtime_owned",
                 runtime_service="figure_renderers+figure_quality_gate")
    phase["details"]["execution_evidence"] = {"accepted": True, "issues": [], "trace_path": str(trace_path),
                                               "runtime_execution_verified": True}
    phase["details"]["artifact_snapshot"] = {p.relative_to(root).as_posix(): artifact_state(p)
                                               for p in (plan, spec, manifest)}
    value["state_pin"] = _write(state_path, state)
    trace = json.loads(trace_path.read_text())
    trace["stages"]["figure"] = {"runtime_invocations": [{"runtime_service": phase["runtime_service"],
        "status": "completed", "execution_verified": True, "run_id": RUN_ID, "operation_id": "actual-operation", "updated_at": 1999}]}
    value["current_trace_pin"] = _write(trace_path, trace)
    event = {"schema": 1, "event": "node_accepted", "run_id": RUN_ID, "timestamp": 2001,
             "data": {"node_id": "figure", "verdict_id": phase["verdict_id"], "reviewer": phase["reviewer"]}}
    journal = root / f".merak/runs/{RUN_ID}.events.jsonl"
    journal.write_text(journal.read_text() + json.dumps(event) + "\n")
    return state_path


def test_only_new_verified_figure_acceptance_can_prove_derived_plan_progress(advanced):
    _new_accepted_figure(advanced)
    assert _validate(advanced)["upstream_acceptance_unchanged"]


@pytest.mark.parametrize("defect", ["after_accept", "status_done", "missing_execution", "escaped_snapshot", "missing_event", "failed_runtime"])
def test_unproved_derived_figure_plan_change_is_never_ignored(advanced, defect):
    root = advanced["root"]
    state_path = _new_accepted_figure(advanced)
    state = json.loads(state_path.read_text())
    figure = state["phases"]["figure"]
    if defect == "after_accept":
        (root / "figures/SCIENTIFIC_ASSET_PLAN.json").write_text("changed after accepted snapshot")
    elif defect == "status_done":
        figure["status"] = "done"
    elif defect == "missing_execution":
        figure["details"].pop("execution_evidence")
    elif defect == "escaped_snapshot":
        figure["details"]["artifact_snapshot"]["figures/../../outside.svg"] = {"kind": "file", "sha256": "0" * 64}
    elif defect == "missing_event":
        journal = root / f".merak/runs/{RUN_ID}.events.jsonl"
        journal.write_text(journal.read_text().splitlines()[0] + "\n")
    else:
        trace_path = root / f".merak/runs/{RUN_ID}.skills.json"
        trace = json.loads(trace_path.read_text())
        trace["stages"]["figure"]["runtime_invocations"][-1]["status"] = "failed"
        advanced["current_trace_pin"] = _write(trace_path, trace)
    advanced["state_pin"] = _write(state_path, state)
    with pytest.raises(ValueError):
        _validate(advanced)
