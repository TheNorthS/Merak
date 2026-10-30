"""Chat WebSocket API — Agent 实时交互通道"""

from fastapi import APIRouter, WebSocket, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, Any
import json

import structlog

from ..agent import model_router, ModelRole
from ..agent.engine import agent_engine
from ..agent.prompts import list_available_commands
from ..api.auth import get_current_user, UserInfo
from ..services.project_memory import project_memory
from ..utils.atomic_write import atomic_write_json
from .chat_support import (
    _apply_chat_scope,
    _chat_history_path,
    _ensure_init,
    _resolve_chat_artifact_path,
    _sanitize_chat_history,
)
from .chat_socket_controller import ChatSocketController


logger = structlog.get_logger()

router = APIRouter()


# ==================== REST API ====================

class ChatRequest(BaseModel):
    session_id: Optional[str] = None
    message: str
    model_role: str = "executor"  # executor | reviewer | general


class SessionInfo(BaseModel):
    id: str
    status: str
    iterations: int
    total_tokens: int


class ChatHistoryPayload(BaseModel):
    project_path: str = "."
    activeConversationId: str = ""
    conversations: list[dict[str, Any]] = []


@router.get("/history")
async def get_chat_history(project_path: str = "."):
    """读取项目级 Chat 历史，持久化位置为 .merak/chat/conversations.json。"""
    path = _chat_history_path(project_path)
    if not path.exists():
        return {"activeConversationId": "", "conversations": [], "path": str(path)}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        clean = _sanitize_chat_history(data)
        clean["path"] = str(path)
        return clean
    except Exception as e:
        logger.warning("Failed to load chat history", path=str(path), error=str(e))
        return {"activeConversationId": "", "conversations": [], "path": str(path), "error": str(e)}


@router.put("/history")
async def save_chat_history(payload: ChatHistoryPayload):
    """保存项目级 Chat 历史。前端 localStorage 只作为临时 fallback。"""
    path = _chat_history_path(payload.project_path)
    clean = _sanitize_chat_history(payload.model_dump())
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, clean)
    return {"status": "saved", "path": str(path), "conversations": len(clean["conversations"])}


@router.post("/sessions")
async def create_session(
    system_prompt: str = "",
    role: str = "executor",
    user: UserInfo = Depends(get_current_user),
):
    """创建 Agent 会话"""
    _ensure_init()
    model_role = ModelRole(role)
    session = agent_engine.create_session(system_prompt=system_prompt, role=model_role)
    return {"session_id": session.id, "role": role}


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, user: UserInfo = Depends(get_current_user)):
    """获取会话状态"""
    session = agent_engine.get_session(session_id)
    if not session:
        return {"error": "Session not found"}
    return {
        "id": session.id,
        "status": session.status.value,
        "iterations": session.iterations,
        "total_tokens": session.total_tokens,
        "messages": len(session.messages),
    }


@router.post("/sessions/{session_id}/cancel")
async def cancel_session(session_id: str, user: UserInfo = Depends(get_current_user)):
    """取消正在执行的 Agent"""
    await agent_engine.cancel(session_id)
    return {"status": "cancelled"}


@router.get("/commands")
async def get_commands(user: UserInfo = Depends(get_current_user)):
    """列出所有可用的 / 命令"""
    _ensure_init()
    return {"commands": list_available_commands()}


@router.get("/models")
async def list_models(user: UserInfo = Depends(get_current_user)):
    """列出可用模型"""
    _ensure_init()
    return {
        "providers": model_router.list_providers(),
        "strategy": model_router.get_strategy(),
    }


@router.get("/context")
async def get_project_context(project_path: str = "."):
    """获取项目研究上下文（供 Copilot 面板展示）"""
    _ensure_init()
    from pathlib import Path
    mem = project_memory.load(project_path)

    # 扫描产物目录
    artifacts = []
    p = Path(project_path)
    for subdir, exts, label in [
        ("paper", [".tex"], "LaTeX 论文"),
        ("slides", [".tex"], "演示文稿"),
        ("experiments", [".py", ".ipynb"], "实验代码"),
        ("figures", [".py", ".mmd", ".tex", ".svg", ".png"], "图表"),
    ]:
        d = p / subdir
        if d.exists():
            files = [f for ext in exts for f in d.rglob(f"*{ext}")]
            if files:
                artifacts.append({"type": label, "count": len(files), "dir": subdir})

    return {
        "research_direction": mem.research_direction,
        "workflow_history": [
            {"status": r.get("status", "?"), "nodes": r.get("nodes_completed", [])}
            for r in mem.workflow_history[-3:]
        ],
        "artifacts": artifacts,
        "recent_entries": [
            {"key": e.key, "content": e.content[:120]}
            for e in sorted(mem.entries, key=lambda x: x.timestamp, reverse=True)[:5]
        ],
    }


@router.post("/models/strategy")
async def set_strategy(role: str, provider: str, user: UserInfo = Depends(get_current_user)):
    """设置模型路由策略"""
    model_router.set_strategy(ModelRole(role), provider)
    return {"status": "updated", "role": role, "provider": provider}


# ==================== 智能修改 API ====================

class SmartEditRequest(BaseModel):
    file_path: str
    instruction: str
    session_id: Optional[str] = None
    project_path: str = "."


@router.post("/smart-edit")
async def smart_edit(request: SmartEditRequest, user: UserInfo = Depends(get_current_user)):
    """智能修改文件（LaTeX/PPT/代码）"""
    _ensure_init()

    target_path = _resolve_chat_artifact_path(request.project_path, request.file_path)
    if not target_path:
        raise HTTPException(
            status_code=400,
            detail="Chat 只能智能修改研究产物目录中的文件：paper/、slides/、experiments/、figures/、literature/、ideas/，以及根目录 NARRATIVE_REPORT.md",
        )

    session_id = request.session_id
    if not session_id:
        session = agent_engine.create_session(
            system_prompt="你是一个专业的科研产物编辑助手。根据用户指令精确修改论文、实验代码、图表或演示稿。只修改需要改动的部分。",
            role=ModelRole.EXECUTOR,
        )
        _apply_chat_scope(session, request.project_path)
        session_id = session.id
    else:
        session = agent_engine.get_session(session_id)
        if session is None:
            session = agent_engine.create_session(
                system_prompt="你是一个专业的科研产物编辑助手。根据用户指令精确修改论文、实验代码、图表或演示稿。只修改需要改动的部分。",
                role=ModelRole.EXECUTOR,
            )
            session_id = session.id
        _apply_chat_scope(session, request.project_path)

    result = await agent_engine.smart_edit(
        session_id=session_id,
        file_path=str(target_path),
        instruction=request.instruction,
    )
    return {"session_id": session_id, "result": result}


# ==================== WebSocket 实时 Chat ====================

@router.websocket("/ws")
async def chat_websocket(websocket: WebSocket) -> None:
    """Accept one chat socket and delegate its bounded protocol handlers."""
    await websocket.accept()
    await ChatSocketController(websocket).run()
