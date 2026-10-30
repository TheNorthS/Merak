"""Typed mutable state for a single workflow execution attempt."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import WorkflowNode, WorkflowRun
from .run_state import RunState
from .session_state import SessionState


class SkipRunNode(BaseException):
    pass


class StopRunNodes(BaseException):
    pass


class RestartRun(BaseException):
    pass


class CompleteRun(BaseException):
    pass


@dataclass
class RunExecutionContext:
    host: Any
    run: WorkflowRun
    research_direction: str
    effort: str
    assurance: str
    opts: dict[str, Any]
    session_state: SessionState | None = None
    run_state: RunState | None = None
    auto_proceed: Any = None
    checkpoint_consumed: Any = None
    checkpoint_timeout: Any = None
    code_review_enabled: Any = None
    completed_nodes: Any = None
    dependencies: Any = None
    dependency_failures: Any = None
    deps_ok: Any = None
    durable_state: Any = None
    failed: Any = None
    gate: Any = None
    human_checkpoint: Any = None
    human_checkpoint_nodes: Any = None
    max_revision_rounds: Any = None
    node: WorkflowNode | None = None
    persisted_phase: Any = None
    persisted_phases: Any = None
    phase_record: Any = None
    raw_checkpoint_nodes: Any = None
    result: Any = None
    resumable_ids: Any = None
    resuming_revision: Any = None
    revalidate_done: Any = None
    upstream_preflight: Any = None
    review_result: Any = None
    assessment: Any = None
    implementation_integrity: Any = None
    report_path: Any = None
    workflow_blocking: Any = None
    wandb_enabled: Any = None
    compact_mode: Any = None
    resume_stage: str = ""


def save_resume_session(
    context: RunExecutionContext, current_node: str
) -> tuple[dict[str, str], dict[str, Any]]:
    if context.run_state is None or context.session_state is None:
        raise RuntimeError("workflow persistence is not initialized")
    durable = context.run_state.load() or {}
    phases = durable.get("phases", {})
    statuses = {
        phase_id: str(phase.get("status", "pending"))
        for phase_id, phase in phases.items()
    }
    if not statuses:
        statuses = {node.id: node.status.value for node in context.run.nodes}
    config = dict(durable.get("config") or {})
    config.update(
        {
            "effort": context.effort,
            "assurance": context.assurance,
            "direction": context.research_direction,
            "options": dict(context.opts),
        }
    )
    context.session_state.save(context.run.id, statuses, current_node, config)
    return statuses, config
