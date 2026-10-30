"""Meta-Optimize 自进化管理 API"""

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/api/meta-optimize", tags=["meta-optimize"])


class MutationDecision(BaseModel):
    decided_by: str = "human"
    reason: str = ""


@router.get("/mutations")
async def list_mutations(project_path: str = ".", status: Optional[str] = None):
    """列出所有 skill 修改提案"""
    from ..services.meta_optimize import get_meta_optimize_gate
    gate = get_meta_optimize_gate(project_path)
    return {"mutations": gate.list_mutations(status)}


@router.get("/mutations/{mutation_id}")
async def get_mutation(mutation_id: str, project_path: str = "."):
    """获取单个 mutation 详情"""
    from ..services.meta_optimize import get_meta_optimize_gate
    gate = get_meta_optimize_gate(project_path)
    mutations = gate.list_mutations()
    for m in mutations:
        if m["id"] == mutation_id:
            return m
    return {"error": "Not found"}


@router.post("/mutations/{mutation_id}/approve")
async def approve_mutation(mutation_id: str, body: MutationDecision, project_path: str = "."):
    """批准并应用 mutation"""
    from ..services.meta_optimize import get_meta_optimize_gate
    gate = get_meta_optimize_gate(project_path)
    return gate.approve_mutation(mutation_id, body.decided_by)


@router.post("/mutations/{mutation_id}/reject")
async def reject_mutation(mutation_id: str, body: MutationDecision, project_path: str = "."):
    """拒绝 mutation"""
    from ..services.meta_optimize import get_meta_optimize_gate
    gate = get_meta_optimize_gate(project_path)
    return gate.reject_mutation(mutation_id, body.reason)


@router.post("/mutations/{mutation_id}/rollback")
async def rollback_mutation(mutation_id: str, project_path: str = "."):
    """回滚已应用的 mutation"""
    from ..services.meta_optimize import get_meta_optimize_gate
    gate = get_meta_optimize_gate(project_path)
    return gate.rollback_mutation(mutation_id)
