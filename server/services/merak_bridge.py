"""
MERAK 技能执行引擎 — API Agent 桥接

功能：
- 通过内置 AgentEngine 执行 MERAK 技能
- 实时记录 agent 事件输出
- 任务生命周期管理（启动/取消/超时）
- 执行历史记录
- 并发控制
"""

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional, Callable

import structlog

logger = structlog.get_logger()


def _skill_system_prompt(
    skill_name: str,
    project_path: str,
) -> tuple[str, Any]:
    from ..agent.prompts import MERAK_SYSTEM_PROMPT
    from ..services.skill_registry import skill_registry

    system_prompt = MERAK_SYSTEM_PROMPT
    skill_meta = skill_registry.get_skill(skill_name)
    if skill_meta and skill_meta.file_path:
        try:
            skill_content = Path(skill_meta.file_path).read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            logger.warning(
                "Failed to load registered skill content",
                skill=skill_name,
                error=str(exc),
            )
        else:
            system_prompt += f"\n\n## SKILL: {skill_name}\n\n{skill_content}"
    system_prompt += f"\n\n## 项目路径\n当前研究项目在: {project_path}"
    return system_prompt, skill_meta


class TaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


@dataclass
class SkillTask:
    """技能执行任务"""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    skill_id: str = ""
    project_path: str = ""
    effort: str = "balanced"
    assurance: str = "draft"
    extra_args: dict = field(default_factory=dict)

    # 状态
    status: TaskStatus = TaskStatus.QUEUED
    progress: float = 0
    phase: str = ""
    message: str = ""

    # 时间
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    timeout_seconds: int = 3600

    # Agent 会话
    session_id: Optional[str] = None

    # 输出
    output_lines: list[str] = field(default_factory=list)
    output_path: Optional[str] = None
    error: Optional[str] = None

    # 回调
    on_output: Optional[Callable] = None
    on_status_change: Optional[Callable] = None


class MerakBridge:
    """MERAK 技能执行桥接"""

    def __init__(self):
        self._tasks: dict[str, SkillTask] = {}
        self._running: dict[str, SkillTask] = {}
        self._task_handles: dict[str, asyncio.Task] = {}
        self._max_concurrent = 3
        self._stopping = False

    async def start(self):
        """初始化桥接器"""
        self._stopping = False
        logger.info("MERAK bridge initialized", backend="agent-engine")

    async def stop(self):
        """Cancel active/queued skill tasks without starting new queued work."""
        self._stopping = True
        queued = [task for task in self._tasks.values() if task.status == TaskStatus.QUEUED]
        for task in queued:
            task.status = TaskStatus.CANCELLED
            task.finished_at = datetime.utcnow()
            await self._notify_status(task)
        handles = list(self._task_handles.values())
        for handle in handles:
            if not handle.done():
                handle.cancel()
        if handles:
            await asyncio.gather(*handles, return_exceptions=True)
        self._task_handles.clear()
        self._running.clear()
        logger.info("MERAK bridge stopped")

    async def execute_skill(
        self,
        skill_id: str,
        project_path: str,
        effort: str = "balanced",
        assurance: str = "draft",
        extra_args: dict | None = None,
        on_output: Optional[Callable] = None,
        on_status_change: Optional[Callable] = None,
        timeout: int = 3600,
    ) -> str:
        """执行 MERAK 技能"""
        if self._stopping:
            raise RuntimeError("MERAK bridge is stopping and cannot accept new tasks")
        task = SkillTask(
            skill_id=skill_id,
            project_path=project_path,
            effort=effort,
            assurance=assurance,
            extra_args=extra_args or {},
            timeout_seconds=timeout,
            on_output=on_output,
            on_status_change=on_status_change,
        )
        self._tasks[task.id] = task

        if len(self._running) >= self._max_concurrent:
            task.status = TaskStatus.QUEUED
            task.message = f"Queued (waiting for slot, {len(self._running)}/{self._max_concurrent} running)"
            logger.info("Skill task queued", task=task.id, skill=skill_id)
        else:
            self._schedule_task(task)

        return task.id

    def _schedule_task(self, task: SkillTask):
        self._running[task.id] = task
        self._task_handles[task.id] = asyncio.create_task(self._run_task(task))

    async def _run_task(self, task: SkillTask):
        """执行单个任务"""
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.utcnow()
        task.phase = "starting"
        task.message = f"Starting /{task.skill_id}..."
        await self._notify_status(task)

        try:
            await self._run_agent_skill(task)
        except asyncio.TimeoutError:
            task.status = TaskStatus.TIMEOUT
            task.error = f"Task timed out after {task.timeout_seconds}s"
            task.message = "Timeout"
        except asyncio.CancelledError:
            task.status = TaskStatus.CANCELLED
            task.message = "Cancelled"
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            task.message = f"Failed: {e}"
            logger.error("Skill task failed", task=task.id, error=str(e))
        finally:
            task.finished_at = datetime.utcnow()
            self._running.pop(task.id, None)
            self._task_handles.pop(task.id, None)
            await self._notify_status(task)
            await self._process_queue()

    async def _run_agent_skill(self, task: SkillTask):
        """通过内置 AgentEngine 执行技能。"""
        from ..agent import ModelRole
        from ..agent.engine import agent_engine, AgentEvent
        from ..services.skill_registry import skill_registry

        skill_name = task.skill_id.lstrip("/")
        system_prompt, skill_meta = _skill_system_prompt(skill_name, task.project_path)
        session = agent_engine.create_session(system_prompt=system_prompt, role=ModelRole.EXECUTOR)
        session.project_path = str(Path(task.project_path).expanduser().resolve())
        session.context_key = f"skill-chain:{skill_name}"
        session.tool_policy = "workflow_artifacts"
        task.session_id = session.id

        prompt_parts = [
            f"/{skill_name}",
            f"Project path: {task.project_path}",
            f"Effort: {task.effort}",
            f"Assurance: {task.assurance}",
        ]
        if task.extra_args:
            prompt_parts.append("Extra arguments:")
            prompt_parts.append(json.dumps(task.extra_args, ensure_ascii=False, indent=2))
        user_message = "\n\n".join(prompt_parts)

        async def on_event(event: AgentEvent):
            if event.type == "status":
                status = event.data.get("status", "running") if isinstance(event.data, dict) else str(event.data)
                task.phase = status
                task.message = status
            elif event.type == "text" and event.data:
                text = str(event.data)
                task.output_lines.append(text)
                task.progress = max(task.progress, 10)
                if task.on_output:
                    await self._call_output(task, text, False)
            elif event.type == "tool_call":
                name = event.data.get("name", "tool") if isinstance(event.data, dict) else "tool"
                task.phase = "tool_calling"
                task.message = f"Running tool: {name}"
                task.output_lines.append(task.message)
            elif event.type == "tool_result":
                data = event.data if isinstance(event.data, dict) else {}
                name = data.get("name", "tool")
                ok = data.get("success", False)
                line = f"Tool {name}: {'ok' if ok else 'failed'}"
                task.output_lines.append(line)
                task.message = line
                task.progress = min(max(task.progress + 5, 15), 95)
            elif event.type == "error":
                task.output_lines.append(str(event.data))
                task.message = str(event.data)
            await self._notify_status(task)

        allowed_tools = (
            skill_registry.resolve_allowed_tools(skill_name, list(agent_engine._tools))
            if skill_meta else []
        )
        allowed_tools = [
            name for name in allowed_tools
            if name not in {"Agent", "AskUserQuestion"}
        ] or [
            name for name in ("Read", "Write", "Edit", "Glob", "Grep")
            if name in agent_engine._tools
        ]
        result = await asyncio.wait_for(
            agent_engine.run(
                session_id=session.id,
                user_message=user_message,
                on_event=on_event,
                tools=allowed_tools,
            ),
            timeout=task.timeout_seconds,
        )
        if result and (not task.output_lines or task.output_lines[-1] != result):
            task.output_lines.append(result)
        task.status = TaskStatus.COMPLETED
        task.progress = 100
        task.phase = "completed"
        task.message = "Completed successfully"

    async def _call_output(self, task: SkillTask, line: str, is_stderr: bool):
        if task.on_output is None:
            return
        try:
            if asyncio.iscoroutinefunction(task.on_output):
                await task.on_output(line, is_stderr)
            else:
                task.on_output(line, is_stderr)
        except Exception as exc:
            logger.warning(
                "Skill output callback failed",
                task=task.id,
                skill=task.skill_id,
                error=str(exc),
            )

    async def _notify_status(self, task: SkillTask):
        """通知状态变更"""
        if task.on_status_change:
            try:
                data = {
                    "task_id": task.id,
                    "skill_id": task.skill_id,
                    "status": task.status.value,
                    "progress": task.progress,
                    "phase": task.phase,
                    "message": task.message,
                }
                if asyncio.iscoroutinefunction(task.on_status_change):
                    await task.on_status_change(data)
                else:
                    task.on_status_change(data)
            except Exception as exc:
                logger.warning(
                    "Skill status callback failed",
                    task=task.id,
                    skill=task.skill_id,
                    error=str(exc),
                )

    async def _process_queue(self):
        """处理等待队列"""
        if self._stopping:
            return
        for task in list(self._tasks.values()):
            if task.status == TaskStatus.QUEUED and len(self._running) < self._max_concurrent:
                self._schedule_task(task)

    async def cancel_task(self, task_id: str) -> bool:
        """取消任务"""
        task = self._tasks.get(task_id)
        if not task:
            return False

        handle = self._task_handles.get(task_id)
        if handle and not handle.done():
            handle.cancel()
            try:
                await handle
            except asyncio.CancelledError:
                pass
        elif task.status == TaskStatus.QUEUED:
            task.status = TaskStatus.CANCELLED
            task.finished_at = datetime.utcnow()
            await self._notify_status(task)
        else:
            return False

        if task.session_id:
            from ..agent.engine import agent_engine
            await agent_engine.cancel(task.session_id)
        return True

    def get_task(self, task_id: str) -> Optional[SkillTask]:
        """获取任务"""
        return self._tasks.get(task_id)

    def list_tasks(self, status: Optional[TaskStatus] = None) -> list[dict]:
        """列出任务"""
        tasks = list(self._tasks.values())
        if status:
            tasks = [t for t in tasks if t.status == status]

        return [
            {
                "id": t.id,
                "skill_id": t.skill_id,
                "status": t.status.value,
                "progress": t.progress,
                "phase": t.phase,
                "message": t.message,
                "created_at": t.created_at.isoformat(),
                "started_at": t.started_at.isoformat() if t.started_at else None,
                "finished_at": t.finished_at.isoformat() if t.finished_at else None,
                "effort": t.effort,
                "assurance": t.assurance,
            }
            for t in sorted(tasks, key=lambda t: t.created_at, reverse=True)
        ]

    def get_task_output(self, task_id: str, last_n: int = 100) -> list[str]:
        """获取任务输出"""
        task = self._tasks.get(task_id)
        if not task:
            return []
        return task.output_lines[-last_n:]


merak_bridge = MerakBridge()
