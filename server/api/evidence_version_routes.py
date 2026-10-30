"""Read-only evidence version plan, bound to an existing workflow's saved settings."""
from pathlib import Path
from fastapi import APIRouter, HTTPException
from ..workflows.run_state import RunState
from ..services.evidence_versions import version_plan

router = APIRouter()


@router.get("/runs/{run_id}/evidence-version-plan")
async def evidence_version_plan(run_id: str, project_path: str) -> dict:
    state = RunState(project_path, run_id).load()
    if not state:
        raise HTTPException(404, "Run state not found")
    if state.get("status") in {"running", "paused"}:
        return {"required": False}
    errors = [str(phase.get("error") or "") for phase in state.get("phases", {}).values()]
    from ..services.evidence_publication_recovery import pending_publication
    required = any("EVIDENCE_VERSION_REQUIRED" in error or "Existing simulation evidence does not match" in error for error in errors)
    required = required or bool(pending_publication(Path(project_path).resolve()))
    if not required:
        return {"required": False}
    config = state.get("config") or {}
    return {"required": True, **version_plan(Path(project_path).resolve(), str(config.get("direction") or ""), config.get("options") or {})}
