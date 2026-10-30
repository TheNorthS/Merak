"""Resume updates only an accepted runtime-owned analysis, never its frozen evidence."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from server.workflows.models import WorkflowRun, WorkflowNode
from server.workflows.result_resume_refresh import refresh_accepted_benchmark_analysis


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,executed,status,expected", [
    ("synthetic_preview", False, "accepted", 1), ("synthetic_preview", True, "accepted", 0),
    ("existing_results", False, "accepted", 0), ("synthetic_preview", False, "pending", 0),
])
async def test_resume_reprojects_only_the_authorized_analysis(tmp_path, monkeypatch, mode, executed, status, expected):
    manifest = tmp_path / "experiments/results/simulated/SIMULATION_MANIFEST.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("frozen evidence fixture")
    operation = AsyncMock()
    monkeypatch.setattr("server.workflows.results_runtime_execution.execute_results_runtime", operation)
    host = SimpleNamespace(_get_default_nodes=lambda: [WorkflowNode("results", "Results", "/analysis")])
    run = WorkflowRun(project_path=str(tmp_path), options={"run_experiment": executed, "non_experiment_evidence_mode": mode})
    await refresh_accepted_benchmark_analysis(host, run, {"phases": {"results": {"status": status}}}, "fixture")
    assert operation.await_count == expected
    assert manifest.read_text() == "frozen evidence fixture"
