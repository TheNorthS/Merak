"""Resolve the real section author of a scientific float, without editing it.

An existing unique authored float is ownership evidence even without a selected
manifest record. Assembly-only assets need current selected source/placement
proof. Labels identify assets, never infer author roles from their spelling.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from .latex_bundle import _reachable_sources, _tex_text
from .paper_asset_placement import (
    _FLOAT, _LABEL, _bound_figure_blocks, section_asset_placements,
)
from .paper_asset_reference_contract import PublicationAssetReference, selected_publication_references
from .paper_profile import FIGURE_ROLE_ALIASES, TABLE_ROLE_ALIASES


def _matching_float(reference: PublicationAssetReference | None, label: str,
                     root: Path, path: Path, text: str) -> bool:
    if reference and reference.kind == "figure":
        return bool(_bound_figure_blocks(root, reference, path, text))
    return any(label in _LABEL.findall(block.group()) for block in _FLOAT.finditer(text))


def _placement_role_stage(reference: PublicationAssetReference) -> str:
    role = reference.scientific_role
    if reference.kind == "figure":
        if role in FIGURE_ROLE_ALIASES["method"]:
            return "method"
        if role in FIGURE_ROLE_ALIASES["evaluation_design"]:
            return "experiments"
        result_roles = set().union(*(values for name, values in FIGURE_ROLE_ALIASES.items()
                                    if name not in {"method", "evaluation_design"}))
        if role in result_roles | {"analysis", "training_dynamics"}:
            return "results"
    else:
        if role == "method_components":
            return "method"
        if role in TABLE_ROLE_ALIASES["dataset_summary"]:
            return "experiments"
        if role in set().union(*(values for name, values in TABLE_ROLE_ALIASES.items()
                                if name != "dataset_summary")):
            return "results"
    raise ValueError("Assembly-only scientific asset has no declared author role: " + reference.label)


def unreferenced_asset_author(root: Path, label: str, specs: Iterable[Any]) -> tuple[str, str]:
    """Require one real authored/assembly placement; unknown ownership stays blocked."""
    root = root.resolve()
    specifications = tuple(specs)
    sources = {item.id: root / f"paper/sections/{item.filename}" for item in specifications}
    selected = [item for item in selected_publication_references(root) if item.label == label]
    if len(selected) > 1:
        raise ValueError("Scientific asset has conflicting selected source identities: " + label)
    reference = selected[0] if selected else None
    owners = set()
    for stage, path in sources.items():
        for source in _reachable_sources(path, root / "paper", root):
            if _matching_float(reference, label, root, source, _tex_text(source)):
                owners.add(stage)
    if len(owners) > 1:
        raise ValueError("Scientific asset is included by multiple authored sections: " + label)
    if owners:
        stage = next(iter(owners))
        return stage, sources[stage].relative_to(root).as_posix()
    if reference is None:
        raise ValueError("Unreferenced scientific asset has no unique authored source or selected placement: " + label)
    sections = [(Path(item.filename).stem, sources[item.id]) for item in specifications]
    placements = section_asset_placements(root, sections)
    placed = {item.stage for item in placements
              if _matching_float(reference, label, root, item.path, item.text)}
    expected = _placement_role_stage(reference)
    if placed != {expected} or expected not in sources:
        raise ValueError("Selected scientific asset has no unique source-bound author placement: " + label)
    return expected, sources[expected].relative_to(root).as_posix()
