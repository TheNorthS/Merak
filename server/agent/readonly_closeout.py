"""Reserve a verdict turn inside the existing budget of read-only workflow delegates."""

from typing import Any

from . import Message
from .session_models import AgentEvent


def reserve_readonly_verdict(state: Any, requested_tools: list[str] | None) -> bool:
    """Disable further reads only on the final turn; never synthesize a review result."""
    session = state.session
    if (session.tool_policy != "workflow_artifacts" or not requested_tools
            or not set(requested_tools) <= {"Read", "Glob", "Grep"}
            or session.max_iterations - session.iterations != 1):
        return False
    state.available_tools = []
    session.messages.append(Message(role="user", content=(
        "Runtime read-only closeout: this is the final model turn in the existing budget. "
        "Tools are now disabled. Use the evidence already returned in this conversation "
        "and submit the requested final response in its exact required format. "
        "Preserve all substantiated findings. Explicitly identify checks left unreviewed; "
        "never infer that unread code is correct or claim unperformed validation. "
        "If required review coverage is incomplete, set review_complete=false, list "
        "unreviewed_files and use category=review_coverage; do not invent a source-code defect."
    )))
    return True


async def warn_remaining_iterations(session: Any, emit: Any) -> None:
    """Give one early budget notice without extending or resetting the hard bound."""
    remaining = session.max_iterations - session.iterations
    if remaining != min(3, session.max_iterations - 1):
        return
    session.messages.append(Message(role="user", content=(
        f"Runtime budget notice: {remaining} model turns remain in this bounded attempt. "
        "Finish only the current scoped deliverables, avoid repeating reads already recorded, "
        "and end with an honest summary of saved files and unresolved blockers. "
        "Do not claim validation or execution that did not happen. The runtime will validate files."
    )))
    await emit(AgentEvent(type="status", data={
        "status": "iteration_budget", "iterations_used": session.iterations,
        "iterations_remaining": remaining, "max_iterations": session.max_iterations,
    }))
