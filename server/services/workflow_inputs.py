"""Immutable workflow inputs and content-based artifact fingerprints."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Sequence


MAX_EXPLICIT_INPUTS = 128
MAX_INPUT_DIRECTORY_FILES = 2000
MAX_INPUT_TOTAL_BYTES = 256 * 1024 * 1024
MAX_ARTIFACT_FILES = 5000

_IGNORED_DIRECTORY_NAMES = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    "node_modules",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_key(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _iter_files(
    path: Path,
    limit: int,
    excluded: set[str] | None = None,
) -> tuple[list[Path], bool, list[str]]:
    files: list[Path] = []
    symlinks: list[str] = []
    truncated = False
    excluded = excluded or set()
    for candidate in sorted(path.rglob("*"), key=lambda item: item.as_posix()):
        if any(part in _IGNORED_DIRECTORY_NAMES for part in candidate.parts):
            continue
        relative = candidate.relative_to(path).as_posix()
        if any(
            relative == prefix or relative.startswith(prefix.rstrip("/") + "/")
            for prefix in excluded
        ):
            continue
        if candidate.is_symlink():
            symlinks.append(relative)
            continue
        if not candidate.is_file():
            continue
        if len(files) >= limit:
            truncated = True
            break
        files.append(candidate)
    return files, truncated, symlinks


def artifact_state(
    path: str | Path,
    *,
    max_files: int = MAX_ARTIFACT_FILES,
    exclude: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Return a stable content descriptor; timestamps are intentionally excluded."""
    target = Path(path).expanduser().resolve()
    if not target.exists():
        return {"kind": "missing", "sha256": "", "size": 0, "file_count": 0}
    if target.is_file():
        try:
            size = target.stat().st_size
            file_digest = _sha256(target)
        except OSError as exc:
            return {
                "kind": "unreadable",
                "sha256": "",
                "size": 0,
                "file_count": 0,
                "error": f"{type(exc).__name__}: {exc}",
            }
        return {
            "kind": "file",
            "sha256": file_digest,
            "size": size,
            "file_count": 1,
        }
    if not target.is_dir():
        return {"kind": "unsupported", "sha256": "", "size": 0, "file_count": 0}

    excluded = {
        str(item).replace("\\", "/").strip("/")
        for item in (exclude or [])
        if str(item).strip()
    }
    files, truncated, symlinks = _iter_files(target, max_files, excluded)
    digest = hashlib.sha256()
    total_bytes = 0
    unreadable: list[str] = []
    for child in files:
        relative = child.relative_to(target).as_posix()
        digest.update(relative.encode("utf-8", errors="replace"))
        try:
            size = child.stat().st_size
            child_hash = _sha256(child)
        except OSError as exc:
            unreadable.append(f"{relative}: {type(exc).__name__}")
            digest.update(b"<unreadable>")
            continue
        total_bytes += size
        digest.update(str(size).encode("ascii"))
        digest.update(child_hash.encode("ascii"))
    if truncated:
        digest.update(b"<directory-scan-truncated>")
    for relative in symlinks:
        digest.update(b"<symbolic-link>")
        digest.update(relative.encode("utf-8", errors="replace"))
    return {
        "kind": "directory",
        "sha256": digest.hexdigest(),
        "size": total_bytes,
        "file_count": len(files),
        "truncated": truncated,
        "symlink_count": len(symlinks),
        "symlinks": symlinks[:20],
        "unreadable": unreadable[:20],
        "excluded": sorted(excluded),
    }


def artifact_state_equal(left: dict[str, Any] | None, right: dict[str, Any] | None) -> bool:
    """Compare only fields that describe content, never volatile filesystem metadata."""
    if not isinstance(left, dict) or not isinstance(right, dict):
        return False
    keys = (
        "kind",
        "sha256",
        "size",
        "file_count",
        "truncated",
        "excluded",
    )
    return all(left.get(key) == right.get(key) for key in keys) and int(
        left.get("symlink_count") or 0
    ) == int(right.get("symlink_count") or 0)


def snapshot_paths(
    project_path: str | Path,
    paths: Iterable[str | Path],
    *,
    directory_exclusions: dict[str, Sequence[str]] | None = None,
) -> dict[str, dict[str, Any]]:
    root = Path(project_path).expanduser().resolve()
    snapshot: dict[str, dict[str, Any]] = {}
    for raw in paths:
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = root / path
        path = path.resolve()
        key = _relative_key(root, path)
        exclusions = (directory_exclusions or {}).get(key, ())
        snapshot[key] = artifact_state(path, exclude=exclusions)
    return snapshot


class WorkflowInputService:
    """Validate and freeze user-selected project files for one workflow run."""

    def resolve(
        self,
        project_path: str | Path,
        raw_paths: Sequence[str] | None,
    ) -> tuple[list[Path], list[str]]:
        root = Path(project_path).expanduser().resolve()
        issues: list[str] = []
        resolved: list[Path] = []
        seen: set[str] = set()
        values = list(raw_paths or [])
        if len(values) > MAX_EXPLICIT_INPUTS:
            issues.append(
                f"Too many explicit workflow inputs ({len(values)}); maximum is {MAX_EXPLICIT_INPUTS}."
            )
            values = values[:MAX_EXPLICIT_INPUTS]
        if not root.is_dir():
            return [], [f"Project path is not a directory: {root}"]

        for raw in values:
            clean = str(raw or "").strip()
            if not clean:
                continue
            candidate = Path(clean).expanduser()
            if not candidate.is_absolute():
                candidate = root / candidate
            try:
                candidate = candidate.resolve()
                relative = candidate.relative_to(root)
            except (OSError, ValueError):
                issues.append(
                    f"Explicit workflow input must stay inside the current project: {clean}"
                )
                continue
            if candidate == root:
                issues.append("The whole project directory cannot be declared as one workflow input.")
                continue
            if relative.parts and relative.parts[0] == ".merak":
                issues.append(
                    f"Runtime-owned .merak files cannot be declared as user inputs: {relative.as_posix()}"
                )
                continue
            if not candidate.exists():
                issues.append(f"Explicit workflow input does not exist: {relative.as_posix()}")
                continue
            key = relative.as_posix().casefold()
            if key in seen:
                continue
            seen.add(key)
            resolved.append(candidate)
        return resolved, issues

    def capture(
        self,
        project_path: str | Path,
        raw_paths: Sequence[str] | None,
        *,
        run_id: str,
    ) -> dict[str, Any]:
        root = Path(project_path).expanduser().resolve()
        paths, issues = self.resolve(root, raw_paths)
        entries: list[dict[str, Any]] = []
        total_bytes = 0
        total_files = 0
        for path in paths:
            try:
                if path.is_file():
                    measured_size = path.stat().st_size
                    measured_files = 1
                    truncated = False
                    symlinks: list[str] = []
                else:
                    measured_paths, truncated, symlinks = _iter_files(
                        path,
                        MAX_INPUT_DIRECTORY_FILES,
                    )
                    measured_size = sum(item.stat().st_size for item in measured_paths)
                    measured_files = len(measured_paths)
            except OSError as exc:
                issues.append(
                    f"Explicit workflow input is not readable: "
                    f"{path.relative_to(root).as_posix()} ({type(exc).__name__})"
                )
                continue
            relative = path.relative_to(root).as_posix()
            if truncated:
                issues.append(
                    f"Explicit input directory contains more than {MAX_INPUT_DIRECTORY_FILES} files: {relative}"
                )
                continue
            if symlinks:
                issues.append(
                    f"Explicit input directory contains symbolic links, which are not allowed: {relative}"
                )
                continue
            if total_bytes + measured_size > MAX_INPUT_TOTAL_BYTES:
                issues.append(
                    "Explicit workflow inputs exceed the 256 MiB snapshot limit; "
                    "use the reference paper/code intake for large external sources."
                )
                continue
            state = artifact_state(path, max_files=MAX_INPUT_DIRECTORY_FILES)
            if state.get("kind") in {"unreadable", "unsupported", "missing"}:
                issues.append(f"Explicit workflow input is not readable: {relative}")
                continue
            if state.get("truncated"):
                issues.append(
                    f"Explicit input directory contains more than {MAX_INPUT_DIRECTORY_FILES} files: {relative}"
                )
                continue
            total_bytes += measured_size
            total_files += measured_files
            entries.append({"path": relative, **state})
        if issues:
            raise ValueError("; ".join(issues))

        canonical = json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        snapshot_id = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return {
            "schema": 1,
            "run_id": str(run_id),
            "project_path": str(root),
            "snapshot_id": snapshot_id,
            "entries": entries,
            "file_count": total_files,
            "total_bytes": total_bytes,
        }

    def validate_snapshot(
        self,
        project_path: str | Path,
        baseline: dict[str, Any] | None,
    ) -> list[str]:
        if not baseline:
            return []
        root = Path(project_path).expanduser().resolve()
        issues: list[str] = []
        entries = baseline.get("entries") if isinstance(baseline, dict) else None
        if not isinstance(entries, list):
            return ["Workflow input baseline is malformed; start a new run to recapture inputs."]
        for entry in entries:
            if not isinstance(entry, dict) or not str(entry.get("path") or "").strip():
                issues.append("Workflow input baseline contains an invalid path entry.")
                continue
            relative = Path(str(entry["path"]))
            target = (root / relative).resolve()
            try:
                target.relative_to(root)
            except ValueError:
                issues.append(f"Workflow input escaped the project boundary: {relative.as_posix()}")
                continue
            current = artifact_state(target, max_files=MAX_INPUT_DIRECTORY_FILES)
            if not artifact_state_equal(entry, current):
                issues.append(
                    f"Explicit workflow input changed after the run started: {relative.as_posix()}"
                )
        return issues

    def covers(
        self,
        project_path: str | Path,
        baseline: dict[str, Any] | None,
        path: str | Path,
    ) -> bool:
        if not baseline:
            return False
        root = Path(project_path).expanduser().resolve()
        target = Path(path).expanduser()
        if not target.is_absolute():
            target = root / target
        try:
            relative = target.resolve().relative_to(root)
        except ValueError:
            return False
        for entry in baseline.get("entries") or []:
            if not isinstance(entry, dict):
                continue
            declared = Path(str(entry.get("path") or ""))
            if entry.get("kind") == "file" and declared == relative:
                return True
            if entry.get("kind") == "directory" and (
                declared == relative or declared in relative.parents
            ):
                return True
        return False


workflow_input_service = WorkflowInputService()
