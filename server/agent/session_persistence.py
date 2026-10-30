"""Durable transcript persistence and bounded session restoration."""

from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

import structlog

from ..utils.atomic_write import atomic_write_json
from . import Message, ModelRole
from .session_models import AgentSession, AgentStatus, PendingChange

logger = structlog.get_logger()


def persist_session_transcript(session: AgentSession) -> Optional[Path]:
    """Persist the complete transcript outside the compacted model view."""
    try:
        root = Path(session.project_path or ".").expanduser().resolve()
        target = root / ".merak" / "agent-sessions" / f"{session.id}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(target, _session_payload(session), default=str)
        return target
    except OSError as exc:
        logger.warning(
            "Agent transcript persistence failed",
            session_id=session.id,
            error=str(exc),
        )
        return None


def _session_payload(session: AgentSession) -> dict[str, Any]:
    return {
        "schema": 2, "session_id": session.id, "status": session.status.value,
        "model_role": session.model_role.value,
        "provider_override": session.provider_override,
        "created_at": session.created_at, "context_key": session.context_key,
        "workflow_node_id": session.workflow_node_id,
        "iterations": session.iterations, "total_tokens": session.total_tokens,
        "usage_status": "partial_or_unknown" if session.usage_unknown_responses else "reported",
        "usage_unknown_responses": session.usage_unknown_responses,
        "max_iterations": session.max_iterations,
        "tool_call_limits": dict(session.tool_call_limits),
        "tool_call_counts": dict(session.tool_call_counts),
        "tool_failure_counts": dict(session.tool_failure_counts),
        "tool_receipts": session.tool_receipts[-200:],
        "tool_policy": session.tool_policy,
        "pending_changes": {key: asdict(value) for key, value in session.pending_changes.items()},
        "readonly_roots": list(session.readonly_roots),
        "allowed_write_paths": session.allowed_write_paths,
        "context_token_limit": session.context_token_limit,
        "context_compactions": session.context_compactions,
        "last_compaction_fingerprint": session.last_compaction_fingerprint,
        "last_repair_fingerprint": session.last_repair_fingerprint,
        "recovery_count": session.recovery_count,
        "last_stop_reason": session.last_stop_reason,
        "updated_at": time.time(),
        "messages": [
            {
                "role": message.role, "content": message.content or "",
                "tool_calls": [dict(item) for item in message.tool_calls],
                "tool_call_id": message.tool_call_id, "name": message.name,
            }
            for message in session.messages
        ],
    }


def restore_session(
    sessions: dict[str, AgentSession],
    session_id: str,
    project_path: str,
    *,
    system_prompt: str = "",
) -> Optional[AgentSession]:
    existing = sessions.get(session_id)
    if existing is not None:
        return existing
    root = Path(project_path or ".").expanduser().resolve()
    payload = _read_transcript(
        root / ".merak" / "agent-sessions" / f"{session_id}.json", session_id
    )
    if payload is None:
        return None
    messages = _restore_messages(payload["messages"])
    if not messages:
        return None
    if system_prompt:
        messages = [message for message in messages if message.role != "system"]
        messages.insert(0, Message(role="system", content=system_prompt))
    session = _restore_session_fields(session_id, root, payload, messages)
    sessions[session.id] = session
    persist_session_transcript(session)
    return session


def _read_transcript(path: Path, session_id: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if (
        not isinstance(payload, dict)
        or str(payload.get("session_id") or "") != session_id
        or not isinstance(payload.get("messages"), list)
    ):
        return None
    return payload


def _restore_messages(raw_messages: list[Any]) -> list[Message]:
    restored = []
    for raw in raw_messages:
        if not isinstance(raw, dict):
            continue
        role = str(raw.get("role") or "")
        if role not in {"system", "user", "assistant", "tool"}:
            continue
        raw_calls = raw.get("tool_calls")
        calls = [dict(item) for item in raw_calls if isinstance(item, dict)] \
            if isinstance(raw_calls, list) else []
        restored.append(Message(
            role=role, content=str(raw.get("content") or ""), tool_calls=calls,
            tool_call_id=str(raw["tool_call_id"])
            if raw.get("tool_call_id") is not None else None,
            name=str(raw["name"]) if raw.get("name") is not None else None,
        ))
    return restored


def _restore_session_fields(
    session_id: str,
    root: Path,
    payload: dict[str, Any],
    messages: list[Message],
) -> AgentSession:
    from .write_scope import normalize_allowed_write_paths

    allowed_write_paths = normalize_allowed_write_paths(root, payload.get("allowed_write_paths"))
    try:
        model_role = ModelRole(str(payload.get("model_role") or ModelRole.EXECUTOR.value))
    except ValueError:
        model_role = ModelRole.EXECUTOR
    try:
        created_at = float(payload.get("created_at") or time.time())
    except (TypeError, ValueError):
        created_at = time.time()
    return AgentSession(
        id=session_id, messages=messages, status=AgentStatus.IDLE,
        model_role=model_role,
        provider_override=str(payload["provider_override"])
        if payload.get("provider_override") else None,
        created_at=created_at,
        total_tokens=_bounded_int(payload, "total_tokens", 0, 0, 2_000_000_000),
        usage_unknown_responses=_bounded_int(payload, "usage_unknown_responses", 0, 0, 2_000_000_000),
        iterations=0,
        max_iterations=_bounded_int(payload, "max_iterations", 100, 1, 1000),
        tool_call_limits=_bounded_counts(payload, "tool_call_limits"),
        tool_call_counts=_bounded_counts(payload, "tool_call_counts"),
        tool_failure_counts=_bounded_counts(payload, "tool_failure_counts"),
        tool_receipts=[item for item in payload.get("tool_receipts", []) if isinstance(item, dict)][-200:],
        tool_policy=str(payload["tool_policy"]) if payload.get("tool_policy") else None,
        project_path=str(root),
        pending_changes=_restore_pending_changes(payload, session_id, root),
        readonly_roots=[str(item) for item in list(payload.get("readonly_roots") or [])
                        if str(item).strip()],
        allowed_write_paths=allowed_write_paths,
        context_key=str(payload.get("context_key") or ""),
        workflow_node_id=str(payload.get("workflow_node_id") or ""),
        context_token_limit=_bounded_int(payload, "context_token_limit", 0, 0, 10_000_000),
        context_compactions=_bounded_int(payload, "context_compactions", 0, 0, 100_000),
        last_compaction_fingerprint=str(payload.get("last_compaction_fingerprint") or ""),
        last_repair_fingerprint=str(payload.get("last_repair_fingerprint") or ""),
        recovery_count=_bounded_int(payload, "recovery_count", 0, 0, 100_000) + 1,
        last_stop_reason=str(payload.get("last_stop_reason") or ""),
    )


def _restore_pending_changes(payload: dict, session_id: str, root: Path) -> dict[str, PendingChange]:
    """Restore durable proposals without granting access outside this project."""
    import re

    result = {}
    raw = payload.get("pending_changes", {})
    if not isinstance(raw, dict):
        raise ValueError("Invalid persisted change proposals")
    for key, value in raw.items():
        if (not isinstance(value, dict) or not re.fullmatch(r"[a-f0-9]{12}", key)
                or value.get("id") != key or value.get("session_id") != session_id):
            raise ValueError("Invalid persisted change identity")
        target = Path(str(value.get("path") or "")).resolve()
        if not target.is_relative_to(root):
            raise ValueError("Persisted change target is outside the research project")
        result[key] = PendingChange(**value)
    return result


def _bounded_int(
    payload: dict[str, Any], key: str, default: int, minimum: int, maximum: int
) -> int:
    try:
        value = int(payload.get(key, default))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _bounded_counts(payload: dict[str, Any], key: str) -> dict[str, int]:
    raw = payload.get(key)
    if not isinstance(raw, dict):
        return {}
    counts = {}
    for raw_key, raw_value in raw.items():
        clean_key = str(raw_key).strip()
        if not clean_key:
            continue
        try:
            counts[clean_key] = max(0, int(raw_value))
        except (TypeError, ValueError):
            continue
    return counts
