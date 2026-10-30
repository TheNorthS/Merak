"""Exact per-session artifact ownership, enforced before model file mutations."""

from __future__ import annotations

import os
from pathlib import Path, PureWindowsPath
from typing import Any


FILE_MUTATION_PATH_KEYS = {
    "Write": "path", "Edit": "path",
    "WritePart": "target_path", "AssembleDocument": "target_path",
}


def _has_traversal(raw: str) -> bool:
    return ".." in raw.replace("\\", "/").split("/")


def _resolved_target(root: Path, raw: str) -> Path:
    path = Path(raw.replace("\\", "/"))
    return (path if path.is_absolute() else root / path).resolve()


def _is_project_local(root: Path, target: Path) -> bool:
    return target != root and target.is_relative_to(root)


def _path_identity(target: Path) -> str:
    # Windows identity is case-insensitive; POSIX identity remains case-sensitive.
    return os.path.normcase(str(target))


def _matches_declared_file(root: Path, relative: str, target: Path) -> bool:
    return _path_identity(root / relative) == _path_identity(target)


def normalize_allowed_write_paths(root: Path, paths: list[str] | None) -> list[str] | None:
    """Validate exact project-relative scope; None preserves unrestricted callers."""
    if paths is None:
        return None
    if not isinstance(paths, list):
        raise ValueError("allowed_write_paths must be a list of exact project-relative files")
    root = root.resolve()
    normalized: list[str] = []
    for value in paths:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("allowed_write_paths contains an empty or non-string target")
        raw = value.strip().replace("\\", "/")
        if (
            Path(raw).is_absolute() or PureWindowsPath(raw).drive
            or _has_traversal(raw) or any(char in raw for char in "*?[]:")
            or raw.endswith("/")
        ):
            raise ValueError("allowed_write_paths must name exact project-relative files without traversal")
        target = _resolved_target(root, raw)
        if not _is_project_local(root, target) or target.is_dir():
            raise ValueError("allowed_write_paths target resolves outside the project or to a directory")
        relative = Path(raw).as_posix()
        if not _matches_declared_file(root, relative, target):
            raise ValueError("allowed_write_paths target redirects to a different file through a symlink")
        if relative not in normalized:
            normalized.append(relative)
    return normalized


def scoped_write_error(
    root: Path, scope: list[str] | None, tool_name: str, arguments: dict[str, Any],
) -> str | None:
    """Reject undeclared/escaped writes before budgets, staging, or tool execution."""
    key = FILE_MUTATION_PATH_KEYS.get(tool_name)
    if scope is None or key is None:
        return None
    raw = arguments.get(key)
    if (
        not isinstance(raw, str) or not raw.strip() or _has_traversal(raw)
        or any(char in raw for char in "*?[]")
    ):
        return "BLOCKED: scoped file mutation requires an exact target without path traversal."
    root = root.resolve()
    target = _resolved_target(root, raw.strip())
    if not _is_project_local(root, target) or target.is_dir():
        return "BLOCKED: scoped file mutation resolves outside the project or to a directory."
    identities = {
        _path_identity(candidate)
        for relative in scope
        if _is_project_local(root, candidate := _resolved_target(root, relative))
        and _matches_declared_file(root, relative, candidate)
    }
    if _path_identity(target) not in identities:
        return "BLOCKED: target is not owned by this isolated stage; declared inputs and other stages are read-only."
    arguments[key] = str(target)
    return None
