"""Cross-owner repair timestamps must attest files written during the actual attempt."""

import hashlib
import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from server.services.paper_plan import paper_plan_service
from server.workflows.engine import WorkflowEngine
from server.workflows.models import WorkflowNode, WorkflowRun
from server.workflows.node_gate_preparation import _prepare_narrative
from server.workflows.revision_loop_context import RevisionLoopContext
from server.workflows.run_state import RunState


@pytest.mark.asyncio
async def test_upstream_narrative_repair_records_actual_authorship_before_revalidation(tmp_path, monkeypatch):
    from server.workflows import revision_attempt

    clock = [1000.0]
    monkeypatch.setattr(revision_attempt, "time", SimpleNamespace(time=lambda: clock[0]))
    host = WorkflowEngine()
    owner = WorkflowNode("narrative", "Narrative", "/domain-narrative", started_at=100)
    consumer = WorkflowNode("figure", "Figure", "/paper-figure")
    run = WorkflowRun(id="owner-clock", project_path=str(tmp_path), nodes=[owner, consumer])
    path = tmp_path / "NARRATIVE_REPORT.md"
    path.write_text("Previous accepted narrative.")
    owner.artifact_baseline = host._snapshot_node_artifacts(owner, run)
    plan = tmp_path / "paper/PAPER_PLAN.md"
    plan.parent.mkdir()
    plan.write_text("# Paper plan\nOne-sentence contribution\nClaim-evidence\nSection plan\nFigure plan\nEvidence gap\n" + "Scientific detail. " * 100)
    state = RunState(str(tmp_path), run.id)
    state.start([{"id": node.id, "name": node.name, "skill": node.skill} for node in run.nodes], {})

    async def revise(**_kwargs):
        path.write_text("Revised scientific narrative.")
        os.utime(path, (1002, 1002))
        paper_plan_service.record_existing(tmp_path)
        clock[0] = 2000.0
        return "Model repair completed"

    async def prepare(node, run, result, direction, assurance, opts):
        await _prepare_narrative(host, node, run, direction, opts)
        return result

    def gate(*_args, **_kwargs):
        receipt = tmp_path / ".merak/NARRATIVE_BUILD.json"
        assert receipt.is_file(), "The repaired narrative must have a current authorship receipt"
        assert json.loads(receipt.read_text())["output_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        return {"accepted": True, "verdict_id": "current-receipt", "reviewer": "local-fixture"}

    monkeypatch.setattr(host, "_revise_node_from_gate", revise)
    monkeypatch.setattr(host, "_prepare_node_for_gate", prepare)
    monkeypatch.setattr(host, "_acceptance_gate", gate)
    monkeypatch.setattr(host, "_changed_nonempty_node_artifacts", lambda *_args: [])
    context = RevisionLoopContext(host, consumer, run, "draft", "fixture", "balanced", {}, 3, 30, "", False, 2,
        revision_owner=owner, run_state=state, result="consumer", diagnostics={}, round_number=1, cycle=1)
    await revision_attempt._apply_revision(context)
    assert owner.started_at == 1000
    assert state.load()["phases"]["narrative"]["status"] == "accepted"


@pytest.mark.asyncio
async def test_completed_primary_receipt_survives_interrupted_plan_delegate(tmp_path, monkeypatch):
    from server.workflows.node_execution_phases import finalize_primary
    from server.services.skill_orchestrator import skill_orchestrator

    path = tmp_path / "NARRATIVE_REPORT.md"
    path.write_text("Completed, source-bounded scientific narrative.")
    node = WorkflowNode("narrative", "Narrative", "/domain-narrative")
    run = WorkflowRun(id="primary-before-delegate", project_path=str(tmp_path), nodes=[node])
    host = SimpleNamespace(_persist_search_evidence=lambda *_args: "", _emit=AsyncMock(),
                           _execute_stage_delegates=AsyncMock(side_effect=TimeoutError("plan interrupted")))
    context = SimpleNamespace(host=host, node=node, run=run, project_path=str(tmp_path), opts={},
        enabled_tools=[], search_tool_trace=[], completion_mode="normal", result="completed",
        session=SimpleNamespace(id="primary"), owner_skill_prompt="loaded",
        skill_plan=SimpleNamespace(primary="domain-narrative", execution_kind="hybrid"),
        observer=SimpleNamespace(state=SimpleNamespace(model_provider_used="fixture", model_name_used="fixture")),
        flush_agent_text=AsyncMock(), direction="fixture", effort="balanced", assurance="draft")
    monkeypatch.setattr(skill_orchestrator, "mark_execution", lambda *_args, **_kwargs: None)
    with pytest.raises(TimeoutError, match="plan interrupted"):
        await finalize_primary(context)
    receipt = json.loads((tmp_path / ".merak/NARRATIVE_BUILD.json").read_text())
    assert receipt["output_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert node.status.value != "completed"


@pytest.mark.asyncio
async def test_stale_narrative_is_repaired_before_any_downstream_plan(tmp_path):
    from server.contracts.preparation import PreparationContractError
    from server.services.scientific_narrative import scientific_narrative_service

    (tmp_path / "NARRATIVE_REPORT.md").write_text("Previously bound narrative.")
    source = tmp_path / "literature/survey.md"
    source.parent.mkdir()
    source.write_text("Previous evidence.")
    scientific_narrative_service.record_existing(tmp_path)
    source.write_text("Revised evidence changes scientific scope.")
    node = WorkflowNode("narrative", "Narrative", "/domain-narrative")
    run = WorkflowRun(project_path=str(tmp_path), nodes=[node])
    with pytest.raises(PreparationContractError, match="narrative sources changed") as raised:
        await _prepare_narrative(WorkflowEngine(), node, run, "fixture", {})
    assert raised.value.paths == ("NARRATIVE_REPORT.md",)
