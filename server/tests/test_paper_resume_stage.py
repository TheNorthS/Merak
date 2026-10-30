"""Unfinished papers resume durable sections before their complete-manuscript gate."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from server.workflows.models import WorkflowRun, WorkflowNode
from server.workflows.run_execution_node import run_primary_execution


@pytest.mark.asyncio
@pytest.mark.parametrize("interrupted,stage_status,blocked,expected", [
    (True, "running", False, True), (False, "running", False, True),
    (False, "pending", False, True), (True, "completed", False, False),
    (True, "running", True, False), (False, "revision_required", False, False),
])
async def test_primary_revalidation_resumes_incomplete_sections(tmp_path, interrupted, stage_status, blocked, expected):
    state = tmp_path / "paper/DRAFT_STATE.json"
    state.parent.mkdir()
    state.write_text(json.dumps({"schema_version": 3, "stages": {
        "introduction": {"status": "completed"}, "method": {"status": stage_status}}}))
    host = SimpleNamespace(_execute_staged_paper=AsyncMock(return_value="resumed"))
    context = SimpleNamespace(host=host, node=WorkflowNode("paper", "Paper", "/paper-write"),
        run=WorkflowRun(project_path=str(tmp_path)), revalidate_done=True, upstream_preflight=["blocker"] if blocked else [],
        phase_record={"details": {"interruption": {"kind": "cancelled"}} if interrupted else {}},
        research_direction="fixture", opts={}, result="")
    await run_primary_execution(context)
    assert host._execute_staged_paper.await_count == int(expected)
    assert context.result == ("resumed" if expected else "")
