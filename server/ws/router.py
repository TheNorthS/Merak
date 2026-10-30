"""WebSocket 路由 — 终端、SSH、实验日志和工作流状态"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import asyncio
import json
from pathlib import Path
import structlog

from ..utils.atomic_write import path_lock

logger = structlog.get_logger()

ws_router = APIRouter()




@ws_router.websocket("/ws/terminal/{session_id}")
async def terminal_websocket(websocket: WebSocket, session_id: str):
    """本地终端 WebSocket — 真实 PTY"""
    from .local_terminal import handle_local_terminal
    await handle_local_terminal(websocket, session_id)


@ws_router.websocket("/ws/ssh/{server_id}")
async def ssh_terminal_websocket(websocket: WebSocket, server_id: str):
    """SSH 远程终端 WebSocket — 真实 PTY 转发"""
    from .ssh_terminal import handle_ssh_terminal
    await handle_ssh_terminal(websocket, server_id)




@ws_router.websocket("/ws/experiment/{experiment_id}/logs")
async def experiment_logs_websocket(websocket: WebSocket, experiment_id: str):
    """Stream scheduler/runtime events for every experiment backend."""
    await websocket.accept()
    logger.info("Experiment log stream opened", experiment=experiment_id)

    from ..services.experiment_runner import experiment_scheduler
    send_lock = asyncio.Lock()

    async def send_json(payload: dict) -> None:
        async with send_lock:
            await websocket.send_text(json.dumps(payload, default=str))

    async def listener(event: str, data: dict):
        if data.get("experiment_id") != experiment_id:
            return
        try:
            await send_json({"type": event, **data})
        except Exception:
            pass

    experiment_scheduler.add_listener(listener)

    try:
        experiment = experiment_scheduler.get_experiment(experiment_id)
        if not experiment:
            await send_json({
                "type": "error",
                "message": "Experiment not found in the active scheduler; use the runtime manifest API after restart",
            })
            return
        await send_json({
            "type": "subscribed",
            "experiment_id": experiment_id,
            "status": experiment.status,
            "jobs": [
                {
                    "job_id": job.id,
                    "status": job.status.value,
                    "backend": job.backend.value,
                    "log_path": job.log_path,
                    "manifest_path": job.manifest_path,
                }
                for job in experiment.jobs
            ],
        })
        while True:
            msg_raw = await websocket.receive_text()
            try:
                msg = json.loads(msg_raw)
            except json.JSONDecodeError:
                await send_json({"type": "protocol_error", "message": "Invalid JSON"})
                continue
            if not isinstance(msg, dict):
                await send_json({"type": "protocol_error", "message": "Message must be an object"})
                continue
            if msg.get("type") == "stop":
                break
            elif msg.get("type") == "ping":
                await send_json({"type": "pong"})

    except WebSocketDisconnect:
        logger.info("Experiment log stream disconnected", experiment=experiment_id)
    except Exception as e:
        logger.error("Experiment log stream error", error=str(e))
        try:
            await send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        experiment_scheduler.remove_listener(listener)


# ==================== Workflow 状态推送 ====================

# 全局 workflow WebSocket 连接池
_workflow_clients: set[WebSocket] = set()
_workflow_client_locks: dict[WebSocket, asyncio.Lock] = {}


@ws_router.websocket("/ws/workflow")
async def workflow_status_websocket(websocket: WebSocket):
    """Workflow 执行状态实时推送"""
    await websocket.accept()
    _workflow_clients.add(websocket)
    _workflow_client_locks[websocket] = asyncio.Lock()
    logger.info("Workflow WS client connected", total=len(_workflow_clients))

    try:
        while True:
            # 心跳 / 客户端命令
            msg_raw = await websocket.receive_text()
            try:
                msg = json.loads(msg_raw)
            except json.JSONDecodeError:
                async with _workflow_client_locks[websocket]:
                    await websocket.send_text(json.dumps({
                        "type": "protocol_error",
                        "message": "Invalid JSON",
                    }))
                continue
            if not isinstance(msg, dict):
                async with _workflow_client_locks[websocket]:
                    await websocket.send_text(json.dumps({
                        "type": "protocol_error",
                        "message": "Message must be an object",
                    }))
                continue
            if msg.get("type") == "ping":
                async with _workflow_client_locks[websocket]:
                    await websocket.send_text(json.dumps({"type": "pong"}))
            elif msg.get("type") == "get_status":
                # 返回当前所有 run 状态
                from ..workflows.engine import workflow_engine
                runs = workflow_engine.list_runs()
                async with _workflow_client_locks[websocket]:
                    await websocket.send_text(json.dumps({"type": "runs_status", "runs": runs}))
            elif msg.get("type") == "answer_question":
                # 用户回答了 Manual Review 问题
                qid = msg.get("question_id", "")
                answer = msg.get("answer", "")
                if qid:
                    resolve_question(qid, answer)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.debug("Workflow WS error", error=str(e))
    finally:
        _workflow_clients.discard(websocket)
        _workflow_client_locks.pop(websocket, None)
        logger.info("Workflow WS client disconnected", total=len(_workflow_clients))


async def broadcast_workflow_event(event_type: str, data: dict):
    """向所有连接的客户端广播 workflow 事件"""
    global _workflow_clients
    if not _workflow_clients:
        return
    message = json.dumps({"type": event_type, **data})
    clients = list(_workflow_clients)

    async def send_one(ws: WebSocket) -> WebSocket | None:
        try:
            lock = _workflow_client_locks.get(ws)
            if lock is None:
                return ws
            async with lock:
                # A disconnected or backpressured renderer must not stall the
                # workflow event loop or suppress logs for every healthy UI.
                await asyncio.wait_for(ws.send_text(message), timeout=5.0)
            return None
        except Exception:
            return ws

    results = await asyncio.gather(
        *(send_one(ws) for ws in clients),
        return_exceptions=False,
    )
    dead = {ws for ws in results if ws is not None}
    _workflow_clients.difference_update(dead)
    for ws in dead:
        _workflow_client_locks.pop(ws, None)


# ==================== Manual Review (Human-in-the-loop) ====================

# 待回答的问题队列
_pending_questions: dict[str, asyncio.Future] = {}


async def push_question_and_wait(question: str, options: str = "", timeout: float = 300) -> str:
    """推送问题到前端并等待用户回答

    通过 workflow WebSocket 广播问题，等待前端发回答案。
    如果没有活跃连接或超时，返回空字符串（让调用方 fallback 到 auto-proceed）。
    """
    if not _workflow_clients:
        return ""

    import uuid
    question_id = uuid.uuid4().hex[:8]

    # 创建 Future 等待回答
    loop = asyncio.get_event_loop()
    future: asyncio.Future = loop.create_future()
    _pending_questions[question_id] = future

    # 广播问题
    await broadcast_workflow_event("user_question", {
        "question_id": question_id,
        "question": question,
        "options": options,
    })

    try:
        answer = await asyncio.wait_for(future, timeout=timeout)
        return answer
    except asyncio.TimeoutError:
        return ""
    finally:
        _pending_questions.pop(question_id, None)


def resolve_question(question_id: str, answer: str):
    """前端通过 WebSocket 回答问题时调用"""
    future = _pending_questions.get(question_id)
    if future and not future.done():
        future.set_result(answer)


# ==================== Meta Event Logging ====================

def log_tool_event(project_path: str, tool_name: str, arguments: dict, output: str, success: bool):
    """记录 tool call 到 .merak/meta/events.jsonl（被动日志）"""
    import time
    meta_dir = Path(project_path) / ".merak" / "meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    event = {
        "ts": time.time(),
        "tool": tool_name,
        "args_keys": list(arguments.keys()),
        "output_len": len(output),
        "success": success,
    }
    event_path = meta_dir / "events.jsonl"
    with path_lock(event_path):
        with event_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
            handle.flush()
