"""Render small scientific design records as prose rather than one-row tables."""

from typing import Any

from .paper_evidence import _latex


def design_records_prose(rows: list[dict[str, Any]], *, identity_key: str) -> str:
    """Preserve every public field without creating a fake tabular comparison."""
    paragraphs = []
    for row in rows:
        identity = _latex(str(row[identity_key]))
        values = " ".join(
            _latex(key.replace("_", " ").capitalize()) + ": " + _latex(value) + "."
            for key, value in row.items() if key != identity_key and str(value).strip()
        )
        paragraphs.append("\\par\\noindent\\textbf{" + identity + "}. " + values + "\\par\n")
    return "\n".join(paragraphs)
