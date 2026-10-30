"""Semantic publication policy for manuscript-facing LaTeX tables."""

from __future__ import annotations

import re
from pathlib import Path


_PLACEHOLDERS = (
    r"registered\\?_factor\\?_\d+",
    r"Prespecified method component\s+\d+",
    r"\b(?:Full Method|Published baseline|Matched-capacity baseline)\b",
    r"replace[_ ]with[_ ][A-Za-z0-9_]+",
)
_MACHINE_FIELDS = re.compile(
    r"\b(?:balanced\\?_accuracy|missing\\?_channel\\?_rate|subject\\?_id|"
    r"site\\?_id|analysis\\?_unit\\?_id|source\\?_run\\?_id)\b",
    re.IGNORECASE,
)


def _table_body_rows(text: str) -> list[str]:
    return [row.strip() for body in re.findall(r"\\midrule(.*?)\\bottomrule", text, re.DOTALL)
            for row in re.split(r"\\\\", body) if "&" in row]


def publication_table_issues(
    paper_root: str | Path, table_paths: list[str | Path] | None = None,
) -> list[str]:
    root = Path(paper_root).expanduser().resolve()
    issues: list[str] = []
    candidates = (
        [(Path(value) if Path(value).is_absolute() else root.parent / value).resolve() for value in table_paths]
        if table_paths is not None else list((root / "tables").glob("*.tex"))
    )
    for path in sorted({path for path in candidates if path.is_file()}):
        if not path.is_relative_to(root):
            continue
        try:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            continue
        relative = path.relative_to(root).as_posix()
        for pattern in _PLACEHOLDERS:
            if re.search(pattern, text, re.IGNORECASE):
                issues.append(f"{relative} exposes a generic or placeholder scientific label")
                break
        if _MACHINE_FIELDS.search(text):
            issues.append(f"{relative} exposes machine-field syntax in publication text")
        rows = _table_body_rows(text)
        if len(rows) == 1:
            issues.append(f"{relative} is a one-row standalone table; merge it into prose or a substantive table")
        for row in rows:
            cells = [re.sub(r"\\[A-Za-z]+\{([^}]*)\}", r"\1", cell).strip() for cell in row.split("&")]
            if any(len(re.sub(r"\\[A-Za-z]+", "", cell)) > 180 for cell in cells):
                issues.append(f"{relative} contains paragraph-length table cells")
                break
    return list(dict.fromkeys(issues))
