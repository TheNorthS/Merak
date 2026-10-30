"""Cache, recovery launch and acceptance delivery contracts using disposable sources."""
import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from server.services.paper_plan import paper_plan_service
from server.services import paper_plan_evidence
from server.services.workflow_recovery import WorkflowRecoveryWatchdog
from server.tests.test_workflow_recovery import FakeWorkflowEngine, write_run
from server.tests.test_paper_plan_and_event_journal import _seed_contracts
from server.workflows.run_state import RunState
from server.workflows.acceptance_manifest import acceptance_details, deliver_acceptance_manifests
from server.workflows.engine import WorkflowEngine
from server.workflows.models import WorkflowRun


@pytest.mark.parametrize("mutation", ["input", "output", "missing-proof"])
def test_plan_hash_mismatch_never_falls_back_to_timestamps(tmp_path, mutation):
    _seed_contracts(tmp_path)
    paper_plan_service.ensure(tmp_path, "fixture")
    assert paper_plan_service.is_current(tmp_path)
    target = tmp_path / ("NARRATIVE_REPORT.md" if mutation == "input" else "paper/PAPER_PLAN.md")
    before = target.stat()
    if mutation == "missing-proof":
        (tmp_path / ".merak/PAPER_PLAN_BUILD.json").unlink()
    else:
        target.write_text(target.read_text(encoding="utf-8") + "\nChanged scientific statement", encoding="utf-8")
        os.utime(target, (before.st_atime, before.st_mtime))
    assert paper_plan_service.is_current(tmp_path) is False


def test_verified_results_do_not_require_future_asset_plan(tmp_path, monkeypatch):
    _seed_contracts(tmp_path)
    manifest = tmp_path / "experiments/results/simulated/SIMULATION_MANIFEST.json"
    manifest.parent.mkdir()
    manifest.write_text('{}')
    verified = []
    monkeypatch.setattr(paper_plan_evidence, "_current_bundle", lambda root: verified.append(root) or {})
    paper_plan_service.ensure(tmp_path, "fixture")
    content = (tmp_path / "paper/PAPER_PLAN.md").read_text(encoding="utf-8")
    assert "**Evidence mode:** synthetic_benchmark" in content and "benchmark-supported" in content
    assert verified and not (tmp_path / "figures/SCIENTIFIC_ASSET_PLAN.json").exists()
    monkeypatch.setattr(paper_plan_evidence, "_current_bundle", lambda root: (_ for _ in ()).throw(ValueError("hash mismatch")))
    with pytest.raises(ValueError, match="hash mismatch"):
        paper_plan_service.is_current(tmp_path)


def test_failed_delegate_records_input_identity_and_manual_recovery(tmp_path):
    paper_plan_evidence.record_delegate_failure(tmp_path, "run-a", "hash-a", "timeout")
    receipt = json.loads((tmp_path / ".merak/PAPER_PLAN_DELEGATE.json").read_text())
    assert receipt["run_id"] == "run-a" and receipt["input_sha256"] == "hash-a"
    assert receipt["manual_resume_required"] is True and "fallback_owner" not in receipt


@pytest.mark.asyncio
async def test_real_delegate_failure_refreshes_changed_plan_without_repeating_model(tmp_path, monkeypatch):
    from server.services.skill_orchestrator import skill_orchestrator
    from server.workflows.models import WorkflowNode
    _seed_contracts(tmp_path)
    engine = WorkflowEngine()
    engine._emit = AsyncMock()
    engine._skill_invocation_traces = lambda *args: []
    invocation = AsyncMock(side_effect=TimeoutError("fixture timeout"))
    monkeypatch.setattr("server.agent.tools.invoke_skill", invocation)
    model_events, runtime_events = [], []
    monkeypatch.setattr(skill_orchestrator, "mark_execution", lambda *args, **kwargs: model_events.append(args[4]))
    monkeypatch.setattr(skill_orchestrator, "mark_runtime_execution", lambda *args, **kwargs: runtime_events.append(args[4]))
    run = WorkflowRun(id="delegate-budget", project_path=str(tmp_path))
    node = WorkflowNode("narrative", "Narrative", "/research-refine")
    async def execute():
        await engine._execute_stage_delegates(node=node, run=run, direction="fixture", effort="balanced", assurance="draft", opts={})
    with pytest.raises(TimeoutError):
        await execute()
    assert not (tmp_path / "paper/PAPER_PLAN.md").exists()
    with pytest.raises(TimeoutError):
        await execute()  # A manual retry is permitted without changing scientific inputs.
    assert invocation.await_count == 2
    assert model_events == ["running", "failed", "running", "failed"]
    assert runtime_events == []



@pytest.mark.asyncio
async def test_failed_resume_launch_consumes_persistent_budget_across_watchdog_restart(tmp_path, monkeypatch):
    revision = {"intervention_kind": "platform_repair", "requires_human_decision": False,
                "transport_exhausted": True, "transport_retry_count": 0,
                "max_transport_checkpoint_retries": 2, "next_retry_at": 0}
    project = tmp_path / "project"
    write_run(project, run_id="bounded", revision=revision)
    attempts = 0
    for iteration in range(5):
        monkeypatch.setattr("server.services.workflow_recovery_scan.time.time", lambda: 1000000 + iteration * 120)
        watchdog = WorkflowRecoveryWatchdog(registry_path=tmp_path / f"registry{iteration}.json")
        watchdog.observe_project(project)
        engine = FakeWorkflowEngine(fail_resume=True)
        await watchdog.scan_once(engine)
        attempts += len(engine.resumed)
    assert attempts == 0
    state = json.loads((project / ".merak/runs/bounded.json").read_text())
    assert "recovery_launch" not in state["phases"]["results"]["details"]


def test_manifest_failure_preserves_acceptance_and_replays_idempotently(tmp_path):
    run = WorkflowRun(id="delivery", project_path=str(tmp_path))
    state = RunState(tmp_path, run.id)
    state.start([{"id": "narrative"}], {})
    state.set_status("narrative", "done")
    gate = {"verdict_id": "fixture:accepted", "summary": "accepted output"}
    state.accept("narrative", gate["verdict_id"], "fixture", acceptance_details(gate, "narrative"))
    def broken(*args): raise OSError("file locked")
    assert deliver_acceptance_manifests(SimpleNamespace(_append_manifest=broken), run)
    assert state.load()["phases"]["narrative"]["status"] == "accepted"
    engine = WorkflowEngine()
    assert deliver_acceptance_manifests(engine, run) == []
    engine._append_manifest(run.project_path, run.id, "narrative", gate["verdict_id"], "accepted", gate["summary"])
    assert (tmp_path / "MANIFEST.md").read_text().count("fixture:accepted") == 1


@pytest.mark.asyncio
async def test_completed_run_replays_manifest_on_scan_without_restarting_workflow(tmp_path):
    run = WorkflowRun(id="finished", project_path=str(tmp_path))
    state = RunState(tmp_path, run.id)
    state.start([{"id": "narrative"}], {})
    state.set_status("narrative", "done")
    state.accept("narrative", "fixture:done", "fixture", acceptance_details({"verdict_id": "fixture:done"}, "narrative"))
    state.complete({"execution_completed": True})
    engine = FakeWorkflowEngine()
    engine._append_manifest = WorkflowEngine()._append_manifest
    watchdog = WorkflowRecoveryWatchdog(registry_path=tmp_path / "registry.json")
    watchdog.observe_project(tmp_path)
    assert await watchdog.scan_once(engine) == []
    assert not engine.resumed
    assert "fixture:done" in (tmp_path / "MANIFEST.md").read_text()


def test_risk_order_uses_shared_dag_and_does_not_audit_future_figure(tmp_path):
    from server.contracts.workflow_nodes import WORKFLOW_NODES
    from server.services.risk_audit_coordinator import NODE_ORDER, audit_workflow
    assert list(NODE_ORDER) == [node["id"] for node in WORKFLOW_NODES]
    from server.services.risk_constants import PROTECTED_UPSTREAM
    assert "narrative" in PROTECTED_UPSTREAM["figure"]
    assert "figure" not in PROTECTED_UPSTREAM["narrative"]
    observed = []
    def audit(root, node_id, options, persist):
        observed.append(node_id)
        return {"counts": {}, "findings": [], "status": "clear"}
    result = audit_workflow(SimpleNamespace(audit_node=audit), tmp_path, through_node="narrative", persist=False)
    assert "figure" not in observed and result["nodes"]["figure"]["status"] == "not_started"
