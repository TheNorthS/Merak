"""Capture genuine continuation failures without manufacturing safety observations.

Only known CLI failures become non-accepting typed diagnostics. Unknown errors
still propagate. A missing guard observation remains unknown, never an empty
successful history; shutdown failures cannot replace the primary cause.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


KNOWN_FAILURES = (RuntimeError, ValueError, OSError, KeyError)


@dataclass
class ContinuationObservation:
    """Facts set at the actual native boundaries, not inferred from later files."""

    blocked_operations: list[str] = field(default_factory=list)
    guards_entered: bool = False
    native_resume_entered: bool = False
    execute_entered: bool = False
    worker_entered: bool = False
    safety_violation: bool = False
    failure_boundary: str = ""

    def snapshot(self) -> dict[str, Any]:
        return {"schema": 1, "guards_entered": self.guards_entered,
                "native_resume_entered": self.native_resume_entered,
                "execute_entered": self.execute_entered, "worker_entered": self.worker_entered,
                "safety_violation": self.safety_violation,
                "failure_boundary": self.failure_boundary,
                "blocked_operations": list(self.blocked_operations) if self.guards_entered else None,
                "blocked_operations_observability": "complete" if self.guards_entered else "unknown",
                "workflow_acceptance_granted": False}


class BenchmarkContinuationFailure(RuntimeError):
    """A real known failure carrying its captured guard evidence and exact context."""

    def __init__(self, primary: BaseException, observation: ContinuationObservation,
                 secondary: BaseException | None = None) -> None:
        super().__init__(f"{type(primary).__name__}: {primary}")
        from scripts.live_snapshot_safety import SnapshotSafetyError

        observation.safety_violation = bool(isinstance(primary, (PermissionError, SnapshotSafetyError))
            or str(primary) == "Live verification prohibits training, experiments and new simulation data"
            or observation.blocked_operations)
        self.primary = primary
        self.observation = observation.snapshot()
        self.secondary = f"{type(secondary).__name__}: {secondary}" if secondary is not None else ""
        self.context: dict[str, Any] = {}


async def observe_continuation(operation: Callable[[], Awaitable[dict]],
                               shutdown: Callable[[], Awaitable[None]],
                               observation: ContinuationObservation) -> dict:
    """Join native cleanup, retain the first known error, and never fake a result."""
    primary = secondary = None
    try:
        try:
            result = await operation()
        except KNOWN_FAILURES as error:
            primary = error
            observation.failure_boundary = ("worker" if observation.worker_entered else
                "execute" if observation.execute_entered else
                "native_resume_prevalidation" if observation.native_resume_entered else "guarded_operation")
    finally:
        try:
            await shutdown()
        except KNOWN_FAILURES as error:
            if primary is None:
                primary = error
                observation.failure_boundary = "shutdown"
            else:
                secondary = error
    if primary is not None:
        raise BenchmarkContinuationFailure(primary, observation, secondary) from primary
    return result


def failure_observation(error: BaseException) -> dict[str, Any]:
    """Uncaptured setup errors explicitly retain unknown operation observability."""
    if not isinstance(error, BenchmarkContinuationFailure):
        return {"blocked_operations": None, "blocked_operations_observability": "unknown"}
    return {**error.context, "blocked_operations": error.observation["blocked_operations"],
            "blocked_operations_observability": error.observation["blocked_operations_observability"],
            "failure_observation": error.observation,
            "shutdown_error": error.secondary}
