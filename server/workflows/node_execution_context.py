"""Explicit state for one model-owned workflow node execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from .models import WorkflowNode, WorkflowRun


@dataclass
class NodeExecutionContext:
    host: Any
    node: WorkflowNode
    run: WorkflowRun
    direction: str
    effort: str
    assurance: str
    wandb: bool
    compact: bool
    gpu_target: str
    ssh_server_id: str
    revision_context: str
    all_tool_names: Any = None
    base_repo: Any = None
    blocked_execution_tools: Any = None
    blueprint_path: Any = None
    completion_mode: str = "normal"
    disabled_tools: Any = None
    enabled_tools: Any = None
    explicit_inputs: Any = None
    flush_agent_text: Callable[[bool], Awaitable[None]] | None = None
    gpu_info: Any = None
    implementation_entrypoint: Any = None
    implementation_family: Any = None
    max_retries: Any = None
    memory_context: Any = None
    observer: Any = None
    opts: dict[str, Any] | None = None
    owner_skill_prompt: Any = None
    project_path: str = ""
    recovery_session_id: Any = None
    ref_paper: Any = None
    research_mode: Any = None
    research_strategy: Any = None
    result: str = ""
    run_experiment: bool = False
    search_context: Any = None
    search_evidence_path: Any = None
    search_tool_trace: Any = None
    session: Any = None
    session_rehydrated: bool = False
    skill_plan: Any = None
    skill_trace_path: Any = None
    source_tool_contract: Any = None
    system_prompt: str = ""
    user_message: str = ""

    def flush(self, force: bool = False) -> Awaitable[None]:
        if self.flush_agent_text is None:
            raise RuntimeError("node event observer is not initialized")
        return self.flush_agent_text(force)
