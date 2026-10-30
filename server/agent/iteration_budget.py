"""Typed exhaustion after joined tool calls, distinct from transport or tool failure."""
from __future__ import annotations


class AgentIterationLimit(RuntimeError):
    """The turn budget ended; only the owning validator may accept saved artifacts."""

    def __init__(self, session_id: str, iterations: int, limit: int):
        self.session_id = session_id
        self.iterations = iterations
        self.limit = limit
        super().__init__(
            "AGENT_ITERATION_LIMIT: tool loop exhausted; artifacts require fresh validation before acceptance"
        )
