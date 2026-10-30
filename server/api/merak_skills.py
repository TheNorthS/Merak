"""MERAK 技能集成 API — 使用真实注册表和执行引擎"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional
import json

from .auth import get_current_user, UserInfo
from ..services.skill_registry import skill_registry
from ..services.merak_bridge import merak_bridge, TaskStatus

router = APIRouter()


class SkillResponse(BaseModel):
    id: str
    name: str
    category: str
    description: str
    trigger: str
    effort_levels: List[str]
    tags: List[str]
    depends_on: List[str]
    input_files: List[str]
    output_files: List[str]
    allowed_tools: List[str]


class SkillExecuteRequest(BaseModel):
    skill_id: str
    project_path: str
    effort: str = "balanced"
    assurance: str = "draft"
    extra_args: dict = Field(default_factory=dict)
    timeout: int = Field(default=3600, ge=30, le=24 * 3600)


class TaskResponse(BaseModel):
    id: str
    skill_id: str
    status: str
    progress: float
    phase: str
    message: str
    created_at: str
    started_at: Optional[str]
    finished_at: Optional[str]


@router.get("/skills", response_model=List[SkillResponse])
async def list_skills(
    category: Optional[str] = None,
    query: Optional[str] = None,
):
    """列出/搜索 MERAK 技能"""
    if query:
        skills = skill_registry.search(query)
    elif category:
        skills = skill_registry.list_by_category(category)
    else:
        skills = skill_registry.list_all()

    return [
        SkillResponse(
            id=s.id,
            name=s.name,
            category=s.category,
            description=s.description,
            trigger=s.trigger,
            effort_levels=s.effort_levels,
            tags=s.tags,
            depends_on=s.depends_on,
            input_files=s.input_files,
            output_files=s.output_files,
            allowed_tools=s.allowed_tools,
        )
        for s in skills
    ]


@router.get("/skill-usage")
async def get_skill_usage(project_path: str, run_id: str = ""):
    """Return the stage-level skill plan actually applied by a workflow run."""
    from pathlib import Path

    runs_dir = Path(project_path).expanduser().resolve() / ".merak" / "runs"
    if run_id:
        candidates = [runs_dir / f"{run_id}.skills.json"]
    elif runs_dir.exists():
        candidates = sorted(runs_dir.glob("*.skills.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    else:
        candidates = []
    for path in candidates:
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        payload["trace_path"] = str(path)
        payload["available_registry_skills"] = skill_registry.total_skills
        return payload
    return {
        "schema": 2,
        "run_id": run_id,
        "registry_total": skill_registry.total_skills,
        "unique_skills_selected": [],
        "unique_skills_candidates": [],
        "unique_skills_executed": [],
        "verified_model_invocation_count": 0,
        "unverified_completed_skills": [],
        "runtime_services_executed": [],
        "stage_execution": {},
        "coverage_ratio": 0.0,
        "stages": {},
        "trace_path": None,
    }


@router.get("/specialist-plan")
async def get_specialist_plan(project_path: str, run_id: str = ""):
    """Return the profile-specific executable subnode plan for one workflow run."""
    from pathlib import Path
    from ..services.research_specialists import research_specialist_service

    root = Path(project_path).expanduser().resolve()
    runs_dir = root / ".merak" / "runs"
    if run_id:
        candidates = [research_specialist_service.plan_path(root, run_id)]
    elif runs_dir.is_dir():
        candidates = sorted(
            runs_dir.glob("*.specialists.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
    else:
        candidates = []
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        payload["plan_path"] = str(path)
        return payload
    return {
        "run_id": run_id,
        "profile": {},
        "subnodes": [],
        "plan_path": None,
    }


@router.get("/skills/{skill_id}")
async def get_skill(skill_id: str):
    """获取技能详情（含内容预览）"""
    skill = skill_registry.get_skill(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    return {
        "id": skill.id,
        "name": skill.name,
        "category": skill.category,
        "description": skill.description,
        "trigger": skill.trigger,
        "effort_levels": skill.effort_levels,
        "assurance_levels": skill.assurance_levels,
        "tags": skill.tags,
        "depends_on": skill.depends_on,
        "input_files": skill.input_files,
        "output_files": skill.output_files,
        "allowed_tools": skill.allowed_tools,
        "content_preview": skill.content_preview,
        "file_path": skill.file_path,
    }


@router.get("/skills/{skill_id}/input-schema")
async def get_skill_input_schema_api(skill_id: str):
    """获取 skill 的输入参数 schema（用于前端动态渲染表单）"""
    from ..workflows.skill_inputs import get_skill_input_schema
    schema = get_skill_input_schema(skill_id)
    return {"skill_id": skill_id, "schema": schema}


@router.get("/atomic-groups")
async def get_atomic_groups():
    """获取所有原子组定义"""
    from ..workflows.skill_inputs import ATOMIC_GROUPS
    return {"groups": ATOMIC_GROUPS}


@router.post("/validate-selection")
async def validate_selection(node_ids: list[str]):
    """验证节点选择是否满足原子组约束"""
    from ..workflows.skill_inputs import validate_node_selection
    return validate_node_selection(node_ids)


@router.get("/categories")
async def list_categories():
    """列出所有技能分类"""
    return {
        "categories": skill_registry.get_categories(),
        "total_skills": skill_registry.total_skills,
    }


@router.get("/pipelines/{pipeline_name}")
async def get_pipeline(pipeline_name: str, user: UserInfo = Depends(get_current_user)):
    """获取流水线定义"""
    stages = skill_registry.get_pipeline_definition(pipeline_name)
    if not stages:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    return {"name": pipeline_name, "stages": stages}


@router.get("/graph")
async def get_skill_graph(user: UserInfo = Depends(get_current_user)):
    """获取技能依赖图"""
    return skill_registry.get_dependency_graph()


# ==================== 执行 ====================


@router.post("/execute", response_model=TaskResponse)
async def execute_skill(
    request: SkillExecuteRequest,
    user: UserInfo = Depends(get_current_user),
):
    """执行 MERAK 技能"""
    skill = skill_registry.get_skill(request.skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill is not registered")

    task_id = await merak_bridge.execute_skill(
        skill_id=request.skill_id,
        project_path=request.project_path,
        effort=request.effort,
        assurance=request.assurance,
        extra_args=request.extra_args,
        timeout=request.timeout,
    )

    task = merak_bridge.get_task(task_id)
    if task is None:
        raise HTTPException(
            status_code=500,
            detail="Skill task was not registered after execution was scheduled",
        )
    return TaskResponse(
        id=task.id,
        skill_id=task.skill_id,
        status=task.status.value,
        progress=task.progress,
        phase=task.phase,
        message=task.message,
        created_at=task.created_at.isoformat(),
        started_at=task.started_at.isoformat() if task.started_at else None,
        finished_at=task.finished_at.isoformat() if task.finished_at else None,
    )


@router.get("/tasks")
async def list_tasks(
    status: Optional[str] = None,
    user: UserInfo = Depends(get_current_user),
):
    """列出任务"""
    task_status = TaskStatus(status) if status else None
    return merak_bridge.list_tasks(task_status)


@router.get("/tasks/{task_id}")
async def get_task(task_id: str, user: UserInfo = Depends(get_current_user)):
    """获取任务详情"""
    task = merak_bridge.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return {
        "id": task.id,
        "skill_id": task.skill_id,
        "status": task.status.value,
        "progress": task.progress,
        "phase": task.phase,
        "message": task.message,
        "effort": task.effort,
        "assurance": task.assurance,
        "created_at": task.created_at.isoformat(),
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "finished_at": task.finished_at.isoformat() if task.finished_at else None,
        "error": task.error,
        "output_lines": task.output_lines[-50:],  # 最后50行
    }


@router.get("/tasks/{task_id}/output")
async def get_task_output(
    task_id: str,
    last_n: int = 200,
    user: UserInfo = Depends(get_current_user),
):
    """获取任务输出"""
    output = merak_bridge.get_task_output(task_id, last_n)
    if output is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"task_id": task_id, "lines": output}


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str, user: UserInfo = Depends(get_current_user)):
    """取消任务"""
    success = await merak_bridge.cancel_task(task_id)
    if not success:
        raise HTTPException(status_code=404, detail="Task not found or already finished")
    return {"status": "cancelled", "task_id": task_id}
