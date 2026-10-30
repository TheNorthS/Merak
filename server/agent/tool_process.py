"""Own local tool process trees, bounded output, and cancellation cleanup."""
from __future__ import annotations

import asyncio
import os
import signal
import subprocess
from typing import Any


def shell_process_options() -> dict[str, Any]:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
    return {"start_new_session": True}


async def read_process_tail(process: Any, limit: int = 64_000) -> bytes:
    tail = b""
    while True:
        chunk = await process.stdout.read(16_384)
        if not chunk:
            break
        tail = (tail + chunk)[-limit:]
    await process.wait()
    return tail


async def stop_process_tree(process: Any) -> None:
    """Stop the owned tree before returning cancellation or timeout to the loop."""
    from .tool_deadline import ToolCancellationUnconfirmed
    try:
        await _stop_process_tree(process)
    except (OSError, TimeoutError) as error:
        raise ToolCancellationUnconfirmed("TOOL_CLEANUP_UNCONFIRMED: process-tree cleanup failed") from error


async def _stop_process_tree(process: Any) -> None:
    cleanup_failed = False
    if process.returncode is None:
        if os.name == "nt":
            killer = await asyncio.create_subprocess_exec(
                "taskkill", "/PID", str(process.pid), "/T", "/F",
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            try:
                await asyncio.wait_for(killer.wait(), 10)
            except TimeoutError:
                killer.kill()
                await asyncio.wait_for(killer.wait(), 5)
                cleanup_failed = True
            cleanup_failed |= killer.returncode != 0
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass  # The owned group exited between cancellation and the signal.
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
    try:
        await asyncio.wait_for(process.wait(), 5)
    except TimeoutError as error:
        from .tool_deadline import ToolCancellationUnconfirmed
        raise ToolCancellationUnconfirmed("TOOL_CLEANUP_UNCONFIRMED: local process did not exit") from error
    if cleanup_failed:
        from .tool_deadline import ToolCancellationUnconfirmed
        raise ToolCancellationUnconfirmed("TOOL_CLEANUP_UNCONFIRMED: taskkill did not confirm tree termination")
