"""Resolve manuscript includes and graphic paths within the paper root."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional


def expand_tex_source(
    source: Path, source_text: dict[Path, str], paper_root: Path, stack: set[Path]
) -> str:
    resolved = source.resolve()
    if resolved in stack:
        return ""
    content = source_text.get(resolved, "")
    if not content:
        return ""
    next_stack = {*stack, resolved}

    def replace_input(match: re.Match[str]) -> str:
        raw_ref = match.group(1).strip()
        if not raw_ref:
            return ""
        for candidate in (paper_root / raw_ref, resolved.parent / raw_ref):
            if candidate.suffix.lower() != ".tex":
                candidate = candidate.with_suffix(".tex")
            candidate = candidate.resolve()
            if candidate in source_text:
                return expand_tex_source(candidate, source_text, paper_root, next_stack)
        return match.group(0)

    return re.sub("\\\\(?:input|include)\\{([^}]+)\\}", replace_input, content)


def resolve_graphic_path(
    raw_path: str, paper_root: Path, root: Path, manifest_outputs: list[Path]
) -> Optional[Path]:
    raw_path = raw_path.strip()
    if not raw_path or "\\" in raw_path or "{" in raw_path:
        return None
    raw = Path(raw_path)
    bases = [paper_root / raw, root / raw]
    for base in bases:
        candidates = (
            [base]
            if base.suffix
            else [
                base.with_suffix(ext)
                for ext in (".pdf", ".png", ".jpg", ".jpeg", ".svg")
            ]
        )
        for candidate in candidates:
            if (
                candidate.exists()
                and candidate.is_file()
                and (candidate.stat().st_size > 0)
            ):
                return candidate.resolve()
    raw_name = raw.name
    for candidate in manifest_outputs:
        if candidate.name == raw_name or candidate.stem == raw.stem:
            return candidate
    return None
