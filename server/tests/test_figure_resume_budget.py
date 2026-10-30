"""Pure checkpoint checks for an unchanged, unaccepted figure producer."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from server.workflows.run_state import RunState
from server.workflows import resume_execution


class _ResumeHost:
    def __init__(self) -> None:
        self.artifact = "revision:unchanged"
        self.executions = 0

    def _revision_artifact_signature(self, *_args: Any) -> str:
        return self.artifact

    def _revision_runtime_signature(self, *_args: Any) -> str:
        return "runtime:unchanged"

    def _is_transport_revision_checkpoint(self, _revision: dict) -> bool:
        return False

    def _is_platform_repair_revision_checkpoint(self, _revision: dict) -> bool:
        return True

    async def execute(self, **_options: Any) -> str:
        self.executions += 1
        return "run100"


@pytest.mark.asyncio
async def test_repeated_explicit_resume_keeps_unchanged_figure_waiting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    durable = RunState(str(tmp_path), "run100")
    durable.start(
        [{"id": "figure", "name": "Figure", "skill": "/paper-figure"}],
        {"direction": "test", "options": {"run_experiment": False}},
    )
    durable.set_revision_waiting(
        "figure", round_number=1, cycle=1,
        gate={
            "reason": "figure producer automatic retry deferred",
            "error_category": "figure_retry_deferred",
            "intervention_kind": "platform_repair",
            "stopped_for_no_progress": True,
            "repair_scope": {
                "asset_ids": ["method_architecture", "core_mechanism"],
            },
        },
        artifact_signature="revision:unchanged",
        runtime_signature="runtime:unchanged",
    )

    async def revalidated(*_args: Any) -> tuple:
        return durable, durable.load(), {"run_experiment": False}, ["figure"]

    monkeypatch.setattr(resume_execution, "_revalidated_resume_state", revalidated)
    host = _ResumeHost()
    request = {
        "run_id": "run100", "project_path": str(tmp_path), "node_ids": None,
        "research_direction": "test", "effort": "balanced", "assurance": "draft",
        "pipeline_options": None, "on_event": None, "checkpoint_feedback": "",
        "resume_source": "explicit",
    }
    for _ in range(2):
        with pytest.raises(ValueError, match="恢复令牌不能重开"):
            await resume_execution.resume_persisted_run_claimed(host, **request)
        phase = durable.load()["phases"]["figure"]
        assert phase["status"] == "awaiting_revision"
        assert phase["details"]["revision"]["cycle"] == 1
    assert host.executions == 0

    request["checkpoint_feedback"] = "Please try again"
    with pytest.raises(ValueError, match="必须明确指向一张失败图"):
        await resume_execution.resume_persisted_run_claimed(host, **request)
    assert host.executions == 0

    request["checkpoint_feedback"] = "Fix method_architecture merge arrow"
    assert await resume_execution.resume_persisted_run_claimed(host, **request) == "run100"
    assert host.executions == 1

    request["checkpoint_feedback"] = ""
    host.artifact = "revision:changed"
    assert await resume_execution.resume_persisted_run_claimed(host, **request) == "run100"
    assert host.executions == 2
