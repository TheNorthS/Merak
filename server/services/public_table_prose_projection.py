"""Move long public table prose to source-bound paragraphs without shortening science."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .paper_evidence import _latex
from .semantic_table import MAX_PUBLIC_TABLE_CELL_CHARACTERS, SemanticTableContractError


@dataclass(frozen=True)
class PublicTableProjection:
    """Exact rendered rows and complete original-public wording in prose notes."""

    rows: list[dict[str, str]]
    metadata: dict[str, Any]
    prose: str


def project_public_table_prose(
    table_id: str, rows: list[dict[str, str]], *, identity_key: str,
    column_labels: dict[str, str], source_bindings: list[dict[str, Any]],
    column_kinds: dict[str, str] | None = None,
) -> PublicTableProjection:
    """Preserve every original cell; long text gets an explicit visible note reference."""
    if len(rows) != len(source_bindings):
        raise ValueError(f"{table_id}: every public row requires source bindings")
    public_rows = [dict(row) for row in rows]
    notes = []
    for index, row in enumerate(rows):
        for key, value in row.items():
            if len(str(value)) <= MAX_PUBLIC_TABLE_CELL_CHARACTERS:
                continue
            if (column_kinds or {}).get(key, "text") != "text":
                raise SemanticTableContractError(
                    "Oversized numeric or interval evidence cannot be moved to prose",
                    table_label="tab:" + table_id.replace("_", "-"), row_index=index, column_key=key,
                )
            if key not in column_labels:
                raise ValueError(f"{table_id}: public column {key} has no declared label")
            bindings = source_bindings[index].get(key) or []
            if not bindings:
                raise ValueError(f"{table_id}: long public {key} has no scientific source binding")
            number = len(notes) + 1
            reference = f"{column_labels[key]} details (Note {number})"
            public_rows[index][key] = reference
            notes.append({
                "note_id": f"{table_id}-note-{number}", "note_number": number,
                "row_index": index, "row_label": str(row[identity_key]), "column_key": key,
                "column_label": column_labels[key], "original_public_text": str(value),
                "display_reference": reference, "source_bindings": bindings,
            })
    metadata = {"schema": 1, "table_id": table_id, "identity_key": identity_key,
                "original_public_rows": [dict(row) for row in rows], "compact_rows": public_rows,
                "notes": notes, "source_bindings": source_bindings}
    return PublicTableProjection(public_rows, metadata, publication_note_prose(notes))


def publication_note_prose(notes: list[dict[str, Any]]) -> str:
    """Render full scientific wording outside every table float at normal prose size."""
    paragraphs = []
    for note in notes:
        heading = f"Note {note['note_number']}: {note['row_label']} — {note['column_label']}"
        paragraphs.append(
            "\\par\\noindent\\textbf{" + _latex(heading) + "} "
            + "\\label{note:" + str(note["note_id"]) + "}"
            + _latex(note["original_public_text"]) + "\\par\n"
        )
    return "\n".join(paragraphs)
