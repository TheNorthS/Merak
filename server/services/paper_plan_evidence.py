"""Resolve plan evidence from verified results, independently of future figure planning."""
from pathlib import Path

from .simulation_publication_attestation import _current_bundle
from ..contracts.preparation import PreparationContractError


def verified_simulation_plan_evidence(root: Path) -> bool:
    manifest = root / "experiments/results/simulated/SIMULATION_MANIFEST.json"
    if not manifest.is_file():
        return False
    try:
        _current_bundle(root)  # Validate schema, provenance and every declared input/output hash.
    except (ValueError, OSError) as error:
        raise PreparationContractError(f"Paper plan result evidence is invalid: {error}", owner="exp-run",
                                       paths=("experiments/results/simulated/SIMULATION_MANIFEST.json",)) from error
    return True


def record_delegate_failure(root: Path, run_id: str, source_hash: str, error: str) -> None:
    from ..utils.atomic_write import atomic_write_json
    atomic_write_json(root / ".merak/PAPER_PLAN_DELEGATE.json", {
        "schema": 1, "run_id": run_id, "input_sha256": source_hash,
        "status": "failed", "error": error[:1000], "manual_resume_required": True,
    })
