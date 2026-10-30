"""Place only missing selected assets beside their reviewed scientific sections.

Authored sections and producer-owned asset bundles remain immutable. A figure
is already present only when one real figure environment uses both its public
label and its canonical graphic. Partial bundles get assembly-owned fragments;
unregistered design prose is never appended as a substitute for a selected table.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from .latex_bundle import GRAPHIC_EXTENSIONS, _reachable_sources, _resolve, _tex_text
from .manuscript_text import write_text_if_changed
from .paper_asset_reference_contract import PublicationAssetReference, selected_publication_references
from .paper_profile import FIGURE_ROLE_ALIASES, TABLE_ROLE_ALIASES


_FIGURE_FILES = ("generated_method_figures.tex", "generated_evaluation_figures.tex",
                 "generated_result_figures.tex", "synthetic_preview_figures.tex")
_FLOAT = re.compile(r"\\begin\{(figure\*?|table\*?|longtable)\}(.*?)\\end\{\1\}", re.DOTALL)
_LABEL = re.compile(r"\\label\s*\{([^}]+)\}")
_GRAPHIC = re.compile(r"\\includegraphics(?:\s*\[[^]]*\])?\s*\{([^}]+)\}")


@dataclass(frozen=True)
class AssetPlacement:
    """One actual include and its hash-bound assembly input identity."""

    stage: str
    path: Path
    text: str
    source_sha256: str
    assembly_owned: bool = False


def section_asset_placements(root: Path, sections: list[tuple[str, Path]]) -> tuple[AssetPlacement, ...]:
    """Compute selected missing inputs without writing or accepting any artifact."""
    root = root.resolve()
    references = selected_publication_references(root)
    if not references:
        return ()
    sources = _section_sources(root, sections)
    stages = {_section_stage(name) for name, _path in sections}
    missing_figures = [item for item in references if item.kind == "figure" and not _figure_used(root, item, sources)]
    figures = _figure_placements(root, missing_figures)
    tables = _table_placements(root, [item for item in references if item.kind == "table"], sources)
    placements = (*figures, *tables)
    if any(item.stage not in stages for item in placements):
        raise ValueError("Selected scientific asset has no owning manuscript section")
    return placements


def write_assembly_fragments(placements: tuple[AssetPlacement, ...]) -> None:
    """Only new assembly-owned fragments may be materialized; never edit authorship."""
    for item in placements:
        if item.assembly_owned:
            write_text_if_changed(item.path, item.text)


def _section_stage(name: str) -> str:
    return name.split("_", 1)[-1]


def _section_sources(root: Path, sections: list[tuple[str, Path]]) -> dict[Path, str]:
    sources = {source for _name, path in sections
               for source in _reachable_sources(path, root / "paper", root)}
    return {path: _tex_text(path) for path in sorted(sources)}


def _graphic_paths(root: Path, source: Path, text: str, context: str) -> set[Path]:
    bases = [root / "paper", source.parent, root]
    # These are the explicit graphicspath roots installed by manuscript assembly.
    bases.extend(root / f"figures/{directory}" for directory in ("plots", "diagrams", "assets"))
    for block in re.findall(r"\\graphicspath\s*\{((?:\{[^}]*\}\s*)+)\}", context):
        bases.extend((base / raw).resolve() for raw in re.findall(r"\{([^}]*)\}", block)
                     for base in (root / "paper", source.parent)
                     if (base / raw).resolve().is_relative_to(root))
    return {path for raw in _GRAPHIC.findall(text)
            if (path := _resolve(raw, bases, root, GRAPHIC_EXTENSIONS)) is not None}


def _bound_figure_blocks(root: Path, reference: PublicationAssetReference,
                         source: Path, text: str) -> list[str]:
    graphic = (root / reference.source_path).resolve()
    if not graphic.is_relative_to(root) or not graphic.is_file():
        raise ValueError(f"Selected figure {reference.label} has no canonical local graphic")
    blocks = []
    for match in _FLOAT.finditer(text):
        if (match.group(1).startswith("figure") and _LABEL.findall(match.group()) == [reference.label]
                and graphic in _graphic_paths(root, source, match.group(), text)):
            blocks.append(match.group())
    return blocks


def _figure_used(root: Path, reference: PublicationAssetReference, sources: dict[Path, str]) -> bool:
    matches = [block for path, text in sources.items() for block in _bound_figure_blocks(root, reference, path, text)]
    labels = sum(_LABEL.findall(text).count(reference.label) for text in sources.values())
    if labels > 1 or labels and not matches:
        raise ValueError(f"Selected figure {reference.label} is duplicated or not bound to its canonical graphic")
    return bool(matches)


def _stage(reference: PublicationAssetReference) -> str:
    if reference.kind == "figure":
        if reference.scientific_role in FIGURE_ROLE_ALIASES["method"]:
            return "method"
        if reference.scientific_role in FIGURE_ROLE_ALIASES["evaluation_design"]:
            return "experiments"
    elif reference.scientific_role == "method_components":
        return "method"
    elif reference.scientific_role in TABLE_ROLE_ALIASES["dataset_summary"]:
        return "experiments"
    return "results"


def _figure_placements(root: Path, missing: list[PublicationAssetReference]) -> list[AssetPlacement]:
    candidates = {root / "paper" / name: _tex_text(root / "paper" / name) for name in _FIGURE_FILES}
    by_stage: dict[str, list[str]] = {}
    bindings: dict[str, list[str]] = {}
    for reference in missing:
        matched = [(path, block) for path, text in candidates.items()
                   for block in _bound_figure_blocks(root, reference, path, text)]
        unique = {block for _path, block in matched}
        if len(unique) != 1:
            raise ValueError(f"Missing selected figure {reference.label} has no unique canonical producer block")
        stage = _stage(reference)
        by_stage.setdefault(stage, []).append(next(iter(unique)))
        bindings.setdefault(stage, []).extend(hashlib.sha256(path.read_bytes()).hexdigest() for path, _block in matched)
        bindings[stage].append(_asset_input_signature(root, reference))
    return [_assembly_placement(root, stage, "figures", blocks, bindings[stage])
            for stage, blocks in by_stage.items()]


def _asset_input_signature(root: Path, reference: PublicationAssetReference) -> str:
    """Bind placement to the current selection, public identity and canonical pixels."""
    digest = hashlib.sha256(repr(reference).encode("utf-8"))
    for relative in (reference.source_path, "figures/FIGURE_MANIFEST.json", "figures/SCIENTIFIC_ASSET_PLAN.json"):
        path = (root / relative).resolve()
        if not path.is_relative_to(root):
            raise ValueError("Scientific placement input leaves its project")
        digest.update(relative.encode("utf-8"))
        digest.update(path.read_bytes() if path.is_file() else b"<missing>")
    return digest.hexdigest()


def _assembly_placement(root: Path, stage: str, kind: str, blocks: list[str], bindings: list[str]) -> AssetPlacement:
    content = "\n\n".join(blocks) + "\n"
    digest = hashlib.sha256(("\n".join(bindings) + "\n" + content).encode("utf-8")).hexdigest()
    text = f"% Assembly input SHA256: {digest}\n" + content
    return AssetPlacement(stage, root / f"paper/assembly_{stage}_{kind}.tex", text, digest, True)


def _table_placements(root: Path, references: list[PublicationAssetReference],
                      sources: dict[Path, str]) -> list[AssetPlacement]:
    by_path: dict[Path, list[PublicationAssetReference]] = {}
    for item in references:
        by_path.setdefault((root / item.source_path).resolve(), []).append(item)
    placements = []
    for path, selected in by_path.items():
        if path in sources:
            continue
        text = _tex_text(path)
        labels = {label for match in _FLOAT.finditer(text) if not match.group(1).startswith("figure")
                  for label in _LABEL.findall(match.group())}
        selected_labels = {item.label for item in selected}
        if not labels or labels != selected_labels:
            raise ValueError("Selected table bundle has no exact source-bound scientific float inventory")
        used = {item.label for item in selected if any(
            item.label in _LABEL.findall(match.group()) for body in sources.values() for match in _FLOAT.finditer(body)
            if not match.group(1).startswith("figure")
        )}
        if used:
            if used == selected_labels:
                continue
            raise ValueError("A partially authored selected table bundle requires its table producer to partition it")
        stages = {_stage(item) for item in selected}
        if len(stages) != 1 or not path.is_relative_to(root / "paper"):
            raise ValueError("Selected table bundle has no unique local manuscript placement")
        placements.append(AssetPlacement(next(iter(stages)), path, text, hashlib.sha256(path.read_bytes()).hexdigest()))
    return placements
