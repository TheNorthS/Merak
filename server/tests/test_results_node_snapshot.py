"""Pure results-node verification keeps source specialist evidence immutable."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.verify_figure_snapshot import SnapshotEngine
from scripts.verify_results_node_snapshot import (
    original_project_changes, original_runtime_mismatch, relocate_specialist_plan, validate_current_node,
)
from server.services.research_specialists import research_specialist_service
from server.services.skill_orchestrator import skill_orchestrator
from server.workflows.models import WorkflowRun
from server.workflows.run_execution_context import RunExecutionContext
from server.workflows.run_execution_node import run_planned_results
from server.workflows.run_state import RunState


def _json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf8")


def test_original_runtime_baseline_records_the_actual_106_mismatch(tmp_path):
    source_id = "original-results-run"
    path = tmp_path / f".merak/runs/{source_id}.skills.json"
    _json(path, {"run_id": source_id, "stages": {"results": {
        "runtime_service": "planned_results_analysis", "runtime_invocations": [
            {"runtime_service": "deterministic_benchmark_analysis", "status": "completed",
             "operation_id": "original-fixture-runtime", "run_id": source_id},
        ],
    }}})
    before = path.read_bytes()
    report = original_runtime_mismatch(tmp_path, source_id)
    assert report == {"declared_runtime": "planned_results_analysis",
                      "completed_runtime_services": ["deterministic_benchmark_analysis"],
                      "declared_runtime_verified": False}
    assert path.read_bytes() == before


def test_original_project_guard_detects_modified_added_and_removed_files():
    before = {"original.md": "same", "changed.md": "before", "removed.md": "old"}
    after = {"original.md": "same", "changed.md": "after", "new-invocation.json": "new"}
    assert original_project_changes(before, after) == {
        "original_project_unchanged": False,
        "original_changed_files": ["changed.md"], "original_added_files": ["new-invocation.json"],
        "original_removed_files": ["removed.md"],
    }
    assert original_project_changes(before, before)["original_project_unchanged"]


def test_specialist_snapshot_relocates_only_new_plan_not_original_invocation(tmp_path):
    original = tmp_path / "original"
    copied = tmp_path / "copied"
    source_id, new_id = "source-run", "new-verification"
    relative = ".merak/skill-invocations/fixture_domain-validation.json"
    trace = {"run_id": source_id, "status": "completed", "policy_loaded": True,
             "session_id": "source-model-fixture", "skill": "domain-validation",
             "skill_sha256": "fixture-policy-sha", "skill_bytes": 40}
    _json(original / relative, trace)
    _json(copied / relative, trace)
    artifact = copied / "experiments/specialists/DOMAIN_VALIDATION.md"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("# Evidence limitations\n" + "Registered source evidence remains unchanged. " * 30)
    plan = {"run_id": source_id, "subnodes": [{"id": "domain-validation", "node_id": "results",
            "skill": "domain-validation", "session_id": trace["session_id"], "status": "completed",
            "artifact": artifact.relative_to(copied).as_posix(), "artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            "required_headings": ["Evidence limitations"], "invocation_trace": str(original / relative)}]}
    source_path = copied / f".merak/runs/{source_id}.specialists.json"
    _json(source_path, plan)
    before = {path: path.read_bytes() for path in (source_path, copied / relative)}
    report = relocate_specialist_plan(copied, original, source_id, new_id)
    assert report["metadata_relocated_for_snapshot"] and not report["new_model_session_claimed"]
    gate = research_specialist_service.gate_node(copied, new_id, "results")
    assert gate["accepted"] and gate["applicable"]
    assert all(path.read_bytes() == value for path, value in before.items())
    changed = json.loads((copied / f".merak/runs/{new_id}.specialists.json").read_text())
    assert changed["subnodes"][0]["session_id"] == trace["session_id"]
    assert json.loads((copied / relative).read_text())["run_id"] == source_id


@pytest.mark.asyncio
async def test_actual_results_runtime_never_grants_acceptance_to_missing_upstream_artifacts(tmp_path):
    host = SnapshotEngine()
    run = WorkflowRun(id="fixture-results-fullgate", project_path=str(tmp_path), nodes=host._get_default_nodes(),
                      options={"run_experiment": False, "non_experiment_evidence_mode": "design_only"})
    node = next(node for node in run.nodes if node.id == "results")
    _json(tmp_path / "ideas/SELECTED_IDEA.json", {"schema": 2, "title": "Declared fixture question", "claims": [{"id": "C1"}]})
    _json(tmp_path / "experiments/METHOD_CONTRACT.json", {"schema": 2, "claim_evidence_plan": []})
    state = RunState(str(tmp_path), run.id)
    state.start([{"id": "results", "name": "Results", "skill": node.skill}], {"options": run.options})
    execution = RunExecutionContext(host, run, "Fixture direction", "balanced", "draft", run.options,
                                    run_state=state, node=node)
    await run_planned_results(execution)
    self_gate = skill_orchestrator.execution_gate(str(tmp_path), run.id, "results")
    assert self_gate["accepted"] and self_gate["runtime_services_executed"] == ["planned_results_analysis"]
    _json(tmp_path / f".merak/runs/{run.id}.specialists.json", {"subnodes": [{
        "id": "domain-validation", "node_id": "results", "status": "pending", "artifact": "missing.md",
    }]})
    gate = await validate_current_node(host, run, {"direction": "Fixture direction", "assurance": "draft"}, execution)
    assert not gate["accepted"]
    assert state.load()["phases"]["results"]["status"] != "accepted"
    assert (tmp_path / "experiments/results/analysis.md").is_file()
