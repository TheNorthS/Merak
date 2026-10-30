"""Stale audit policy is an audit operation, not a reason to mutate scientific results."""

from server.workflows.engine import WorkflowEngine
from server.workflows.models import WorkflowRun


def test_stale_audit_policy_cannot_route_provenance_keyword_to_results():
    host = WorkflowEngine()
    nodes = host._get_default_nodes()
    audit = next(node for node in nodes if node.id == "audit")
    gate = {"accepted": False, "reason": "audit bundle provenance or freshness validation failed",
        "summary": "audit layer 1 policy provenance is missing or stale",
        "details": {"issues": ["audit layer 1 policy provenance is missing or stale"]}}
    assert host._revision_owner_for_gate(audit, WorkflowRun(nodes=nodes), gate).id == "audit"
