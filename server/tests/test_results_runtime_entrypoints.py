"""Every results entrypoint preserves its owner and genuine runtime evidence."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.verify_figure_snapshot import SnapshotEngine
from server.services.skill_execution_trace import trace_path
from server.services.skill_orchestrator import skill_orchestrator
from server.workflows.models import WorkflowNode, WorkflowRun
from server.workflows.results_runtime_execution import execute_results_runtime
from server.workflows.run_execution_context import RunExecutionContext
from server.workflows.run_execution_node import prepare_node_inputs
from server.workflows.revision_execution import _results_repair
from server.workflows.node_gate_preparation import _prepare_results_and_paper


@pytest.mark.parametrize("mode", ["existing_results", "secondary_analysis"])
@pytest.mark.asyncio
async def test_imported_results_preparation_never_calls_pending_generators(tmp_path, monkeypatch, mode):
    host = SnapshotEngine()
    node = WorkflowNode(id="results", name="Results", skill="/domain-results-analysis")
    options = {"run_experiment": False, "non_experiment_evidence_mode": mode}
    run = WorkflowRun(project_path=str(tmp_path), nodes=[node], options=options)
    calls = []

    async def forbidden(*_args, **_kwargs):
        calls.append("forbidden-generator")
        pytest.fail("Imported evidence must not be replaced with planned or generated results")

    monkeypatch.setattr(host, "_ensure_planned_result_templates", forbidden)
    monkeypatch.setattr(host, "_ensure_planned_results_analysis", forbidden)
    ctx = RunExecutionContext(host, run, "Fixture", "balanced", "draft", options, node=node,
                              revalidate_done=False, upstream_preflight=[])
    await prepare_node_inputs(ctx)
    result = await _prepare_results_and_paper(host, node, run, "Verified imported analysis", "Fixture", options)
    assert result == "Verified imported analysis" and calls == []


@pytest.mark.parametrize("mode", ["design_only", "synthetic_preview"])
@pytest.mark.asyncio
async def test_results_input_preparation_cannot_generate_or_replace_source_data(tmp_path, monkeypatch, mode):
    host = SnapshotEngine()
    node = WorkflowNode(id="results", name="Results", skill="/domain-results-analysis")
    options = {"run_experiment": False, "non_experiment_evidence_mode": mode}
    run = WorkflowRun(project_path=str(tmp_path), nodes=[node], options=options)

    async def forbidden(*_args, **_kwargs):
        pytest.fail("Results must project existing evidence, not regenerate simulation or template data")

    monkeypatch.setattr(host, "_ensure_planned_result_templates", forbidden)
    ctx = RunExecutionContext(host, run, "Fixture", "balanced", "draft", options, node=node,
                              revalidate_done=False, upstream_preflight=[])
    await prepare_node_inputs(ctx)
    assert not (tmp_path / "experiments/results").exists()


@pytest.mark.asyncio
async def test_results_automatic_repair_records_actual_projection_even_when_bytes_unchanged(tmp_path):
    host = SnapshotEngine()
    node = WorkflowNode(id="results", name="Results", skill="/domain-results-analysis")
    options = {"run_experiment": False, "non_experiment_evidence_mode": "design_only"}
    run = WorkflowRun(id="fixture-results-repair", project_path=str(tmp_path), nodes=[node], options=options)
    first = await execute_results_runtime(host, node, run, "Declared design", options)
    path = tmp_path / "experiments/results/analysis.md"
    previous = path.read_bytes()
    assert await _results_repair(host, node, run, "Declared design", 1, options) == first
    assert path.read_bytes() == previous
    assert skill_orchestrator.execution_gate(str(tmp_path), run.id, "results")["accepted"]
    assert [data["changed"] for event, data in host.snapshot_events if event == "planned_results_platform_repair"] == [False]


@pytest.mark.asyncio
async def test_empty_run_policy_cannot_be_replaced_by_a_conflicting_argument(tmp_path, monkeypatch):
    host = SnapshotEngine()
    node = WorkflowNode(id="results", name="Results", skill="/domain-results-analysis")
    run = WorkflowRun(id="fixture-missing-mode", project_path=str(tmp_path), nodes=[node], options={})
    with pytest.raises(ValueError, match="immutable evidence contract"):
        await execute_results_runtime(host, node, run, "Fixture", {"non_experiment_evidence_mode": "synthetic_preview"})
    assert not trace_path(str(tmp_path), run.id).exists()
    assert not (tmp_path / "experiments/results/analysis.md").exists()


@pytest.mark.asyncio
async def test_wrong_service_override_is_rejected_before_runtime_trace(tmp_path):
    host = SnapshotEngine()
    node = WorkflowNode(id="results", name="Results", skill="/domain-results-analysis")
    options = {"non_experiment_evidence_mode": "synthetic_preview"}
    run = WorkflowRun(id="fixture-wrong-override", project_path=str(tmp_path), nodes=[node], options=options)
    with pytest.raises(ValueError, match="does not match the current execution contract"):
        await host._runtime_execution_started(node, run, options, "planned_results_analysis")
    assert not trace_path(str(tmp_path), run.id).exists() and host.snapshot_events == []
