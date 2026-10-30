"""Collect explicitly declared inputs of already validated retained public tables.

The publication refresh owns only its new simulation projection. Retained
tables and their scientific/prose sources are copied into the transaction for
the unchanged full validator, never regenerated or rebound to changed sources.
"""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
import re
from typing import Any


def retained_table_input_hashes(root: Path, entries: list[dict[str, Any]]) -> dict[str, str]:
    """Hash the complete declared local dependency closure, rejecting stale bindings.

    Callers first validate each retained table's public rows and data/LaTeX
    hashes. These hashes additionally freeze every copied source until commit.
    Only named path fields and typed public-cell bindings are traversed.
    """
    root = root.resolve()
    hashes: dict[str, str] = {}
    for entry in entries:
        for path_key, hash_key in (("data_path", "data_sha256"), ("latex_path", "latex_sha256")):
            _include_source(root, hashes, entry.get(path_key), entry.get(hash_key), require_expected=True)
        sources = entry.get("source_data", [])
        if not isinstance(sources, list):
            raise ValueError("Retained publication table source_data must be a path list")
        for relative in sources:
            _include_source(root, hashes, relative)
        for binding in _projection_bindings(entry.get("publication_projection")):
            _include_source(root, hashes, binding.get("source_path"), binding.get("source_sha256"),
                            require_expected=True)
    return hashes


def _projection_bindings(projection: Any) -> list[dict[str, Any]]:
    if projection is None:
        return []
    if not isinstance(projection, dict):
        raise ValueError("Retained public projection must be an object")
    rows, notes = projection.get("source_bindings"), projection.get("notes")
    if not isinstance(rows, list) or not isinstance(notes, list):
        raise ValueError("Retained public projection must declare row bindings and notes")
    bindings: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Retained public row bindings must be objects")
        for values in row.values():
            bindings.extend(_binding_list(values))
    for note in notes:
        if not isinstance(note, dict):
            raise ValueError("Retained public notes must be objects")
        bindings.extend(_binding_list(note.get("source_bindings")))
    return bindings


def _binding_list(value: Any) -> list[dict[str, Any]]:
    values = value if isinstance(value, list) else [value]
    if any(not isinstance(binding, dict) for binding in values):
        raise ValueError("Retained public source bindings must be objects")
    return values


def _include_source(
    root: Path, hashes: dict[str, str], relative: Any, expected: Any = None,
    *, require_expected: bool = False,
) -> None:
    if not isinstance(relative, str) or not relative or relative != relative.strip():
        raise ValueError("Retained publication source must be an explicit relative path")
    normalized = relative.replace("\\", "/")
    parts = PurePosixPath(normalized).parts
    if not parts or any(part in {".", ".."} or ":" in part for part in parts) or normalized.startswith("/"):
        raise ValueError("Retained publication source escapes its project: " + relative)
    path = root / normalized
    if any((root.joinpath(*parts[:index])).is_symlink() for index in range(1, len(parts) + 1)):
        raise ValueError("Retained publication source is linked: " + relative)
    resolved = path.resolve()
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise ValueError("Retained publication source is missing or escapes its project: " + relative)
    current = hashlib.sha256(resolved.read_bytes()).hexdigest()
    if expected is not None or require_expected:
        if not isinstance(expected, str) or not re.fullmatch(r"[a-f0-9]{64}", expected) or expected != current:
            raise ValueError("Retained publication source binding is stale: " + relative)
    key = resolved.relative_to(root).as_posix()
    if key in hashes and hashes[key] != current:
        raise ValueError("Retained publication source changed during preparation: " + relative)
    hashes[key] = current
