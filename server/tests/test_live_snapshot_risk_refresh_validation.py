"""Changed implementation metadata needs fresh evidence, not a weaker gate."""

import copy
import socket
import subprocess
import sys

import pytest

from scripts import live_snapshot_progress_validation as progress
from scripts import live_snapshot_risk_refresh_validation as refresh
from scripts.live_snapshot_resume_validation import UPSTREAM, scientific_digest
from server.services.node_risk_audit import node_risk_audit_service
from server.services.workflow_inputs import artifact_state
from server.workflows.engine import WorkflowEngine


@pytest.fixture
def refreshed(tmp_path, monkeypatch):
    root = tmp_path / "copy"
    output, data = root / "literature/REVIEW.md", root / "experiments/frozen.csv"
    for path, content in ((output, "Reviewed current literature\n"), (data, "value\n10\n")):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    report = {"schema": 1, "node_id": "lit", "generated_at": 100, "blocking": False,
              "status": "advisory", "mode": "synthetic_preview", "purpose": "literature",
              "counts": {"blocker": 0, "warning": 1, "info": 0}, "checks_executed": ["sources"],
              "risk_policy": {"warning": "researcher judgment"}, "report_path": ".merak/quality/lit-risk.json",
              "findings": [{"id": "LIT-WARN", "severity": "warning", "message": "Limited breadth"}]}
    old = {"status": "accepted", "accepted_at": 1000, "verdict_id": "lit-exact", "reviewer": "local-verifier",
           "details": {"risk_audit_bound": True, "risk_audit_validator_signature": "1" * 64,
                       "node_risk_audit": report, "input_baseline_snapshot_id": "current-baseline",
                       "artifact_snapshot": {"literature/REVIEW.md": artifact_state(output)},
                       "acceptance_rebindings": [], "scientific_support": "unchanged"}}
    current = copy.deepcopy(old)
    current["details"]["risk_audit_validator_signature"] = "2" * 64
    current["details"]["node_risk_audit"].pop("report_path")
    current["details"]["node_risk_audit"]["generated_at"] = 200
    current["details"]["acceptance_rebindings"].append({"reason": "refreshed accepted-phase risk audit cache",
        "timestamp": 200, "verdict_id": old["verdict_id"], "reviewer": old["reviewer"]})
    fresh = copy.deepcopy(current["details"]["node_risk_audit"])
    fresh["generated_at"] = 300
    calls = []

    def audit(project, node, options, *, persist):
        calls.append((project, node, copy.deepcopy(options), persist))
        return copy.deepcopy(fresh)

    monkeypatch.setattr(node_risk_audit_service, "audit_node", audit)
    files = refresh._copy_hashes(root)
    science = scientific_digest({key: value for key, value in files.items()
                                 if key.startswith(("ideas/", "literature/", "experiments/"))})
    return {"root": root, "old": old, "current": current, "fresh": fresh, "calls": calls,
            "options": {"run_experiment": False, "non_experiment_evidence_mode": "synthetic_preview"},
            "baseline": {"snapshot_id": "current-baseline"}, "science": science}


def _validate(item):
    return refresh.validate_risk_signature_refresh(item["root"], "lit", item["current"], item["old"],
        item["options"], item["baseline"], item["science"])


def _progress(item):
    recorded = {node: copy.deepcopy(item["old"]) for node in UPSTREAM}
    current = {node: copy.deepcopy(item["old"]) for node in UPSTREAM}
    current["lit"] = item["current"]
    state = {"phases": current, "config": {"options": item["options"]}, "input_baseline": item["baseline"]}
    return progress._upstream_phase_progress(state, recorded, item["root"], item["science"])


def test_exact_semantics_prove_three_distinct_epochs_without_copy_or_acceptance_writes(refreshed):
    before = refresh._copy_hashes(refreshed["root"])
    phase, old = copy.deepcopy(refreshed["current"]), copy.deepcopy(refreshed["old"])
    proof = _progress(refreshed)[0]
    assert proof["historical_cache_implementation_sha256"] == "1" * 64
    assert proof["saved_cache_implementation_sha256"] == "2" * 64
    assert proof["current_validator_implementation_sha256"] == WorkflowEngine._risk_audit_validator_signature(refreshed["options"])
    assert proof["current_validator_implementation_sha256"] not in {"1" * 64, "2" * 64}
    assert proof["acceptance_identity_changed"] is proof["model_or_producer_invoked"] is False
    assert refreshed["calls"] == [(refreshed["root"], "lit", refreshed["options"], False)]
    assert refresh._copy_hashes(refreshed["root"]) == before
    assert refreshed["current"] == phase and refreshed["old"] == old


@pytest.mark.parametrize("defect", ["old_sha", "new_sha", "same_sha", "unbound_old", "unbound_new",
    "empty_history", "old_history", "reason", "verdict", "reviewer"])
def test_changed_stamp_requires_exact_bound_cache_and_appended_history(refreshed, defect):
    old, current = refreshed["old"]["details"], refreshed["current"]["details"]
    if defect == "old_sha":
        old["risk_audit_validator_signature"] = "old"
    elif defect == "new_sha":
        current["risk_audit_validator_signature"] = "wrong"
    elif defect == "same_sha":
        current["risk_audit_validator_signature"] = old["risk_audit_validator_signature"]
    elif defect.startswith("unbound"):
        (old if defect.endswith("old") else current)["risk_audit_bound"] = False
    elif defect == "empty_history":
        current["acceptance_rebindings"] = []
    elif defect == "old_history":
        old["acceptance_rebindings"] = [{"recorded": "historical prefix"}]
    else:
        key = "verdict_id" if defect == "verdict" else defect
        current["acceptance_rebindings"][0][key] = "invented"
    with pytest.raises(ValueError, match="refresh history"):
        _validate(refreshed)
    assert refreshed["calls"] == []


@pytest.mark.parametrize("field", ["accepted_at", "status", "reviewer", "verdict_id"])
def test_progress_preserves_every_upstream_acceptance_identity(refreshed, field):
    refreshed["current"][field] = "invented"
    with pytest.raises(ValueError, match="frozen upstream acceptance identity"):
        _progress(refreshed)
    assert refreshed["calls"] == []


def test_no_other_scientific_detail_is_excluded_with_the_cache_stamp(refreshed):
    refreshed["current"]["details"]["scientific_support"] = "invented support"
    with pytest.raises(ValueError, match="scientific acceptance details"):
        _progress(refreshed)


@pytest.mark.parametrize("field", ["counts", "findings", "checks_executed", "mode", "status", "risk_policy"])
def test_every_nonvolatile_fresh_risk_field_must_equal_both_cached_epochs(refreshed, field):
    refreshed["fresh"][field] = {"changed": True} if field == "counts" else [] if field == "findings" else "changed"
    with pytest.raises(ValueError, match="risk|report"):
        _validate(refreshed)


def test_blocker_cannot_hide_behind_an_unchanged_stored_cache(refreshed):
    refreshed["fresh"]["blocking"] = True
    refreshed["fresh"]["counts"]["blocker"] = 1
    refreshed["fresh"]["findings"] = [{"id": "ACTUAL-FAIL", "severity": "blocker"}]
    with pytest.raises(ValueError, match="nonblocking"):
        _validate(refreshed)


@pytest.mark.parametrize("defect", ["baseline", "empty_snapshot", "foreign_snapshot", "output_bytes", "science"])
def test_signature_metadata_never_rebinds_scientific_or_output_content(refreshed, defect):
    if defect == "baseline":
        refreshed["baseline"]["snapshot_id"] = "foreign"
    elif defect == "empty_snapshot":
        refreshed["current"]["details"]["artifact_snapshot"] = {}
    elif defect == "foreign_snapshot":
        refreshed["current"]["details"]["artifact_snapshot"] = {"../foreign.md": {"kind": "file"}}
    elif defect == "output_bytes":
        (refreshed["root"] / "literature/REVIEW.md").write_text("altered output")
        refreshed["science"] = refresh._science_hash(refresh._copy_hashes(refreshed["root"]))
    else:
        (refreshed["root"] / "experiments/frozen.csv").write_text("changed numbers")
    with pytest.raises(ValueError, match="input|snapshot|artifact|scientific"):
        _validate(refreshed)
    assert refreshed["calls"] == []


@pytest.mark.parametrize("operation", ["file", "mkdir", "process", "network", "options"])
def test_readonly_reinspection_denies_side_effects_and_option_changes(refreshed, monkeypatch, operation):
    original = refresh._copy_hashes(refreshed["root"])
    original_options = copy.deepcopy(refreshed["options"])

    def unsafe(root, _node, options, *, persist):
        assert persist is False
        if operation == "file":
            (root / "unauthorized.txt").write_text("forbidden")
        elif operation == "mkdir":
            (root / "unauthorized-directory").mkdir()
        elif operation == "process":
            subprocess.Popen(["must-not-start"])
        elif operation == "network":
            socket.getaddrinfo("must-not-resolve.invalid", 443)
        else:
            options["run_experiment"] = True
        return copy.deepcopy(refreshed["fresh"])

    monkeypatch.setattr(node_risk_audit_service, "audit_node", unsafe)
    with pytest.raises((PermissionError, ValueError)):
        _validate(refreshed)
    assert refresh._copy_hashes(refreshed["root"]) == original
    assert refreshed["options"] == original_options
    (refreshed["root"] / "after-scope.txt").write_text("guard correctly deactivated")


def test_validator_sources_must_remain_same_during_reinspection(refreshed, monkeypatch):
    reads = iter([{"source": "before"}, {"source": "after"}])
    monkeypatch.setattr(refresh, "_source_hashes", lambda: next(reads))
    with pytest.raises(ValueError, match="validator sources"):
        _validate(refreshed)


def test_current_implementation_signature_cannot_change_mid_inspection(refreshed, monkeypatch):
    signatures = iter(["3" * 64, "4" * 64])
    monkeypatch.setattr(WorkflowEngine, "_risk_audit_validator_signature", staticmethod(lambda _options: next(signatures)))
    with pytest.raises(ValueError, match="validator sources"):
        _validate(refreshed)


@pytest.mark.parametrize("operation", ["file", "process", "network"])
def test_swallowed_side_effect_errors_cannot_be_reported_as_success(refreshed, monkeypatch, operation):
    def swallowed(root, _node, _options, *, persist):
        assert persist is False
        try:
            if operation == "file":
                (root / "must-not-exist.txt").write_text("forbidden")
            elif operation == "process":
                subprocess.Popen(["must-not-start"])
            else:
                socket.getaddrinfo("must-not-resolve.invalid", 443)
        except PermissionError:
            pass
        return copy.deepcopy(refreshed["fresh"])

    monkeypatch.setattr(node_risk_audit_service, "audit_node", swallowed)
    with pytest.raises(ValueError, match="forbidden side effects"):
        _validate(refreshed)
    assert not (refreshed["root"] / "must-not-exist.txt").exists()


def test_contradictory_warning_counter_cannot_reuse_a_clear_blocker_counter(refreshed):
    refreshed["fresh"]["counts"]["warning"] = 0
    with pytest.raises(ValueError, match="risk counters"):
        _validate(refreshed)


@pytest.mark.parametrize("field", ["counts", "findings"])
def test_changed_saved_risk_semantics_are_not_treated_as_cache_metadata(refreshed, field):
    refreshed["current"]["details"]["node_risk_audit"][field] = {} if field == "counts" else []
    with pytest.raises(ValueError, match="risk verdict"):
        _progress(refreshed)


def test_existing_global_and_returned_local_trace_handlers_are_restored(refreshed, monkeypatch):
    events, held_frames = [], []

    def local(frame, event, _argument):
        if frame.f_code.co_name == "audited":
            events.append(("local", event))
        return local

    def existing(frame, event, _argument):
        if frame.f_code.co_name == "audited":
            events.append(("global", event))
        return local

    def audited(_root, _node, _options, *, persist):
        assert persist is False
        held_frames.append(sys._getframe())
        return copy.deepcopy(refreshed["fresh"])

    monkeypatch.setattr(node_risk_audit_service, "audit_node", audited)
    before, caller, caller_local = sys.gettrace(), sys._getframe(), sys._getframe().f_trace
    try:
        sys.settrace(existing)
        assert _validate(refreshed)["copy_files_unchanged"]
        assert sys.gettrace() is existing
        assert held_frames[0].f_trace is local
        assert ("global", "call") in events and ("local", "return") in events
    finally:
        sys.settrace(before)
        caller.f_trace = caller_local


def test_permission_failure_is_unverifiable_even_when_unrelated_to_an_audit_hook(refreshed, monkeypatch):
    def denied_read(_root, _node, _options, *, persist):
        assert persist is False
        try:
            raise PermissionError("Input cannot be read completely")
        except PermissionError:
            pass
        return copy.deepcopy(refreshed["fresh"])

    monkeypatch.setattr(node_risk_audit_service, "audit_node", denied_read)
    before = sys.gettrace()
    with pytest.raises(ValueError, match="forbidden side effects"):
        _validate(refreshed)
    assert sys.gettrace() is before


def test_validator_cannot_disable_the_exception_observer(refreshed, monkeypatch):
    def disabled(_root, _node, _options, *, persist):
        assert persist is False
        sys.settrace(None)
        return copy.deepcopy(refreshed["fresh"])

    monkeypatch.setattr(node_risk_audit_service, "audit_node", disabled)
    before = sys.gettrace()
    with pytest.raises(ValueError, match="exception-observation scope"):
        _validate(refreshed)
    assert sys.gettrace() is before
