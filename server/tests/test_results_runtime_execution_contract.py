"""Pure proof that exact current results ownership never aliases runtime evidence."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from server.services.node_execution_contract import resolve_execution_contract
from server.services.results_execution_policy import (
    BENCHMARK_RESULTS_RUNTIME, PLANNED_RESULTS_RUNTIME, RESULTS_HYBRID_RUNTIME,
)
from server.services.skill_execution_trace import SkillExecutionTrace, trace_path
from server.services.skill_orchestrator import SkillPlan
from server.workflows.acceptance_context import AcceptanceContext
from server.workflows.acceptance_pipeline import finalize_gate
from server.workflows.models import WorkflowNode, WorkflowRun


RUN_ID = "results-proof-106"


@pytest.fixture
def trace(tmp_path: Path) -> SkillExecutionTrace:
    policy = tmp_path / "results-policy.md"
    policy.write_text("Verified fixture results author policy.", encoding="utf-8")
    return SkillExecutionTrace(SimpleNamespace(total_skills=1, get_skill=lambda _name: SimpleNamespace(file_path=str(policy))))


def _plan(root: Path, options: dict) -> SkillPlan:
    contract = resolve_execution_contract("results", options, project_path=root)
    return SkillPlan(node_id="results", primary="domain-results-analysis", execution_kind=contract.kind,
                     runtime_service=contract.runtime_service, policy_required=contract.policy_required,
                     model_execution_mode=contract.model_execution_mode,
                     execution_contract_issues=list(contract.blocking_issues))


def _completed(trace: SkillExecutionTrace, root: Path, runtime: str, *, status: str = "completed") -> None:
    trace.mark_runtime_execution(str(root), RUN_ID, "results", runtime, status, operation_id="actual-analysis-1")


def _trace_payload(root: Path) -> dict:
    return json.loads(trace_path(str(root), RUN_ID).read_text(encoding="utf-8"))


def test_reselecting_current_synthetic_declaration_preserves_actual_execution_without_faking_completion(trace, tmp_path: Path) -> None:
    trace.record(str(tmp_path), RUN_ID, _plan(tmp_path, {"run_experiment": False}))
    _completed(trace, tmp_path, BENCHMARK_RESULTS_RUNTIME)
    before = _trace_payload(tmp_path)
    assert trace.execution_gate(str(tmp_path), RUN_ID, "results")["accepted"] is False
    trace.record(str(tmp_path), RUN_ID, _plan(tmp_path, {"run_experiment": False, "non_experiment_evidence_mode": "synthetic_preview"}))
    after = _trace_payload(tmp_path)
    assert after["stages"]["results"]["runtime_invocations"] == before["stages"]["results"]["runtime_invocations"]
    gate = trace.execution_gate(str(tmp_path), RUN_ID, "results")
    assert gate["accepted"] is True
    assert gate["runtime_services_executed"] == [BENCHMARK_RESULTS_RUNTIME]
    assert gate["model_execution_verified"] is False
    assert after["unique_skills_executed"] == []


def test_reselecting_does_not_alias_a_planned_runtime_as_benchmark_execution(trace, tmp_path: Path) -> None:
    trace.record(str(tmp_path), RUN_ID, _plan(tmp_path, {}))
    _completed(trace, tmp_path, PLANNED_RESULTS_RUNTIME)
    trace.record(str(tmp_path), RUN_ID, _plan(tmp_path, {"non_experiment_evidence_mode": "synthetic_preview"}))
    assert trace.execution_gate(str(tmp_path), RUN_ID, "results")["accepted"] is False


@pytest.mark.parametrize("status", ["running", "failed", "cancelled"])
def test_current_reselection_never_borrows_previous_completed_status(trace, tmp_path: Path, status: str) -> None:
    trace.record(str(tmp_path), RUN_ID, _plan(tmp_path, {"non_experiment_evidence_mode": "synthetic_preview"}))
    _completed(trace, tmp_path, BENCHMARK_RESULTS_RUNTIME)
    _completed(trace, tmp_path, BENCHMARK_RESULTS_RUNTIME, status=status)
    trace.record(str(tmp_path), RUN_ID, _plan(tmp_path, {"non_experiment_evidence_mode": "synthetic_preview"}))
    assert trace.execution_gate(str(tmp_path), RUN_ID, "results")["runtime_execution_verified"] is False


def test_latest_wrong_runtime_blocks_even_when_an_earlier_benchmark_completed(trace, tmp_path: Path) -> None:
    trace.record(str(tmp_path), RUN_ID, _plan(tmp_path, {"non_experiment_evidence_mode": "synthetic_preview"}))
    _completed(trace, tmp_path, BENCHMARK_RESULTS_RUNTIME)
    _completed(trace, tmp_path, PLANNED_RESULTS_RUNTIME)
    assert trace.execution_gate(str(tmp_path), RUN_ID, "results")["accepted"] is False


def test_foreign_run_cannot_be_relabelled_or_reused_as_current_execution(trace, tmp_path: Path) -> None:
    trace.record(str(tmp_path), RUN_ID, _plan(tmp_path, {"non_experiment_evidence_mode": "synthetic_preview"}))
    _completed(trace, tmp_path, BENCHMARK_RESULTS_RUNTIME)
    payload = _trace_payload(tmp_path)
    payload["run_id"] = "foreign-results-run"
    trace_path(str(tmp_path), RUN_ID).write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(RuntimeError, match="identity or schema"):
        trace.record(str(tmp_path), RUN_ID, _plan(tmp_path, {"non_experiment_evidence_mode": "synthetic_preview"}))
    assert trace.execution_gate(str(tmp_path), RUN_ID, "results")["accepted"] is False


@pytest.mark.parametrize("options", [
    {"run_experiment": True}, {"run_experiment": False, "non_experiment_evidence_mode": "existing_results"},
    {"run_experiment": False, "non_experiment_evidence_mode": "secondary_analysis"},
])
def test_actual_evidence_hybrid_never_substitutes_runtime_for_model_authorship(trace, tmp_path: Path, options: dict) -> None:
    plan = _plan(tmp_path, options)
    trace.record(str(tmp_path), RUN_ID, plan)
    _completed(trace, tmp_path, RESULTS_HYBRID_RUNTIME)
    gate = trace.execution_gate(str(tmp_path), RUN_ID, "results")
    assert gate["accepted"] is False
    assert gate["runtime_execution_verified"] is True
    assert gate["requires_model"] is True
    trace.mark_execution(str(tmp_path), RUN_ID, "results", "research-lit", "completed", role="delegate",
                         session_id="unrelated-model", policy_loaded=True, execution_kind="model_owned")
    assert trace.execution_gate(str(tmp_path), RUN_ID, "results")["accepted"] is False


def _complete_context(root: Path) -> AcceptanceContext:
    node = WorkflowNode(id="results", name="Results", skill="/domain-results-analysis")
    run = WorkflowRun(id=RUN_ID, project_path=str(root), nodes=[node], status="running",
                      options={"run_experiment": False, "non_experiment_evidence_mode": "synthetic_preview"})
    return AcceptanceContext(SimpleNamespace(), node, run, "submission", "current analysis", False, options=run.options)


def test_full_finalization_requires_runtime_trace_and_preserves_a_failing_scientific_hash_gate(trace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from server.services.node_risk_audit import node_risk_audit_service
    from server.services.research_quality import research_quality_service
    from server.services.skill_orchestrator import skill_orchestrator

    monkeypatch.setattr(research_quality_service, "apply_gate", lambda gate, *_args: gate)
    monkeypatch.setattr(node_risk_audit_service, "apply_gate", lambda gate, *_args: gate)
    monkeypatch.setattr("server.workflows.research_gates.apply_research_gates", lambda gate, *_args: gate)
    monkeypatch.setattr(skill_orchestrator, "execution_gate", trace.execution_gate)
    context = _complete_context(tmp_path)
    provisional = {"accepted": True, "details": {}}
    assert finalize_gate(context, provisional)["accepted"] is False
    trace.record(str(tmp_path), RUN_ID, _plan(tmp_path, context.options))
    _completed(trace, tmp_path, BENCHMARK_RESULTS_RUNTIME)
    assert finalize_gate(context, {"accepted": True, "details": {}})["accepted"] is True
    stale = {"accepted": False, "reason": "result source hashes changed", "details": {"issues": ["RESULT-STALE-001"]}}
    result = finalize_gate(context, stale)
    assert result["accepted"] is False
    assert result["reason"] == "result source hashes changed"
    assert result["details"]["execution_evidence"]["runtime_execution_verified"] is True


def _runtime_host(trace: SkillExecutionTrace, root: Path, monkeypatch: pytest.MonkeyPatch):
    from server.workflows.engine import WorkflowEngine
    from server.services.skill_orchestrator import skill_orchestrator

    engine = WorkflowEngine()
    monkeypatch.setattr(skill_orchestrator, "execution_trace", trace)
    events = []

    async def emit(_run, event: str, payload: dict) -> None:
        events.append((event, payload))

    monkeypatch.setattr(engine, "_emit", emit)
    return engine, events


@pytest.mark.asyncio
async def test_wrapper_runs_real_planned_producer_once_and_records_actual_completion(trace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from server.workflows.results_runtime_execution import execute_results_runtime

    ideas = tmp_path / "ideas"
    experiments = tmp_path / "experiments"
    ideas.mkdir()
    experiments.mkdir()
    (ideas / "SELECTED_IDEA.json").write_text(json.dumps({"title": "Declared transfer study", "claims": [{"id": "C1"}]}), encoding="utf-8")
    (experiments / "METHOD_CONTRACT.json").write_text(json.dumps({"claim_evidence_plan": []}), encoding="utf-8")
    host, events = _runtime_host(trace, tmp_path, monkeypatch)
    calls = []
    producer = host._ensure_planned_results_analysis

    def real_producer(*args, **kwargs):
        calls.append("real-producer")
        return producer(*args, **kwargs)

    monkeypatch.setattr(host, "_ensure_planned_results_analysis", real_producer)
    node = WorkflowNode(id="results", name="Results", skill="/domain-results-analysis")
    options = {"run_experiment": False, "non_experiment_evidence_mode": "design_only"}
    run = WorkflowRun(id=RUN_ID, project_path=str(tmp_path), nodes=[node], status="running", options=options)
    output = await execute_results_runtime(host, node, run, "declared study", options)
    assert output
    assert calls == ["real-producer"]
    assert "PENDING" in (experiments / "results/analysis.md").read_text(encoding="utf-8")
    gate = trace.execution_gate(str(tmp_path), RUN_ID, "results")
    assert gate["accepted"] is True
    assert gate["runtime_services_executed"] == [PLANNED_RESULTS_RUNTIME]
    assert gate["model_execution_verified"] is False
    assert [event for event, _ in events if event.startswith("runtime_execution_")] == ["runtime_execution_started", "runtime_execution_completed"]


@pytest.mark.asyncio
async def test_wrapper_records_failed_actual_producer_not_a_false_completion(trace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from server.workflows.results_runtime_execution import execute_results_runtime

    host, events = _runtime_host(trace, tmp_path, monkeypatch)

    def failed_producer(*_args, **_kwargs):
        raise ValueError("current CSV hash mismatch")

    monkeypatch.setattr(host, "_ensure_planned_results_analysis", failed_producer)
    node = WorkflowNode(id="results", name="Results", skill="/domain-results-analysis")
    options = {"non_experiment_evidence_mode": "synthetic_preview"}
    run = WorkflowRun(id=RUN_ID, project_path=str(tmp_path), nodes=[node], status="running", options=options)
    with pytest.raises(ValueError, match="CSV hash mismatch"):
        await execute_results_runtime(host, node, run, "declared study", options)
    gate = trace.execution_gate(str(tmp_path), RUN_ID, "results")
    assert gate["accepted"] is False
    assert _trace_payload(tmp_path)["stages"]["results"]["runtime_invocations"][-1]["status"] == "failed"
    assert any(event == "runtime_execution_failed" for event, _ in events)
    assert not any(event == "runtime_execution_completed" for event, _ in events)


@pytest.mark.asyncio
async def test_wrapper_cannot_execute_pending_producer_for_existing_or_executed_evidence(trace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from server.workflows.results_runtime_execution import execute_results_runtime

    host, events = _runtime_host(trace, tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(host, "_ensure_planned_results_analysis", lambda *_args, **_kwargs: calls.append("forbidden"))
    node = WorkflowNode(id="results", name="Results", skill="/domain-results-analysis")
    for options in ({"run_experiment": True}, {"non_experiment_evidence_mode": "existing_results"},
                    {"non_experiment_evidence_mode": "secondary_analysis"}):
        run = WorkflowRun(id=RUN_ID, project_path=str(tmp_path), nodes=[node], status="running", options=options)
        with pytest.raises(ValueError):
            await execute_results_runtime(host, node, run, "declared study", options)
    assert calls == []
    assert events == []
    assert not trace_path(str(tmp_path), RUN_ID).exists()


@pytest.mark.asyncio
async def test_wrapper_rejects_options_that_disagree_with_the_producer_run_mode(trace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from server.workflows.results_runtime_execution import execute_results_runtime

    host, events = _runtime_host(trace, tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(host, "_ensure_planned_results_analysis", lambda *_args, **_kwargs: calls.append("forbidden"))
    node = WorkflowNode(id="results", name="Results", skill="/domain-results-analysis")
    run = WorkflowRun(id=RUN_ID, project_path=str(tmp_path), nodes=[node], status="running",
                      options={"non_experiment_evidence_mode": "design_only"})
    with pytest.raises(ValueError, match="disagree"):
        await execute_results_runtime(host, node, run, "declared study", {"non_experiment_evidence_mode": "synthetic_preview"})
    assert calls == events == []
    assert not trace_path(str(tmp_path), RUN_ID).exists()


def test_runtime_completion_cannot_accept_data_changed_after_analysis_binding(trace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from server.services.node_risk_audit import node_risk_audit_service

    results = tmp_path / "experiments/results"
    metrics = results / "accepted/metrics.csv"
    metrics.parent.mkdir(parents=True)
    metrics.write_text("run_id,seed,metric\nr1,1,0.5\n", encoding="utf-8")
    (results / "analysis.md").write_text("# Analysis\nClaim C1 is bounded to the accepted run with uncertainty and limitations.", encoding="utf-8")
    monkeypatch.setattr("server.services.execution_provenance.execution_provenance_service.proven_result_sources",
                        lambda _root, **_kwargs: {metrics.relative_to(tmp_path).as_posix()})
    options = {"run_experiment": True}
    node_risk_audit_service.bind_result_analysis_inputs(tmp_path, options)
    trace.record(str(tmp_path), RUN_ID, _plan(tmp_path, options))
    _completed(trace, tmp_path, RESULTS_HYBRID_RUNTIME)
    trace.mark_execution(str(tmp_path), RUN_ID, "results", "domain-results-analysis", "completed", role="primary",
                         session_id="actual-results-model", policy_loaded=True, execution_kind="hybrid")
    assert trace.execution_gate(str(tmp_path), RUN_ID, "results")["accepted"] is True
    metrics.write_text("run_id,seed,metric\nr1,1,0.9\n", encoding="utf-8")
    findings = node_risk_audit_service._audit_results(tmp_path, options)
    stale = next(item for item in findings if item["id"] == "RESULT-STALE-001")
    assert stale["freshness_basis"] == "content_hashes"
    assert "experiments/results/accepted/metrics.csv" in stale["changed_inputs"]
