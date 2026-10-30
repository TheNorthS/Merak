"""Semantic progress fingerprints for staged figure drafts and their reviews."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


_ROOT_FILES = {
    "manifest.json",
    "canvas-layout.json",
    "mechanism-ir.json",
}
_VOLATILE_KEYS = {
    "reviewed_at",
    "updated_at",
    "created_at",
    "preview_path",
    "review_trace_path",
    "blind_readback_trace_path",
    "review_invocation_id",
    "blind_readback_invocation_id",
    "candidate_path",
}


def _stable_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _stable_json(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if str(key).casefold() not in _VOLATILE_KEYS
        }
    if isinstance(value, list):
        return [_stable_json(item) for item in value]
    return value


def _semantic_bytes(path: Path) -> bytes:
    try:
        if path.suffix.casefold() == ".json":
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            return json.dumps(
                _stable_json(payload), ensure_ascii=False, sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        return path.read_bytes()
    except (OSError, UnicodeError, json.JSONDecodeError):
        return b"<unreadable>"


def _evidence_files(directory: Path) -> list[Path]:
    files = [
        path for path in directory.iterdir()
        if path.is_file()
        and (path.name in _ROOT_FILES or path.suffix.casefold() == ".svg")
    ]
    for relative in ("parts", "best-composition", "best-composition/parts"):
        child = directory / relative
        if child.is_dir():
            files.extend(path for path in child.iterdir() if path.is_file())
    return sorted(
        set(files), key=lambda path: path.relative_to(directory).as_posix().casefold(),
    )


def figure_draft_progress_signature(
    project_path: str | Path,
    asset_ids: Iterable[str] | None = None,
) -> str:
    """Hash active SVG/parts plus normalized composition-review and best state.

    Preview pixels and trace directories are intentionally excluded: the active
    SVG hash and manifest review fields bind those artifacts without treating a
    retry timestamp or a new trace path as scientific progress.
    """
    root = Path(project_path).expanduser().resolve()
    drafts = root / ".merak" / "figure-drafts"
    selected = {
        str(value).strip() for value in asset_ids or [] if str(value).strip()
    }
    digest = hashlib.sha256(b"figure-draft-progress:v1")
    directories = []
    if drafts.is_dir():
        directories = [
            path for path in drafts.iterdir()
            if path.is_dir() and (not selected or path.name in selected)
        ]
    if not directories:
        digest.update(b"<no-staged-figure-drafts>")
    for directory in sorted(directories, key=lambda path: path.name.casefold()):
        digest.update(directory.name.encode("utf-8", errors="replace"))
        files = _evidence_files(directory)
        if not files:
            digest.update(b"<empty-draft>")
        for path in files:
            digest.update(path.relative_to(directory).as_posix().encode("utf-8"))
            digest.update(hashlib.sha256(_semantic_bytes(path)).digest())
    return f"figure-draft:{digest.hexdigest()[:24]}"
