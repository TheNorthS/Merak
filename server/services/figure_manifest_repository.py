"""Atomic manifest reconciliation, validation, and record transactions."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Optional

from ..utils.atomic_write import atomic_write_json
from .figure_artifact_support import (
    EDITABLE_EXTENSIONS,
    NON_SUBMISSION_EVIDENCE_STATUSES,
    PAPER_READY_EXTENSIONS,
    SCIENTIFIC_METADATA_FIELDS,
    _sha256,
    _short_label,
)


def _asset(root: Path, value: Any) -> Optional[Path]:
    if not value:
        return None
    candidate = Path(str(value)).expanduser()
    candidate = candidate if candidate.is_absolute() else root / candidate
    candidate = candidate.resolve()
    return candidate if candidate.is_file() and candidate.stat().st_size > 0 else None


def _relative(root: Path, path: Optional[Path]) -> Optional[str]:
    if not path:
        return None
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _reconcile_item(registry: Any, raw: Any, root: Path) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    output, source = _asset(root, raw.get("output_path")), _asset(root, raw.get("source_path"))
    if not output and not source:
        return None
    item = dict(raw)
    metadata = dict(item.get("metadata") or {})
    for field in SCIENTIFIC_METADATA_FIELDS:
        if field not in metadata and field in item:
            metadata[field] = item.get(field)
    if str(metadata.get("evidence_status") or "").casefold() in NON_SUBMISSION_EVIDENCE_STATUSES:
        metadata["paper_selected"] = False
    metadata["semantic_key"] = registry.semantic_key(str(item.get("description") or ""), metadata)
    if metadata.get("managed_by") == "merak":
        item["id"] = metadata["semantic_key"]
    output_rel, source_rel = _relative(root, output), _relative(root, source)
    item.update({
        "output_path": output_rel, "source_path": source_rel,
        "paper_path": f"../{output_rel}" if output_rel and not output_rel.startswith("../") else output_rel,
        "paper_ready": bool(output and output.suffix.casefold() in PAPER_READY_EXTENSIONS)
        and registry._is_scientific_figure(str(item.get("description") or ""))
        and registry._is_manuscript_asset(metadata)
        and metadata.get("paper_selected", True) is not False,
        "editable": bool(source and source.suffix.casefold() in EDITABLE_EXTENSIONS),
        "output_sha256": _sha256(output) if output else None,
        "source_sha256": _sha256(source) if source else None,
        "output_bytes": output.stat().st_size if output else 0,
        "metadata": metadata,
    })
    return item


def _semantic_changed(before: dict[str, Any], after: dict[str, Any], exists: bool) -> bool:
    if not exists:
        return True
    before = dict(before)
    before.pop("updated_at", None)
    after = dict(after)
    after.pop("updated_at", None)
    return json.dumps(before, ensure_ascii=False, sort_keys=True) != json.dumps(
        after, ensure_ascii=False, sort_keys=True,
    )


def reconcile_manifest(registry: Any, path: str | Path) -> dict[str, Any]:
    figures_root, root = registry.figures_root(path), registry.project_root(path)
    payload = registry.load(figures_root, strict=True)
    manifest = registry.manifest_path(figures_root)
    figures = [
        item for raw in payload.get("figures", [])
        if (item := _reconcile_item(registry, raw, root)) is not None
    ]
    after = {**payload, "schema": 1, "figures": figures}
    if not _semantic_changed(payload, after, manifest.exists()):
        return after
    after["updated_at"] = time.time()
    figures_root.mkdir(parents=True, exist_ok=True)
    atomic_write_json(manifest, after)
    registry._write_markdown(figures_root / "FIGURE_MANIFEST.md", after)
    return after


def _validate_file(
    root: Path, figure_id: str, value: Any, expected_hash: Any, label: str,
) -> list[str]:
    if not value:
        return []
    candidate = Path(str(value)).expanduser()
    candidate = candidate if candidate.is_absolute() else root / candidate
    candidate = candidate.resolve()
    if not candidate.is_file() or candidate.stat().st_size == 0:
        return [f"{figure_id}: missing {label} {value}"]
    if expected_hash and _sha256(candidate) != expected_hash:
        return [f"{figure_id}: hash mismatch for {label} {value}"]
    return []


def _validate_protocol(
    root: Path, figure_id: str, metadata: dict[str, Any],
) -> list[str]:
    paths = dict(metadata.get("protocol_artifacts") or {})
    hashes = dict(metadata.get("protocol_artifact_sha256") or {})
    issues: list[str] = []
    for name, value in paths.items():
        candidate = Path(str(value)).expanduser()
        candidate = candidate if candidate.is_absolute() else root / candidate
        candidate = candidate.resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            issues.append(f"{figure_id}: protocol artifact escapes project {name}")
            continue
        empty_stderr = candidate.is_file() and candidate.stat().st_size == 0 and str(name).casefold().endswith("stderr")
        if not candidate.is_file() or (candidate.stat().st_size == 0 and not empty_stderr):
            issues.append(f"{figure_id}: missing protocol artifact {name} {value}")
        elif not hashes.get(name):
            issues.append(f"{figure_id}: missing protocol artifact hash for {name}")
        elif _sha256(candidate) != hashes[name]:
            issues.append(f"{figure_id}: hash mismatch for protocol artifact {name}")
    issues.extend(
        f"{figure_id}: protocol hash has no artifact path for {name}"
        for name in sorted(set(hashes) - set(paths))
    )
    return issues


def _validate_item(root: Path, item: dict[str, Any]) -> list[str]:
    figure_id = str(item.get("id") or "unknown")
    issues: list[str] = []
    for path_key, hash_key in (("output_path", "output_sha256"), ("source_path", "source_sha256")):
        issues.extend(_validate_file(root, figure_id, item.get(path_key), item.get(hash_key), path_key))
    metadata = dict(item.get("metadata") or {})
    variants = dict(metadata.get("rendered_variants") or {})
    hashes = dict(metadata.get("rendered_variant_sha256") or {})
    for name, value in variants.items():
        issues.extend(_validate_file(
            root, figure_id, value, hashes.get(name), f"rendered variant {name}",
        ))
    issues.extend(_validate_protocol(root, figure_id, metadata))
    return issues


def validate_manifest(registry: Any, path: str | Path) -> tuple[bool, list[str], dict[str, Any]]:
    manifest = registry.manifest_path(path)
    if not manifest.exists():
        return False, [f"missing manifest: {manifest}"], registry.load(path)
    payload = registry.load(path)
    issues = ([
        "figure manifest is unreadable or malformed: " + str(payload["_load_error"])
    ] if payload.get("_load_error") else [])
    root = registry.project_root(path)
    issues.extend(
        issue for item in payload.get("figures", []) if isinstance(item, dict)
        for issue in _validate_item(root, item)
    )
    return not issues, issues, payload


def _record_entry(
    registry: Any, root: Path, figure_type: str, description: str,
    output: Path | None, source: Path | None, metadata: Optional[dict[str, Any]],
) -> dict[str, Any]:
    value = dict(metadata or {})
    value["semantic_key"] = registry.semantic_key(description, value)
    value.setdefault("managed_by", "merak")
    output_rel, source_rel = _relative(root, output), _relative(root, source)
    identity = source_rel or output_rel or f"{figure_type}:{description}"
    figure_id = value["semantic_key"] if value.get("managed_by") == "merak" else hashlib.sha256(identity.encode("utf-8", errors="replace")).hexdigest()[:16]
    return {
        "id": figure_id, "type": figure_type,
        "description": " ".join(description.split())[:500],
        "caption": _short_label(str((metadata or {}).get("caption") or description), 180),
        "output_path": output_rel, "source_path": source_rel,
        "paper_path": f"../{output_rel}" if output_rel and not output_rel.startswith("../") else output_rel,
        "paper_ready": bool(output and output.suffix.casefold() in PAPER_READY_EXTENSIONS)
        and registry._is_scientific_figure(description)
        and registry._is_manuscript_asset(value)
        and value.get("paper_selected", True) is not False,
        "editable": bool(source and source.suffix.casefold() in EDITABLE_EXTENSIONS),
        "output_sha256": _sha256(output) if output else None,
        "source_sha256": _sha256(source) if source else None,
        "output_bytes": output.stat().st_size if output else 0,
        "created_at": time.time(), "metadata": value,
    }


def _replace_entry(
    registry: Any, payload: dict[str, Any], entry: dict[str, Any],
    figures_root: Path, root: Path,
) -> list[dict[str, Any]]:
    metadata = dict(entry.get("metadata") or {})
    output_rel, source_rel = entry.get("output_path"), entry.get("source_path")
    kept, superseded = [], []
    for item in payload.get("figures", []):
        key = registry.semantic_key(str(item.get("description") or ""), dict(item.get("metadata") or {}))
        same = item.get("id") == entry["id"] or (source_rel and item.get("source_path") == source_rel) or (output_rel and item.get("output_path") == output_rel) or key == metadata["semantic_key"]
        (superseded if same else kept).append(item)
    kept.append(entry)
    variants = {str(value) for value in dict(metadata.get("rendered_variants") or {}).values() if str(value).strip()}
    registry._delete_managed_assets(
        figures_root, root, superseded,
        {value for value in (source_rel, output_rel) if value} | variants,
    )
    return kept


def record_manifest_entry(
    registry: Any, *, output_dir: str | Path, figure_type: str,
    description: str, output_path: Optional[str], source_path: Optional[str],
    metadata: Optional[dict[str, Any]],
) -> tuple[Path, dict[str, Any]]:
    figures_root, root = registry.figures_root(output_dir), registry.project_root(output_dir)
    figures_root.mkdir(parents=True, exist_ok=True)
    output, source = _asset(root, output_path), _asset(root, source_path)
    entry = _record_entry(
        registry, root, figure_type, description, output, source, metadata,
    )
    payload = registry.load(figures_root, strict=True)
    figures = _replace_entry(registry, payload, entry, figures_root, root)
    payload.update({"schema": 1, "updated_at": time.time(), "figures": figures})
    manifest = figures_root / "FIGURE_MANIFEST.json"
    atomic_write_json(manifest, payload)
    registry._write_markdown(figures_root / "FIGURE_MANIFEST.md", payload)
    return manifest, entry
