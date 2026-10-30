"""Isolated model stages retain operator intent and the authoritative contracts."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from server.contracts.implementation_readiness import readiness_instruction
from server.services.scheduler_authoring_contract import scheduler_authoring_instruction
from server.tests.test_implementation_owner_reconciliation import _context
from server.tests.test_experiment_implementation_build import _write_json
from server.workflows.implementation_model_invocation import StageModelInvocation
from server.workflows.implementation_reconciliation import prepare_stage
from server.workflows.run_state import RunState


@pytest.mark.asyncio
@pytest.mark.parametrize("feedback_source", ["resume", "checkpoint"])
async def test_integration_invocation_keeps_feedback_and_approved_edits(tmp_path, monkeypatch, feedback_source):
    context = _context(tmp_path)
    feedback = "Keep the approved loss definition and retain every data prerequisite."
    RunState(str(tmp_path), context.run.id).start([
        {"id": context.node.id, "name": context.node.name, "skill": context.node.skill},
    ], {"options": context.run.options})
    if feedback_source == "resume":
        from server.workflows.engine import WorkflowEngine
        from server.workflows.run_start_lifecycle import create_run
        from server.workflows.run_start_preparation import RunStartPlan

        plan = RunStartPlan(
            {}, "draft", None, {}, [context.node], context.run.id, "", "", "", feedback,
        )
        resumed, _ = create_run(WorkflowEngine(), plan, str(tmp_path), context.direction, "balanced", None)
        assert resumed.checkpoint_feedback == feedback
        # Primary/revision preparation consumes these fields before staged codegen.
        resumed.checkpoint_feedback = resumed.checkpoint_node_id = ""
        assert "resume_feedback" not in resumed.options
        context = replace(context, run=resumed)
    else:
        context.run.checkpoint_feedback = feedback
        context.run.checkpoint_node_id = context.node.id
    _write_json(tmp_path / ".merak/research-edits/approved.json", {
        "status": "applied", "path": "experiments/src/objectives.py", "created_at": 1,
        "after_sha256": "approved-hash", "affected_phases": ["exp-design"],
    })
    training = context.service.validate_stage(tmp_path, "training", context.direction)
    context.service.record_stage(tmp_path, "training", training, context.direction,
        session_summaries=["Cross-owner requirement: provenance must commit the checkpoint with the evaluation artifacts."])
    received = {}

    async def invoke(skill, arguments, **kwargs):
        received.update(skill=skill, arguments=arguments, **kwargs)
        return "reviewed"

    async def await_task(**kwargs):
        return await kwargs["task"]

    monkeypatch.setattr("server.agent.tools.invoke_skill", invoke)
    context = replace(context, host=SimpleNamespace(_await_agent_with_activity_watchdog=await_task))
    state = prepare_stage(context, next(stage for stage in context.stages if stage.id == "integration"))
    assert await StageModelInvocation(context, state, 1)._invoke() == "reviewed"
    assert readiness_instruction() in received["arguments"]
    assert scheduler_authoring_instruction() in received["arguments"]
    assert "provenance must commit the checkpoint" in received["arguments"]
    assert "not proof of correctness" in received["arguments"]
    assert feedback in received["arguments"]
    assert "User-approved research revisions" in received["arguments"]
    assert "experiments/src/objectives.py (approved sha256: approved-hash)" in received["arguments"]
    assert received["allowed_write_paths"] == state.effective_targets
    assert "experiments/METHOD_CONTRACT.json" not in received["allowed_write_paths"]


def test_operator_feedback_survives_restart_and_stays_node_scoped(tmp_path):
    from server.workflows.models import WorkflowRun
    from server.workflows.operator_feedback import current_operator_feedback, record_operator_feedback

    state = RunState(str(tmp_path), "operator-feedback")
    state.start([{"id": name, "name": name, "skill": name} for name in ("exp-design", "paper")], {})
    record_operator_feedback(state, "exp-design", "Preserve subject-disjoint validation.")
    restarted = WorkflowRun(id=state.run_id, project_path=str(tmp_path))
    assert current_operator_feedback(restarted, "exp-design") == "Preserve subject-disjoint validation."
    assert not current_operator_feedback(restarted, "paper")
    record_operator_feedback(state, "exp-design", "Use the approved revised validation protocol.")
    details = state.load()["phases"]["exp-design"]["details"]
    assert details["operator_feedback_history"][0]["text"] == "Preserve subject-disjoint validation."
    assert current_operator_feedback(restarted, "exp-design") == "Use the approved revised validation protocol."


@pytest.mark.asyncio
async def test_stage_retry_progress_preserves_request_budget_without_throttling(tmp_path):
    from server.services.workflow_event_display import format_display_entry

    events = []

    async def emit(run, kind, payload):
        events.append((kind, payload))

    host = SimpleNamespace(_emit=emit, _agent_event_counts_as_progress=lambda event: False)
    context = SimpleNamespace(host=host, run=SimpleNamespace(), root=tmp_path)
    state = SimpleNamespace(stage=SimpleNamespace(id="integration"), effective_targets=[])
    invocation = StageModelInvocation(context, state, 1)
    await invocation.progress(SimpleNamespace(type="status", data={"status": "thinking"}))
    await invocation.progress(SimpleNamespace(type="status", data={
        "status": "retrying_provider", "attempt": 1, "next_attempt": 2, "max_attempts": 2,
        "remaining_seconds": 120, "total_budget_seconds": 300, "attempt_remaining_seconds": 120, "retry_in_seconds": 3,
        "unrelated_secret": "must not enter the progress event",
    }))
    assert len(events) == 2
    kind, payload = events[-1]
    assert payload["attempt"] == 1
    assert payload["model_request"]["next_attempt"] == 2
    assert payload["model_request"]["attempt_remaining_seconds"] == 120
    assert "unrelated_secret" not in payload["model_request"]
    entry = format_display_entry(kind, payload, lambda value, limit: str(value or "")[:limit])
    assert entry["level"] == "warn"
    assert "2/2" in entry["message"] and "120s" in entry["message"]
    entry = format_display_entry(kind, {**payload, "status": "streaming_model"}, lambda value, limit: str(value or "")[:limit])
    assert "正在接收模型输出" in entry["message"] and "本次截止剩余 120s" in entry["message"]


def test_default_stage_targets_allow_review_only_after_fresh_complete_pass(tmp_path):
    from server.services.impl_stage_targets import existing_stage_review_instruction

    context = _context(tmp_path)
    report = context.service.validate_stage(tmp_path, "data", context.direction)
    assert report["passed"]
    assert "do not rewrite correct source" in existing_stage_review_instruction(tmp_path, "data", report)
    for rejected in ({**report, "passed": False}, {**report, "existing_targets": []}):
        assert "do not rewrite correct source" not in existing_stage_review_instruction(tmp_path, "data", rejected)


def test_stale_stage_still_receives_concrete_owned_blocker(tmp_path):
    import json

    context = _context(tmp_path)
    service = context.service
    stage = next(stage for stage in context.stages if stage.id == "training")
    report = service.validate_stage(tmp_path, stage.id, context.direction)
    service.record_stage(tmp_path, stage.id, report, context.direction)
    spec_path = tmp_path / "experiments/RUN_SPEC.json"
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    spec.update(integration_readiness="blocked", integration_blockers=[{
        "id": "fraction-coverage", "owner": "training", "path": "experiments/src/train.py",
        "description": "Consume every configured label fraction instead of only the first.",
    }])
    spec["data"] = {"manifest_path": "data/revised-manifest.csv"}
    _write_json(spec_path, spec)
    current = prepare_stage(context, stage)
    assert any("fingerprint is stale" in issue for issue in current.report["issues"])
    assert any("Consume every configured label fraction" in issue for issue in current.report["issues"])


def test_scheduler_prompt_uses_current_fields_and_treats_output_directory_as_opaque():
    from server.services.run_spec import SCHEDULER_COMMAND_FIELDS

    prompt = scheduler_authoring_instruction()
    assert all("{" + field + "}" in prompt for field in SCHEDULER_COMMAND_FIELDS)
    assert "{label_fraction}" not in prompt
    assert "opaque project-relative directory" in prompt
    assert "do not reconstruct it from condition/axis/seed" in prompt
    assert "integrity index does not substitute" in prompt
