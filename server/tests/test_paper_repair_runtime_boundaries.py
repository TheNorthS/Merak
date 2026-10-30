"""Public presentation, scientific freshness and cancellation keep separate owners."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from server.services.paper_artifacts import simulation_manifest_semantic_hash
from server.services.paper_presentation_findings import publication_table_findings
from server.services.scientific_narrative import _semantic_source_bytes
from server.workflows.engine import WorkflowEngine
from server.workflows.models import WorkflowNode, WorkflowRun
from server.workflows.paper_repair_runtime import PAPER_RUNTIME_TARGETS, paper_refresh_required
from server.workflows.run_state import RunState


def test_table_presentation_is_paper_runtime_not_analysis_owner(tmp_path: Path) -> None:
    finding = publication_table_findings([
        "tables/synthetic_preview_results.tex exposes a generic or placeholder scientific label",
    ])[0]
    host = WorkflowEngine()
    run = WorkflowRun(id="fixture-presentation", project_path=str(tmp_path), nodes=host._get_default_nodes(),
                      options={"run_experiment": False})
    node = next(node for node in run.nodes if node.id == "paper")
    gate = {"accepted": False, "reason": "paper quality contract failed",
            "details": {"issues": [finding["message"]], "findings": [finding]}}
    diagnostics = host._gate_revision_diagnostics(gate)
    assert diagnostics["findings"][0]["owner_node"] == "paper"
    assert host._revision_owner_for_gate(node, run, gate).id == "paper"
    assert "paper/tables/synthetic_preview_results.tex" in PAPER_RUNTIME_TARGETS
    assert "experiments/results/analysis.md" not in diagnostics["repair_scope"]["target_files"]


def test_runtime_freeze_target_is_never_inferred_as_upstream_edit(tmp_path: Path) -> None:
    host = WorkflowEngine()
    run = WorkflowRun(project_path=str(tmp_path), nodes=host._get_default_nodes())
    paper = next(node for node in run.nodes if node.id == "paper")
    issue = "Authoritative paper-input hashes changed after the manuscript scientific freeze."
    finding = {"id": "PAPER-STALE-001", "severity": "blocker", "category": "freshness",
               "message": issue, "changed_inputs": ["figures/FIGURE_MANIFEST.json"],
               "target_files": ["paper/SCIENTIFIC_FREEZE.json", "experiments/results/analysis.md"]}
    gate = {"accepted": False, "details": {"findings": [finding], "issues": [issue]}}
    diagnostics = host._gate_revision_diagnostics(gate)
    assert host._revision_owner_for_gate(paper, run, gate).id == "paper"
    assert diagnostics["findings"][0]["target_files"] == ["paper/DRAFT_STATE.json", "paper/SCIENTIFIC_FREEZE.json"]
    assert diagnostics["findings"][0]["changed_inputs"] == ["figures/FIGURE_MANIFEST.json"]
    assert paper_refresh_required(diagnostics)


def test_renderer_only_table_reprojection_does_not_invalidate_narrative_science(tmp_path: Path) -> None:
    path = tmp_path / "SIMULATION_MANIFEST.json"
    science = {"schema": 11, "simulation_id": "fixed-fixture", "replicate_contract": {"seeds": [1, 2, 3]},
               "data_files": [{"path": "main.csv", "sha256": "registered-rows"}],
               "paper_table_sha256": "previous-table", "renderer_sha256": "previous-code"}
    path.write_text(json.dumps(science), encoding="utf8")
    before = _semantic_source_bytes(path)
    rendered = {**science, "paper_table_sha256": "new-public-labels", "renderer_sha256": "new-code"}
    path.write_text(json.dumps(rendered), encoding="utf8")
    assert before == _semantic_source_bytes(path)
    assert simulation_manifest_semantic_hash(science) == simulation_manifest_semantic_hash(rendered)
    changed = copy.deepcopy(rendered)
    changed["data_files"][0]["sha256"] = "different-scientific-rows"
    path.write_text(json.dumps(changed), encoding="utf8")
    assert before != _semantic_source_bytes(path)
    assert simulation_manifest_semantic_hash(science) != simulation_manifest_semantic_hash(changed)


@pytest.mark.parametrize("source", ["watchdog", "background", "platform"])
def test_queued_automatic_recovery_cannot_claim_operator_stopped_run(tmp_path: Path, source) -> None:
    state = RunState(str(tmp_path), "fixture-operator-stop")
    state.start([{"id": "paper", "name": "Paper", "skill": "/paper-write"}], {})
    state.set_run_status("cancelled")
    before = state.path.read_bytes()
    assert not state.claim_resume(owner_id="queued-worker", expected_status="cancelled", source=source)
    assert state.path.read_bytes() == before
    assert state.claim_resume(owner_id="researcher", expected_status="cancelled", source="explicit")


@pytest.mark.asyncio
async def test_nonmanual_resume_refuses_before_project_claim_or_model(tmp_path: Path) -> None:
    state = RunState(str(tmp_path), "fixture-no-auto-resume")
    state.start([{"id": "paper", "name": "Paper", "skill": "/paper-write"}], {})
    state.set_run_status("cancelled")
    with pytest.raises(ValueError, match="explicit manual continuation"):
        await WorkflowEngine().resume_persisted_run(state.run_id, str(tmp_path), resume_source="watchdog")
    assert not (tmp_path / ".merak/active-workflow.json").exists()
