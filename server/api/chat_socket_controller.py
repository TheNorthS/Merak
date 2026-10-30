"""Bounded message handlers for one Chat WebSocket connection."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import structlog
from fastapi import WebSocket, WebSocketDisconnect

from ..agent import ModelRole
from ..agent.engine import AgentEvent, agent_engine
from ..agent.prompts import COPILOT_SYSTEM_PROMPT
from ..services.project_memory import project_memory
from .chat_support import (
    CHAT_CONTEXT_ASK_SYSTEM_PROMPT,
    CHAT_MODE_PROMPTS,
    _SerializedChatSocket,
    _apply_chat_scope,
    _build_context_block,
    _build_conversation_context_block,
    _build_project_overview_context,
    _chat_role_for_mode,
    _chat_system_prompt,
    _chat_task_hint,
    _chat_tools_for_mode,
    _ensure_init,
    _looks_like_project_overview_request,
    _normalize_chat_mode,
    _resolve_chat_artifact_path,
)


logger = structlog.get_logger()


class ChatSocketController:
    """Own one socket's session pointer, tasks, and protocol dispatch."""

    def __init__(self, websocket: WebSocket):
        self.websocket = _SerializedChatSocket(websocket)
        self.session_id: str | None = None
        self.project_path = "."
        self.tasks: set[asyncio.Task[Any]] = set()

    async def run(self) -> None:
        _ensure_init()
        logger.info("Chat WebSocket connected")
        try:
            while True:
                message = await self._receive_message()
                if message is not None:
                    await self._dispatch(message)
        except WebSocketDisconnect:
            logger.info("Chat WebSocket disconnected", session=self.session_id)
        finally:
            await self._cancel_connection_tasks()

    async def _receive_message(self) -> dict[str, Any] | None:
        raw = await self.websocket.receive_text()
        try:
            message = json.loads(raw)
        except json.JSONDecodeError as exc:
            await self._send("protocol_error", error=f"Invalid JSON message: {exc.msg}")
            return None
        if not isinstance(message, dict):
            await self._send("protocol_error", error="Chat messages must be JSON objects.")
            return None
        return message

    async def _dispatch(self, message: dict[str, Any]) -> None:
        handlers = {
            "create_session": self._create_session,
            "message": self._message,
            "new_session": self._new_session,
            "select_session": self._select_session,
            "set_provider": self._set_provider,
            "attach_file": self._attach_file,
            "resolve_change": self._resolve_change,
            "cancel": self._cancel,
            "smart_edit": self._smart_edit,
            "ping": self._ping,
        }
        message_type = str(message.get("type") or "message")
        handler = handlers.get(message_type)
        if handler is None:
            await self._send("protocol_error", error=f"Unsupported chat message type: {message_type}")
            return
        await handler(message)

    async def _send(self, event_type: str, **payload: Any) -> None:
        await self.websocket.send_text(json.dumps({"type": event_type, **payload}))

    def _memory_prompt(self, system_prompt: str, project_path: str) -> str:
        memory = project_memory.get_context_for_agent(project_path)
        prompt = system_prompt
        if memory:
            prompt += f"\n\n{memory}"
        return prompt + f"\n\n## 项目路径\n当前研究项目在: {project_path}"

    def _session(
        self, *, system_prompt: str, role: ModelRole, provider: str = "",
        context_key: str = "",
    ) -> Any:
        session = agent_engine.create_session(system_prompt=system_prompt, role=role)
        _apply_chat_scope(session, self.project_path)
        if provider:
            session.provider_override = provider
        session.context_key = context_key
        self.session_id = session.id
        return session

    async def _create_session(self, message: dict[str, Any]) -> None:
        self.project_path = str(message.get("project_path") or ".")
        provider = str(message.get("provider") or "")
        context_key = str(message.get("context_key") or "")
        prompt = self._memory_prompt(
            str(message.get("system_prompt") or COPILOT_SYSTEM_PROMPT), self.project_path,
        )
        session = self._session(
            system_prompt=prompt,
            role=ModelRole(message.get("role", "executor")),
            provider=provider, context_key=context_key,
        )
        await self._send(
            "session_created", session_id=session.id, project_path=self.project_path,
            provider=provider, conversation_id=message.get("conversation_id", ""),
            context_key=context_key,
        )

    def _context(self, message: dict[str, Any], mode: str, user_text: str) -> str:
        context = _build_context_block(self.project_path, message.get("context_files", []))
        if mode == "ask" and not context and _looks_like_project_overview_request(user_text):
            context = _build_project_overview_context(self.project_path)
        return context

    def _message_session(
        self, user_text: str, mode: str, context_key: str,
    ) -> Any:
        session = agent_engine.get_session(self.session_id) if self.session_id else None
        if session is None:
            session = self._session(
                system_prompt=_chat_system_prompt(user_text),
                role=_chat_role_for_mode(mode), context_key=context_key,
            )
        elif user_text.strip().startswith("/") and session.messages and session.messages[0].role == "system":
            session.messages[0].content = _chat_system_prompt(user_text)
        session.model_role = _chat_role_for_mode(mode)
        _apply_chat_scope(session, self.project_path)
        session.context_key = context_key or session.context_key
        self.session_id = session.id
        return session

    def _user_message(
        self, message: dict[str, Any], session: Any, mode: str,
        raw_text: str, context: str,
    ) -> str:
        empty_session = not any(item.role != "system" for item in session.messages)
        history = _build_conversation_context_block(
            message.get("conversation_messages", [])
        ) if empty_session else ""
        return (
            f"{CHAT_MODE_PROMPTS[mode]}{_chat_task_hint(raw_text, mode)}\n\n"
            f"{raw_text}{history}{context}"
        )

    async def _message(self, message: dict[str, Any]) -> None:
        self.project_path = str(message.get("project_path") or self.project_path)
        mode = _normalize_chat_mode(str(message.get("mode") or "edit"))
        raw_text = str(message.get("content") or "")
        context = self._context(message, mode, raw_text)
        session = self._message_session(
            raw_text, mode, str(message.get("context_key") or ""),
        )
        existing = agent_engine._running.get(session.id)
        if existing and not existing.done():
            await self._send(
                "agent_error",
                data="This chat session is already processing a request; cancel it or wait for completion.",
                conversation_id=message.get("conversation_id", ""),
                request_id=message.get("request_id", ""),
            )
            return
        await self._start_agent(
            message, session, raw_text, mode, context,
            self._user_message(message, session, mode, raw_text, context),
        )

    async def _start_agent(
        self, message: dict[str, Any], session: Any, raw_text: str,
        mode: str, context: str, user_message: str,
    ) -> None:
        conversation_id = str(message.get("conversation_id") or "")
        request_id = str(message.get("request_id") or "")
        event_state = {"error_sent": False}

        async def send_event(event: AgentEvent) -> None:
            if event.type == "error":
                event_state["error_sent"] = True
            try:
                await self._send(
                    f"agent_{event.type}", data=event.data, timestamp=event.timestamp,
                    conversation_id=conversation_id, request_id=request_id,
                )
            except Exception:
                pass

        tools = [] if mode in {"ask", "review"} and context else _chat_tools_for_mode(mode)
        max_tokens = 1000 if mode in {"ask", "review"} and context else 4096
        override = CHAT_CONTEXT_ASK_SYSTEM_PROMPT if mode in {"ask", "review"} and context else None
        task = asyncio.create_task(self._run_agent(
            session.id, user_message, raw_text, self.project_path,
            conversation_id, request_id, tools, max_tokens, override,
            event_state, send_event,
        ))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        agent_engine._running[session.id] = task

    async def _run_agent(
        self, session_id: str, user_message: str, raw_text: str, project_path: str,
        conversation_id: str, request_id: str, tools: list[str], max_tokens: int,
        system_override: str | None, event_state: dict[str, bool], send_event: Any,
    ) -> None:
        try:
            result = await agent_engine.run(
                session_id=session_id, user_message=user_message,
                on_event=send_event, tools=tools, max_tokens=max_tokens,
                system_prompt_override=system_override,
            )
            if raw_text.strip().startswith("/") and result:
                command = raw_text.strip().split()[0]
                project_memory.add_entry(
                    project_path, key=f"chat/{command}/{int(time.time())}",
                    content=f"User: {raw_text[:100]}\nAgent: {result[:200]}", source="chat",
                )
        except asyncio.CancelledError:
            await self._safe_agent_terminal(
                "agent_done", conversation_id, request_id,
                data={"response": "[已取消]", "tokens": 0},
            )
        except Exception as exc:
            if not event_state["error_sent"]:
                await self._safe_agent_terminal(
                    "agent_error", conversation_id, request_id, data=str(exc),
                )
        finally:
            if agent_engine._running.get(session_id) is asyncio.current_task():
                agent_engine._running.pop(session_id, None)

    async def _safe_agent_terminal(
        self, event_type: str, conversation_id: str, request_id: str, **payload: Any,
    ) -> None:
        try:
            await self._send(
                event_type, conversation_id=conversation_id,
                request_id=request_id, **payload,
            )
        except Exception:
            pass

    async def _new_session(self, message: dict[str, Any]) -> None:
        self.project_path = str(message.get("project_path") or self.project_path)
        provider = str(message.get("provider") or "")
        context_key = str(message.get("context_key") or "")
        session = self._session(
            system_prompt=self._memory_prompt(COPILOT_SYSTEM_PROMPT, self.project_path),
            role=ModelRole(message.get("role", "executor")),
            provider=provider, context_key=context_key,
        )
        await self._send(
            "session_created", session_id=session.id, is_new=True, provider=provider,
            conversation_id=message.get("conversation_id", ""), context_key=context_key,
        )

    async def _select_session(self, message: dict[str, Any]) -> None:
        self.project_path = str(message.get("project_path") or self.project_path)
        requested_id = str(message.get("session_id") or "")
        role = ModelRole(message.get("role", "executor"))
        context_key = str(message.get("context_key") or "")
        provider = str(message.get("provider") or "")
        session = agent_engine.get_session(requested_id) if requested_id else None
        if requested_id and session is None:
            from ..agent.session_persistence import restore_session

            session = restore_session(agent_engine._sessions, requested_id, self.project_path)
        from pathlib import Path

        reusable = bool(
            session and session.model_role == role
            and Path(session.project_path).resolve() == Path(self.project_path).resolve()
            and (not context_key or session.context_key == context_key)
        )
        if reusable:
            self.session_id = session.id
            _apply_chat_scope(session, self.project_path)
            if provider:
                session.provider_override = provider
            await self._send(
                "session_selected", session_id=session.id,
                conversation_id=message.get("conversation_id", ""),
                context_key=session.context_key, recovered=True,
            )
            return
        session = self._session(
            system_prompt=self._memory_prompt(COPILOT_SYSTEM_PROMPT, self.project_path),
            role=role, provider=provider, context_key=context_key,
        )
        await self._send(
            "session_created", session_id=session.id,
            conversation_id=message.get("conversation_id", ""),
            context_key=context_key, recovered=False, requested_session_id=requested_id,
        )

    async def _set_provider(self, message: dict[str, Any]) -> None:
        provider = str(message.get("provider") or "")
        session = agent_engine.get_session(self.session_id) if self.session_id else None
        if session:
            session.provider_override = provider or None
        await self._send("provider_set", provider=provider)

    async def _attach_file(self, message: dict[str, Any]) -> None:
        self.project_path = str(message.get("project_path") or self.project_path)
        target = _resolve_chat_artifact_path(self.project_path, str(message.get("path") or ""))
        if not target:
            await self._send("attach_error", error="Chat can attach only managed research artifacts.")
            return
        try:
            content = target.read_text(encoding="utf-8", errors="replace")
            session = agent_engine.get_session(self.session_id) if self.session_id else None
            if session is None:
                session = self._session(
                    system_prompt=COPILOT_SYSTEM_PROMPT, role=ModelRole.EXECUTOR,
                )
            _apply_chat_scope(session, self.project_path)
            if session.messages and session.messages[0].role == "system":
                session.messages[0].content += (
                    f"\n\n## 已附加文件: {target.name}\n路径: {target}\n```\n{content[:8000]}\n```"
                )
            await self._send("file_attached", path=str(target), name=target.name)
        except Exception as exc:
            await self._send("attach_error", error=str(exc))

    async def _resolve_change(self, message: dict[str, Any]) -> None:
        change_id = str(message.get("change_id") or "")
        session_id = str(message.get("session_id") or self.session_id or "")
        try:
            if not session_id:
                raise ValueError("No active chat session for this pending change")
            if agent_engine.get_session(session_id) is None:
                from ..agent.session_persistence import restore_session

                restore_session(agent_engine._sessions, session_id, self.project_path)
            from pathlib import Path

            session = agent_engine.get_session(session_id)
            if session and Path(session.project_path).resolve() != Path(self.project_path).resolve():
                raise PermissionError("Change proposal belongs to another research project")
            approved = bool(message.get("approved", False))
            payload = await agent_engine.resolve_pending_change(session_id, change_id, approved)
            await self._send(
                "change_applied" if payload.get("status") == "applied" else "change_rejected", data=payload,
                conversation_id=message.get("conversation_id", ""),
                request_id=message.get("request_id", ""),
            )
        except Exception as exc:
            await self._send(
                "change_error", data={"id": change_id, "error": str(exc)},
                conversation_id=message.get("conversation_id", ""),
                request_id=message.get("request_id", ""),
            )

    async def _cancel(self, message: dict[str, Any]) -> None:
        session_id = str(message.get("session_id") or self.session_id or "")
        if session_id:
            await agent_engine.cancel(session_id)

    async def _smart_edit(self, message: dict[str, Any]) -> None:
        self.project_path = str(message.get("project_path") or self.project_path)
        target = _resolve_chat_artifact_path(
            self.project_path, str(message.get("file_path") or ""),
        )
        if not target:
            await self._send("edit_error", data="Chat can edit only managed research artifacts.")
            return
        session = agent_engine.get_session(self.session_id) if self.session_id else None
        if session is None:
            session = self._session(
                system_prompt="你是科研产物编辑助手。精确修改用户指定的论文、实验代码、图表或演示稿。",
                role=ModelRole.EXECUTOR,
            )
        _apply_chat_scope(session, self.project_path)

        async def send_edit_event(event: AgentEvent) -> None:
            await self._send(f"edit_{event.type}", data=event.data)

        await agent_engine.smart_edit(
            session_id=session.id, file_path=str(target),
            instruction=str(message.get("instruction") or ""),
            on_event=send_edit_event,
        )

    async def _ping(self, _message: dict[str, Any]) -> None:
        await self._send("pong")

    async def _cancel_connection_tasks(self) -> None:
        pending = [task for task in self.tasks if not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
