"""Bounded local printed-figure repair, never model or research regeneration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Awaitable, Callable

from .paper_layout_errors import PaperPublicationLayoutError
from .paper_pdf_quality import inspect_compiled_paper


def _json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(payload, dict):
        raise ValueError('Printed figure inventory must be an object')
    return payload


def _placed_minimum(root: Path, entry: dict[str, Any], width_bp: float) -> float:
    from .publication_pdf_fonts import minimum_readable_font_pt
    import fitz
    original = (root / str(entry.get('output_path') or '')).resolve()
    if not original.is_relative_to(root) or original.suffix.casefold() != '.pdf':
        raise ValueError('Printed font measurement requires a local source PDF')
    with fitz.open(original) as document:
        if len(document) != 1 or not document[0].rect.width:
            raise ValueError('Printed figure requires exactly one verified PDF page')
        return minimum_readable_font_pt(document[0]) * width_bp / float(document[0].rect.width)


async def prepare_print_figures(root: Path) -> list[dict[str, Any]]:
    """Repair unreadable or semantically mislabelled trusted paper presentations."""
    from .publication_print_contract import read_publication_print_contract
    from .paper_derived_figure_rendering import derive_paper_figure
    from .paper_print_projection import install_print_projection, restore_print_entrypoint
    from .paper_plot_semantics_projection import requires_source_presentation_projection
    from .paper_print_producer_findings import scoped_print_projection_error
    root = root.resolve()
    restore_print_entrypoint(root)
    manifest = root / 'figures/FIGURE_MANIFEST.json'
    if not manifest.exists():
        return []
    entries = _json(manifest).get('figures') or []
    contract = read_publication_print_contract(root).to_dict()
    placements = contract.get('placements') or []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in placements:
        grouped.setdefault(item['graphic_relative'], []).append(item)
    packets = []
    for entry in entries:
        positions = grouped.get(str(entry.get('output_path') or ''), [])
        if not positions:
            continue
        try:
            width = min(float(row['width_bp']) for row in positions)
            if _placed_minimum(root, entry, width) >= 8.0 and not requires_source_presentation_projection(root, entry):
                continue
            placement = {**min(positions, key=lambda row: row['width_bp']),
                         'print_contract': contract, 'contract_sha256': contract['contract_sha256'],
                         'target_font_bp': 8.5, 'minimum_font_bp': 8.0}
            packets.append(await derive_paper_figure(root, entry, placement))
        except ValueError as error:
            scoped = scoped_print_projection_error(entry, error)
            if scoped is error:
                raise
            raise scoped from error
    if packets:
        install_print_projection(root, packets)
    return packets


def _repairs(root: Path) -> list[dict[str, Any]]:
    payload = _json(root / '.merak/quality/paper-layout.json')
    return [row for row in payload.get('repair_findings') or [] if isinstance(row, dict)]


async def compile_print_verified_paper(
    compiler: Any, root: str | Path, *, on_repair: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
) -> Any:
    """At most two local compile/layout rounds; a passing fresh gate alone advances."""
    root = Path(root).resolve()
    for attempt in range(1, 3):
        if attempt == 1:
            try:
                packets = await prepare_print_figures(root)
            except ValueError as error:
                from .paper_print_producer_findings import print_projection_finding
                finding = print_projection_finding(error)
                raise PaperPublicationLayoutError([str(error)], [finding],
                    attempts=len(finding['render_attempts'])) from error
            if packets and on_repair:
                await on_repair({'attempt': attempt, 'asset_ids': [row.get('asset_id') for row in packets],
                                 'model_invoked': False, 'scientific_inputs_modified': False})
        result = await compiler.compile(str(root / 'paper'), 'main.tex', clean=True)
        if not result.success:
            return result
        import asyncio
        _layout, issues = await asyncio.to_thread(inspect_compiled_paper, compiler, root, result.pdf_path)
        if not issues:
            return result
        # Producers already performed their bounded local fit. Never ask an author
        # to rewrite prose, or recompile identical geometry hoping it will pass.
        raise PaperPublicationLayoutError(issues, _repairs(root), attempts=attempt)
    raise AssertionError('Printed manuscript compile budget exhausted without a verdict')
