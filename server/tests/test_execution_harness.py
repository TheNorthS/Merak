"""Fault injection for real harness boundaries, without models or scientific execution."""
import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from server.agent.execution_harness import ExecutionAttempt, attempt_directory, record_independent_review


def begin(root, run_id="run"):
    (root / "source.py").write_text("value = 1\n")
    return ExecutionAttempt(root, run_id, {"node_id": "owner", "targets": ["source.py"], "findings": ["defect-1"]})


def read(attempt):
    return json.loads(attempt.path.read_text(encoding="utf-8"))


def test_static_success_and_output_claim_never_resolve_an_independent_defect(tmp_path):
    attempt = begin(tmp_path)
    assert read(attempt)["status"] == "running"
    attempt.finish({"passed": True}, "All issues fixed", "snapshot")
    record = read(attempt)
    assert record["status"] == "awaiting_review" and record["changed_targets"] == []
    assert record["contract"]["findings"] == ["defect-1"]
    record_independent_review(tmp_path, "run", "owner", "snapshot", {"findings": [{"id": "defect-1"}]}, blocking=True)
    assert read(attempt)["status"] == "review_blocked"


def test_review_cannot_accept_stale_snapshot_or_another_run(tmp_path):
    first = begin(tmp_path)
    first.finish({"passed": True}, "", "old")
    second = begin(tmp_path, "other")
    second.finish({"passed": True}, "", "new")
    record_independent_review(tmp_path, "run", "owner", "new", {"findings": []}, blocking=False)
    assert read(first)["status"] == "superseded"
    assert read(second)["status"] == "awaiting_review"
    record_independent_review(tmp_path, "other", "owner", "new", {"findings": []}, blocking=False)
    assert read(second)["status"] == "review_passed"


def test_failed_validation_cannot_be_promoted_by_later_review(tmp_path):
    attempt = begin(tmp_path)
    (tmp_path / "source.py").write_text("invalid syntax!")
    attempt.finish({"passed": False, "issues": ["syntax"]}, "fixed", "snapshot")
    assert read(attempt)["changed_targets"] == ["source.py"]
    record_independent_review(tmp_path, "run", "owner", "snapshot", {}, blocking=False)
    assert read(attempt)["status"] == "validation_failed"


def test_interruption_is_durable_and_does_not_leak_exception_secrets(tmp_path):
    attempt = begin(tmp_path)
    attempt.interrupt(RuntimeError("token=SECRET"))
    assert read(attempt)["outcome_requires_reconciliation"]
    assert "SECRET" not in attempt.path.read_text()
    record_independent_review(tmp_path, "run", "owner", "snapshot", {}, blocking=False)
    assert read(attempt)["status"] == "interrupted"


@pytest.mark.parametrize("target", ["../outside.py", ".merak/../../outside.py", "C:/outside.py"])
def test_contract_rejects_escaped_targets_before_recording(tmp_path, target):
    with pytest.raises(ValueError):
        ExecutionAttempt(tmp_path, "run", {"node_id": "owner", "targets": [target]})
    assert not list(tmp_path.rglob("*.json"))


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["begin", "finish", "cancel", "review_changed", "none"])
async def test_production_coordinator_cannot_accept_failed_harness_boundary(tmp_path, monkeypatch, failure):
    import server.agent.execution_harness as harness
    from server.tests.test_implementation_owner_reconciliation import _context
    from server.workflows.implementation_model_invocation import StageModelInvocation
    from server.workflows.implementation_reconciliation import prepare_stage
    from server.workflows.staged_implementation_coordinator import StagedImplementationCoordinator
    from server.services.implementation_review_receipt import persist_review

    context = _context(tmp_path)
    events, calls = [], []
    async def emit(_run, kind, data):
        events.append(kind)
    context = replace(context, host=SimpleNamespace(_emit=emit))
    state = prepare_stage(context, context.stages[0])
    save = harness.atomic_write_json
    def fault(path, payload):
        if failure == "begin" or (failure == "finish" and payload["status"] == "awaiting_review"):
            raise OSError("injected storage failure")
        save(path, payload)
    monkeypatch.setattr(harness, "atomic_write_json", fault)
    async def invoke(invocation):
        calls.append(invocation.prepared_input_fingerprint)
        assert invocation.prepared_arguments
        if failure == "cancel":
            raise asyncio.CancelledError()
        if failure == "review_changed":
            persist_review(tmp_path, "new-review", {"findings": []})
        return "Existing fixture implementation checked"
    monkeypatch.setattr(StageModelInvocation, "run", invoke)
    monkeypatch.setattr(StageModelInvocation, "mark", lambda *args, **kwargs: None)
    coordinator = StagedImplementationCoordinator(context.host, context.run, context.direction)
    if failure == "none":
        await coordinator._attempts(context, state)
        assert "implementation_stage_accepted" in events
    else:
        expected = asyncio.CancelledError if failure == "cancel" else RuntimeError if failure == "review_changed" else OSError
        with pytest.raises(expected):
            await coordinator._attempts(context, state)
        assert "implementation_stage_accepted" not in events
        assert not context.service.load_build(tmp_path).get("stages", {}).get(state.stage.id)
    assert len(calls) == (0 if failure == "begin" else 1)
    records = [json.loads(path.read_text()) for path in attempt_directory(tmp_path, context.run.id).glob("*.json")]
    assert len(records) == (0 if failure == "begin" else 1)
    if records:
        assert records[0]["status"] == ("awaiting_review" if failure == "none" else "interrupted")


def test_changed_review_changes_actual_model_resume_identity(tmp_path):
    from server.tests.test_implementation_owner_reconciliation import _context
    from server.workflows.implementation_model_invocation import StageModelInvocation
    from server.workflows.implementation_reconciliation import prepare_stage
    from server.services.implementation_review_receipt import persist_review
    context = _context(tmp_path)
    stage = context.stages[0]
    before = StageModelInvocation(context, prepare_stage(context, stage), 1).resume_fingerprint()
    persist_review(tmp_path, "reviewed", {"findings": [{"id": "defect", "severity": "blocker",
        "target_files": list(stage.targets), "message": "Repair lineage"}]})
    after = StageModelInvocation(context, prepare_stage(context, stage), 1).resume_fingerprint()
    assert before != after


@pytest.mark.asyncio
async def test_unchanged_source_rebuttal_gets_one_independent_review_not_cached_failure(tmp_path):
    from unittest.mock import AsyncMock
    from server.services.implementation_review_receipt import persist_review, review_source_hash
    from server.workflows.design_review import ensure_design_review
    from server.workflows.engine import WorkflowEngine
    from server.workflows.models import WorkflowRun

    run = WorkflowRun(id="rebuttal", project_path=str(tmp_path))
    previous = {"blocking": True, "findings": [{"id": "defect-1", "severity": "blocker",
        "scope": "implementation_correctness", "target_files": ["source.py"], "message": "Claimed defect"}]}
    attempt = ExecutionAttempt(tmp_path, run.id, {"node_id": "exp-design", "targets": ["source.py"], "findings": ["defect-1"]})
    snapshot = review_source_hash(tmp_path)
    persist_review(tmp_path, snapshot, previous)
    attempt.finish({"passed": True}, "Disputed defect with source evidence", snapshot)
    response = json.dumps({"verdict": "PASS", "summary": "Original claim disproven", "findings": [],
        "resolved_findings": [{"id": "defect-1", "evidence": ["Current source contract disproves the original assumption"]}]})
    host = SimpleNamespace(_emit=AsyncMock(), _run_code_review=AsyncMock(return_value=response),
        _parse_training_check_result=WorkflowEngine()._parse_training_check_result, _persist_training_check=lambda *args: None)
    await ensure_design_review(host, run, "research", {}, "draft")
    assert read(attempt)["status"] == "review_passed"
    await ensure_design_review(host, run, "research", {}, "draft")
    assert host._run_code_review.await_count == 1
