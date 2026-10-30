"""Reject authored noncanonical figure paths at their section owner before assembly."""

from pathlib import Path


def section_figure_binding_issues(root: Path, filename: str) -> list[str]:
    from .paper_asset_placement import _figure_used, _section_sources
    from .paper_asset_reference_contract import selected_publication_references
    from .paper_candidate_io import candidate_path
    root = root.resolve()
    path = root / 'paper/sections' / filename
    if not candidate_path(path).is_file():
        return []
    sources = _section_sources(root.resolve(), [(path.stem, path)])
    issues = []
    for reference in selected_publication_references(root):
        if reference.kind != 'figure':
            continue
        try:
            _figure_used(root.resolve(), reference, sources)
        except ValueError as error:
            issues.append(f'{error}. Repair only paper/sections/{filename}: use the canonical '
                          f'graphic ../{reference.source_path} and one label {reference.label}; '
                          'do not modify the figure or remove required scientific content.')
    return issues
