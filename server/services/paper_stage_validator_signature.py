"""Bind reusable manuscript reviews to the local validators that actually ran."""

from __future__ import annotations

import hashlib
import json

from ..utils.runtime_source_root import server_source_root


def stage_validator_signature(stage_id: str) -> str:
    """Current validator byte changes invalidate acceptance, never authored content."""
    common = ("manuscript_text.py", "manuscript_language.py", "manuscript_math_syntax.py", "simulation_policy.py", "paper_deferred_rebind.py",
              "paper_stage_validator_signature.py", "paper_stage_cache_revalidation.py", "paper_table_ownership.py",
              "paper_section_figure_binding.py", "paper_stage_lifecycle.py", "latex_bundle.py",
              "paper_candidate_io.py", "paper_asset_placement.py", "paper_draft_coordinator.py", "paper_revision_queue.py")
    if stage_id == "blueprint":
        names = (*common, "paper_stage_validation.py")
    elif stage_id == "front_matter":
        names = (*common, "paper_stage_validation.py", "paper_profile.py")
    elif stage_id in {"consistency", "assembly"}:
        names = (*common, "paper_complete_validation.py", "paper_consistency_findings.py", "paper_length_findings.py", "execution_review_evidence.py",
                 "paper_model_consistency_findings.py", "paper_stage_lifecycle.py", "paper_review_source_inventory.py",
                 "paper_asset_author_ownership.py",
                 "paper_section_review.py", "paper_contribution_validation.py", "paper_stage_validation.py",
                 "paper_asset_reference_contract.py", "paper_profile.py", "paper_asset_placement.py",
                 "paper_manuscript_assembly.py", "paper_appendix_assembly.py", "simulation_primary_table.py", "simulation_table_projection_binding.py")
        names = (*names, "paper_print_projection.py", "paper_derived_figure_rendering.py",
                 "paper_native_plot_source.py",
                 "publication_print_contract.py", "paper_gate_reporting.py", "paper_derived_figure_binding.py",
                 "paper_derived_svg_projection.py", "paper_trusted_plot_source.py")
        names = (*names, "paper_plot_semantics_projection.py", "paper_presentation_caption.py",
                 "paper_curve_layout.py", "paper_risk_layout.py", "simulation_plot_layout.py",
                 "publication_labels.py", "paper_print_repair.py", "paper_print_producer_findings.py")
        names = (*names, "paper_figurespec_source.py", "paper_figurespec_typography.py")
        names = (*names, "paper_evaluation_svg_layout.py", "paper_derived_pixel_binding.py", "paper_matplotlib_memory.py")
        names = (*names, "table_panel_reference_contract.py", "latex_bundle.py", "paper_prose_references.py",
                 "simulation_calibration_table.py", "simulation_table_publication.py",
                 "simulation_table_publication_refresh.py", "paper_submission_tables.py", "paper_table_transaction.py",
                 "retained_table_input_closure.py", "simulation_robustness_table.py", "simulation_interval_caption.py")
    else:
        names = (*common, "paper_section_review.py", "paper_asset_reference_contract.py")
        if stage_id == "discussion":
            names = (*names, "paper_drafting.py")
        if stage_id == "introduction":
            names = (*names, "paper_contribution_validation.py")
        elif stage_id == 'results':
            names = (*names, 'paper_drafting.py', 'table_panel_reference_contract.py', 'simulation_primary_table.py',
                     'simulation_table_projection_binding.py', 'simulation_table_publication.py', 'latex_bundle.py',
                     'simulation_calibration_table.py', 'paper_prose_references.py', 'simulation_interval_caption.py')
    source_root = server_source_root()
    root = source_root / "services"
    payload = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names}
    if stage_id in {"consistency", "assembly"}:
        for name in ('paper_consistency_invocation.py', 'consistency_response_contract.py'):
            payload['workflows/' + name] = hashlib.sha256((source_root / 'workflows' / name).read_bytes()).hexdigest()
        from .paper_figurespec_source import figurespec_implementation_paths

        payload.update({f"figurespec/{path.name}": hashlib.sha256(path.read_bytes()).hexdigest()
                        for path in figurespec_implementation_paths(root)})
    payload["utils/runtime_source_root.py"] = hashlib.sha256(
        (source_root / "utils/runtime_source_root.py").read_bytes(),
    ).hexdigest()
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
