"""Stable workflow domain models shared by orchestration and API layers."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional


class NodeStatus(str, Enum):
    IDLE = "idle"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class AgentNodeWatchdogTimeout(asyncio.TimeoutError):
    """Raised when an agent exceeds its idle or wall-time contract."""

    def __init__(
        self,
        *,
        node_id: str,
        kind: str,
        limit_seconds: float,
        elapsed_seconds: float,
        idle_seconds: float,
    ) -> None:
        self.node_id = node_id
        self.kind = kind
        self.limit_seconds = float(limit_seconds)
        self.elapsed_seconds = float(elapsed_seconds)
        self.idle_seconds = float(idle_seconds)
        label = "idle-time" if kind == "idle" else "hard wall-time"
        super().__init__(
            f"Agent node {label} limit reached after "
            f"{self.limit_seconds:.1f}s: {node_id}"
        )


@dataclass
class WorkflowNode:
    """Mutable lifecycle state for one node in a workflow run."""

    id: str
    name: str
    skill: str
    depends_on: list[str] = field(default_factory=list)
    status: NodeStatus = NodeStatus.IDLE
    session_id: Optional[str] = None
    output: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    artifact_baseline: dict[str, dict[str, Any]] = field(default_factory=dict)
    execution_kind: str = "model_owned"
    runtime_service: str = ""
    policy_required: bool = True


@dataclass
class WorkflowRun:
    """Persisted and in-memory state for one workflow execution."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    project_path: str = ""
    nodes: list[WorkflowNode] = field(default_factory=list)
    status: str = "idle"
    created_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    on_event: Optional[Callable[..., Any]] = None
    checkpoint_future: Optional[asyncio.Future] = None
    checkpoint_feedback: str = ""
    checkpoint_node_id: str = ""
    checkpoint_deadline: float = 0.0
    checkpoint_resolution: str = ""
    options: dict[str, Any] = field(default_factory=dict)
    risk_fingerprints: set[str] = field(default_factory=set)
    input_baseline: dict[str, Any] = field(default_factory=dict)
    completion: dict[str, Any] = field(default_factory=dict)
    resume_claim_token: str = ""
    project_claim_token: str = ""
    interruption_reason: str = ""
