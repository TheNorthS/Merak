"""Source-only checks that repair-policy changes reopen stopped checkpoints."""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import pytest

from server.workflows.engine_revision_signature import _bind_validator_sources


_FIGURE_PRODUCER_SOURCES = (
    "scientific_scene_figure.py", "scientific_scene_placement.py", "scientific_scene_labels.py", "figure_semantic_projection.py",
    "scientific_plotting.py", "scientific_plot_template.py",
    "deterministic_figure_builder.py", "figure_producer_errors.py",
    "figure_producer_fingerprint.py", "scientific_asset_contract.py",
    "evaluation_design_svg.py", "evaluation_design_contract.py",
    "evaluation_protocol_projection.py", "evaluation_conditions_projection.py",
    "evaluation_design_content.py", "simulation_figure_refresh.py",
    "simulation_plot_layout.py", "simulation_plot_layout_refresh.py", "simulation_plot_template.py", "paper_trusted_plot_source.py",
    "figure_execution_policy.py", "figure_execution_evidence.py",
    "node_execution_contract.py", "skill_selection.py",
    "skill_orchestrator.py", "skill_execution_trace.py",
    "figure_execution_verification.py", "acceptance_pipeline.py", "revision_gate_phases.py",
    "simulation_publication_registry.py", "simulation_publication_attestation.py",
    "simulation_render_refresh.py",
    "simulation_comparison_plots.py", "multitask_matrix.py.tmpl",
    "figure_renderer.py", "figure_semantic_rendering.py",
    "figurespec_backend.py", "figurespec_layout_policy.py",
    "figure_generation_transaction.py", "figure_result_finalizer.py", "figure_diagram_text.py", "figure_scientific_alignment.py",
    "figure_raster_quality.py", "svg_variant_conversion.py",
    "svg_marker_fallback.py", "figure_svg_sources.py", "figure_engine.py",
)


@pytest.fixture(scope="module")
def renderer_module():
    path = Path(__file__).resolve().parents[2] / "merak-skills/figure-spec/scripts/figure_renderer.py"
    spec = importlib.util.spec_from_file_location("figure_signature_test_renderer", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("node_id", ["novelty", "figure"])
@pytest.mark.parametrize("source_name", [
    "repairs.py", "revision_diagnostics.py", "revision_owner_rules.py",
    "engine_artifacts_a.py",
    "revision_owner_policy.py", "node_execution_completion.py",
    "artifact_snapshot_ownership.py", "engine_snapshot_paths.py", "revision_attempt.py", "paper_plan_repair.py", "node_gate_preparation.py",
    "accepted_phase_validation.py", "dependency_reuse.py",
    "specialist_inputs.py", "specialist_plan.py", "research_specialists.py",
])
def test_routing_or_completion_code_change_reopens_old_checkpoint_signature(
    node_id: str, source_name: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = Path.read_bytes
    changed = False

    def source_bytes(path: Path) -> bytes:
        if path.name == source_name:
            return b"revised producer policy" if changed else b"initial producer policy"
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", source_bytes)
    before = hashlib.sha256()
    _bind_validator_sources(before, node_id)
    changed = True
    after = hashlib.sha256()
    _bind_validator_sources(after, node_id)
    assert before.hexdigest() != after.hexdigest()


@pytest.mark.parametrize("source_name", [
    "slide_contract_sources.py", "scientific_slides.py", "slide_figures.py",
    "slide_deck_builder.py", "slide_sources.py", "risk_stage_ppt.py",
    "simulation_figure_portfolio.py", "evidence_asset_portfolio.py",
    "simulation_publication_attestation.py", "engine_inputs.py",
    "runtime_source_root.py",
])
def test_slide_producer_change_reopens_stopped_ppt_checkpoint(
    source_name: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = Path.read_bytes
    changed = False

    def source_bytes(path: Path) -> bytes:
        if path.name == source_name:
            return b"fixed slide contract" if changed else b"previous slide contract"
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", source_bytes)
    before = hashlib.sha256()
    _bind_validator_sources(before, "ppt")
    changed = True
    after = hashlib.sha256()
    _bind_validator_sources(after, "ppt")
    assert before.hexdigest() != after.hexdigest()


def test_contribution_recognizer_change_reopens_stopped_paper_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = Path.read_bytes
    changed = False

    def source_bytes(path: Path) -> bytes:
        if path.name == "paper_contribution_validation.py":
            return b"fixed semantic recognizer" if changed else b"previous semantic recognizer"
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", source_bytes)
    before = hashlib.sha256()
    _bind_validator_sources(before, "paper")
    changed = True
    after = hashlib.sha256()
    _bind_validator_sources(after, "paper")
    assert before.hexdigest() != after.hexdigest()


@pytest.mark.parametrize("source_name", [
    "risk_stage_ppt.py", "slide_figures.py", "slide_deck_builder.py",
    "slide_contract_sources.py", "risk_validator_sources.py",
    "paper_contribution_validation.py", "paper_section_review.py",
    "risk_stage_paper.py", "risk_validator_support.py", "runtime_source_root.py",
])
def test_validator_repair_invalidates_previously_accepted_risk_cache(
    source_name: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.workflows.engine import WorkflowEngine

    original = Path.read_bytes
    changed = False

    def source_bytes(path: Path) -> bytes:
        if path.name == source_name:
            return b"fixed risk validator" if changed else b"previous risk validator"
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", source_bytes)
    options = {"run_experiment": False, "non_experiment_evidence_mode": "synthetic_preview"}
    before = WorkflowEngine._risk_audit_validator_signature(options)
    changed = True
    assert WorkflowEngine._risk_audit_validator_signature(options) != before


@pytest.mark.parametrize("source_name", [
    "method_contract_persistence.py", "implementation_build_revalidation.py",
    "implementation_stage_validation.py", "implementation_reconciliation.py",
    "implementation_model_invocation.py",
    "implementation_evidence.py",
    "staged_implementation_coordinator.py", "simulation_render_bundle.py",
    "simulation_artifact_io.py", "acceptance_context.py", "write_scope.py",
    "tool_response_protocol.py", "node_gate_preparation.py",
    "implementation_candidate_recovery.py", "implementation_graph.py",
    "implementation_scopes.py", "implementation_audit.py", "acceptance_coordinator.py",
])
def test_exp_design_producer_change_reopens_its_own_checkpoint(
    source_name: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = Path.read_bytes
    changed = False

    def source_bytes(path: Path) -> bytes:
        if path.name == source_name:
            return b"fixed producer" if changed else b"previous producer"
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", source_bytes)
    before = hashlib.sha256()
    _bind_validator_sources(before, "exp-design")
    changed = True
    after = hashlib.sha256()
    _bind_validator_sources(after, "exp-design")
    assert before.hexdigest() != after.hexdigest()


@pytest.mark.parametrize("source_name", _FIGURE_PRODUCER_SOURCES)
def test_figure_source_change_reopens_checkpoint_and_asset_budget(
    source_name: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.services.figure_delegate_budget import figure_producer_code_sha256

    original = Path.read_bytes
    changed = False

    def source_bytes(path: Path) -> bytes:
        if path.name == source_name:
            return b"fixed figure producer" if changed else b"previous figure producer"
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", source_bytes)
    before = hashlib.sha256()
    _bind_validator_sources(before, "figure")
    budget_before = figure_producer_code_sha256()
    changed = True
    after = hashlib.sha256()
    _bind_validator_sources(after, "figure")
    assert before.hexdigest() != after.hexdigest()
    assert budget_before != figure_producer_code_sha256()


@pytest.mark.parametrize("module_name", [
    "scientific_scene_figure", "scientific_scene_placement", "scientific_scene_labels", "figurespec_backend",
    "figurespec_layout_policy", "deterministic_figure_builder",
    "figure_generation_transaction", "figure_scientific_alignment",
    "figure_raster_quality", "svg_variant_conversion", "svg_marker_fallback",
])
def test_architecture_loaded_dependency_changes_its_artifact_fingerprint(
    module_name: str, renderer_module, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.services import figure_producer_fingerprint as fingerprint
    from server.services.deterministic_figure_builder import _architecture_code_sha256

    changed = False

    def loaded_digest(name: str, _package: str) -> bytes:
        return b"repaired" if changed and name == module_name else b"previous"

    monkeypatch.setattr(fingerprint, "loaded_module_digest", loaded_digest)
    before = _architecture_code_sha256(renderer_module)
    changed = True
    assert before != _architecture_code_sha256(renderer_module)


@pytest.mark.parametrize("module_name", [
    "evaluation_design_svg", "evaluation_design_contract", "evaluation_design_content",
    "evaluation_protocol_projection", "evaluation_conditions_projection",
    "scientific_asset_builders", "scientific_asset_contract", "deterministic_figure_builder",
    "figure_generation_transaction", "figure_scientific_alignment",
    "figure_raster_quality", "svg_variant_conversion", "svg_marker_fallback",
])
def test_template_loaded_dependency_changes_its_artifact_fingerprint(
    module_name: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.services import deterministic_figure_builder as builder

    changed = False

    def loaded_digest(name: str) -> bytes:
        return b"repaired" if changed and name == module_name else b"previous"

    monkeypatch.setattr(builder, "_module_code_digest", loaded_digest)
    before = builder._template_code_sha256()
    changed = True
    assert before != builder._template_code_sha256()


@pytest.mark.parametrize("owner", ["renderer", "semantic_renderer"])
def test_external_loaded_function_change_invalidates_architecture(
    owner: str, renderer_module, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.services.deterministic_figure_builder import _architecture_code_sha256

    module = renderer_module if owner == "renderer" else renderer_module._SEMANTIC_RENDERER
    name = "render_svg" if owner == "renderer" else "render_node_text"
    before = _architecture_code_sha256(renderer_module)
    replacement = lambda *_args: "repaired publication rendering"
    replacement.__module__ = module.__name__
    monkeypatch.setattr(module, name, replacement)
    assert before != _architecture_code_sha256(renderer_module)


@pytest.mark.parametrize("source_name", ["figure_renderer.py", "figure_semantic_rendering.py"])
def test_unloaded_disk_edit_reopens_resume_without_claiming_loaded_code_changed(
    source_name: str, renderer_module, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.services.deterministic_figure_builder import _architecture_code_sha256
    from server.services.figure_delegate_budget import figure_producer_code_sha256

    loaded_before = _architecture_code_sha256(renderer_module)
    source_before = figure_producer_code_sha256()
    original = Path.read_bytes
    monkeypatch.setattr(Path, "read_bytes", lambda path: (
        b"future source on disk" if path.name == source_name else original(path)
    ))
    assert figure_producer_code_sha256() != source_before
    assert _architecture_code_sha256(renderer_module) == loaded_before


from server.services.paper_preparation_sources import (
    PAPER_PREPARATION_SERVICES, PAPER_PREPARATION_WORKFLOWS,
)


@pytest.mark.parametrize("source_name", [*PAPER_PREPARATION_SERVICES, *PAPER_PREPARATION_WORKFLOWS])
def test_paper_preparation_producer_change_reopens_checkpoint(source_name, monkeypatch):
    original = Path.read_bytes
    changed = False

    def source_bytes(path):
        if path.name == source_name:
            return b"fixed paper preparation" if changed else b"previous paper preparation"
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", source_bytes)
    before = hashlib.sha256()
    _bind_validator_sources(before, "paper")
    changed = True
    after = hashlib.sha256()
    _bind_validator_sources(after, "paper")
    assert before.hexdigest() != after.hexdigest()


@pytest.mark.parametrize("source_name", [
    "results_execution_policy.py", "node_execution_contract.py", "results_runtime_execution.py",
    "run_execution_node.py", "revision_execution.py", "node_gate_preparation.py",
    "skill_execution_trace.py", "simulation_result_analysis.py", "engine_execution.py",
    "engine_inputs.py", "simulation_report_contract.py", "skill_selection.py", "simulation_asset_profile.py", "planned_result_reuse.py",
    "simulation_figure_portfolio.py", "simulation_paper_projection.py", "simulation_render_bundle.py", "simulation_publication_registry.py", "planned_simulation_bindings.py",
])
def test_results_runtime_contract_change_reopens_checkpoint(source_name, monkeypatch):
    original = Path.read_bytes
    changed = False

    def source_bytes(path):
        if path.name == source_name:
            return b"fixed results contract" if changed else b"previous results contract"
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", source_bytes)
    before = hashlib.sha256()
    _bind_validator_sources(before, "results")
    changed = True
    after = hashlib.sha256()
    _bind_validator_sources(after, "results")
    assert before.hexdigest() != after.hexdigest()


@pytest.mark.parametrize("node_id,source_name", [
    ("results", "engine_execution.py"), ("results", "engine_inputs.py"),
    ("lit", "artifact_snapshot_ownership.py"), ("lit", "engine_snapshot_paths.py"),
    ("lit", "accepted_phase_validation.py"), ("lit", "dependency_reuse.py"),
    ("results", "specialist_inputs.py"), ("results", "specialist_plan.py"),
    ("results", "research_specialists.py"),
    ("results", "skill_selection.py"), ("results", "simulation_report_contract.py"),
    ("figure", "figure_semantic_projection.py"), ("figure", "evaluation_design_svg.py"),
    ("paper", "paper_contribution_validation.py"),
    ("paper", "runtime_source_root.py"),
    ("ppt", "slide_contract_sources.py"), ("ppt", "slide_figures.py"),
    ("ppt", "latex_graphics_paths.py"), ("ppt", "slide_rendered_contrast.py"),
    ("ppt", "slide_deck_builder.py"), ("ppt", "slide_sources.py"),
    ("ppt", "risk_stage_ppt.py"), ("ppt", "simulation_figure_portfolio.py"),
    ("ppt", "evidence_asset_portfolio.py"),
    ("ppt", "simulation_publication_attestation.py"), ("ppt", "engine_inputs.py"),
    ("ppt", "runtime_source_root.py"),
])
def test_real_execution_source_change_reopens_runtime_capability(node_id, source_name, tmp_path, monkeypatch):
    from server.services.skill_registry import skill_registry
    from server.workflows.engine import WorkflowEngine

    host = WorkflowEngine()
    monkeypatch.setattr(host, "_ensure_agent_tools", lambda: None)
    monkeypatch.setattr(host, "_workflow_stage_required_tools", lambda *_args: set())
    monkeypatch.setattr(skill_registry, "get_skill", lambda *_args: None)
    original = Path.read_bytes
    changed = False

    def source_bytes(path):
        if path.name == source_name:
            return b"fixed results operation" if changed else b"previous results operation"
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", source_bytes)
    options = {"run_experiment": False, "non_experiment_evidence_mode": "design_only"}
    before = host._revision_runtime_signature(str(tmp_path), node_id, options)
    changed = True
    assert host._revision_runtime_signature(str(tmp_path), node_id, options) != before
