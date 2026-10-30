"""Inspect source-authored table labels and captions without aliasing or repair."""

from __future__ import annotations

import re


def _caption(block: str) -> str:
    match = re.search(r"\\caption(?:\[[^]]*\])?\s*\{", block)
    if match is None:
        raise ValueError("Registered publication table source has no caption")
    depth, start = 1, match.end()
    for position in range(start, len(block)):
        character = block[position]
        if position > start and block[position - 1] == "\\":
            continue
        depth += 1 if character == "{" else -1 if character == "}" else 0
        if depth == 0:
            return block[start:position]
    raise ValueError("Registered publication table caption is unbalanced")


def selected_table_source_records(text: str) -> dict[str, dict[str, str]]:
    """Every public label resolves to exactly one real table float."""
    result = {}
    for block in re.findall(r"\\begin\{table\*?\}.*?\\end\{table\*?\}", text, re.DOTALL):
        labels = re.findall(r"\\label\{([^}]+)\}", block)
        if len(labels) != 1 or not labels[0].startswith("tab:") or labels[0] in result:
            raise ValueError("Registered table source needs one unique public label per table")
        result[labels[0]] = {"caption": _caption(block), "source": block}
    return result
