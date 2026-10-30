"""Expose the current global citation gap to its bounded literature author."""

from pathlib import Path

from .manuscript_text import bib_keys, citation_keys


def related_work_citation_context(root: Path, minimum: int) -> str:
    if minimum <= 0:
        return ""
    bibliography = bib_keys(root / "paper/references.bib")
    sections = root / "paper/sections"
    used = set()
    for path in sections.glob("*.tex"):
        used.update(citation_keys(path.read_text(encoding="utf-8-sig")))
    verified = used & bibliography
    deficit = max(0, minimum - len(verified))
    return (f"\nGlobal literature coverage: {len(verified)}/{minimum} distinct verified citations in current sections; "
            f"{deficit} additional distinct sources are needed across the manuscript. Repeating already cited keys "
            "does not close this gap. Read relevant evidence in literature/survey.md and the verified bibliography, "
            "then integrate substantive closest-work and assumption-level comparisons in this section. "
            "Do not rely on later sections to meet the global threshold or add irrelevant citation lists. "
            "If relevant verified sources are insufficient, report the concrete source gap.\n"
            f"Already cited keys: {', '.join(sorted(verified)) or '(none)'}\n"
            f"Available unused keys (inventory only, not a relevance recommendation): {', '.join(sorted(bibliography - verified)) or '(none)'}\n")
