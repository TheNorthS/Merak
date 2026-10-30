"""Resolve only current native FigureSpec JSON to its exact source-bound SVG.

Canonical JSON identity and every original source/variant remain immutable.
No arbitrary JSON, guessed SVG path, current-hash substitute or source program
execution can enter the paper-only typography producer through this resolver.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def figurespec_implementation_paths(services_root: Path) -> list[Path]:
    """Reuse native producer dependencies in paper, review and slide signatures.

    Discovery does not load a configured renderer or execute a scientific source.
    The existing producer resolver owns packaged skill paths and runtime source
    mirrors; actual source resolution separately verifies loaded native code.
    """
    from .deterministic_figure_builder import _ARCHITECTURE_CODE_MODULES
    from .figure_delegate_budget import _code_source_path

    names = {"paper_figurespec_source", "paper_figurespec_typography", "deterministic_figure_freshness",
             *_ARCHITECTURE_CODE_MODULES}
    return [*(services_root / f"{name}.py" for name in sorted(names)),
            *(_code_source_path(f"../merak-skills/figure-spec/scripts/{name}.py")
              for name in ("figure_renderer", "figure_semantic_rendering"))]


def figurespec_svg_source(root: Path, entry: dict[str, Any]) -> tuple[Path, bytes, dict]:
    """Recompute the native scene/compiler/renderer closure before paper projection."""
    from .deterministic_figure_freshness import _contracts, current_design_input_sha256
    from .figure_engine import _load_figurespec_renderer
    from .figurespec_layout_policy import figurespec_layout_issues_payload
    from .paper_derived_figure_binding import bound_original_inputs, local_path
    from .paper_derived_figure_rendering import _current_entry
    from .scientific_scene_figure import compile_scientific_scene_figure

    metadata = entry.get("metadata") or {}
    identity = str(metadata.get("semantic_key") or entry.get("id") or "")
    source = local_path(root, entry.get("source_path"))
    if (source.suffix.casefold() != ".json" or metadata.get("producer_kind") != "deterministic"
            or metadata.get("production_strategy") != "deterministic_architecture"
            or metadata.get("recommended_backend") != "figurespec"
            or metadata.get("renderer") != "figurespec-v2"
            or metadata.get("source_faithful") != "deterministic-json-to-svg-same-source"
            or _current_entry(root, identity) != entry):
        raise ValueError("Paper FigureSpec requires its exact current native deterministic producer")
    bound_original_inputs(root, entry)
    plan, specifications = _contracts(root, [entry])
    spec = specifications[identity]
    if metadata.get("producer_input_sha256") != current_design_input_sha256(spec, plan):
        raise ValueError("Paper FigureSpec producer inputs or loaded implementation are stale")
    compiled = compile_scientific_scene_figure(spec)
    payload = json.loads(source.read_text(encoding="utf-8-sig"))
    if payload != compiled.spec or metadata.get("element_mappings") != compiled.element_mappings:
        raise ValueError("Paper FigureSpec JSON differs from its current scientific scene or source mappings")
    renderer = _load_figurespec_renderer()
    issues = [*renderer.validate_spec(payload), *figurespec_layout_issues_payload(payload)]
    if issues:
        raise ValueError("Paper FigureSpec source is invalid: " + "; ".join(map(str, issues)))
    svg = local_path(root, metadata["rendered_variants"]["svg"])
    expected = renderer.render_svg(payload).encode("utf-8")
    if svg.read_bytes() != expected:
        raise ValueError("Paper FigureSpec SVG differs from its exact current native JSON renderer")
    return svg, expected, payload


def projected_figurespec_svg(root: Path, entry: dict[str, Any], multiplier: float) -> bytes:
    """The same pure source resolution and typography also drive read-only pixel proof."""
    from .figure_engine import _load_figurespec_renderer
    from .paper_figurespec_typography import render_figurespec_typography

    _source, _original, spec = figurespec_svg_source(root, entry)
    return render_figurespec_typography(spec, _load_figurespec_renderer(), multiplier).encode("utf-8")
