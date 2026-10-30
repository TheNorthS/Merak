"""Validate a complete publication table bundle before atomic canonical replacement."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from contextlib import ExitStack

from ..utils.atomic_write import atomic_write_bytes, path_lock


def commit_prepared_table_bundle(
    root: Path, stage: Path, entries: list[dict[str, Any]],
    *, source_hashes: dict[str, str], owned_paths: set[str], canonical_baseline: dict[str, bytes],
) -> None:
    """Commit CSV, LaTeX, full prose notes, raw records and manifest, or restore all.

    The stage owns freshly generated content. External existing result files are
    copied only for hash validation; no plot, scientific source or dataset runs.
    """
    from .paper_artifacts import build_table_manifest

    generated = {relative: (stage / relative).read_bytes() for relative in owned_paths}
    for relative in source_hashes:
        if relative in generated:
            continue
        target = stage / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(target, (root / relative).read_bytes())
    for entry in entries:
        for key in ("data_path", "latex_path"):
            relative = str(entry[key])
            target = (stage / relative).resolve()
            if not target.is_relative_to(stage.resolve()):
                raise ValueError("Prepared publication table path escapes its stage")
            if not target.exists():
                source = (root / relative).resolve()
                if not source.is_relative_to(root) or not source.is_file():
                    raise ValueError(f"Prepared publication table source is missing: {relative}")
                target.parent.mkdir(parents=True, exist_ok=True)
                atomic_write_bytes(target, source.read_bytes())
    from .publication_table_policy import publication_table_issues
    issues = publication_table_issues(stage / "paper", sorted({str(item["latex_path"]) for item in entries}))
    if issues:
        raise ValueError("Prepared public table source rejected: " + "; ".join(issues))
    payload = build_table_manifest(stage, entries)
    manifest = "paper/tables/TABLE_MANIFEST.json"
    with ExitStack() as locks:
        for relative in sorted({manifest, *(path for path in generated if path.endswith("MANIFEST.json"))}):
            locks.enter_context(path_lock(root / relative))
        _assert_unchanged(root, source_hashes, {**generated, manifest: b""}, canonical_baseline)
        previous = _read_current_manifest(root / manifest)
        payload["updated_at"] = (previous.get("updated_at") if
            {key: value for key, value in previous.items() if key != "updated_at"} == payload
            else time.time())
        generated[manifest] = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        before = {relative: (root / relative).read_bytes() if (root / relative).is_file() else None
                  for relative in generated}
        try:
            for relative, content in generated.items():
                if before[relative] != content:
                    atomic_write_bytes(root / relative, content)
            _assert_unchanged(root, {relative: expected for relative, expected in source_hashes.items()
                                     if relative not in generated}, {}, {})
            import hashlib
            for relative in source_hashes.keys() & generated.keys():
                if hashlib.sha256((root / relative).read_bytes()).digest() != hashlib.sha256(generated[relative]).digest():
                    raise ValueError("Publication table source changed during commit: " + relative)
        except BaseException:
            for relative, content in before.items():
                if content is None:
                    (root / relative).unlink(missing_ok=True)
                else:
                    atomic_write_bytes(root / relative, content)
            raise


def _read_current_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Current table manifest is unreadable; producer will not overwrite it") from exc
    if (not isinstance(payload, dict) or payload.get("schema") != 3
            or not isinstance(payload.get("tables"), list)
            or any(not isinstance(item, dict) for item in payload["tables"])):
        raise ValueError("Current table manifest has an unsupported contract; no automatic migration")
    return payload


def _assert_unchanged(
    root: Path, source_hashes: dict[str, str], generated: dict[str, bytes],
    baseline: dict[str, bytes],
) -> None:
    import hashlib

    for relative, expected in source_hashes.items():
        path = root / relative
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("Scientific table inputs changed during preparation: " + relative)
    for relative in generated:
        path = root / relative
        current = path.read_bytes() if path.is_file() else None
        if current != baseline.get(relative):
            raise ValueError("Canonical table changed during preparation: " + relative)
