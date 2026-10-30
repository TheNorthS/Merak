"""Overleaf synchronization API."""

from dataclasses import asdict

from fastapi import APIRouter
from pydantic import BaseModel

from ..services.overleaf_sync import overleaf_sync

router = APIRouter(prefix="/api/overleaf", tags=["overleaf"])


class LinkRequest(BaseModel):
    project_id: str
    local_path: str
    email: str
    token: str


class PushRequest(BaseModel):
    project_id: str
    message: str = "Update from MERAK"


def _result_payload(result) -> dict:
    return asdict(result)


@router.post("/link")
async def link_project(req: LinkRequest):
    """Verify credentials and persist a credential-safe project link."""
    result = await overleaf_sync.link_project(req.project_id, req.local_path, req.email, req.token)
    return _result_payload(result)


@router.post("/test/{project_id}")
async def test_connection(project_id: str):
    """Run a real authenticated Git gateway test for a linked project."""
    return _result_payload(await overleaf_sync.test_connection(project_id))


@router.post("/pull/{project_id}")
async def pull(project_id: str):
    """Pull without overwriting local conflict sides."""
    return _result_payload(await overleaf_sync.pull(project_id))


@router.post("/push")
async def push(req: PushRequest):
    """Commit and push the local paper tree."""
    result = await overleaf_sync.push(req.project_id, req.message)
    return _result_payload(result)


@router.post("/sync/{project_id}")
async def sync(project_id: str):
    """Commit local changes, pull safely, then push."""
    return _result_payload(await overleaf_sync.sync(project_id))


@router.post("/auto-sync/start/{project_id}")
async def start_auto_sync(project_id: str):
    started = await overleaf_sync.start_auto_sync(project_id)
    return {"success": started, "status": "started" if started else "not_linked"}


@router.post("/auto-sync/stop/{project_id}")
async def stop_auto_sync(project_id: str):
    stopped = await overleaf_sync.stop_auto_sync(project_id)
    return {"success": stopped, "status": "stopped" if stopped else "not_linked"}


@router.get("/status/{project_id}")
async def get_status(project_id: str):
    """获取同步状态"""
    return overleaf_sync.get_status(project_id)


@router.get("/projects")
async def list_projects():
    return overleaf_sync.list_projects()


@router.delete("/projects/{project_id}")
async def unlink_project(project_id: str):
    unlinked = await overleaf_sync.unlink(project_id)
    return {"success": unlinked, "status": "unlinked" if unlinked else "not_linked"}
