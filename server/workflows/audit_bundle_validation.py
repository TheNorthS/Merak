"""Proof-source and committed audit-bundle validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _api() -> Any:
    from . import review_audit

    return review_audit


def proof_source_bundle(
    project_path: str | Path,
) -> tuple[str, dict[str, str], list[Path], int, list[str]]:
    from .proof_audit_validation import proof_source_bundle as build_bundle

    return build_bundle(project_path)


def proof_semantic_sha256(
    proof_source_bundle_sha256: str, proof: dict[str, Any],
) -> str:
    from .proof_audit_validation import proof_semantic_sha256 as semantic_hash

    return semantic_hash(proof_source_bundle_sha256, proof)


def validate_proof_audit_artifact(
    project_path: str | Path, **kwargs: Any,
) -> tuple[list[str], dict[str, Any]]:
    from .proof_audit_validation import validate_proof_audit_artifact as validate

    return validate(project_path, **kwargs)
def validate_audit_bundle(
    project_path: str | Path, *, run_id: str = "", evidence_mode: str = "",
    executor_model: str = "", allow_non_model_layers: bool = False,
) -> dict[str, Any]:
    from .audit_bundle_checks import validate_bundle

    return validate_bundle(
        project_path, run_id=run_id, evidence_mode=evidence_mode,
        executor_model=executor_model,
        allow_non_model_layers=allow_non_model_layers,
    )
