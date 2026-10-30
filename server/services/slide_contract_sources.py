"""Shared code dependencies for slide execution and recovery contracts."""

from pathlib import Path

from ..utils.runtime_source_root import implementation_source_path


SLIDE_CONTRACT_SERVICES = (
    "slide_contract_sources.py", "scientific_slides.py", "slide_figures.py", "slide_authoring_contract.py",
    "slide_deck_builder.py", "slide_sources.py", "slide_presentation_projection.py", "risk_stage_ppt.py",
    "paper_print_projection.py", "paper_derived_figure_rendering.py", "paper_derived_figure_binding.py",
    "paper_presentation_caption.py", "slide_scope_validation.py", "slide_rendered_contrast.py", "latex_graphics_paths.py",
    "paper_figurespec_source.py", "paper_figurespec_typography.py",
    "paper_derived_pixel_binding.py", "paper_trusted_plot_source.py", "paper_plot_semantics_projection.py",
    "slide_overflow_validation.py",
    "simulation_figure_portfolio.py", "evidence_asset_portfolio.py",
    "simulation_publication_attestation.py",
)


def slide_contract_implementation_paths(services_root: Path) -> list[Path]:
    """Producer or validator repairs must reopen the same stopped slide node."""
    from .paper_figurespec_source import figurespec_implementation_paths

    paths = [*(services_root / name for name in SLIDE_CONTRACT_SERVICES),
             services_root.parent / "workflows/engine_inputs.py",
             services_root.parent / "utils/runtime_source_root.py",
             *figurespec_implementation_paths(services_root)]
    return [implementation_source_path(path) for path in paths]
