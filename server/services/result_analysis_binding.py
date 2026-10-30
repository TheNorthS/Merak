"""Bind accepted analysis to owned result bytes using optimistic atomic writes."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from ..utils.atomic_write import atomic_write_json, path_lock
from .risk_artifact_support import _json, _sha256
from .risk_validator_support import (
    _executed_result_data_files,
    _result_analysis_source_hashes,
    _hash_mapping_digest,
    _newest_mtime,
)
from .risk_evidence_policy import (
    workflow_evidence_mode as _workflow_evidence_mode,
    has_complete_manuscript_evidence as _has_trusted_empirical_evidence,
)

RESULT_ANALYSIS_BUILD_SCHEMA = 1
RESULT_ANALYSIS_BUILD_PATH = Path("experiments") / "results" / "ANALYSIS_BUILD.json"


def _read_binding(build_path: Path) -> dict[str, Any]:
    existing, existing_error = _json(build_path)
    if build_path.exists() and existing_error:
        raise RuntimeError(
            f"Result analysis binding is unreadable or corrupt; refusing to overwrite it: {build_path}: {existing_error}"
        )
    if existing is None:
        existing = {}
    elif not isinstance(existing, dict):
        raise RuntimeError(
            f"Result analysis binding root must be a JSON object; refusing to overwrite it: {build_path}"
        )
    return existing


def _persist_binding(
    build_path: Path, payload: dict[str, Any], expected: dict[str, Any]
) -> None:
    with path_lock(build_path):
        latest = _read_binding(build_path)
        if latest != expected:
            raise RuntimeError(
                f"Result analysis binding changed concurrently; refusing to overwrite it: {build_path}"
            )
        atomic_write_json(build_path, payload)


def bind_result_analysis_inputs(
    project_path: str | Path, options: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Bind an accepted analysis to current provenance-owned result bytes.

    This method is called only after the results gate accepts the analysis.
    It deliberately refuses to update an existing binding when the analysis
    bytes are unchanged but any bound result hash changed. That keeps a
    stale analysis from blessing new evidence merely because validation ran.
    """
    root = Path(project_path).expanduser().resolve()
    resolved_options = dict(options or {})
    if not _has_trusted_empirical_evidence(resolved_options):
        return {}
    analysis_path = root / "experiments" / "results" / "analysis.md"
    if not analysis_path.is_file() or analysis_path.stat().st_size <= 0:
        return {}
    _, source_paths = _executed_result_data_files(root)
    source_hashes = _result_analysis_source_hashes(root, source_paths)
    if not source_hashes:
        return {}
    analysis_hash = _sha256(analysis_path)
    evidence_mode = _workflow_evidence_mode(resolved_options)
    build_path = root / RESULT_ANALYSIS_BUILD_PATH
    existing = _read_binding(build_path)
    existing_applies = bool(
        existing.get("schema") == RESULT_ANALYSIS_BUILD_SCHEMA
        and str(existing.get("analysis_path") or "")
        == "experiments/results/analysis.md"
        and (str(existing.get("analysis_sha256") or "") == analysis_hash)
        and (str(existing.get("evidence_mode") or "") == evidence_mode)
    )
    if existing_applies:
        if dict(existing.get("source_artifact_sha256") or {}) != source_hashes:
            return {}
        return existing
    if analysis_path.stat().st_mtime + 1.0 < _newest_mtime(source_paths):
        return {}
    payload = {
        "schema": RESULT_ANALYSIS_BUILD_SCHEMA,
        "analysis_path": "experiments/results/analysis.md",
        "analysis_sha256": analysis_hash,
        "evidence_mode": evidence_mode,
        "source_artifact_sha256": source_hashes,
        "source_bundle_sha256": _hash_mapping_digest(source_hashes),
        "bound_at": time.time(),
    }
    _persist_binding(build_path, payload, existing)
    return payload
