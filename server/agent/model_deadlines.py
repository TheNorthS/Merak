"""One monotonic budget across request retries, with bounded cancellation."""
from __future__ import annotations

import asyncio
import inspect
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Awaitable

from .tool_deadline import cancel_tool_task


class ModelResponseInterrupted(TimeoutError):
    """Partial model output is preserved but cannot be treated as completion."""


@dataclass
class ModelRequestBudget:
    total_seconds: float = 300.0
    max_attempts: int = 2
    started: float = field(default_factory=time.monotonic)
    attempts: int = 0

    def remaining(self) -> float:
        return max(0.0, self.total_seconds - (time.monotonic() - self.started))

    def begin_attempt(self) -> None:
        if self.attempts >= self.max_attempts or self.remaining() <= 0:
            raise TimeoutError("MODEL_BUDGET_EXHAUSTED: model request/retry budget exhausted; resume manually")
        self.attempts += 1

    def allow_rejected_request_retry(self, error: Exception) -> None:
        """Known gateway rejection permits four attempts inside the original deadline."""
        from .remote_errors import RemoteCallError
        if isinstance(error, RemoteCallError) and error.status in {502, 503, 504}:
            self.max_attempts = max(self.max_attempts, 4)

    def status(self) -> dict[str, Any]:
        return {"attempt": self.attempts, "max_attempts": self.max_attempts,
                "total_elapsed_seconds": round(time.monotonic() - self.started, 1),
                "remaining_seconds": round(self.remaining(), 1), "total_budget_seconds": self.total_seconds}


active_model_budget: ContextVar[ModelRequestBudget | None] = ContextVar("model_budget", default=None)
active_attempt_deadline: ContextVar[float | None] = ContextVar("model_attempt_deadline", default=None)


async def bounded_model_attempt(operation: Awaitable[Any], timeout: float) -> Any:
    budget = active_model_budget.get()
    remaining = min(timeout, budget.remaining()) if budget else timeout
    if remaining <= 0:
        if inspect.iscoroutine(operation):
            operation.close()
        raise TimeoutError("MODEL_BUDGET_EXHAUSTED: no time remains for another request")
    deadline_token = active_attempt_deadline.set(time.monotonic() + remaining)
    task = asyncio.create_task(operation)
    try:
        try:
            done, _ = await asyncio.wait({task}, timeout=max(0, remaining))
        except asyncio.CancelledError:
            await cancel_tool_task(task, 5.0)
            raise
        if done:
            return task.result()
        await cancel_tool_task(task, 5.0)
        raise TimeoutError(f"MODEL_REQUEST_DEADLINE: request exceeded remaining {remaining:.1f}s; partial artifacts preserved")
    finally:
        active_attempt_deadline.reset(deadline_token)
