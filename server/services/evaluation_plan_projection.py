"""Project one explicit plan-table split without inventing scientific semantics.

The canonical registered plan supplies its own label and complete definition.
Publication uses the authored label before a colon; the full source cell and
raw-file hash remain invisible provenance. Ambiguous declarations fail closed.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any


PLAN_SOURCE = "experiments/EXPERIMENT_PLAN.md"
_FIELD = re.compile(r"^\s*(?:\*\*)?Primary split(?:\*\*)?\s*$", re.IGNORECASE)


def split_label(value: str) -> str:
    """Keep the source-authored split name, not its explanatory paragraph."""
    return value.partition(":")[0].strip().replace(r"\|", "|")


def split_labels_agree(left: str, right: str) -> bool:
    """Compare spelling only; do not equate different scientific holdout axes."""
    def normalized(value: str) -> str:
        return re.sub(r"[\s_-]+", " ", split_label(value).casefold())

    return normalized(left) == normalized(right)


def _table_cells(line: str) -> list[str]:
    """An odd backslash escapes a pipe; an even run does not escape a separator."""
    cells, current, backslashes = [], [], 0
    for character in line.strip():
        if character == "|" and backslashes % 2 == 0:
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(character)
        backslashes = backslashes + 1 if character == "\\" else 0
    cells.append("".join(current).strip())
    return cells[1:]


def declared_plan_split(raw: bytes | None) -> dict[str, str] | None:
    """Read exactly one named table field; absence does not imply a held-out split."""
    if raw is None:
        return None
    if not isinstance(raw, bytes):
        raise ValueError("evaluation_design registered plan source must be raw bytes")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeError as error:
        raise ValueError("evaluation_design registered plan source is not UTF-8") from error
    declarations, fence = [], ""
    for line_number, line in enumerate(text.splitlines(), 1):
        marker = re.match(r"^\s*(`{3,}|~{3,})", line)
        if marker:
            candidate = marker[1][0]
            fence = "" if fence == candidate else candidate if not fence else fence
            continue
        if fence:
            continue
        if not line.lstrip().startswith("|"):
            continue
        cells = _table_cells(line)
        if cells and _FIELD.fullmatch(cells[0]):
            declarations.append((line_number, cells[1] if len(cells) > 1 else ""))
    if not declarations:
        return None
    if len(declarations) != 1:
        raise ValueError("evaluation_design registered plan has multiple Primary split declarations")
    line_number, definition = declarations[0]
    label = split_label(definition)
    if not label or label.casefold() in {"-", "tbd", "todo", "pending", "unknown", "unspecified"}:
        raise ValueError("evaluation_design registered plan Primary split lacks an explicit named split")
    return {"display_name": label, "source_path": PLAN_SOURCE,
            "source_symbol": f"markdown.table.Primary split:line:{line_number}",
            "source_sha256": hashlib.sha256(raw).hexdigest(), "source_text": definition}


def bind_plan_split(protocol: dict[str, Any], raw: bytes | None) -> None:
    """Combine agreeing explicit facts; never choose between conflicting sources."""
    declared = declared_plan_split(raw)
    if declared is None:
        return
    primary = str(protocol.get("primary_split") or "").strip()

    if primary and not split_labels_agree(primary, declared["display_name"]):
        raise ValueError("evaluation_design structured and registered-plan primary splits conflict")
    binding = {key: value for key, value in declared.items() if key != "display_name"}
    if primary:
        protocol.setdefault("source_bindings", {})["primary_split_plan"] = binding
    else:
        protocol["primary_split"] = declared["display_name"]
        protocol.setdefault("source_bindings", {})["primary_split"] = binding
