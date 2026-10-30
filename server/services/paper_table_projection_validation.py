"""Validate public table subtraction without losing source-bound scientific prose.

Consumers only inspect producer-owned CSV, LaTeX and semantic projection. They
never shorten cells, repair notes, or rebind a changed scientific source hash.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .paper_evidence import _latex
from .semantic_table import MAX_PUBLIC_TABLE_CELL_CHARACTERS


def _source_issues(root: Path, binding: Any, expected_text: str = "") -> list[str]:
    if not isinstance(binding, dict):
        return ["public row source binding must be an object"]
    relative = str(binding.get("source_path") or "")
    path = (root / relative).resolve()
    if not relative or not path.is_relative_to(root) or not path.is_file():
        return ["public row source binding is missing or escapes its project"]
    if hashlib.sha256(path.read_bytes()).hexdigest() != binding.get("source_sha256"):
        return [f"public row source binding is stale: {relative}"]
    symbol = str(binding.get("source_symbol") or "")
    if not (expected_text and path.suffix.casefold() == ".json" and symbol.startswith("/")):
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        for part in symbol.lstrip("/").split("/"):
            key = part.replace("~1", "/").replace("~0", "~")
            if isinstance(value, list) and not re.fullmatch(r"0|[1-9]\d*", key):
                return [f"public row source symbol is invalid: {relative}#{symbol}"]
            value = value[int(key)] if isinstance(value, list) else value[key]
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError):
        return [f"public row source symbol is invalid: {relative}#{symbol}"]
    if str(value).strip() != expected_text:
        return [f"public row wording differs from its source symbol: {relative}#{symbol}"]
    return []


def _csv_rows(root: Path, item: dict[str, Any]) -> list[dict[str, str]]:
    path = (root / str(item.get("data_path") or "")).resolve()
    if not path.is_relative_to(root):
        raise ValueError("public table CSV escapes its project")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def public_table_compact_row_issues(compact: list[dict[str, Any]], latex: str) -> list[str]:
    """Check visible per-cell row identity for producer reuse and consumer gates."""
    rows = []
    for body in re.findall(r"\\midrule(.*?)\\bottomrule", latex, re.DOTALL):
        for row in re.split(r"\\\\", body):
            if "&" not in row:
                continue
            cells = re.split(r"(?<!\\)&", row.strip())
            rows.append([" ".join(cell.split()) for cell in cells])
    if len(rows) != len(compact):
        return ["public table LaTeX does not preserve its complete compact row inventory"]
    for row, expected in zip(rows, compact):
        if len(row) != len(expected) or any(
            _latex(str(value)) not in cell for cell, value in zip(row, expected.values())
        ):
            return ["public table LaTeX differs from its exact compact scientific rows"]
    return []


def _note_issues(
    root: Path, projection: dict[str, Any], originals: list[dict[str, Any]],
    compact: list[dict[str, Any]], latex: str,
) -> list[str]:
    notes = projection.get("notes")
    if not isinstance(notes, list):
        return ["public table projection needs a notes list"]
    seen: set[tuple[int, str]] = set()
    issues = []
    for number, note in enumerate(notes, start=1):
        if not isinstance(note, dict):
            issues.append("public table note must be an object")
            continue
        row, key = note.get("row_index"), str(note.get("column_key") or "")
        if not isinstance(row, int) or isinstance(row, bool) or not 0 <= row < len(originals) or key not in originals[row]:
            issues.append("public table note has an invalid row or column binding")
            continue
        if (row, key) in seen:
            issues.append("public table has duplicate notes for one scientific cell")
        seen.add((row, key))
        original = str(originals[row][key])
        expected_id = f"{projection['table_id']}-note-{number}"
        expected_reference = f"{note.get('column_label') or ''} details (Note {number})"
        if (note.get("note_number") != number or note.get("note_id") != expected_id
                or note.get("original_public_text") != original or note.get("display_reference") != expected_reference
                or compact[row].get(key) != expected_reference
                or note.get("row_label") != originals[row].get(projection["identity_key"])):
            issues.append(f"public table Note {number} lost its exact scientific cell binding")
        heading = f"Note {number}: {note.get('row_label')} — {note.get('column_label')}"
        expected = "\\par\\noindent\\textbf{" + _latex(heading) + "} \\label{note:" + expected_id + "}" + _latex(original) + "\\par"
        if expected not in latex or latex.find(expected) < latex.rfind("\\end{table}"):
            issues.append(f"public table Note {number} does not visibly preserve its complete escaped wording outside table floats")
        bindings = note.get("source_bindings") or []
        expected_bindings = (projection["source_bindings"][row].get(key) or [])
        if not isinstance(bindings, list) or not bindings or bindings != expected_bindings:
            issues.append(f"public table Note {number} source binding differs from its scientific row")
            continue
        for binding in bindings:
            issues.extend(_source_issues(root, binding, original))
        for binding in bindings:
            if not isinstance(binding, dict):
                continue
            relative = str(binding.get("source_path") or "")
            path = (root / relative).resolve()
            if path.suffix.casefold() == ".json" and relative.startswith("ideas/") and not str(binding.get("source_symbol") or "").startswith("/"):
                issues.append(f"public table Note {number} has no exact authored-public JSON source symbol")
    expected_cells = {(index, key) for index, row in enumerate(originals) for key, value in row.items()
                      if len(str(value)) > MAX_PUBLIC_TABLE_CELL_CHARACTERS}
    if seen != expected_cells:
        issues.append("public table notes do not exactly cover the long scientific cells")
    for index, row in enumerate(originals):
        for key, value in row.items():
            if (index, key) not in expected_cells and compact[index].get(key) != value:
                issues.append("public table projection altered a bounded scientific cell")
    return issues


def table_publication_projection_issues(root: Path, item: dict[str, Any]) -> list[str]:
    """Reject stale or lossy notes before a producer or consumer accepts hashes."""
    projection = item.get("publication_projection")
    if projection is None:
        return []
    if not isinstance(projection, dict) or projection.get("schema") != 1:
        return ["public table projection schema is unsupported"]
    originals, compact = projection.get("original_public_rows"), projection.get("compact_rows")
    bindings = projection.get("source_bindings")
    identity = projection.get("identity_key")
    if (projection.get("table_id") != item.get("id") or not isinstance(identity, str)
            or not isinstance(originals, list) or not originals or not isinstance(compact, list)
            or not isinstance(bindings, list) or len(originals) != len(compact) or len(originals) != len(bindings)
            or any(not isinstance(row, dict) or identity not in row for row in originals)
            or any(not isinstance(row, dict) for row in compact + bindings)):
        return ["public table projection has invalid scientific row identities"]
    if any(set(row) != set(original) for row, original in zip(compact, originals)):
        return ["public table projection changed registered scientific columns"]
    try:
        if _csv_rows(root, item) != compact:
            return ["public table CSV differs from its exact compact public rows"]
        path = (root / str(item.get("latex_path") or "")).resolve()
        if not path.is_relative_to(root):
            return ["public table LaTeX escapes its project"]
        latex = path.read_text(encoding="utf-8-sig")
        issues = public_table_compact_row_issues(compact, latex)
        issues.extend(_note_issues(root, projection, originals, compact, latex))
        for index, row in enumerate(bindings):
            for key, values in row.items():
                for binding in values if isinstance(values, list) else [values]:
                    issues.extend(_source_issues(root, binding, str(originals[index].get(key) or "")))
        return list(dict.fromkeys(issues))
    except (OSError, UnicodeError, ValueError) as exc:
        return [f"public table projection cannot be verified: {exc}"]
