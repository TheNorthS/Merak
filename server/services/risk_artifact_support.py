"""Artifact readers and structured findings shared by node risk validators."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

def _text(path: Path, limit: int = 2_000_000) -> str:
    if not path.is_file() or path.stat().st_size == 0:
        return ""
    try:
        return path.read_text(encoding="utf-8-sig", errors="replace")[:limit]
    except OSError:
        return ""


def _json(path: Path) -> tuple[Any, str]:
    if not path.is_file() or path.stat().st_size == 0:
        return None, f"missing or empty JSON artifact: {path}"
    try:
        return json.loads(path.read_text(encoding="utf-8-sig", errors="strict")), ""
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, f"invalid JSON artifact {path}: {exc}"


def _has_content(path: Path) -> bool:
    if path.is_file():
        return path.stat().st_size > 0
    if path.is_dir():
        return any(item.is_file() and item.stat().st_size > 0 for item in path.rglob("*"))
    return False


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return str(path)


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def _finding(
    finding_id: str,
    severity: str,
    category: str,
    message: str,
    plain_message: str,
    evidence: list[str],
    remediation: str,
    *,
    target_files: list[str] | None = None,
    asset_ids: list[str] | None = None,
) -> dict[str, Any]:
    finding = {
        "id": finding_id,
        "severity": severity,
        "category": category,
        "message": message,
        "plain_message": plain_message,
        "evidence": evidence,
        "remediation": remediation,
    }
    if target_files is not None:
        finding["target_files"] = target_files
    if asset_ids is not None:
        finding["asset_ids"] = asset_ids
    return finding


def _missing(
    finding_id: str,
    relative: str,
    *,
    severity: str = "blocker",
) -> dict[str, Any]:
    return _finding(
        finding_id,
        severity,
        "artifact",
        f"Required canonical artifact is missing or empty: {relative}",
        f"标准产物 {relative} 缺失或为空，当前节点没有形成可审计交付物。",
        [relative],
        f"Create or repair {relative} at the canonical path, then rerun validation.",
    )


def _latex_sources(root: Path, start: Path) -> dict[Path, str]:
    sources: dict[Path, str] = {}
    queue = [start]
    while queue:
        path = queue.pop(0).resolve()
        if path in sources or not path.is_file():
            continue
        try:
            path.relative_to(root)
        except ValueError:
            continue
        content = _text(path)
        sources[path] = content
        for raw in re.findall(r"\\(?:input|include)\{([^}]+)\}", content):
            candidate = (path.parent / raw.strip())
            if candidate.suffix.lower() != ".tex":
                candidate = candidate.with_suffix(".tex")
            if candidate.is_file():
                queue.append(candidate)
    return sources


def _source_bundle_sha256(source_root: Path) -> tuple[str, list[Path]]:
    from .latex_bundle import latex_source_bundle

    return latex_source_bundle(source_root)
