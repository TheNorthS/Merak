"""Separate scientific prose references from links inside figure/table captions."""

import re
from pathlib import Path

from .manuscript_text import reference_keys


def scientific_prose_text(text: str) -> str:
    """Use the native paper gate's exact float-removal boundary."""
    return re.sub(r"\\begin\{(?:figure|table)\*?\}.*?\\end\{(?:figure|table)\*?\}", " ", text, flags=re.DOTALL)


def asset_prose_reference_keys(root: Path, text: str) -> set[str]:
    """Only existing exact source-bound primary panels may share parent prose."""
    from .table_panel_reference_contract import source_bound_primary_panel_parents

    references = reference_keys(scientific_prose_text(text))
    blocks = re.findall(r"\\begin\{table\*?\}.*?\\end\{table\*?\}", text, re.DOTALL)
    parents = source_bound_primary_panel_parents(root, blocks)
    return references | {label for label, parent in parents.items() if parent in references}


def checked_asset_prose_references(root: Path, text: str, issues: list[str]) -> set[str]:
    """Record invalid panel provenance as a failing gate, never a workflow exception."""
    try:
        return asset_prose_reference_keys(root, text)
    except ValueError as error:
        issues.append(f"scientific table reference binding is invalid: {error}")
        return reference_keys(scientific_prose_text(text))
