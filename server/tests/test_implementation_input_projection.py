"""Diagnostic closure cannot invalidate unchanged scientific training inputs."""

import json

import pytest

from server.tests.test_implementation_owner_reconciliation import _context
from server.tests.test_experiment_implementation_build import _write_json
from server.workflows.implementation_reconciliation import prepare_stage


def test_integration_diagnostic_updates_leave_training_science_hash_stable(tmp_path):
    ctx = _context(tmp_path)
    spec_path = tmp_path / "experiments/RUN_SPEC.json"
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    before = {stage: ctx.service.input_hash(tmp_path, stage, ctx.direction) for stage in ("training", "integration")}
    spec.update(integration_readiness="ready", integration_blockers=[],
                integration_resolution=[{"id": "interface", "rationale": "Fresh owner checks passed"}])
    _write_json(spec_path, spec)
    assert ctx.service.input_hash(tmp_path, "training", ctx.direction) == before["training"]
    assert ctx.service.input_hash(tmp_path, "integration", ctx.direction) != before["integration"]


@pytest.mark.parametrize("field", [
    "current_static_review", "integration_reclassification_rationale",
    "integration_reclassification_rationale_current",
])
def test_handoff_notes_do_not_reopen_training_but_still_invalidate_review(tmp_path, field):
    from server.services.implementation_review_receipt import review_source_hash
    ctx = _context(tmp_path)
    path = tmp_path / "experiments/RUN_SPEC.json"
    spec = json.loads(path.read_text(encoding="utf-8"))
    before = ctx.service.input_hash(tmp_path, "training", ctx.direction)
    review_before = review_source_hash(tmp_path)
    spec[field] = "Owner reviewed the unchanged interface; runtime gate pending."
    _write_json(path, spec)
    assert ctx.service.input_hash(tmp_path, "training", ctx.direction) == before
    assert review_source_hash(tmp_path) != review_before


@pytest.mark.parametrize("field,value", [
    ("seeds", [73, 101]), ("command", "python experiments/src/train.py --revised"),
    ("data", {"manifest_path": "revised.csv"}), ("evaluation", {"threshold": 0.3}),
    ("execution_readiness", "blocked"), ("execution_prerequisites", [{"id": "needs-data"}]),
    ("outputs", {"per_run_files": ["new.json"]}), ("status", "blocked"),
])
def test_real_training_inputs_remain_hash_dependencies(tmp_path, field, value):
    ctx = _context(tmp_path)
    path = tmp_path / "experiments/RUN_SPEC.json"
    spec = json.loads(path.read_text(encoding="utf-8"))
    before = ctx.service.input_hash(tmp_path, "training", ctx.direction)
    spec[field] = value
    _write_json(path, spec)
    assert ctx.service.input_hash(tmp_path, "training", ctx.direction) != before


def test_new_integration_blocker_still_requires_owning_model_even_without_hash_change(tmp_path):
    ctx = _context(tmp_path)
    stage = next(stage for stage in ctx.stages if stage.id == "training")
    ctx.service.record_stage(tmp_path, stage.id, ctx.service.validate_stage(tmp_path, stage.id, ctx.direction), ctx.direction)
    path = tmp_path / "experiments/RUN_SPEC.json"
    spec = json.loads(path.read_text(encoding="utf-8"))
    spec.update(integration_readiness="blocked", integration_blockers=[{
        "id": "atomic-output", "owner": "training", "path": "experiments/src/train.py",
        "description": "Stage the checkpoint before publishing the cell.",
    }])
    _write_json(path, spec)
    state = prepare_stage(ctx, stage)
    assert not state.report["passed"]
    assert any("Stage the checkpoint" in issue for issue in state.report["issues"])
