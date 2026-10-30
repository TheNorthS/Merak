"""Execute an explicitly approved evidence version in its authorized producer run."""
from pathlib import Path
from typing import Any
from ..services.evidence_versions import create_evidence_version
from ..services.experiment_placeholders import experiment_placeholder_service
from ..services.simulation_publication_attestation import _current_bundle


async def produce_approved_version(run: Any, direction: str) -> dict:
    approval = run.options.get("_evidence_version_approval")
    if not isinstance(approval, dict):
        raise ValueError("EVIDENCE_VERSION_REQUIRED: explicitly approve a new evidence version before resuming")
    async def producer(stage: Path) -> dict:
        return await experiment_placeholder_service.ensure(stage, direction, evidence_mode="synthetic_preview",
            target_venue=str(run.options.get("target_venue") or ""), research_family=str(run.options.get("research_family") or ""),
            study_archetype=str(run.options.get("study_archetype") or ""))
    result = await create_evidence_version(Path(run.project_path), direction, run.options, approval,
                                          producer=producer, validate=_current_bundle)
    run.options.pop("_evidence_version_approval", None)
    return result
