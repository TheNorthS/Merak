"""An exhausted figure producer pauses the outer loop without accepting a figure."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from server.workflows.revision_gate_phases import (
    classify_stop_policy, record_no_progress_stop,
)


def _context(*, node_id: str = "figure", feedback: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        node=SimpleNamespace(id=node_id),
        revision_owner=SimpleNamespace(id=node_id),
        no_progress_count=0, no_progress_limit=2,
        pending_feedback=feedback,
        diagnostics={
            "error_category": "figure_retry_deferred",
            "issues": ["The source-bound figure remains unaccepted."],
        },
        gate={},
    )


@pytest.mark.asyncio
async def test_unchanged_figure_retry_waits_after_first_defer() -> None:
    context = _context()
    await classify_stop_policy(context)
    assert context.stop_for_no_progress is True
    await record_no_progress_stop(context)
    assert context.diagnostics["reason"] == "figure producer automatic retry deferred"
    assert "remains unaccepted" in context.diagnostics["issues"][0]


@pytest.mark.asyncio
async def test_feedback_or_other_node_does_not_trigger_figure_stop() -> None:
    for context in (_context(feedback="Please repair the arrow"),
                    _context(node_id="paper")):
        await classify_stop_policy(context)
        assert context.stop_for_no_progress is False
