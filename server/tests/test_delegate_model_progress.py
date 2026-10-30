"""Delegate status retains the bounded request clock without forwarding private payloads."""

import pytest

from server.workflows.model_progress_fields import model_progress_fields
from server.services.workflow_event_display import format_display_entry


@pytest.mark.parametrize("status", ["waiting_model", "retrying_provider"])
def test_paper_wait_and_retry_display_preserve_actual_request_budget(status):
    data = {"status": status, "elapsed": 60, "attempt": 1, "next_attempt": 2,
            "max_attempts": 2, "remaining_seconds": 180, "total_budget_seconds": 300,
            "api_key": "private-fixture", "response_body": "private-fixture"}
    forwarded = model_progress_fields(data)
    assert "api_key" not in forwarded and "response_body" not in forwarded
    result = format_display_entry("paper_stage_agent_status", {
        **forwarded, "status": status, "stage_label": "Method",
    }, lambda value, limit: str(value or "")[:limit])
    assert "本次 60s" in result["message"]
    assert "总预算剩余 180s" in result["message"]
    assert result["level"] == ("warn" if status == "retrying_provider" else "info")


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["waiting_model", "retrying_provider"])
async def test_specialist_status_retains_budget_without_private_provider_payload(tmp_path, status):
    from types import SimpleNamespace
    from server.services.specialist_execution import SpecialistExecutor

    events = []
    async def emit(kind, data):
        events.append((kind, data))
    executor = SpecialistExecutor(None, tmp_path, "run", "results", "fixture", {}, emit)
    entry = {"id": "domain-validation", "skill": "domain-validation", "name": "Domain validation", "artifact": "report.md"}
    data = {"status": status, "provider": "selected", "elapsed": 150, "attempt": 1,
        "max_attempts": 2, "next_attempt": 2, "retry_in_seconds": 2, "remaining_seconds": 148,
        "total_budget_seconds": 300, "api_key": "private", "response_body": "private"}
    await executor._event_callback(entry)(SimpleNamespace(type="status", data=data))
    kind, forwarded = events[0]
    assert kind == "specialist_node_progress" and forwarded["elapsed"] == 150
    assert forwarded["remaining_seconds"] == 148 and forwarded["max_attempts"] == 2
    assert "api_key" not in forwarded and "response_body" not in forwarded
    display = format_display_entry(kind, forwarded, lambda value, limit: str(value or "")[:limit])
    assert "本次 150s" in display["message"] and "总预算剩余 148s" in display["message"]
