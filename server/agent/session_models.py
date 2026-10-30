"""Durable in-memory contracts for agent sessions and UI events."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from . import Message, ModelRole


class AgentStatus(str, Enum):
    IDLE = "idle"
    THINKING = "thinking"
    TOOL_CALLING = "tool_calling"
    WAITING_USER = "waiting_user"
    COMPLETED = "completed"
    ERROR = "error"
    CANCELLED = "cancelled"


@dataclass
class ToolResult:
    """Result returned by one registered agent tool."""

    tool_call_id: str
    success: bool
    output: str
    error: Optional[str] = None
    error_code: str = ""
    phase: str = ""
    retryable: bool = False
    duration_ms: int = 0
    argument_fingerprint: str = ""
    http_status: int | None = None
    request_id: str = ""
    retry_after: float | None = None


@dataclass
class PendingChange:
    """Human-reviewed file change proposed by Chat."""

    id: str
    session_id: str
    action: str
    path: str
    before: str
    after: str
    diff: str
    status: str = "pending"
    impact: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentEvent:
    """Event streamed from the agent engine to the frontend."""

    type: str
    data: Any = None
    timestamp: float = field(default_factory=time.time)


@dataclass
class AgentSession:
    """Mutable state for one isolated model conversation."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    messages: list[Message] = field(default_factory=list)
    status: AgentStatus = AgentStatus.IDLE
    model_role: ModelRole = ModelRole.EXECUTOR
    provider_override: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    total_tokens: int = 0
    usage_unknown_responses: int = 0
    iterations: int = 0
    max_iterations: int = 100
    tool_call_limits: dict[str, int] = field(default_factory=dict)
    tool_call_counts: dict[str, int] = field(default_factory=dict)
    tool_failure_counts: dict[str, int] = field(default_factory=dict)
    tool_receipts: list[dict[str, Any]] = field(default_factory=list)
    tool_policy: Optional[str] = None
    project_path: str = "."
    readonly_roots: list[str] = field(default_factory=list)
    # None preserves ordinary sessions; an empty exact scope is read-only.
    allowed_write_paths: list[str] | None = None
    context_key: str = ""
    workflow_node_id: str = ""
    pending_changes: dict[str, PendingChange] = field(default_factory=dict)
    context_token_limit: int = 0
    context_compactions: int = 0
    last_compaction_fingerprint: str = ""
    last_repair_fingerprint: str = ""
    recovery_count: int = 0
    last_stop_reason: str = ""
