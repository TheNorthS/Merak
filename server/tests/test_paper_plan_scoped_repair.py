"""Plan-only owner findings avoid unrelated scientific narrative regeneration."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from server.workflows.paper_plan_repair import repair_plan_only


@pytest.mark.asyncio
@pytest.mark.parametrize("targets,delegated", [
    (["paper/PAPER_PLAN.md"], True), (["paper\\PAPER_PLAN.md"], True),
    (["NARRATIVE_REPORT.md", "paper/PAPER_PLAN.md"], False), ([], False),
])
async def test_only_exact_plan_scope_delegates_without_primary_reexecution(targets, delegated):
    host = SimpleNamespace(_execute_stage_delegates=AsyncMock())
    node = SimpleNamespace(id="narrative")
    options = {"run_experiment": False}
    result = await repair_plan_only(host, node, object(), {"repair_scope": {"target_files": targets}},
                                   "Preserve required asset links", "fixture", "balanced", "draft", options)
    assert bool(result) is delegated
    assert host._execute_stage_delegates.await_count == int(delegated)
    if delegated:
        forwarded = host._execute_stage_delegates.call_args.kwargs["opts"]
        assert forwarded["_paper_plan_revision_instruction"] == "Preserve required asset links"
    assert options == {"run_experiment": False}
