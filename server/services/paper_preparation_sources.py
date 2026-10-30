"""Explicit code dependencies that reopen paper preparation checkpoints."""

from pathlib import Path


PAPER_PREPARATION_SERVICES = (
    "paper_submission_tables.py", "paper_table_projection.py", "semantic_table.py", "paper_fallback_manuscript.py",
    "public_table_prose_projection.py", "publication_design_prose.py",
    "paper_table_transaction.py", "paper_table_projection_validation.py",
    "paper_preparation_errors.py", "paper_acceptance_errors.py", "paper_failure_details.py", "paper_preparation_sources.py",
    "paper_draft_coordinator.py", "paper_draft_preparation.py", "paper_draft_state.py",
    "paper_draft_contracts.py", "paper_draft_stages.py", "paper_scientific_freeze.py",
    "paper_layout_attribution.py",
    "paper_pdf_quality.py", "publication_pdf_fonts.py", "pdf_review_inspection.py",
    "pdf_overlap_pixels.py",
    "latex_compile_execution.py", "local_compile_process.py", "windows_compile_job.py",
    "paper_layout_errors.py", "paper_print_repair.py", "paper_print_projection.py", "paper_print_producer_findings.py",
    "paper_presentation_caption.py",
    "paper_figurespec_source.py", "paper_figurespec_typography.py",
    "publication_print_contract.py", "paper_derived_figure_rendering.py",
    "paper_derived_figure_binding.py", "paper_derived_svg_projection.py", "paper_trusted_plot_source.py",
    "paper_evaluation_svg_layout.py", "paper_derived_pixel_binding.py",
    "paper_matplotlib_memory.py", "paper_plot_semantics_projection.py", "publication_labels.py",
    "simulation_plot_layout.py", "simulation_plot_template.py",
    "paper_plan_asset_links.py", "paper_plan.py", "paper_plan_runtime.py",
    "paper_citation_context.py",
    "paper_deferred_rebind.py",
    "paper_model_consistency_findings.py", "paper_stage_lifecycle.py",
    "paper_review_source_inventory.py",
    "paper_explanation_refresh.py",
    "research_delivery_prompt.py",
    "manuscript_math_syntax.py",
    "paper_table_ownership.py",
    "paper_curve_layout.py",
    "paper_risk_layout.py",
    "simulation_robustness_table.py",
    "simulation_interval_caption.py",
    "table_panel_reference_contract.py", "paper_gate_reporting.py",
    "paper_stage_cache_revalidation.py",
    "latex_bundle.py",
    "paper_consistency_findings.py", "paper_asset_author_ownership.py", "paper_complete_validation.py", "paper_gate_reporting.py",
    "paper_stage_prompts.py", "paper_asset_reference_contract.py", "paper_asset_placement.py", "paper_presentation_findings.py",
    "simulation_table_portfolio.py", "simulation_table_projection.py", "simulation_table_publication.py",
    "simulation_primary_table.py", "simulation_calibration_table.py", "simulation_table_projection_binding.py",
    "simulation_table_publication_refresh.py", "paper_prose_references.py",
    "retained_table_input_closure.py",
    "paper_manuscript_assembly.py", "paper_review_reconciliation.py",
    "paper_appendix_assembly.py",
    "simulation_figure_portfolio.py", "simulation_paper_projection.py", "simulation_render_bundle.py", "simulation_publication_registry.py", "planned_simulation_bindings.py",
    "simulation_publication_names.py", "paper_table_source_labels.py", "publication_table_policy.py",
    "scientific_narrative.py",
    "paper_section_review.py", "paper_contribution_validation.py", "paper_stage_validator_signature.py", "risk_stage_paper.py",
)
PAPER_PREPARATION_WORKFLOWS = (
    "paper_preparation_checkpoint.py", "run_execution_execute.py", "engine_execution.py",
    "engine_inputs.py", "engine_artifacts_a.py",
    "paper_repair_runtime.py", "revision_execution.py", "revision_diagnostics.py", "paper_runtime_failure_diagnostics.py",
    "revision_owner_policy.py", "revision_owner_rules.py", "revision_loop_phases.py",
    "paper_acceptance_coordinator.py",
    "node_gate_preparation.py", "paper_acceptance_checks_2.py",
    "paper_plan_repair.py",
    "paper_stage_invocation.py",
    "paper_resume_stage.py", "run_execution_node.py",
    "paper_acceptance_checks_3.py",
)


def paper_preparation_implementation_paths(services_root: Path) -> list[Path]:
    """Recovery compares disk capabilities; it never asserts a loaded repair ran."""
    from .paper_figurespec_source import figurespec_implementation_paths

    return [*(services_root / name for name in PAPER_PREPARATION_SERVICES),
            *(services_root.parent / "workflows" / name for name in PAPER_PREPARATION_WORKFLOWS),
            services_root.parent / "contracts/repairs.py",
            *figurespec_implementation_paths(services_root)]
