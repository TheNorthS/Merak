"""Changed integration dependencies go to their owner without another wrong-owner prompt."""

import json
import asyncio

import pytest

from server.tests.test_implementation_iteration_handoff import fixture_context
from server.tests.test_implementation_owner_reconciliation import DIRECTION, SERVICE
from server.workflows.implementation_model_invocation import StageModelInvocation
from server.workflows.staged_implementation_coordinator import StagedImplementationCoordinator


@pytest.mark.asyncio
@pytest.mark.parametrize("owner_breaks_source", [False, True])
async def test_integration_handoff_revalidates_without_reprompting_integration(tmp_path, monkeypatch, owner_breaks_source):
    context, events = fixture_context(tmp_path)
    patch_path = tmp_path / "experiments/IMPLEMENTATION_EVIDENCE_PATCH.json"
    patch = json.loads(patch_path.read_text(encoding="utf-8"))
    patch["checks"][0]["idea_mechanism_ids"] = ["M1"]
    patch_path.unlink()
    calls = []
    preserved = {path: path.read_bytes() for path in (tmp_path / "experiments/src").glob("*.py")}

    async def authored(invocation):
        stage = invocation.state.stage.id
        calls.append(stage)
        if stage == "integration":
            assert calls.count(stage) == 1, "A runtime dependency handoff must not invoke integration again"
            patch_path.write_text(json.dumps(patch), encoding="utf-8")
            spec_path = tmp_path / "experiments/RUN_SPEC.json"
            spec = json.loads(spec_path.read_text(encoding="utf-8"))
            spec["execution_readiness"] = "blocked"
            spec["execution_prerequisites"] = [{"id": "registered-mask", "owner": "data",
                "path": "experiments/configs/main.yaml", "description": "Registered masks must be supplied before training."}]
            spec_path.write_text(json.dumps(spec), encoding="utf-8")
        elif stage == "training":
            if owner_breaks_source:
                (tmp_path / "experiments/src/train.py").write_text("def main():\n    return None\n", encoding="utf-8")
        else:
            pytest.fail(f"Unchanged accepted owner must be reused: {stage}")
        return "Source reviewed against current prerequisites; no scientific execution performed."

    monkeypatch.setattr(StageModelInvocation, "run", authored)
    monkeypatch.setattr(StageModelInvocation, "mark", lambda *_args, **_kwargs: None)
    await StagedImplementationCoordinator(context.host, context.run, DIRECTION)._run_stages(context)
    assert calls[:2] == ["integration", "training"]
    assert calls.count("integration") == 1
    assert any(kind == "implementation_owner_reconciliation_started" for kind, _ in events)
    report = SERVICE.audit(tmp_path, DIRECTION)
    assert report["blocking"] is owner_breaks_source, report["issues"]
    if not owner_breaks_source:
        assert all(path.read_bytes() == before for path, before in preserved.items())
        assert all(SERVICE.can_reuse(tmp_path, stage.id, DIRECTION) for stage in context.stages)


@pytest.mark.asyncio
async def test_unresolved_scientific_blocker_cannot_be_finalized_by_owner_handoff(tmp_path, monkeypatch):
    context, _events = fixture_context(tmp_path)
    spec_path = tmp_path / "experiments/RUN_SPEC.json"
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    spec.update(integration_readiness="blocked", integration_blockers=[{
        "id": "missing-mechanism", "owner": "integration", "path": "experiments/src/test_pipeline.py",
        "description": "Required counterfactual mechanism is not implemented.",
    }])
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    calls = []

    async def no_fix(invocation):
        calls.append(invocation.state.stage.id)
        return "No implementation changes."

    monkeypatch.setattr(StageModelInvocation, "run", no_fix)
    monkeypatch.setattr(StageModelInvocation, "mark", lambda *_args, **_kwargs: None)
    await StagedImplementationCoordinator(context.host, context.run, DIRECTION)._run_stages(context)
    assert calls and set(calls) == {"integration"} and len(calls) <= 2
    assert SERVICE.audit(tmp_path, DIRECTION)["blocking"]
    assert json.loads(spec_path.read_bytes())["integration_blockers"][0]["id"] == "missing-mechanism"


@pytest.mark.asyncio
async def test_cancelled_owner_handoff_resumes_saved_integration_without_reauthoring(tmp_path, monkeypatch):
    context, _events = fixture_context(tmp_path)
    patch_path = tmp_path / "experiments/IMPLEMENTATION_EVIDENCE_PATCH.json"
    patch = json.loads(patch_path.read_bytes())
    patch["checks"][0]["idea_mechanism_ids"] = ["M1"]
    patch_path.unlink()
    calls = []
    interrupted = False

    async def authored(invocation):
        nonlocal interrupted
        stage = invocation.state.stage.id
        calls.append(stage)
        if stage == "integration":
            assert calls.count(stage) == 1
            patch_path.write_text(json.dumps(patch), encoding="utf-8")
            path = tmp_path / "experiments/RUN_SPEC.json"
            spec = json.loads(path.read_bytes())
            spec["execution_status"] = "not_executed"
            path.write_text(json.dumps(spec), encoding="utf-8")
        elif stage == "training" and not interrupted:
            interrupted = True
            raise asyncio.CancelledError()
        elif stage != "training":
            pytest.fail(f"An unaffected stage was rerun: {stage}")
        return "Reviewed existing source against the saved execution contract."

    monkeypatch.setattr(StageModelInvocation, "run", authored)
    monkeypatch.setattr(StageModelInvocation, "mark", lambda *_args, **_kwargs: None)
    with pytest.raises(asyncio.CancelledError):
        await StagedImplementationCoordinator(context.host, context.run, DIRECTION)._run_stages(context)
    saved_patch = patch_path.read_bytes()
    result = await StagedImplementationCoordinator(context.host, context.run, DIRECTION).execute()
    assert not result["blocking"], result["issues"]
    assert calls == ["integration", "training", "training"]
    assert patch_path.read_bytes() == saved_patch
