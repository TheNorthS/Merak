"""Normalization of method-to-evidence contract variants."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalized(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def _nonempty_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) and value else []


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def normalize_claim_evidence_plan(value: Any) -> list[dict[str, Any]]:
    """Return current claim-evidence objects without inventing missing fields."""
    return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def normalize_mechanism_coverage(value: Any) -> list[dict[str, Any]]:
    """Return current mechanism mappings without translating alternate keys."""
    return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _structured_evidence_paths(value: Any) -> list[str]:
    """Extract source paths from the current structured evidence register."""
    if not isinstance(value, dict):
        return []
    candidates: list[Any] = []
    candidates.extend(value.get("source_artifacts") or [])
    return [str(item).strip() for item in candidates if str(item).strip()]


def normalize_implementation_evidence(value: Any) -> list[dict[str, Any]]:
    """Project the two current evidence forms to path-selector records."""
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, dict)]
    if not isinstance(value, dict):
        return []
    if str(value.get("path") or "").strip():
        return [dict(value)]
    shared = {
        key: value.get(key)
        for key in ("symbols", "anchors", "config_keys")
        if value.get(key)
    }
    structured_data_keys = (
        value.get("data_keys")
        or value.get("batch_fields")
        or value.get("output_keys")
    )
    if structured_data_keys:
        shared["data_keys"] = structured_data_keys
    return [
        {"path": path, "_structured_register": True, **shared}
        for path in _structured_evidence_paths(value)
    ]


def implementation_evidence_register_map(payload: Any) -> dict[str, Any]:
    """Index optional top-level evidence registers by implementation-check ID."""
    if not isinstance(payload, dict):
        return {}
    register = payload.get("implementation_evidence_register")
    if isinstance(register, dict):
        return {
            str(key).strip(): value
            for key, value in register.items()
            if str(key).strip()
        }
    if not isinstance(register, list):
        return {}
    indexed: dict[str, Any] = {}
    for item in register:
        if not isinstance(item, dict):
            continue
        check_id = str(item.get("id") or item.get("check_id") or "").strip()
        if check_id:
            indexed[check_id] = item.get("evidence") or item
    return indexed


def resolve_implementation_evidence(
    check: Any,
    registered: Any = None,
) -> Any:
    """Return one canonical evidence value from supported writer formats.

    Agents have emitted three semantically equivalent shapes over time:
    ``evidence`` itself, a top-level register keyed by check ID, and a staged
    obligation embedded in the check as ``future_owner_targets`` plus
    ``required_runtime_evidence``. Normalizing those aliases at the contract
    boundary keeps valid repairs visible while requiring real source files.
    """
    if not isinstance(check, dict):
        return None
    explicit = check.get("evidence")
    if normalize_implementation_evidence(explicit):
        return explicit
    if normalize_implementation_evidence(registered):
        return registered

    source_artifacts = (
        check.get("source_artifacts")
        or check.get("future_owner_targets")
        or check.get("owner_targets")
        or []
    )
    runtime_entries = (
        check.get("required_runtime_evidence")
        or check.get("observable_outputs")
        or []
    )
    observable_outputs: list[str] = []
    for item in runtime_entries if isinstance(runtime_entries, list) else []:
        if isinstance(item, dict):
            path = str(item.get("path") or "").strip()
        else:
            path = str(item or "").strip()
        if path:
            observable_outputs.append(path)
    if not _string_list(source_artifacts):
        return explicit or registered
    return {
        "source_artifacts": _string_list(source_artifacts),
        "observable_outputs": observable_outputs,
        "observation": str(
            check.get("observation") or check.get("pass_observation") or ""
        ).strip(),
        "acceptance_criterion": str(
            check.get("acceptance_criterion")
            or check.get("requirement")
            or check.get("description")
            or check.get("purpose")
            or ""
        ).strip(),
        "evidence_status": str(
            check.get("evidence_status")
            or check.get("status")
            or check.get("evidence_absence")
            or ""
        ).strip(),
    }
