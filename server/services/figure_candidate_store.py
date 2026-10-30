"""Preserve the best hash-current figure candidate across repair attempts."""

from __future__ import annotations

import json
import math
import re
import shutil
import time
from pathlib import Path
from typing import Any, Iterable

from ..utils.atomic_write import atomic_write_json


def candidate_penalty(issues: Iterable[str]) -> float:
    penalty = 0.0
    for raw in issues:
        issue = " ".join(str(raw or "").split()).casefold()
        if not issue:
            continue
        penalty += 20.0
        if any(marker in issue for marker in (
            "missing rendered variant", "hash mismatch", "cannot be decoded",
            "not rendered", "backend mismatch", "skill mismatch",
        )):
            penalty += 180.0
        for pattern, threshold, weight in (
            (r"(?:median size|scaling) \((\d+(?:\.\d+)?) pt", 7.0, 25.0),
            (r"occupies only (\d+(?:\.\d+)?)%", 40.0, 3.0),
        ):
            match = re.search(pattern, issue)
            if match:
                penalty += max(0.0, threshold - float(match.group(1))) * weight
        match = re.search(r"needs (\d+) text lines", issue)
        if match:
            penalty += max(0, int(match.group(1)) - 4) * 18.0
        if "exposes code symbols" in issue:
            penalty += 60.0
        if "omits required domain-facing terms" in issue:
            penalty += 50.0
    return round(penalty, 3)


def _backend(item: dict[str, Any]) -> str:
    declared = str(item.get("recommended_backend") or item.get("type") or "").strip().casefold()
    if declared:
        return declared.replace("-", "_")
    return {
        ".mmd": "mermaid", ".svg": "rich_svg", ".json": "figurespec",
        ".excalidraw": "excalidraw", ".py": "matplotlib",
    }.get(Path(str(item.get("source_path") or "")).suffix.casefold(), "")


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _manifest_entry(root: Path, figure_id: str) -> tuple[dict[str, Any], str]:
    manifest = _load_json(root / "figures" / "FIGURE_MANIFEST.json")
    entry = next((
        item for item in manifest.get("figures") or []
        if isinstance(item, dict) and str(item.get("id") or "") == figure_id
    ), None)
    return (entry, "") if isinstance(entry, dict) else ({}, "manifest entry unavailable")


def _authoritative_backend(root: Path, figure_id: str) -> str:
    specs = _load_json(root / "figures" / "FIGURE_SPECS.json")
    entry = next((
        item for item in specs.get("figures") or []
        if isinstance(item, dict) and str(item.get("id") or "") == figure_id
    ), {})
    return str(entry.get("recommended_backend") or "").strip().casefold().replace("-", "_")


def _candidate_files(root: Path, entry: dict[str, Any]) -> list[str]:
    relatives = [
        "figures/FIGURE_MANIFEST.json", "figures/FIGURE_SPECS.json",
        str(entry.get("source_path") or ""), str(entry.get("output_path") or ""),
        *[str(value) for value in dict(
            (entry.get("metadata") or {}).get("rendered_variants") or {}
        ).values()],
    ]
    files: list[str] = []
    for relative in dict.fromkeys(value.replace("\\", "/") for value in relatives if value.strip()):
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            continue
        if candidate.is_file() and candidate.stat().st_size > 0:
            files.append(relative)
    return files


def _save_candidate(
    root: Path, store: Path, figure_id: str, backend: str,
    penalty: float, issues: list[str], files: list[str], previous: float,
) -> dict[str, Any]:
    files_root = store / "files"
    for relative in files:
        source, target = (root / relative).resolve(), files_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    atomic_write_json(store / "state.json", {
        "schema": 1, "figure_id": figure_id, "backend": backend,
        "penalty": penalty, "issues": issues, "files": files,
        "saved_at": time.time(),
    })
    return {
        "action": "saved", "penalty": penalty,
        "previous_penalty": None if math.isinf(previous) else previous,
    }


def _restore(root: Path, store: Path, state: dict[str, Any], penalty: float) -> dict[str, Any]:
    restored = 0
    for relative in state.get("files") or []:
        source, target = store / "files" / str(relative), (root / str(relative)).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            continue
        if source.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            restored += 1
    return {
        "action": "restored", "penalty": penalty,
        "best_penalty": float(state.get("penalty") or float("inf")),
        "restored_files": restored,
    }


def preserve_best_candidate(
    project_path: str | Path, figure_id: str, issues: Iterable[str],
) -> dict[str, Any]:
    root = Path(project_path).expanduser().resolve()
    entry, error = _manifest_entry(root, figure_id)
    if error:
        return {"action": "skipped", "reason": error}
    backend, authoritative = _backend(entry), _authoritative_backend(root, figure_id)
    if authoritative and backend and backend != authoritative:
        return {
            "action": "skipped",
            "reason": "candidate backend differs from authoritative figure specification",
            "candidate_backend": backend, "authoritative_backend": authoritative,
        }
    files = _candidate_files(root, entry)
    if not files:
        return {"action": "skipped", "reason": "candidate files unavailable"}
    issue_list = list(issues)
    penalty = candidate_penalty(issue_list)
    store = root / ".merak" / "figure-best" / figure_id
    state = _load_json(store / "state.json")
    if state.get("backend") and backend and state.get("backend") != backend:
        state = {}
    previous = float(state.get("penalty") or float("inf"))
    if penalty <= previous:
        return _save_candidate(
            root, store, figure_id, backend, penalty, issue_list, files, previous,
        )
    return _restore(root, store, state, penalty)
