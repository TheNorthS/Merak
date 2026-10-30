"""Offline positive/negative replay of 111 readiness, ownership and evidence regressions."""
import ast
import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from server.services.implementation_readiness_checks import readiness_findings, command_findings
from server.services.planning_input_identity import planning_identity
from server.services.search_evidence_snapshot import search_evidence_snapshot
from server.services.evidence_versions import create_evidence_version, version_plan, MANIFEST
from server.workflows.run_state import RunState
from server.workflows.models import WorkflowNode, WorkflowRun
from server.workflows.owner_revision_transaction import begin_owner_revision
from server.workflows.interruption_checkpoint import record_interruption


def write(root, relative, value):
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value) if not isinstance(value, str) else value, encoding="utf-8")
    return target


def test_explicit_integration_blockers_cannot_disappear_behind_implemented_status(tmp_path):
    spec = {"status": "integration_blocked_pending_read_only_entrypoint_repair", "integration_readiness": "blocked",
            "integration_blockers": [{"id": "IB2", "owner": "training", "path": "experiments/src/train.py",
                                      "description": "Aggregate entrypoint is absent"}]}
    findings = readiness_findings(tmp_path, spec)
    assert findings[0]["stage_id"] == "training"
    assert findings[0]["severity"] == "blocker" and "train.py" in str(findings[0]["target_files"])
    assert readiness_findings(tmp_path, {"integration_readiness": "ready", "integration_blockers": []}) == []
    assert readiness_findings(tmp_path, {"integration_readiness": "ready", "integration_blockers": spec["integration_blockers"]})


def test_declared_commands_are_checked_without_importing_training(tmp_path):
    write(tmp_path, "experiments/src/train.py", """
raise RuntimeError('this file must never be imported')
import argparse
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config')
    parser.add_argument('--preflight-only', action='store_true')
    return parser.parse_args()
""")
    spec = {"preflight_command": "python experiments/src/train.py --config config.yaml --preflight-only --axes dataset,montage",
            "aggregate_command": "python experiments/src/train.py --aggregate"}
    findings = command_findings(tmp_path, spec)
    assert len(findings) == 2 and "--axes" in findings[0]["message"] and "--aggregate" in findings[1]["message"]
    assert not command_findings(tmp_path, {"command": "python experiments/src/train.py --config=config.yaml"})


def test_input_identity_ignores_json_format_but_includes_run_seeds(tmp_path):
    method = write(tmp_path, "experiments/METHOD_CONTRACT.json", {"schema": 2, "status": "implemented", "updated_at": 1})
    spec = write(tmp_path, "experiments/RUN_SPEC.json", {"seeds": [13, 42, 73]})
    before = planning_identity(tmp_path)
    method.write_text('{\n "status":"implemented", "schema":2, "updated_at":99\n}', encoding="utf-8")
    assert planning_identity(tmp_path)["sha256"] == before["sha256"]
    spec.write_text('{"seeds":[11,23,37]}', encoding="utf-8")
    after = planning_identity(tmp_path)
    assert after["sha256"] != before["sha256"]
    assert after["sources"]["experiments/RUN_SPEC.json"] != before["sources"]["experiments/RUN_SPEC.json"]


def test_downstream_search_and_clock_changes_do_not_invalidate_literature(tmp_path):
    value = {"schema_version": 1, "run_id": "run", "selected_sources": ["arxiv"], "stages": {
        "lit": {"complete": True, "attempts": [{"recorded_at": 1, "calls": [{"source": "arxiv", "success": True, "args": {"query": "EEG"}, "called_at": 1}]}]}}}
    path = write(tmp_path, "literature/SEARCH_EVIDENCE.json", value)
    original = search_evidence_snapshot(path, "lit")
    value["stages"]["novelty"] = {"complete": True, "attempts": []}
    value["updated_at"] = 100
    value["stages"]["lit"]["attempts"].append(copy.deepcopy(value["stages"]["lit"]["attempts"][0]))
    write(tmp_path, "literature/SEARCH_EVIDENCE.json", value)
    assert search_evidence_snapshot(path, "lit") == original
    value["stages"]["lit"]["attempts"][0]["calls"][0]["success"] = False
    write(tmp_path, "literature/SEARCH_EVIDENCE.json", value)
    assert search_evidence_snapshot(path, "lit") != original


def test_owner_revision_revokes_acceptance_before_any_mutation_and_preserves_failure_identity(tmp_path):
    from server.workflows.engine import WorkflowEngine

    owner = WorkflowNode("exp-design", "design", "/design", session_id="owner-session")
    consumer = WorkflowNode("exp-run", "run", "/run", depends_on=["exp-design"])
    other = WorkflowNode("results", "results", "/results", depends_on=["exp-run"])
    run = WorkflowRun(id="r", project_path=str(tmp_path), nodes=[owner, consumer, other])
    state = RunState(str(tmp_path), "r")
    state.start([{"id": n.id} for n in run.nodes], {})
    for node in run.nodes:
        state.set_status(node.id, "done")
        state.accept(node.id, "old", "validator")
    host = WorkflowEngine()
    host._get_default_nodes = lambda: run.nodes
    ctx = SimpleNamespace(revision_owner=owner, node=consumer, run=run, run_state=state,
                          scope_signature="before", host=host)
    begin_owner_revision(ctx)
    saved = state.load()
    assert all(p["status"] != "accepted" and not p["verdict_id"] for p in saved["phases"].values())
    receipt = record_interruption(run, consumer, "producer failed", kind="error")
    assert receipt["consumer_node"] == "exp-run" and receipt["owner_node"] == "exp-design"
    assert receipt["session_id"] == "owner-session" and receipt["input_signature"] == "before"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["none", "generation", "validation", "publication"])
async def test_evidence_version_preserves_old_bytes_and_rolls_back(tmp_path, failure):
    options = {"non_experiment_evidence_mode": "synthetic_preview"}
    write(tmp_path, MANIFEST, {"old": True})
    original = (tmp_path / MANIFEST).read_bytes()
    plan = version_plan(tmp_path, "offline", options)
    approval = {key: plan[key] for key in ("input_sha256", "manifest_sha256")}
    async def producer(stage):
        write(stage, MANIFEST, {"new": True})
        if failure == "generation":
            raise RuntimeError("generation failed")
        return {"generated": True}
    def validate(root):
        if failure == "validation" or (failure == "publication" and root == tmp_path):
            raise ValueError("invalid evidence")
    if failure != "none":
        with pytest.raises((RuntimeError, ValueError)):
            await create_evidence_version(tmp_path, "offline", options, approval, producer=producer, validate=validate)
        assert (tmp_path / MANIFEST).read_bytes() == original
    else:
        result = await create_evidence_version(tmp_path, "offline", options, approval, producer=producer, validate=validate)
        assert (Path(result["archive"]) / "previous" / MANIFEST).read_bytes() == original
        assert json.loads((tmp_path / MANIFEST).read_text())["new"]


@pytest.mark.asyncio
async def test_stale_version_approval_never_calls_producer(tmp_path):
    write(tmp_path, MANIFEST, {})
    with pytest.raises(ValueError, match="approval"):
        await create_evidence_version(tmp_path, "", {"non_experiment_evidence_mode": "synthetic_preview"}, {},
                                      producer=AsyncMock(side_effect=AssertionError("called")), validate=lambda _: None)


@pytest.mark.asyncio
async def test_model_code_review_failure_prevents_evidence_generation(tmp_path):
    from server.workflows.design_review import ensure_design_review, ImplementationReviewBlocked
    assessment = {"verdict": "FAIL", "blocking": True, "summary": "axis missing", "findings": [
        {"id": "axis", "severity": "blocker", "scope": "implementation_correctness",
         "message": "missing axis resolution", "target_files": ["experiments/src/train.py"]}]}
    host = SimpleNamespace(_emit=AsyncMock(), _run_code_review=AsyncMock(return_value="review"),
                           _parse_training_check_result=lambda *a, **k: assessment, _persist_training_check=lambda *a: None)
    run = SimpleNamespace(project_path=str(tmp_path), options={})
    with pytest.raises(ImplementationReviewBlocked):
        await ensure_design_review(host, run, "offline", {}, "draft")
    assert not (tmp_path / MANIFEST).exists()
    from server.services.implementation_review_receipt import stage_obligations
    assert stage_obligations(tmp_path, ["experiments/src/train.py"])


def test_integration_changes_cannot_silently_rebind_upstream_stage(tmp_path):
    from server.tests.test_implementation_owner_reconciliation import _context, _accept_owners, SERVICE, DIRECTION
    from server.workflows.implementation_reconciliation import prepare_stage, _refresh_integration_dependencies
    context = _context(tmp_path)
    _accept_owners(context)
    state = prepare_stage(context, context.stages[-1])
    before = SERVICE.load_build(tmp_path)["stages"]["data"]["input_sha256"]
    path = tmp_path / "experiments/configs/main.yaml"
    path.write_text(path.read_text(encoding="utf-8") + "new_requirement: true\n", encoding="utf-8")
    result = _refresh_integration_dependencies(context, state, {"passed": True, "issues": []})
    assert not result["passed"] and "owning stage" in str(result["issues"])
    assert SERVICE.load_build(tmp_path)["stages"]["data"]["input_sha256"] == before


@pytest.mark.asyncio
async def test_publication_recovery_restores_recognized_bytes_but_never_overwrites_user_edit(tmp_path):
    from server.services.evidence_publication_recovery import recover_publications
    import hashlib
    old, new = b'{"old":true}', b'{"new":true}'
    relative = Path(MANIFEST)
    target = tmp_path / relative
    target.parent.mkdir(parents=True)
    target.write_bytes(new)
    archive = tmp_path / ".merak/evidence-versions/interrupted"
    backup = archive / "previous" / relative
    backup.parent.mkdir(parents=True)
    backup.write_bytes(old)
    receipt = {"status": "publishing", "previous": {MANIFEST: hashlib.sha256(old).hexdigest()},
               "next": {MANIFEST: hashlib.sha256(new).hexdigest()}}
    write(tmp_path, ".merak/evidence-versions/interrupted/VERSION.json", receipt)
    plan = version_plan(tmp_path, "", {"non_experiment_evidence_mode": "synthetic_preview"})
    assert plan["manifest_sha256"] == hashlib.sha256(old).hexdigest()
    assert plan["interrupted_publication"]
    with pytest.raises(ValueError, match="approval"):
        await create_evidence_version(tmp_path, "", {"non_experiment_evidence_mode": "synthetic_preview"}, {},
                                      producer=AsyncMock(side_effect=AssertionError("called")), validate=lambda _: None)
    assert target.read_bytes() == new
    recover_publications(tmp_path)
    assert target.read_bytes() == old
    write(tmp_path, ".merak/evidence-versions/interrupted/VERSION.json", receipt)
    target.write_bytes(b'user edit')
    with pytest.raises(ValueError, match="changed externally"):
        recover_publications(tmp_path)
    assert target.read_bytes() == b'user edit'


@pytest.mark.asyncio
async def test_evidence_authorization_expires_if_inputs_change_during_generation(tmp_path):
    options = {"non_experiment_evidence_mode": "synthetic_preview"}
    manifest = write(tmp_path, MANIFEST, {"old": True})
    original = manifest.read_bytes()
    spec = write(tmp_path, "experiments/RUN_SPEC.json", {"seeds": [13, 42]})
    plan = version_plan(tmp_path, "offline", options)
    approval = {key: plan[key] for key in ("input_sha256", "manifest_sha256")}
    async def producer(stage):
        write(stage, MANIFEST, {"new": True})
        spec.write_text('{"seeds":[13,42,73]}', encoding="utf-8")
        return {}
    with pytest.raises(ValueError, match="changed while"):
        await create_evidence_version(tmp_path, "offline", options, approval, producer=producer, validate=lambda _: None)
    assert manifest.read_bytes() == original


def test_evidence_producer_requires_current_review_even_for_nontraining_mode(tmp_path, monkeypatch):
    from server.workflows.evidence_producer_gate import require_evidence_producer_ready
    from server.services.implementation_review_receipt import persist_review, review_source_hash
    from server.services.experiment_implementation import experiment_implementation_service
    monkeypatch.setattr(experiment_implementation_service, "audit", lambda _: {"blocking": False})
    write(tmp_path, "experiments/METHOD_CONTRACT.json", {"status": "implemented"})
    with pytest.raises(ValueError, match="current passing"):
        require_evidence_producer_ready(str(tmp_path), {"run_experiment": False})
    persist_review(tmp_path, review_source_hash(tmp_path), {"verdict": "PASS", "blocking": False})
    require_evidence_producer_ready(str(tmp_path), {"run_experiment": False})
    write(tmp_path, "experiments/RUN_SPEC.json", {"changed": True})
    with pytest.raises(ValueError, match="current passing"):
        require_evidence_producer_ready(str(tmp_path), {"run_experiment": False})
