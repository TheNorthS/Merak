"""Decide planned-result reuse without regenerating existing scientific evidence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .results_execution_policy import resolve_results_execution_policy
from .simulation_publication_attestation import _current_bundle


def planned_result_evidence_mode(options: dict[str, Any]) -> str:
    """Only explicitly pending or synthetic modes may enter the planning producer."""
    policy = resolve_results_execution_policy(options)
    if policy.issues or (options.get("run_experiment") is not True and policy.kind != "runtime_owned"):
        raise ValueError("Planned-result preparation cannot replace existing or unsupported evidence: "
                         + "; ".join(policy.issues or (policy.reason,)))
    return str(options.get("non_experiment_evidence_mode") or "design_only").strip().casefold() or "design_only"


def _read_existing(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Existing {label} is unreadable; scientific files were not regenerated") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Existing {label} must be an object; scientific files were not regenerated")
    return value


def resolve_planned_result_reuse(
    root: Path, required: list[Path], *, mode: str, input_hash: str,
    target_venue: str, force: bool, frozen_authority: dict[str, Any] | None = None,
) -> tuple[bool, dict[str, Any]]:
    """Existing simulation identity permits only hash-current reuse, never regeneration.

    Initial creation when no simulation manifest exists remains a producer action.
    Force cannot authorize replacing an existing scientific benchmark bundle.
    """
    simulation = root / "experiments/results/simulated/SIMULATION_MANIFEST.json"
    from .evidence_publication_recovery import pending_publication
    if pending_publication(root):
        from .evidence_versions import EvidenceVersionRequired
        raise EvidenceVersionRequired(root, input_hash)
    owns_existing = mode == "synthetic_preview" and simulation.exists()
    if owns_existing:
        if force:
            raise ValueError("Forced regeneration of existing simulation evidence is unsupported; start an explicitly scoped new producer run")
        # This owner verifier checks the current schema/renderer and every data,
        # static source and output hash without changing files or executing code.
        _current_bundle(root)
    missing = [path for path in required if not path.is_file() or path.stat().st_size <= 0]
    if missing:
        if owns_existing:
            raise ValueError("Existing simulation evidence has missing canonical artifacts; no regeneration: "
                             + ", ".join(path.relative_to(root).as_posix() for path in missing[:8]))
        return True, {}
    planned = _read_existing(required[0], "planned-result manifest")
    if frozen_authority is not None:
        if not owns_existing or force:
            raise ValueError("Frozen benchmark authority cannot create, regenerate or change evidence modes")
        from .frozen_benchmark_runtime import validate_reuse_authority

        proof = validate_reuse_authority(root, frozen_authority, input_hash)
        if (planned.get("schema") != 5 or planned.get("evidence_mode") != mode
                or planned.get("input_bundle_sha256") != proof["original_generation_input_sha256"]
                or proof["settings"]["target_venue"] != target_venue):
            raise ValueError("The supplied benchmark differs from its explicit original generation authority")
        return False, planned
    valid = (planned.get("schema") == 5 and planned.get("evidence_mode") == mode
             and planned.get("input_bundle_sha256") == input_hash
             and str((planned.get("publication_style") or {}).get("target_venue") or "") == target_venue)
    if not valid and owns_existing:
        from .evidence_versions import EvidenceVersionRequired
        raise EvidenceVersionRequired(root, input_hash)
    return bool(force or not valid), planned if valid else {}
