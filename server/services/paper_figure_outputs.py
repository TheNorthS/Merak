"""Project admitted scientific figures into LaTeX include bundles."""

from __future__ import annotations

import re
from typing import Any

from ..utils.atomic_write import atomic_write_text
from .paper_evidence import (
    PaperEvidence,
    _figure_publication_caption,
    _first_publication_text,
    _latex,
)

_RESULT_ROLES = frozenset({
    "result", "ablation", "robustness", "analysis", "efficiency",
    "calibration", "error_analysis", "sensitivity", "training_dynamics",
})
_EVALUATION_ROLES = frozenset({"evaluation_design", "dataset", "data", "study_overview"})
_EXCLUDED_ROLES = frozenset({
    "protocol", "administrative", "claim_map", "execution_status",
    "experimental_design", "internal_protocol",
})
_EXCLUDED_STATUS = frozenset({
    "placeholder", "synthetic", "synthetic_preview", "administrative", "internal",
})


def write_paper_figure_bundles(evidence: PaperEvidence) -> None:
    paper_dir = evidence.root / "paper"
    paper_dir.mkdir(parents=True, exist_ok=True)
    groups: dict[str, list[str]] = {
        "generated_figures.tex": [],
        "generated_method_figures.tex": [],
        "generated_evaluation_figures.tex": [],
        "generated_result_figures.tex": [],
    }
    used: set[str] = set()
    for index, item in enumerate(evidence.figures[:4], start=1):
        projected = _project_figure(item, index, used)
        if projected is None:
            continue
        block, role = projected
        groups["generated_figures.tex"].append(block)
        groups[_group_name(role)].append(block)
    for filename, blocks in groups.items():
        atomic_write_text(
            paper_dir / filename,
            "\n\n".join(blocks) + ("\n" if blocks else ""),
        )


def _project_figure(
    item: dict[str, Any], index: int, used: set[str]
) -> tuple[str, str] | None:
    output = str(item.get("paper_path") or "")
    metadata = dict(item.get("metadata") or {})
    role = str(metadata.get("scientific_role") or "").casefold()
    status = str(metadata.get("evidence_status") or "").casefold()
    if not output or role in _EXCLUDED_ROLES or status in _EXCLUDED_STATUS:
        return None
    slug = _unique_slug(item, metadata, index, used)
    metadata["label"] = f"fig:{slug}"
    item["metadata"] = metadata
    caption = _publication_caption(item, metadata, role, index)
    block = rf"""\begin{{figure*}}[t]
\centering
\includegraphics[width=0.94\textwidth]{{{output}}}
\caption{{{_latex(caption)}}}
\label{{fig:{slug}}}
\end{{figure*}}"""
    return block, role


def _unique_slug(
    item: dict[str, Any], metadata: dict[str, Any], index: int, used: set[str]
) -> str:
    label = str(metadata.get("label") or "").strip()
    description = str(item.get("description") or "").lower()
    if label.startswith("fig:"):
        slug = label[4:]
    elif "method" in description:
        slug = "method-overview"
    elif "novelty" in description or "reference-to" in description:
        slug = "novelty-delta"
    elif "claim" in description or "evidence" in description:
        slug = "evidence-workflow"
    elif "readiness" in description:
        slug = "artifact-readiness"
    else:
        slug = f"artifact-{index}"
    if slug in used:
        slug = f"{slug}-{index}"
    used.add(slug)
    return slug


def _publication_caption(
    item: dict[str, Any], metadata: dict[str, Any], role: str, index: int
) -> str:
    brief = metadata.get('method_brief') or {}
    if role == 'evaluation_design' and (brief.get('evaluation_conditions') or {}).get('mode') == 'declared_conditions':
        from .scientific_asset_builders import _evaluation_caption
        return _evaluation_caption(brief)
    caption = _first_publication_text(
        {**item, **metadata, "item_caption": item.get("caption"),
         "item_description": item.get("description")},
        ("publication_caption", "caption_en", "english_caption", "caption",
         "item_caption", "item_description"),
        _figure_publication_caption(role, index),
        reject_meta=True,
    )
    caption = re.sub(
        r"(?<![A-Za-z0-9])(?:C|M|F|I)\d+(?![A-Za-z0-9])", "", str(caption)
    )
    return " ".join(caption.split())


def _group_name(role: str) -> str:
    if role in _RESULT_ROLES:
        return "generated_result_figures.tex"
    if role in _EVALUATION_ROLES:
        return "generated_evaluation_figures.tex"
    return "generated_method_figures.tex"
