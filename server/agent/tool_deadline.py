"""Cooperative async deadlines with a separate bounded cancellation grace.

An unconfirmed cancellation is fatal: retrying could duplicate an in-flight write.
Python tasks cannot be forcibly killed; process isolation remains required for
untrusted synchronous code and handlers which suppress cancellation.
"""
from __future__ import annotations

import asyncio
from contextvars import ContextVar
from collections.abc import Awaitable
from typing import Any


TOOL_WALL_TIMEOUT = 600.0
TOOL_CANCEL_GRACE = 5.0
execution_session: ContextVar[str] = ContextVar("execution_session", default="")
_unconfirmed: dict[str, set[asyncio.Task]] = {}


def assert_session_quiescent(session_id: str) -> None:
    tasks = {task for task in _unconfirmed.get(session_id, set()) if not task.done()}
    if tasks:
        raise ValueError("Previous session still has an uncancelled operation; wait for cleanup before manual resume")
    _unconfirmed.pop(session_id, None)


class ToolCancellationUnconfirmed(RuntimeError):
    """The caller must stop rather than retry a possibly active operation."""


def _retrieve_failure(task: asyncio.Task) -> None:
    if not task.cancelled():
        task.exception()


async def cancel_tool_task(task: asyncio.Task, grace: float) -> None:
    task.cancel()
    done, _ = await asyncio.wait({task}, timeout=grace)
    if not done:
        owner = execution_session.get()
        if owner:
            _unconfirmed.setdefault(owner, set()).add(task)
            task.add_done_callback(lambda completed: _unconfirmed.get(owner, set()).discard(completed))
        task.add_done_callback(_retrieve_failure)
        raise ToolCancellationUnconfirmed("TOOL_CLEANUP_UNCONFIRMED: handler ignored cancellation; automatic retry prohibited")
    _retrieve_failure(task)


async def run_with_deadline(operation: Awaitable[Any]) -> Any:
    task = asyncio.create_task(operation)
    try:
        done, _ = await asyncio.wait({task}, timeout=TOOL_WALL_TIMEOUT)
    except asyncio.CancelledError:
        await cancel_tool_task(task, TOOL_CANCEL_GRACE)
        raise
    if done:
        return task.result()
    await cancel_tool_task(task, TOOL_CANCEL_GRACE)
    raise TimeoutError(f"TOOL_TIMEOUT: handler exceeded {TOOL_WALL_TIMEOUT:g}s; inspect effects before retrying")
