"""Audit a bounded, non-executing correction without re-signing workflow gates."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.live_snapshot_resume_validation import scientific_digest, validate_copy_boundary


MUTABLE_FILES = frozenset({
    "experiments/configs/main.yaml", "experiments/RUN_SPEC.json",
    "experiments/src/data.py", "experiments/PROTOCOL_CONFORMANCE.json",
    "experiments/results/analysis.md", "experiments/results/CLAIM_DECISIONS.json",
    "NARRATIVE_REPORT.md", "paper/sections/03_method.tex",
    "paper/sections/04_experiments.tex", "paper/sections/05_results.tex",
})
_DIRECTORIES = (
    "ideas", "literature", "experiments", "figures", "paper", "review-stage",
    ".merak/runs", ".merak/skill-invocations", ".merak/snapshot-source-traces",
)


def digest_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def input_inventory(root: Path) -> dict[str, str]:
    paths = {path for name in _DIRECTORIES for path in (root / name).rglob("*") if path.is_file()}
    paths.update(root / name for name in ("NARRATIVE_REPORT.md",) if (root / name).is_file())
    return {path.relative_to(root).as_posix(): digest_file(path) for path in sorted(paths)}


def correction_baseline(root: Path, original: Path, run_id: str, *,
                        state_pin: str, science_pin: str) -> dict:
    """Capture stopped owner identities before any explicit correction is applied."""
    from scripts.verify_live_remaining_snapshot import protected_inputs

    root, original = root.resolve(strict=True), original.resolve(strict=True)
    if root == original or root.is_relative_to(original) or original.is_relative_to(root):
        raise ValueError("Scientific correction requires a distinct isolated copy")
    validate_copy_boundary(root)
    state_path = root / f".merak/runs/{run_id}.json"
    state = json.loads(state_path.read_text(encoding="utf-8-sig"))
    source = json.loads((original / f".merak/runs/{run_id}.json").read_text(encoding="utf-8-sig"))
    if (digest_file(state_path) != state_pin or scientific_digest(protected_inputs(root)) != science_pin
            or state.get("run_id") != run_id or state.get("status") != "incomplete"
            or source.get("run_id") != run_id or source.get("status") != "cancelled"):
        raise ValueError("Correction requires the independently pinned, stopped copy and source")
    return {
        "schema": 1, "operation": "authorized_nonexecuting_scientific_correction",
        "snapshot_path": str(root), "original_path": str(original), "run_id": run_id,
        "state_sha256": state_pin, "science_before_sha256": science_pin,
        "mutable_files": sorted(MUTABLE_FILES), "copy_before": input_inventory(root),
        "original_before": input_inventory(original),
        "models_authorized_in_this_operation": False, "training_authorized": False,
        "raw_result_changes_authorized": False,
    }


def verify_correction(root: Path, original: Path, baseline_path: Path, baseline_pin: str) -> dict:
    """Verify exact raw-data preservation; this is NOT a scientific acceptance."""
    from scripts.verify_live_remaining_snapshot import protected_inputs

    if digest_file(baseline_path) != baseline_pin:
        raise ValueError("Correction baseline differs from the independently recorded digest")
    baseline = json.loads(baseline_path.read_text(encoding="utf-8-sig"))
    root, original = root.resolve(strict=True), original.resolve(strict=True)
    if (baseline.get("schema") != 1
            or baseline.get("operation") != "authorized_nonexecuting_scientific_correction"
            or baseline.get("snapshot_path") != str(root) or baseline.get("original_path") != str(original)
            or baseline.get("mutable_files") != sorted(MUTABLE_FILES)
            or any(baseline.get(name) is not False for name in (
                "models_authorized_in_this_operation", "training_authorized", "raw_result_changes_authorized"))):
        raise ValueError("Scientific correction baseline has a different authority or scope")
    validate_copy_boundary(root)
    current, before = input_inventory(root), baseline["copy_before"]
    changed = sorted(name for name in set(before) | set(current) if before.get(name) != current.get(name))
    if not changed or not set(changed) <= MUTABLE_FILES:
        raise ValueError("Correction changes no inputs or changes files outside its explicit scope")
    if any(name not in current for name in before):
        raise ValueError("Scientific correction cannot delete an existing input")
    if input_inventory(original) != baseline["original_before"]:
        raise ValueError("Scientific correction changed the original project")
    run_id = baseline["run_id"]
    if digest_file(root / f".merak/runs/{run_id}.json") != baseline["state_sha256"]:
        raise ValueError("Scientific correction cannot rewrite workflow acceptance or execution evidence")
    return {
        "schema": 1, "boundary_verified": True, "baseline_sha256": baseline_pin,
        "snapshot_path": str(root), "run_id": run_id, "changed_files": changed,
        "changed_sha256": {name: {"before": before.get(name), "after": current[name]} for name in changed},
        "science_before_sha256": baseline["science_before_sha256"],
        "science_after_sha256": scientific_digest(protected_inputs(root)),
        "all_raw_results_byte_identical": True, "original_inputs_unchanged": True,
        "workflow_state_and_execution_evidence_unchanged": True,
        "scientific_execution_performed": False, "model_invoked": False,
        "scientific_acceptance_granted": False,
        "requires_fresh_owner_validation": ["exp-design", "exp-run", "results", "narrative", "figure", "paper", "review"],
    }
