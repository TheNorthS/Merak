"""Explicit current manuscript wording for method tables, bound to its authored scientific sources."""

import hashlib
import json
import re
from pathlib import Path

from ..utils.atomic_write import atomic_write_json


PRESENTATION = 'paper/METHOD_TABLE_PRESENTATION.json'
SOURCES = ('ideas/SELECTED_IDEA.json', 'paper/sections/03_method.tex', 'paper/sections/04_experiments.tex')


def contains_projected_note_references(rows: list[dict[str, str]]) -> bool:
    """Layout-owned note pointers cannot stand in for authored scientific cells."""
    return any(re.search(r"\bdetails\s*\(Note\s+\d+\)", value, re.IGNORECASE)
               for row in rows for value in row.values())


def _hashes(root: Path) -> dict[str, str]:
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in SOURCES}


def _validate_rows(rows: object, names: list[str]) -> list[dict[str, str]]:
    if not isinstance(rows, list) or len(rows) != len(names):
        raise ValueError('Method table presentation must preserve every original method element')
    for row, name in zip(rows, names):
        if (not isinstance(row, dict) or set(row) != {'component', 'function', 'evaluation'}
                or row['component'] != name or any(not isinstance(value, str) or not value.strip()
                    or len(value) > 3000 for value in row.values())):
            raise ValueError('Method table presentation contains missing, foreign or invalid authored cells')
    # JSON object member order has no meaning. Public table column order does.
    return [{key: row[key] for key in ('component', 'function', 'evaluation')} for row in rows]


def write_method_presentation(root: Path, rows: list[dict[str, str]], *, author: str) -> None:
    """An explicitly requested author correction preserves original design files and records source hashes."""
    if not author.strip():
        raise ValueError('Method table presentation requires author attribution')
    selected = json.loads((root / SOURCES[0]).read_bytes())
    names = [item['publication_name'] for item in selected['mechanisms']]
    rows = _validate_rows(rows, names)
    if contains_projected_note_references(rows):
        raise ValueError('Method-table author must return complete scientific cells, not generated note pointers')
    atomic_write_json(root / PRESENTATION, {'schema': 1, 'author': author, 'source_sha256': _hashes(root),
        'scope': 'current-method-description-and-prospective-controls', 'rows': rows})


def current_method_rows(root: Path, original: list[dict[str, str]]) -> list[dict[str, str]]:
    path = root / PRESENTATION
    if not path.exists():
        return original
    value = json.loads(path.read_bytes())
    if (not isinstance(value, dict) or value.get('schema') != 1 or not value.get('author')
            or value.get('scope') != 'current-method-description-and-prospective-controls'
            or value.get('source_sha256') != _hashes(root)):
        raise ValueError('Current method-table presentation source changed; its author must review the text before rebinding')
    return _validate_rows(value.get('rows'), [row['component'] for row in original])


def presentation_bindings(rows: list[dict[str, str]], source_hashes: dict[str, str]) -> list[dict]:
    return [{key: [{'source_path': PRESENTATION, 'source_sha256': source_hashes[PRESENTATION],
                    'source_symbol': f'/rows/{index}/{key}'}] for key in row} for index, row in enumerate(rows)]
