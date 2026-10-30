"""Cross-platform subprocess execution for backend services.

The FastAPI server can run on a Windows selector event loop, where
``asyncio.create_subprocess_exec`` is not implemented. Renderer and compiler
jobs are bounded batch commands, so running ``subprocess.run`` in a worker
thread is both portable and sufficient.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


async def run_process(
    command: Sequence[str | os.PathLike[str]],
    *,
    cwd: str | os.PathLike[str] | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
    stdin: bytes | None = None,
    stdout: Any = subprocess.PIPE,
    stderr: Any = subprocess.PIPE,
) -> subprocess.CompletedProcess[bytes]:
    """Run a non-interactive child process without depending on asyncio pipes."""

    args = [os.fspath(value) for value in command]
    creationflags = 0
    if os.name == "nt":
        creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def invoke() -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            args,
            cwd=os.fspath(Path(cwd)) if cwd is not None else None,
            env=dict(env) if env is not None else None,
            input=stdin,
            stdout=stdout,
            stderr=stderr,
            timeout=timeout,
            check=False,
            shell=False,
            creationflags=creationflags,
        )

    try:
        return await asyncio.to_thread(invoke)
    except subprocess.TimeoutExpired as exc:
        detail = " ".join(args[:3])
        raise TimeoutError(
            f"Process timed out after {timeout} seconds: {detail}"
        ) from exc


__all__ = ["run_process"]
