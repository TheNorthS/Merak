"""Full figure-node runtime verification after actual local figure generation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.verify_figure_snapshot import SnapshotEngine
from server.services.deterministic_figure_builder import ensure_evaluation_design
from server.services.figure_artifacts import figure_artifact_registry
from server.services.figure_routing import recommend_figure_route
from server.services.figure_spec_repository import persist_figure_specs
from server.services.skill_orchestrator import skill_orchestrator
from server.services.skill_registry import SkillRegistry
from server.services.skill_execution_trace import SkillExecutionTrace
from server.workflows.models import WorkflowRun
from server.workflows.revision_gate_phases import (
    persist_gate_inputs, build_current_gate, record_runtime_gate,
    verify_runtime_execution, normalize_gate_outcome, complete_accepted_gate,
)
from server.workflows.revision_loop_context import RevisionComplete, RevisionLoopContext
from server.workflows.revision_loop_phases import initialize_progress, initialize_revision
from server.workflows.run_execution_context import RunExecutionContext
from server.workflows.run_execution_execute import persist_node_acceptance, refresh_node_audits
from server.workflows.run_state import RunState


def _json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf8")


def _method_fixture(root: Path) -> dict:
    scene = {"schema": 1, "objects": [
        {"id": "raw_inputs", "kind": "input", "label": "Observed research inputs",
         "source_path": "experiments/EXPERIMENT_PLAN.md"},
        {"id": "claim_link", "kind": "operation", "label": "Claim-to-evidence binding",
         "source_path": "ideas/SELECTED_IDEA.json"},
        {"id": "bounded_output", "kind": "output", "label": "Evidence-bounded conclusion",
         "source_path": "experiments/EXPERIMENT_PLAN.md"},
    ], "relations": [{"from": "raw_inputs", "to": "claim_link", "kind": "data"},
                     {"from": "claim_link", "to": "bounded_output", "kind": "data"}]}
    selected = {"schema": 2, "title": "Claim-linked research planning",
                "hypothesis": "Binding research claims retains evidence-bounded conclusions.",
                "publication": {"language": "en", "method_name": "Claim-linked planner",
                                "contribution_type": "system_architecture"},
                "claims": [{"id": "C1", "publication_statement": "Bind each research claim to evidence."}],
                "mechanisms": [{"id": "M1", "required": True,
                                "publication_name": "Claim-to-evidence binding",
                                "publication_description": "Bind each claim to evidence."}]}
    _json(root / "ideas/SELECTED_IDEA.json", selected)
    source = root / "experiments/EXPERIMENT_PLAN.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Matched controls for claim-to-evidence binding\n")
    asset = {
        "id": "method_architecture", "kind": "figure", "required": True,
        "scientific_role": "method", "generation_phase": "phase_2b", "generation_policy": "generate",
        "scientific_question": "How does claim-to-evidence binding retain bounded conclusions?",
        "intended_comparison": "Observed inputs through binding to evidence-bounded conclusions",
        "visual_encoding": "Source-bound directed processing and outcome flow",
        "uncertainty_encoding": "Not applicable to conceptual method architecture",
        "evidence_status": "implemented_design", "claim_ids": ["C1"], "label": "fig:method",
        "caption": "Claim-to-evidence binding transforms observed inputs into bounded conclusions.",
        "source_data": ["ideas/SELECTED_IDEA.json", "experiments/EXPERIMENT_PLAN.md"],
        "publication_labels": [{"schema": 1, "id": "method.mechanism", "kind": "concept",
                                "display_text": "Claim-to-evidence binding"}],
        "scientific_scene": scene, "scene_contract": {"contribution_type": "system_architecture"},
        "method_brief": {"publication": selected["publication"]},
        **recommend_figure_route({"kind": "figure", "scientific_role": "method", "figure_nature": "conceptual"}),
    }
    plan = {"schema": 2, "evidence_mode": "design_only", "submission_eligible": False,
            "publication_style": {}, "assets": [asset]}
    _json(root / "figures/SCIENTIFIC_ASSET_PLAN.json", plan)
    persist_figure_specs(root, plan)
    return plan


def _record_prior_fixture_trace(root: Path, run: WorkflowRun) -> None:
    """Record explicit fixture lifecycle evidence; never claim a real model ran."""
    for node in run.nodes:
        if node.id == "figure":
            break
        plan = skill_orchestrator.select(node.id, node.skill, str(root), run.options)
        skill_orchestrator.record(str(root), run.id, plan)
        if plan.policy_required:
            skill_orchestrator.mark_execution(
                str(root), run.id, node.id, plan.primary, "completed",
                session_id=f"fixture-{node.id}", policy_loaded=True,
                execution_kind=plan.execution_kind, output="Synthetic fixture lifecycle only",
            )
        if plan.runtime_service:
            skill_orchestrator.mark_runtime_execution(
                str(root), run.id, node.id, plan.runtime_service, "completed",
                operation_id=f"fixture-runtime-{node.id}", output="Fixture runtime evidence",
            )


@pytest.mark.parametrize("negative", ["none", "upstream_missing", "wrong_runtime"])
@pytest.mark.asyncio
async def test_complete_node_rejects_missing_upstream_and_wrong_runtime(tmp_path, monkeypatch, negative):
    from server.services.node_risk_audit import node_risk_audit_service
    from server.services.research_quality import research_quality_service

    # This local fixture isolates execution ordering. The real snapshot runner
    # keeps all risk and quality checks; neither figure nor execution gates are mocked.
    monkeypatch.setattr(node_risk_audit_service, "apply_gate", lambda gate, *_a, **_k: gate)
    monkeypatch.setattr(research_quality_service, "apply_gate", lambda gate, *_a, **_k: gate)
    local_registry = SkillRegistry()
    local_registry.scan_directory(Path(__file__).resolve().parents[2] / "merak-skills")
    monkeypatch.setattr(skill_orchestrator, "registry", local_registry)
    monkeypatch.setattr(skill_orchestrator, "execution_trace", SkillExecutionTrace(local_registry))
    host = SnapshotEngine()
    run = WorkflowRun(id="fixture-full-gate", project_path=str(tmp_path), nodes=host._get_default_nodes(),
                      options={"run_experiment": False, "non_experiment_evidence_mode": "design_only"})
    state = RunState(str(tmp_path), run.id)
    state.start([{"id": node.id, "name": node.name, "skill": node.skill} for node in run.nodes],
                {"options": run.options})
    plan = _method_fixture(tmp_path)
    _record_prior_fixture_trace(tmp_path, run)
    node = next(node for node in run.nodes if node.id == "figure")
    owner = skill_orchestrator.select("figure", node.skill, str(tmp_path), run.options)
    skill_orchestrator.record(str(tmp_path), run.id, owner)
    await ensure_evaluation_design(host, run, tmp_path / "figures", plan["assets"], plan, set(), figure_artifact_registry)
    assert host._figure_acceptance_gate(str(tmp_path))["accepted"]
    trace = tmp_path / f".merak/runs/{run.id}.skills.json"
    if negative == "upstream_missing":
        payload = json.loads(trace.read_text())
        payload["stages"].pop("novelty")
        _json(trace, payload)
    ctx = RevisionLoopContext(host, node, run, "draft", "Fixture direction", "balanced",
                              run.options, 1, 1, "Local real deterministic rendering", False, 2)
    await initialize_revision(ctx)
    await initialize_progress(ctx)
    await persist_gate_inputs(ctx)
    ctx.preparation_error = ""
    await build_current_gate(ctx)
    if negative == "wrong_runtime":
        ctx.gate_runtime_service = "unrelated_plot_runtime"
    await record_runtime_gate(ctx)
    await verify_runtime_execution(ctx)
    if negative != "none":
        assert not ctx.gate["accepted"]
        expected = "novelty" if negative == "upstream_missing" else "runtime execution"
        assert expected in ctx.gate["summary"]
        assert state.load()["phases"]["figure"]["status"] != "accepted"
        return
    assert ctx.gate["accepted"], ctx.gate.get("summary")
    assert set(ctx.gate["details"]["workflow_execution_evidence"]["stages"]) == {
        "lit", "idea", "novelty", "exp-design", "exp-run", "results", "narrative", "figure",
    }
    await normalize_gate_outcome(ctx)
    with pytest.raises(RevisionComplete):
        await complete_accepted_gate(ctx)
    outcome = RunExecutionContext(host, run, "Fixture direction", "balanced", "draft", run.options,
                                  run_state=state, node=node, gate=ctx.gate, result=ctx.result)
    await persist_node_acceptance(outcome)
    await refresh_node_audits(outcome)
    assert state.load()["phases"]["figure"]["status"] == "accepted"
