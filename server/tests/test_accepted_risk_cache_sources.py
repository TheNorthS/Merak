"""A validator-source repair must cause real cache branch reinspection."""

from __future__ import annotations

from pathlib import Path

import pytest

from server.services.node_risk_audit import node_risk_audit_service
from server.workflows.accepted_phase_validation import AcceptedPhaseAudit, _risk_cache_issues
from server.workflows.engine import WorkflowEngine
from server.workflows.models import WorkflowRun


def _cached_details(signature: str) -> dict:
    return {"risk_audit_bound": True, "risk_audit_validator_signature": signature,
            "node_risk_audit": {"findings": []}}


def test_changed_validator_reruns_audit_and_refuses_current_blocker(tmp_path, monkeypatch):
    run = WorkflowRun(project_path=str(tmp_path), options={"run_experiment": False})
    signature = WorkflowEngine._risk_audit_validator_signature(run.options)
    audit = AcceptedPhaseAudit({}, {}, {"ppt"})
    calls = []

    def inspect(project, node, options, *, persist):
        calls.append((project, node, options, persist))
        return {"findings": [{"severity": "blocker", "message": "Current required figure is stale"}]}

    monkeypatch.setattr(node_risk_audit_service, "audit_node", inspect)
    issues = _risk_cache_issues(run, "ppt", _cached_details("old-validator"), signature, audit)
    assert issues == ["Current required figure is stale"]
    assert calls == [(str(tmp_path), "ppt", run.options, False)]
    assert audit.risk_refreshes == {}


def test_changed_validator_refreshes_details_only_after_current_audit_pass(tmp_path, monkeypatch):
    run = WorkflowRun(project_path=str(tmp_path), options={"run_experiment": False})
    signature = WorkflowEngine._risk_audit_validator_signature(run.options)
    audit = AcceptedPhaseAudit({}, {}, {"ppt"})
    calls = []
    report = {"findings": [], "actual_inspection": "current contract"}

    def inspect(project, node, options, *, persist):
        calls.append((project, node, options, persist))
        return report

    monkeypatch.setattr(node_risk_audit_service, "audit_node", inspect)
    assert _risk_cache_issues(run, "ppt", _cached_details("old-validator"), signature, audit) == []
    assert len(calls) == 1 and calls[0][-1] is False
    assert audit.risk_refreshes == {"ppt": {
        "node_risk_audit": report, "risk_audit_validator_signature": signature,
    }}
    assert audit.accepted == {"ppt"} and audit.issues == {}


def test_current_validator_cache_reuses_unchanged_audit_without_reinspection(tmp_path, monkeypatch):
    run = WorkflowRun(project_path=str(tmp_path), options={"run_experiment": False})
    signature = WorkflowEngine._risk_audit_validator_signature(run.options)
    audit = AcceptedPhaseAudit({}, {}, {"ppt"})

    def unexpected(*_args, **_kwargs):
        raise AssertionError("Unchanged, hash-bound risk cache should be reused")

    monkeypatch.setattr(node_risk_audit_service, "audit_node", unexpected)
    assert _risk_cache_issues(run, "ppt", _cached_details(signature), signature, audit) == []
    assert audit.risk_refreshes == {}


@pytest.mark.parametrize("module", [
    "paper_asset_author_ownership.py", "paper_plot_semantics_projection.py",
    "simulation_calibration_table.py", "simulation_table_publication_refresh.py", "paper_prose_references.py",
    "retained_table_input_closure.py",
    "paper_presentation_caption.py",
    "paper_figurespec_source.py", "paper_figurespec_typography.py",
])
def test_new_publication_producer_dependencies_reopen_preparation_and_risk_cache(module, monkeypatch):
    from server.services.paper_preparation_sources import paper_preparation_implementation_paths
    from server.services.risk_validator_sources import risk_validator_source_paths
    from server.utils.runtime_source_root import server_source_root

    services = server_source_root() / "services"
    dependency = services / module
    assert dependency.is_file()
    assert dependency in paper_preparation_implementation_paths(services)
    assert dependency in risk_validator_source_paths(services)
    previous = WorkflowEngine._risk_audit_validator_signature({"run_experiment": False})
    read_bytes = Path.read_bytes

    def changed_source(path):
        content = read_bytes(path)
        return content + b"\n# Pure fixture dependency change" if path == dependency else content

    monkeypatch.setattr(Path, "read_bytes", changed_source)
    assert WorkflowEngine._risk_audit_validator_signature({"run_experiment": False}) != previous
