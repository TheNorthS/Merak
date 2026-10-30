"""
Agent 执行引擎 — IDE 的 AI 大脑

核心循环：
1. 接收用户指令（自然语言 or /命令）
2. 选择合适的模型（按角色路由）
3. 执行 Agent Loop（think → tool_use → observe → repeat）
4. 实时推送进度到前端
5. 返回结果

支持：
- 多轮对话
- 工具调用（文件操作、终端、搜索、部署等）
- Executor/Reviewer 角色隔离（可使用同一模型，但不得共享会话上下文）
- 流式输出
- 可中断/恢复
"""

import asyncio
from typing import Optional, Callable, Any, AsyncIterator

import structlog

from . import (
    ModelProvider, ModelRole, ModelRouter, model_router,
    Message, ToolDefinition, DEFAULT_MAX_OUTPUT_TOKENS,
)
from .session_models import (
    AgentEvent as AgentEvent,
    AgentSession as AgentSession,
    AgentStatus as AgentStatus,
    PendingChange as PendingChange,
    ToolResult as ToolResult,
)
from .context_management import AgentContextMixin
from .response_protocol import ResponseProtocolMixin
from .tool_policy import ToolPolicyMixin
from .tool_execution import ToolExecutionMixin
from .model_transport import ModelTransportMixin

logger = structlog.get_logger()

RESEARCH_ARTIFACT_DIRS = ("paper", "slides", "experiments", "figures", "literature", "ideas")
RESEARCH_ARTIFACT_FILES = ("NARRATIVE_REPORT.md",)
RESEARCH_ARTIFACTS_LABEL = ", ".join(f"{name}/" for name in RESEARCH_ARTIFACT_DIRS) + ", " + ", ".join(RESEARCH_ARTIFACT_FILES)
MODEL_WAIT_STATUS_INTERVAL = 8.0
MODEL_FIRST_RESPONSE_TIMEOUT = 120.0
MODEL_TOOL_RESPONSE_TIMEOUT = 240.0
MODEL_STREAM_SILENCE_TIMEOUT = 90.0
MODEL_TOOL_STREAM_SILENCE_TIMEOUT = 90.0
# A figure delegate may legitimately use a bounded provider turn plus
# rendering, but it must still finish before the figure node's 720s idle gate.
NESTED_SKILL_WALL_TIMEOUT = 660.0
NESTED_SKILL_HEARTBEAT_INTERVAL = 10.0
NESTED_SKILL_CANCEL_GRACE = 5.0


class AgentEngine(
    ModelTransportMixin,
    ToolExecutionMixin,
    ToolPolicyMixin,
    ResponseProtocolMixin,
    AgentContextMixin,
):
    """Agent 执行引擎"""

    def __init__(self, router: ModelRouter):
        self.router = router
        self._sessions: dict[str, AgentSession] = {}
        self._tools: dict[str, Any] = {}  # name -> tool_handler
        self._tool_definitions: list[ToolDefinition] = []
        self._running: dict[str, asyncio.Task] = {}

    def register_tool(self, name: str, description: str, parameters: dict, handler: Callable):
        """注册工具"""
        from .tool_schema import prepare_tool_schema

        parameters = prepare_tool_schema(parameters, handler)
        self._tools[name] = handler
        definition = ToolDefinition(
            name=name,
            description=description,
            parameters=parameters,
        )
        for index, existing in enumerate(self._tool_definitions):
            if existing.name == name:
                self._tool_definitions[index] = definition
                return
        self._tool_definitions.append(definition)

    def create_session(self, system_prompt: str = "", role: ModelRole = ModelRole.EXECUTOR) -> AgentSession:
        """创建新会话"""
        session = AgentSession(model_role=role)
        if system_prompt:
            session.messages.append(Message(role="system", content=system_prompt))
        self._sessions[session.id] = session
        return session

    def get_session(self, session_id: str) -> Optional[AgentSession]:
        return self._sessions.get(session_id)

    def _candidate_providers(self, session: AgentSession) -> tuple[list[tuple[str, ModelProvider]], bool]:
        """Return Auto-mode provider candidates and whether transient fallback is allowed."""
        if session.provider_override:
            provider = self.router.get_provider_by_name(session.provider_override)
            if not provider:
                raise ValueError(f"Provider '{session.provider_override}' not found or not configured")
            return [(session.provider_override, provider)], False

        providers: dict[str, ModelProvider] = getattr(self.router, "_providers", {})
        strategy = getattr(self.router, "_strategy", {})
        primary_name = strategy.get(session.model_role, "openai-api")
        preferred = [primary_name, "openai-api", "claude-api", "deepseek", "qwen", "glm", "gemini"]
        order = [name for name in preferred if name in providers]
        order.extend(name for name in providers.keys() if name not in order)

        candidates: list[tuple[str, ModelProvider]] = []
        seen: set[str] = set()
        for name in order:
            if name in seen:
                continue
            provider = providers.get(name)
            if provider:
                candidates.append((name, provider))
                seen.add(name)

        if candidates:
            return candidates, len(candidates) > 1

        provider = self.router.get_provider(session.model_role)
        return [(provider.name, provider)], False

    def _is_transient_model_error(self, exc: Exception) -> bool:
        """Detect upstream capacity/availability failures that are safe to retry elsewhere."""
        from .remote_errors import RemoteCallError
        if isinstance(exc, RemoteCallError):
            return exc.retryable
        text = str(exc).lower()
        transient_markers = (
            "502",
            "bad gateway",
            "503",
            "service temporarily unavailable",
            "service unavailable",
            "no available accounts",
            "overloaded",
            "rate limit",
            "429",
            "timeout",
            "timed out",
            "请求超时",
            "temporarily unavailable",
            "connection reset",
            "connection aborted",
            "peer closed connection",
            "incomplete chunked read",
        )
        return any(marker in text for marker in transient_markers)

    def _model_error_message(self, exc: Exception, provider_name: str, allow_fallback: bool) -> str:
        """Normalize raw SDK/proxy failures into a Chat-friendly explanation."""
        raw = str(exc)
        lower = raw.lower()
        if "no available accounts" in lower:
            detail = "当前模型路由返回 503：账号池暂无可用账号。"
        elif "502" in lower or "bad gateway" in lower:
            detail = "当前模型路由返回 502：上游服务临时不可用。"
        elif "503" in lower or "service temporarily unavailable" in lower or "service unavailable" in lower:
            detail = "当前模型路由返回 503：上游服务临时不可用。"
        elif "timeout" in lower or "timed out" in lower or "请求超时" in lower:
            detail = "当前模型请求超时，模型未在限定时间内返回。"
        else:
            detail = raw

        if allow_fallback:
            return f"{detail}\n已尝试 Auto 模式下的可用模型兜底，但仍未成功。\n最后失败路由: {provider_name}\n原始错误: {raw}"
        return f"{detail}\n当前手动选择的模型: {provider_name}\n原始错误: {raw}"

    async def run(
        self, session_id: str, user_message: str,
        on_event: Optional[Callable[[AgentEvent], Any]] = None,
        tools: Optional[list[str]] = None, max_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
        system_prompt_override: Optional[str] = None,
        partial_stream_timeout_seconds: Optional[float] = None,
    ) -> str:
        from .agent_loop import AgentLoopCoordinator

        coordinator = AgentLoopCoordinator(
            self, session_id, user_message, on_event, tools, max_tokens,
            system_prompt_override, partial_stream_timeout_seconds,
        )
        return await coordinator.run()
    async def run_stream(
        self,
        session_id: str,
        user_message: str,
        tools: Optional[list[str]] = None,
    ) -> AsyncIterator[AgentEvent]:
        """流式执行 Agent Loop（用于 WebSocket 推送）"""
        events: list[AgentEvent] = []

        async def collect_event(event: AgentEvent):
            events.append(event)

        # 在后台运行 Agent Loop
        task = asyncio.create_task(self.run(session_id, user_message, on_event=collect_event, tools=tools))
        self._running[session_id] = task

        # 逐步 yield 事件
        yielded = 0
        while not task.done():
            await asyncio.sleep(0.05)
            while yielded < len(events):
                yield events[yielded]
                yielded += 1

        # yield 剩余事件
        while yielded < len(events):
            yield events[yielded]
            yielded += 1

        # 检查异常
        if task.exception():
            yield AgentEvent(type="error", data=str(task.exception()))

        self._running.pop(session_id, None)

    async def cancel(self, session_id: str):
        """取消正在执行的 Agent"""
        task = self._running.get(session_id)
        if task:
            task.cancel()
        session = self._sessions.get(session_id)
        if session:
            session.status = AgentStatus.CANCELLED
            self._persist_session_transcript(session)

    async def _emit(self, callback: Optional[Callable], event: AgentEvent):
        """发送事件"""
        if callback:
            if asyncio.iscoroutinefunction(callback):
                await callback(event)
            else:
                callback(event)

    # ==================== 智能修改能力 ====================

    async def smart_edit(
        self,
        session_id: str,
        file_path: str,
        instruction: str,
        on_event: Optional[Callable] = None,
    ) -> str:
        """
        智能修改文件（LaTeX 论文/PPT/代码）

        Agent 读取文件内容，理解上下文，根据指令精确修改指定部分。
        不是重新生成，而是 diff-based 编辑。
        """
        # 构建编辑专用 prompt
        edit_prompt = f"""请修改文件 `{file_path}` 的内容。

用户指令：{instruction}

要求：
1. 只修改需要改动的部分，不要重写整个文件
2. 使用 Write 工具写回修改后的完整文件（如果改动大），或用 Edit 工具精确替换（如果改动小）
3. 如果是 LaTeX 文件，确保修改后仍能正确编译
4. 如果是 PPT/Slides 文件，确保格式和结构完整
5. 先用 Read 工具读取当前内容，理解上下文后再修改

请开始："""

        session = self._sessions.get(session_id)
        tools = ["Read", "Write", "Edit"]
        if not session or session.tool_policy != "research_artifacts":
            tools.append("Bash")

        return await self.run(
            session_id=session_id,
            user_message=edit_prompt,
            on_event=on_event,
            tools=tools,
        )


    # ==================== Session Recovery ====================

    def save_session_state(self, session_id: str, project_path: str):
        """保存 agent session 状态到 .merak/runs/ 用于断点恢复

        当 context 接近上限或 workflow 中断时调用。
        """
        from pathlib import Path

        session = self._sessions.get(session_id)
        if not session:
            return

        runs_dir = Path(project_path) / ".merak" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)

        state = {
            "session_id": session.id,
            "status": session.status.value,
            "model_role": session.model_role.value,
            "iterations": session.iterations,
            "total_tokens": session.total_tokens,
            "messages_count": len(session.messages),
            # 保存最后 N 条消息摘要（不保存完整 content 避免文件过大）
            "last_messages": [
                {"role": m.role, "content_preview": (m.content or "")[:200], "has_tool_calls": bool(m.tool_calls)}
                for m in session.messages[-10:]
            ],
            # 保存最后的 assistant 输出（用于恢复时作为上下文）
            "last_output": next(
                (m.content for m in reversed(session.messages) if m.role == "assistant" and m.content),
                ""
            )[:3000],
        }

        state_file = runs_dir / f"{session_id}.json"
        from ..utils.atomic_write import atomic_write_json

        atomic_write_json(state_file, state)

    def load_session_state(self, session_id: str, project_path: str) -> Optional[dict]:
        """从 .merak/runs/ 加载 session 状态"""
        import json
        from pathlib import Path

        state_file = Path(project_path) / ".merak" / "runs" / f"{session_id}.json"
        if not state_file.exists():
            return None

        try:
            payload = json.loads(state_file.read_text(encoding='utf-8'))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"Agent session state is unreadable or corrupt: {state_file}"
            ) from exc
        if not isinstance(payload, dict):
            raise RuntimeError(
                f"Agent session state root must be a JSON object: {state_file}"
            )
        return payload


# 全局 Agent Engine 实例
agent_engine = AgentEngine(model_router)
