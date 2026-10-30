"""Source dependencies for cached accepted-phase risk audits."""

from pathlib import Path

from ..utils.runtime_source_root import server_source_root
from .slide_contract_sources import slide_contract_implementation_paths
from ..workflows.review_contract_sources import review_contract_implementation_paths
from .scientific_contract_sources import scientific_contract_implementation_paths


def risk_validator_source_paths(services_root: Path) -> list[Path]:
    """A split validator repair must not preserve a stale accepted risk report."""
    services_root = server_source_root() / "services"
    explicit = [services_root / name for name in (
        "node_risk_audit.py", "research_workflow_contract.py", "run_spec.py",
        "risk_validator_sources.py", "paper_section_review.py",
        "paper_contribution_validation.py", "manuscript_text.py",
        "specialist_inputs.py", "specialist_plan.py", "research_specialists.py",
        "simulation_primary_table.py", "simulation_table_projection_binding.py",
        "paper_asset_placement.py", "paper_manuscript_assembly.py",
        "paper_print_projection.py", "paper_derived_figure_rendering.py", "publication_print_contract.py",
        "paper_presentation_caption.py",
        "paper_figurespec_source.py", "paper_figurespec_typography.py",
        "paper_pdf_quality.py", "publication_pdf_fonts.py", "pdf_review_inspection.py", "pdf_overlap_pixels.py",
        "paper_derived_figure_binding.py", "paper_derived_svg_projection.py", "paper_trusted_plot_source.py",
        "paper_evaluation_svg_layout.py", "paper_derived_pixel_binding.py",
        "paper_matplotlib_memory.py", "paper_plot_semantics_projection.py", "publication_labels.py",
        "table_panel_reference_contract.py", "paper_gate_reporting.py",
        "paper_consistency_findings.py", "paper_asset_author_ownership.py", "paper_complete_validation.py",
        "simulation_calibration_table.py", "simulation_table_publication.py", "paper_print_repair.py",
        "simulation_table_publication_refresh.py", "paper_prose_references.py",
        "retained_table_input_closure.py",
        "paper_stage_cache_revalidation.py",
    )]
    paths = [*explicit, services_root.parent / "utils/runtime_source_root.py",
             *services_root.glob("risk_*.py"),
             *review_contract_implementation_paths(services_root),
             *scientific_contract_implementation_paths(services_root, "results"),
             *slide_contract_implementation_paths(services_root)]
    return sorted(set(paths), key=lambda path: path.as_posix())
