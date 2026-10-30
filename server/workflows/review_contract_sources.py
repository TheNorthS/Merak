"""Shared implementation dependencies for the actual PDF review handoff."""

from pathlib import Path


def review_contract_implementation_paths(services_root: Path) -> list[Path]:
    """A print or native-evidence repair must invalidate every review cache."""
    from ..services.paper_preparation_sources import paper_preparation_implementation_paths

    workflows = services_root.parent / "workflows"
    return [
        workflows / "review_contract_sources.py",
        *(workflows / name for name in (
            "review_execution.py", "review_loop.py", "review_visuals.py",
            "review_snapshot_reuse.py", "review_audit.py",
            "review_visual_artifact_evidence.py", "review_visual_trace_evidence.py",
            "review_visual_attachment_evidence.py", "review_visual_evidence.py",
        )),
        services_root / "api_visual_reviewer.py",
        *paper_preparation_implementation_paths(services_root),
    ]
