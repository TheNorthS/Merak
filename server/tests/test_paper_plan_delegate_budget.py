"""A progressing plan/review delegate uses bounded node activity, never a short fixed wall timer."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from server.workflows.engine import WorkflowEngine
from server.workflows.models import WorkflowNode, WorkflowRun


def _setup(tmp_path, monkeypatch):
    from server.services.paper_plan import paper_plan_service
    root = tmp_path
    (root / "paper").mkdir()
    engine = WorkflowEngine()
    monkeypatch.setattr(engine, "_emit", AsyncMock())
    monkeypatch.setattr(engine, "_agent_node_timeout_seconds", lambda *args, **kwargs: 0.06)
    monkeypatch.setattr(engine, "_agent_node_hard_timeout_seconds", lambda *args, **kwargs: 1.0)
    monkeypatch.setattr(paper_plan_service, "is_current", lambda *args: False)
    monkeypatch.setattr(paper_plan_service, "is_valid", lambda path: path.exists())
    monkeypatch.setattr(paper_plan_service, "record_existing", lambda *args, **kwargs: None)
    node = WorkflowNode(id="narrative", name="Narrative", skill="research-refine")
    run = WorkflowRun(id="delegate-budget", project_path=str(root), nodes=[node])
    return engine, node, run


@pytest.mark.asyncio
async def test_progressing_paper_plan_outlives_old_fixed_timer(tmp_path, monkeypatch):
    engine, node, run = _setup(tmp_path, monkeypatch)

    async def invoke(*args, **kwargs):
        for _ in range(5):
            await asyncio.sleep(0.02)
            await kwargs["on_event"](SimpleNamespace(type="tool_result", data={"name": "Read", "success": True}))
        (tmp_path / "paper/PAPER_PLAN.md").write_text("# Authored plan\n")
        return "completed"

    monkeypatch.setattr("server.agent.tools.invoke_skill", invoke)
    await engine._execute_stage_delegates(node=node, run=run, direction="fixture", effort="balanced", assurance="draft", opts={})
    assert (tmp_path / "paper/PAPER_PLAN.md").read_text() == "# Authored plan\n"


@pytest.mark.asyncio
async def test_wait_status_cannot_keep_plan_alive_and_child_is_joined(tmp_path, monkeypatch):
    engine, node, run = _setup(tmp_path, monkeypatch)
    closed = asyncio.Event()

    async def invoke(*args, **kwargs):
        try:
            while True:
                await kwargs["on_event"](SimpleNamespace(type="status", data={"status": "waiting_model"}))
                await asyncio.sleep(0.01)
        finally:
            closed.set()

    monkeypatch.setattr("server.agent.tools.invoke_skill", invoke)
    with pytest.raises(TimeoutError):
        await engine._execute_stage_delegates(node=node, run=run, direction="fixture", effort="balanced", assurance="draft", opts={})
    assert closed.is_set()
    assert not (tmp_path / "paper/PAPER_PLAN.md").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("linked", [False, True])
async def test_plan_delegate_receives_required_links_and_cannot_drop_them(tmp_path, monkeypatch, linked):
    engine, node, run = _setup(tmp_path, monkeypatch)
    (tmp_path / "figures").mkdir()
    (tmp_path / "figures/SCIENTIFIC_ASSET_PLAN.json").write_text(json.dumps({"assets": [
        {"id": "method_architecture", "label": "fig:method", "kind": "figure", "required": True},
    ]}))

    async def invoke(_skill, arguments, **kwargs):
        assert "method_architecture: fig:method" in arguments
        (tmp_path / "paper/PAPER_PLAN.md").write_text("# Plan\n" + ("Appendix: fig:method" if linked else "Generic diagram"))
        return "completed"

    monkeypatch.setattr("server.agent.tools.invoke_skill", invoke)
    operation = engine._execute_stage_delegates(node=node, run=run, direction="fixture", effort="balanced", assurance="draft", opts={})
    if linked:
        await operation
    else:
        with pytest.raises(RuntimeError, match="required figure is not referenced"):
            await operation


@pytest.mark.asyncio
async def test_existing_plan_repairs_are_edit_only_and_preserve_unaffected_text(tmp_path, monkeypatch):
    engine, node, run = _setup(tmp_path, monkeypatch)
    path = tmp_path / "paper/PAPER_PLAN.md"
    path.write_text("Accepted section\nOld evidence sentence.")

    async def invoke(_skill, arguments, **kwargs):
        assert "targeted Edit calls only" in arguments
        assert "Write" not in kwargs["allowed_tools_override"]
        assert {"Edit", "Read", "reviewer_api"} <= set(kwargs["allowed_tools_override"])
        path.write_text(path.read_text().replace("Old evidence", "Current evidence"))
        return "updated"

    monkeypatch.setattr("server.agent.tools.invoke_skill", invoke)
    await engine._execute_stage_delegates(node=node, run=run, direction="fixture", effort="balanced", assurance="draft", opts={})
    assert path.read_text() == "Accepted section\nCurrent evidence sentence."
