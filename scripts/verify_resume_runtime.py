"""Exercise every resume fingerprint in the frozen backend without executing a workflow."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from server.services.figure_delegate_budget import figure_producer_code_sha256
from server.workflows.engine import workflow_engine


def main() -> None:
    project = Path.cwd() / "resume-fingerprint-fixture"
    project.mkdir(exist_ok=True)
    producer = figure_producer_code_sha256()
    assert len(producer) == 64
    from server.workflows.review_policy_fingerprint import review_policy_fingerprint
    from server.workflows.review_audit import audit_runtime_attestation
    policy = review_policy_fingerprint(SimpleNamespace(difficulty="hard", delivery_goal="reviewable_draft",
        evidence_mode="synthetic_preview", researcher_feedback=""))
    audit = audit_runtime_attestation()
    assert len(policy) == 64 and audit["components"]
    assert all(len(value) == 64 and value != "missing" for value in audit["components"].values())
    nodes = ("lit", "idea", "novelty", "exp-design", "exp-run", "results", "narrative",
             "figure", "paper", "review", "audit", "compile", "ppt")
    signatures = {}
    for node in nodes:
        signature = workflow_engine._revision_artifact_signature(str(project), node, {})
        assert signature.startswith("revision:") and len(signature) == 33, node
        assert signature == workflow_engine._revision_artifact_signature(str(project), node, {}), node
        signatures[node] = signature
    receipt = {"accepted": True, "figure_producer_sha256": producer,
               "review_policy_sha256": policy, "audit_runtime_signature": audit["signature"],
               "nodes_checked": list(signatures), "model_calls": 0, "workflow_runs": 0}
    Path("resume-smoke.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
