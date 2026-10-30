"""Real child work refreshes parent activity while waiting pulses never do."""

from types import SimpleNamespace
import pytest

from server.agent.delegate_activity import delegate_observer, parent_activity_callback, run_observed_delegate
from server.workflows.engine import WorkflowEngine


@pytest.mark.asyncio
async def test_child_activity_is_forwarded_without_private_payload_or_false_parent_write():
    events = []
    async def observe(event):
        events.append(event)
    async def child():
        callback = parent_activity_callback("paper-slides")
        await callback(SimpleNamespace(type="status", data={"status": "waiting_model", "elapsed": 300}))
        await callback(SimpleNamespace(type="tool_result", data={"name": "Write", "success": True,
            "output": "private-body", "path": "private-path", "api_key": "private-key"}))
    await run_observed_delegate(child, {}, observe)
    assert len(events) == 1 and events[0].type == "step"
    assert WorkflowEngine._agent_event_counts_as_progress(events[0])
    assert "private" not in str(events[0].data)
    assert delegate_observer.get() is None


@pytest.mark.asyncio
async def test_observer_context_resets_when_child_fails():
    async def child():
        raise RuntimeError("fixture child failure")
    with pytest.raises(RuntimeError):
        await run_observed_delegate(child, {}, lambda event: None)
    assert parent_activity_callback("next") is None
