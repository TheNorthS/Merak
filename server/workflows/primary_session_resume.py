"""Restore a stopped conversation with current routing and an explicit new attempt."""
from __future__ import annotations

from typing import Any

from ..agent import Message
from ..agent.session_models import AgentStatus


def restore_primary_session(engine: Any, session_id: str, project_path: str, *, system_prompt: str) -> Any:
    from ..agent.tool_deadline import assert_session_quiescent
    assert_session_quiescent(session_id)
    session = engine.get_session(session_id)
    if session and session.status in {AgentStatus.THINKING, AgentStatus.TOOL_CALLING}:
        raise ValueError("Previous agent session is still active; wait for cancellation cleanup before resuming")
    existing = session is not None
    session = session or engine.restore_session(session_id, project_path, system_prompt=system_prompt)
    if session is None:
        return None
    session.messages = [Message(role="system", content=system_prompt),
                        *[message for message in session.messages if message.role != "system"
                          and not (message.role == "user" and str(message.content or "").startswith(
                              ("Runtime budget notice:", "Runtime read-only closeout:")))]]
    session.iterations = 0
    session.status = AgentStatus.IDLE
    session.provider_override = None  # The user's current route is selected again by configuration.
    session.tool_failure_counts.clear()
    if existing:
        session.recovery_count += 1
    engine._persist_session_transcript(session)
    return session
