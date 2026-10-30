"""Pure fixture producer-identity revalidation; no figure/model/workflow execution."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from server.services import deterministic_figure_builder as builder
from server.services.deterministic_figure_freshness import (
    current_design_input_sha256, deterministic_figure_freshness_issues,
)
from server.services.workflow_inputs import snapshot_paths
from server.workflows.accepted_phase_validation import validated_accepted_phase_ids
from server.workflows.models import WorkflowNode, WorkflowRun
from server.workflows.run_state import RunState


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _fixture(root: Path, spec: dict | None = None) -> tuple[dict, dict, dict]:
    spec = spec or {"id": "evaluation_design", "kind": "figure", "producer_kind": "deterministic",
        "production_strategy": "deterministic_template", "recommended_backend": "rich_svg",
        "scientific_question": "How are registered comparison conditions evaluated?",
        "caption": "Declared evaluation conditions", "publication_labels": [],
        "generation_policy": "generate"}
    spec = copy.deepcopy(spec)
    spec.setdefault("kind", "figure")
    spec.setdefault("caption", spec["scientific_question"])
    plan = {"schema": 2, "publication_style": {"visual_standard": "test-publication-style"}, "assets": [spec]}
    specifications = {"schema": 4, "figures": [spec]}
    entry = {"id": spec["id"], "metadata": {**spec, "semantic_key": spec["id"],
        "producer_input_sha256": current_design_input_sha256(spec, plan),
        "paper_selected": True, "manuscript_eligible": True}}
    _write(root / "figures/SCIENTIFIC_ASSET_PLAN.json", plan)
    _write(root / "figures/FIGURE_SPECS.json", specifications)
    _write(root / "figures/FIGURE_MANIFEST.json", {"schema": 1, "figures": [entry]})
    return plan, spec, entry


def _protected(root: Path) -> dict:
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def _reject(*_args, **_kwargs):
    raise AssertionError("Read-only freshness cannot execute model, rendering, compilation or plan persistence")


@pytest.fixture
def no_execution(monkeypatch):
    from server.agent.engine import agent_engine
    from server.services.figure_engine import figure_engine
    from server.services.scientific_assets import scientific_asset_service
    from server.services.paper_compiler import paper_compiler

    monkeypatch.setattr(agent_engine, "run", _reject)
    monkeypatch.setattr(figure_engine, "generate", _reject)
    monkeypatch.setattr(figure_engine, "refresh_editable_source", _reject)
    monkeypatch.setattr(scientific_asset_service, "build_plan", _reject)
    monkeypatch.setattr(paper_compiler, "compile", _reject)


def test_current_template_signature_reuses_exact_producer_algorithm_without_any_write(tmp_path, no_execution):
    plan, spec, entry = _fixture(tmp_path)
    before = _protected(tmp_path)
    expected = builder._template_input_sha256(spec, plan["publication_style"]["visual_standard"],
        builder._template_code_sha256())
    assert current_design_input_sha256(spec, plan) == expected == entry["metadata"]["producer_input_sha256"]
    assert deterministic_figure_freshness_issues(tmp_path) == []
    assert _protected(tmp_path) == before


@pytest.mark.parametrize("module_name", ["evaluation_conditions_projection", "evaluation_design_content"])
def test_loaded_template_projection_repair_invalidates_old_hash_while_every_artifact_stays_unchanged(
        tmp_path, monkeypatch, no_execution, module_name):
    import importlib

    _fixture(tmp_path)
    before = _protected(tmp_path)
    module = importlib.import_module("server.services." + module_name)
    function_name = "project_evaluation_conditions" if module_name.endswith("projection") else "_declared_comparators"
    monkeypatch.setattr(module, function_name, lambda *_args, **_kwargs: "Changed loaded implementation")
    issues = deterministic_figure_freshness_issues(tmp_path)
    assert len(issues) == 1 and "evaluation_design" in issues[0] and "loaded implementation changed" in issues[0]
    assert _protected(tmp_path) == before


def test_architecture_shared_hash_preserves_previous_producer_bytes_without_rendering(tmp_path, monkeypatch, no_execution):
    from server.services.figure_engine import _load_figurespec_renderer
    from server.services.scientific_scene_figure import compile_scientific_scene_figure
    from server.tests.test_deterministic_architecture_integration import _asset

    plan, spec, entry = _fixture(tmp_path, _asset())
    renderer = _load_figurespec_renderer()
    monkeypatch.setattr(renderer, "render_svg", _reject)
    compiled = compile_scientific_scene_figure(spec).spec
    code = builder._architecture_code_sha256(renderer)
    expected = hashlib.sha256(json.dumps({
        "version": builder._ARCHITECTURE_VERSION, "spec": spec, "compiled": compiled,
        "style": plan["publication_style"]["visual_standard"], "code_hash": code,
    }, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    assert builder.architecture_input_sha256(spec, plan["publication_style"]["visual_standard"], compiled, code) == expected
    # Changing the loaded renderer must reject the old provenance, not invoke it.
    assert entry["metadata"]["producer_input_sha256"] != expected
    assert "method_architecture" in deterministic_figure_freshness_issues(tmp_path)[0]


@pytest.mark.parametrize("defect", ["missing_hash", "wrong_hash", "changed_spec", "missing_spec",
    "missing_plan", "unknown_schema", "duplicate_id", "producer_kind", "backend", "portfolio", "linked_proof"])
def test_deterministic_design_provenance_fails_closed_for_inconsistent_contracts(tmp_path, defect, no_execution):
    plan, spec, entry = _fixture(tmp_path)
    if defect == "missing_hash": entry["metadata"].pop("producer_input_sha256")
    elif defect == "wrong_hash": entry["metadata"]["producer_input_sha256"] = "0" * 64
    elif defect == "changed_spec":
        spec = {**spec, "caption": "Uncommitted replacement"}
        _write(tmp_path / "figures/FIGURE_SPECS.json", {"schema": 4, "figures": [spec]})
    elif defect == "missing_spec": (tmp_path / "figures/FIGURE_SPECS.json").unlink()
    elif defect == "missing_plan": (tmp_path / "figures/SCIENTIFIC_ASSET_PLAN.json").unlink()
    elif defect == "unknown_schema": _write(tmp_path / "figures/FIGURE_SPECS.json", {"schema": 3, "figures": [spec]})
    elif defect == "duplicate_id": _write(tmp_path / "figures/FIGURE_SPECS.json", {"schema": 4, "figures": [spec, spec]})
    elif defect == "producer_kind":
        spec["producer_kind"] = "model"
        plan["assets"] = [spec]
        _write(tmp_path / "figures/SCIENTIFIC_ASSET_PLAN.json", plan)
        _write(tmp_path / "figures/FIGURE_SPECS.json", {"schema": 4, "figures": [spec]})
    elif defect == "backend": entry["metadata"]["recommended_backend"] = "mermaid"
    elif defect == "portfolio":
        plan["assets"] = []
        _write(tmp_path / "figures/SCIENTIFIC_ASSET_PLAN.json", plan)
    else:
        path = tmp_path / "figures/FIGURE_SPECS.json"
        import os
        try:
            os.link(path, tmp_path / "linked-spec.json")
        except OSError:
            pytest.skip("Temporary hard links unavailable")
    _write(tmp_path / "figures/FIGURE_MANIFEST.json", {"schema": 1, "figures": [entry]})
    before = _protected(tmp_path)
    assert deterministic_figure_freshness_issues(tmp_path)
    assert _protected(tmp_path) == before


@pytest.mark.parametrize("kind", ["model", "quantitative", "unselected", "no_manifest"])
def test_non_design_figure_modes_keep_their_existing_gate_contracts(tmp_path, kind, no_execution):
    if kind != "no_manifest":
        metadata = {"producer_kind": "model", "production_strategy": "model_composed_full_svg"}
        if kind == "quantitative": metadata = {"producer_kind": "deterministic", "production_strategy": "deterministic_plot"}
        if kind == "unselected":
            metadata = {"producer_kind": "deterministic", "production_strategy": "deterministic_template", "paper_selected": False}
        _write(tmp_path / "figures/FIGURE_MANIFEST.json", {"schema": 1, "figures": [{"id": "unrelated", "metadata": metadata}]})
    before = _protected(tmp_path)
    assert deterministic_figure_freshness_issues(tmp_path) == []
    assert _protected(tmp_path) == before


def _accepted_fixture(root: Path):
    definitions = [
        WorkflowNode("narrative", "Narrative", "/research-refine"),
        WorkflowNode("figure", "Figure", "/paper-figure", depends_on=["narrative"]),
        WorkflowNode("paper", "Paper", "/paper-write", depends_on=["figure"]),
        WorkflowNode("review", "Review", "/auto-review-loop", depends_on=["paper"]),
        WorkflowNode("audit", "Audit", "/experiment-audit", depends_on=["review"]),
        WorkflowNode("compile", "PDF", "/paper-compile", depends_on=["audit"]),
        WorkflowNode("ppt", "PPT", "/paper-talk", depends_on=["compile"]),
    ]
    durable = RunState(str(root), "pure-cached-owner-fixture")
    baseline = {"snapshot_id": "fixed-pure-input", "entries": []}
    durable.start([{"id": node.id} for node in definitions], {"options": {}}, baseline)
    owned = root / "figures/FIGURE_MANIFEST.json"
    for node in definitions:
        durable.set_status(node.id, "done")
        durable.accept(node.id, "fixture-" + node.id, "pure-fixture", {
            "input_baseline_snapshot_id": baseline["snapshot_id"], "artifact_snapshot": snapshot_paths(root, [owned]),
            "risk_audit_bound": True, "risk_audit_validator_signature": "unchanged-risk-signature",
            "node_risk_audit": {"findings": []}})
    host = SimpleNamespace(_get_default_nodes=lambda: definitions,
        _risk_audit_validator_signature=lambda _options: "unchanged-risk-signature",
        _artifact_snapshot_issues=lambda _project, _snapshot: [])
    run = WorkflowRun(id=durable.run_id, project_path=str(root), input_baseline=baseline)
    return durable, host, run


def test_frozen_accepted_owner_cache_cannot_hide_new_template_code_and_invalidates_only_dependents(
        tmp_path, monkeypatch, no_execution):
    from server.services import evaluation_conditions_projection as projection
    from server.services.node_risk_audit import node_risk_audit_service

    _fixture(tmp_path)
    durable, host, run = _accepted_fixture(tmp_path)
    original = durable.load()
    manifest_before = (tmp_path / "figures/FIGURE_MANIFEST.json").read_bytes()
    monkeypatch.setattr(node_risk_audit_service, "audit_node", _reject)
    assert validated_accepted_phase_ids(host, run, durable) == [node.id for node in host._get_default_nodes()]
    monkeypatch.setattr(projection, "project_evaluation_conditions", lambda *_args: "Source-owned corrected conditions")
    assert validated_accepted_phase_ids(host, run, durable) == ["narrative"]
    state = durable.load()
    assert state["phases"]["narrative"] == original["phases"]["narrative"]
    for name in ("figure", "paper", "review", "audit", "compile", "ppt"):
        assert state["phases"][name]["status"] == "done"
        assert state["phases"][name]["accepted_at"] is None
        assert state["phases"][name]["details"]["acceptance_invalidations"]
    assert "evaluation_design" in state["phases"]["figure"]["details"]["acceptance_invalidations"][-1]["reason"]
    assert (tmp_path / "figures/FIGURE_MANIFEST.json").read_bytes() == manifest_before


def test_final_figure_gate_registry_refresh_reports_same_readonly_stale_producer_issue(
        tmp_path, monkeypatch, no_execution):
    from server.services.figure_artifacts import figure_artifact_registry as registry
    from server.workflows.figure_acceptance_policy import FigureGateContext, _refresh_registry
    from server.services import evaluation_design_content as content

    _fixture(tmp_path)
    payload = json.loads((tmp_path / "figures/FIGURE_MANIFEST.json").read_text())
    monkeypatch.setattr(registry, "validate", lambda *_args: (True, [], payload))
    for name in ("scientific_quality_issues", "scientific_alignment_issues", "paper_ready_entries"):
        monkeypatch.setattr(registry, name, lambda *_args: [])
    context = FigureGateContext(SimpleNamespace(), tmp_path, tmp_path / "figures",
        tmp_path / "figures/FIGURE_MANIFEST.json", tmp_path / "figures/FIGURE_SPECS.json",
        tmp_path / "figures/SCIENTIFIC_ASSET_PLAN.json")
    before = _protected(tmp_path)
    monkeypatch.setattr(content, "_declared_comparators", lambda *_args: "Corrected declaration semantics")
    _refresh_registry(context)
    assert any("evaluation_design" in issue and "loaded implementation changed" in issue for issue in context.problems)
    assert _protected(tmp_path) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("strategy", ["deterministic_template", "deterministic_architecture"])
async def test_normal_owner_real_input_provenance_passes_shared_validator_after_pure_fake_render(
        tmp_path, monkeypatch, no_execution, strategy):
    from server.services.figure_engine import FigureType, figure_engine
    from server.services.figure_models import FigureResult
    from server.services import evaluation_conditions_projection as projection
    from server.tests.test_deterministic_architecture_integration import _asset

    asset = _asset() if strategy == "deterministic_architecture" else None
    plan, spec, _entry = _fixture(tmp_path, asset)
    if strategy == "deterministic_template":
        monkeypatch.setattr(projection, "project_evaluation_conditions", lambda *_args: "Corrected source projection")
        assert deterministic_figure_freshness_issues(tmp_path)
    observed = []
    async def generate(**arguments):
        observed.append(arguments)
        _write(tmp_path / "figures/FIGURE_MANIFEST.json", {"schema": 1, "figures": [{
            "id": spec["id"], "metadata": arguments["metadata"]}]})
        return FigureResult(True, FigureType.RICH_SVG if strategy == "deterministic_template"
            else FigureType.FIGURESPEC, source_path="fixture-owned-source", output_path="fixture-owned-output")
    async def emitted(*_arguments):
        return None
    class Registry:
        @staticmethod
        def load(_path):
            return json.loads((tmp_path / "figures/FIGURE_MANIFEST.json").read_text())
    monkeypatch.setattr(figure_engine, "generate", generate)
    monkeypatch.setattr("server.services.figure_engine._evaluation_design_svg",
        lambda _spec: ("<svg/>", []))
    await builder.ensure_evaluation_design(SimpleNamespace(_emit=emitted), object(), tmp_path / "figures",
        [spec], plan, set(), Registry())
    assert len(observed) == 1
    assert observed[0]["metadata"]["producer_input_sha256"] == current_design_input_sha256(spec, plan)
    assert deterministic_figure_freshness_issues(tmp_path) == []


def test_absent_legacy_artifact_binding_cannot_hide_existing_stale_producer_proof(tmp_path, monkeypatch, no_execution):
    from server.services import evaluation_conditions_projection as projection
    from server.workflows.accepted_phase_validation import AcceptedPhaseAudit, _phase_issues

    _fixture(tmp_path)
    monkeypatch.setattr(projection, "project_evaluation_conditions", lambda *_args: "Changed loaded source producer")
    run = WorkflowRun(project_path=str(tmp_path))
    issues = _phase_issues(SimpleNamespace(), run, "figure", {"status": "accepted"}, "", "",
        AcceptedPhaseAudit({}, {}, {"figure"}))
    assert "evaluation_design" in issues[0]
