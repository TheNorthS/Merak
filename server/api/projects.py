"""项目管理 API"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import List, Literal, Optional
from datetime import datetime

from .access import current_principal, require_project_location
from ..services.access_identity import Principal
from ..services import project_repository
from ..db.engine import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from ..models.models import Project as ProjectRecord

router = APIRouter()


class Project(BaseModel):
    id: str
    name: str
    path: str
    description: str = ""
    created_at: datetime
    updated_at: datetime
    owner: str
    collaborators: List[str] = Field(default_factory=list)
    gpu_config: Optional[dict] = None
    merak_config: Optional[dict] = None


class ProjectCreate(BaseModel):
    name: str
    path: str
    description: str = ""


@router.get("/", response_model=List[Project])
async def list_projects(principal: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db)):
    """列出用户的所有项目"""
    projects = await project_repository.visible_projects(db, principal)
    return [await project_repository.project_payload(db, project) for project in projects]


@router.post("/", response_model=Project)
async def create_project(data: ProjectCreate, principal: Principal = Depends(current_principal),
                         db: AsyncSession = Depends(get_db)):
    """创建新项目"""
    root = require_project_location(principal, data.path)
    project = await project_repository.create_project(db, principal, data.name, str(root), data.description)
    return await project_repository.project_payload(db, project)


class ScaffoldRequest(BaseModel):
    path: str = Field(min_length=1, max_length=4096)
    name: str = Field(default="Untitled Research", min_length=1, max_length=200)
    venue: str = Field(default="ICLR", min_length=1, max_length=200)
    direction: str = Field(default="", max_length=20000)
    mode: Literal["create", "ensure"] = "create"


@router.post("/scaffold")
async def scaffold_project_api(req: ScaffoldRequest, principal: Principal = Depends(current_principal),
                               db: AsyncSession = Depends(get_db)):
    """创建研究项目目录结构（约定大于配置）"""
    from ..services.project_scaffold import ProjectScaffoldConflict, scaffold_project
    root = require_project_location(principal, req.path)
    try:
        result = scaffold_project(req.path, req.name, req.venue, req.direction, mode=req.mode)
    except ProjectScaffoldConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    project = (await db.execute(select(ProjectRecord).where(ProjectRecord.path == str(root)))).scalar_one_or_none()
    if project is None:
        project = await project_repository.create_project(db, principal, req.name, str(root), "")
    result["project_id"] = project.id
    return result


@router.get("/conventions")
async def get_conventions(path: str):
    """获取项目的约定路径"""
    from ..services.project_scaffold import get_convention_paths
    return get_convention_paths(path)


@router.get("/sections")
async def get_sections():
    """获取侧边栏快捷入口"""
    from ..services.project_scaffold import get_directory_sections
    return get_directory_sections()


@router.get("/{project_id}", response_model=Project)
async def get_project(project_id: str, principal: Principal = Depends(current_principal),
                      db: AsyncSession = Depends(get_db)):
    """获取项目详情"""
    for project in await project_repository.visible_projects(db, principal):
        if project.id == project_id:
            return await project_repository.project_payload(db, project)
    raise HTTPException(status_code=404, detail="Project not found")
