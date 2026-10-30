"""Owner repair receipts avoid repeated work without granting independent review acceptance."""

from types import SimpleNamespace

import pytest

from server.tests.test_implementation_owner_reconciliation import _context
from server.services.implementation_review_receipt import persist_review
from server.workflows.implementation_reconciliation import prepare_stage
from server.workflows.staged_implementation_coordinator import StagedImplementationCoordinator


def _review():
    return {"verdict": "FAIL", "blocking": True, "summary": "Check data lineage", "findings": [{
        "id": "data-lineage", "severity": "blocker", "scope": "implementation_correctness",
        "message": "Verify subject identity is preserved", "target_files": ["experiments/src/data.py"],
    }]}


def test_resolved_declared_obligation_does_not_reopen_the_same_independent_finding(tmp_path, monkeypatch):
    from server.services import implementation_review_receipt as receipts
    from server.workflows.implementation_model_invocation import StageModelInvocation

    context = _context(tmp_path)
    persist_review(tmp_path, "reviewed-source-1", _review())
    stage = context.stages[0]
    remaining = ["Review data-lineage: verify identity", "IMPL-DECLARED: old readiness blocker"]
    monkeypatch.setattr(receipts, "stage_obligations", lambda *_args: list(remaining))
    state = prepare_stage(context, stage)
    invocation = StageModelInvocation(context, state, 1)
    invocation.mark = lambda *a, **k: None
    remaining.pop()  # A normal owned repair resolves its declared readiness blocker.
    state.report = context.service.validate_stage(tmp_path, stage.id, context.direction)
    assert state.report["passed"]
    coordinator = StagedImplementationCoordinator(context.host, context.run, context.direction)
    coordinator._record_result(state, 1, invocation, "Current gate passed")
    assert receipts.pending_stage_obligations(context.service, tmp_path, stage.id,
        context.direction, list(stage.targets)) == []
    assert receipts.load_review(tmp_path)["assessment"]["verdict"] == "FAIL"
    remaining.append("Review new-defect: a new obligation")
    assert receipts.pending_stage_obligations(context.service, tmp_path, stage.id,
        context.direction, list(stage.targets))


@pytest.mark.parametrize("change", ["none", "review", "input", "output"])
def test_completed_owner_attempt_is_reusable_only_for_same_review_and_artifacts(tmp_path, change):
    context = _context(tmp_path)
    persist_review(tmp_path, "reviewed-source-1", _review())
    stage = context.stages[0]
    state = prepare_stage(context, stage)
    assert any("data-lineage" in item for item in state.report["issues"])
    coordinator = StagedImplementationCoordinator(context.host, context.run, context.direction)
    from server.workflows.implementation_model_invocation import StageModelInvocation
    invocation = StageModelInvocation(context, state, 1)
    invocation.mark = lambda *args, **kwargs: None
    # This boundary is called only after a model turn and its fresh deterministic gate.
    state.report = context.service.validate_stage(tmp_path, stage.id, context.direction)
    assert state.report["passed"]
    state.summaries.append("Reviewed the current sources against the finding")
    coordinator._record_result(state, 1, invocation, state.summaries[-1])
    if change == "review":
        persist_review(tmp_path, "reviewed-source-2", _review())
    elif change in {"input", "output"}:
        path = tmp_path / ("experiments/configs/main.yaml" if change == "input" else stage.targets[0])
        path.write_text(path.read_text(encoding="utf-8") + ("\nnew_requirement: true\n" if change == "input" else "\n# Later source change\n"), encoding="utf-8")
    from server.services.implementation_review_receipt import pending_stage_obligations
    pending = pending_stage_obligations(context.service, tmp_path, stage.id, context.direction, list(stage.targets))
    assert bool(pending) == (change != "none")
    # The original independent FAIL is never removed by an owner receipt.
    from server.services.implementation_review_receipt import load_review
    assert load_review(tmp_path)["assessment"]["verdict"] == "FAIL"


@pytest.mark.asyncio
async def test_owner_receipt_does_not_bypass_independent_failed_review(tmp_path):
    from unittest.mock import AsyncMock
    from server.services.implementation_review_receipt import review_source_hash
    from server.workflows.design_review import ensure_design_review, ImplementationReviewBlocked
    from server.workflows.implementation_model_invocation import StageModelInvocation

    context = _context(tmp_path)
    persist_review(tmp_path, review_source_hash(tmp_path), _review())
    state = prepare_stage(context, context.stages[0])
    invocation = StageModelInvocation(context, state, 1)
    invocation.mark = lambda *args, **kwargs: None
    state.report = context.service.validate_stage(tmp_path, state.stage.id, context.direction)
    coordinator = StagedImplementationCoordinator(context.host, context.run, context.direction)
    coordinator._record_result(state, 1, invocation, "Reviewed")
    host = SimpleNamespace(_emit=AsyncMock(), _run_code_review=AsyncMock(side_effect=AssertionError("unchanged review must stay blocked")))
    with pytest.raises(ImplementationReviewBlocked):
        await ensure_design_review(host, context.run, context.direction, {}, "draft")
