"""Atomic lifecycle updates for method-contract coordination state."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..utils.atomic_write import path_lock
from ..contracts.writers import write_versioned_artifact
from .research_contract_versions import METHOD_CONTRACT_SCHEMA
from ..contracts.implementation_evidence import (
    ImplementationEvidencePatch,
    IntegrationVerdict,
)


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _has_authored_design(payload: dict[str, Any]) -> bool:
    status = str(payload.get("status") or "").strip().casefold()
    has_design = any(
        isinstance(payload.get(field), list) and bool(payload[field])
        for field in (
            "mechanism_coverage", "claim_evidence_plan", "implementation_checks",
        )
    )
    return status not in {"", "scaffold_only"} or has_design


def write_planned_contract(path: Path, planned: dict[str, Any]) -> bool:
    if not planned or _has_authored_design(_json(path)):
        return False
    with path_lock(path):
        if _has_authored_design(_json(path)):
            return False
        write_versioned_artifact(path.parents[1], "method_contract", planned)
    return True


def bind_idea_contract(
    contract_path: Path,
    idea_path: Path,
    idea_relative_path: Path,
    *,
    finalize: bool,
) -> bool:
    with path_lock(contract_path):
        payload = _json(contract_path)
        idea = _json(idea_path)
        if not payload or not idea:
            return False
        if int(payload.get("schema") or 0) != METHOD_CONTRACT_SCHEMA:
            return False
        payload["idea_contract_path"] = idea_relative_path.as_posix()
        payload["idea_contract_sha256"] = hashlib.sha256(idea_path.read_bytes()).hexdigest()
        if finalize:
            payload["status"] = "implemented"
        write_versioned_artifact(contract_path.parents[1], "method_contract", payload)
    return True


def validate_implementation_evidence_patches(
    contract_path: Path, patches: list[ImplementationEvidencePatch],
) -> None:
    """Check frozen mechanism IDs and coverage shape without changing a file."""
    payload = _json(contract_path)
    if int(payload.get("schema") or 0) != METHOD_CONTRACT_SCHEMA:
        raise ValueError(f"method contract requires schema={METHOD_CONTRACT_SCHEMA}")
    _linked_mechanism_coverage(contract_path, payload, patches)


def apply_implementation_evidence_patches(
    contract_path: Path,
    patches: list[ImplementationEvidencePatch],
) -> bool:
    """Merge authored evidence and explicit mechanism links, never readiness.

    Unknown IDs are rejected before any write. Existing scientific design and
    linkage are preserved; names and check-ID prefixes never infer coverage.
    """
    with path_lock(contract_path):
        payload = _json(contract_path)
        if int(payload.get("schema") or 0) != METHOD_CONTRACT_SCHEMA:
            raise ValueError(f"method contract requires schema={METHOD_CONTRACT_SCHEMA}")
        coverage = _linked_mechanism_coverage(contract_path, payload, patches)
        existing = {
            str(item.get("id") or ""): dict(item)
            for item in payload.get("implementation_checks") or []
            if isinstance(item, dict) and str(item.get("id") or "").strip()
        }
        for patch in patches:
            existing[patch.check_id] = patch.as_check()
        payload["implementation_checks"] = list(existing.values())
        payload["mechanism_coverage"] = coverage
        write_versioned_artifact(contract_path.parents[1], "method_contract", payload)
    return True


def _linked_mechanism_coverage(
    contract_path: Path, payload: dict[str, Any],
    patches: list[ImplementationEvidencePatch],
) -> list[dict[str, Any]]:
    idea = _json(contract_path.parents[1] / "ideas" / "SELECTED_IDEA.json")
    accepted_ids = {
        str(item.get("id") or "").strip()
        for item in idea.get("mechanisms") or [] if isinstance(item, dict)
    } - {""}
    named_ids = {identity for patch in patches for identity in patch.idea_mechanism_ids}
    unknown = named_ids - accepted_ids
    if unknown:
        raise ValueError("evidence patch references unknown idea mechanism(s): " + ", ".join(sorted(unknown)))
    raw_coverage = payload.get("mechanism_coverage") or []
    if not isinstance(raw_coverage, list) or any(not isinstance(item, dict) for item in raw_coverage):
        raise ValueError("method contract mechanism_coverage must be a list of objects")
    coverage = [dict(item) for item in raw_coverage]
    by_id = {str(item.get("idea_mechanism_id") or ""): item for item in coverage}
    for patch in patches:
        for identity in patch.idea_mechanism_ids:
            if identity not in by_id:
                by_id[identity] = {"idea_mechanism_id": identity, "implementation_check_ids": []}
                coverage.append(by_id[identity])
            links = by_id[identity].get("implementation_check_ids") or []
            if not isinstance(links, list):
                raise ValueError(f"mechanism {identity} implementation_check_ids must be a list")
            by_id[identity]["implementation_check_ids"] = list(dict.fromkeys([*links, patch.check_id]))
    return coverage


def finalize_from_integration_verdict(
    contract_path: Path,
    idea_path: Path,
    idea_relative_path: Path,
    verdict: IntegrationVerdict,
) -> bool:
    """Only a passing deterministic integration verdict may finalize state."""
    if not verdict.passed:
        return False
    if not bind_idea_contract(
        contract_path, idea_path, idea_relative_path, finalize=True,
    ):
        return False
    with path_lock(contract_path):
        payload = _json(contract_path)
        for item in payload.get("mechanism_coverage") or []:
            if isinstance(item, dict) and item.get("implementation_check_ids"):
                item["status"] = "implemented"
        payload["integration_verdict"] = {
            "validator": "implementation-integration-v1",
            "output_sha256": verdict.report_sha256,
        }
        write_versioned_artifact(contract_path.parents[1], "method_contract", payload)
    return True
