"""Agent commands cannot wait indefinitely on inherited interactive console input."""

import asyncio
from types import SimpleNamespace
import pytest

from server.agent.tools.remote_tools import terminal_exec


@pytest.mark.asyncio
async def test_terminal_closes_stdin_before_spawning(monkeypatch):
    calls = []
    stream = asyncio.StreamReader()
    stream.feed_data(b"EOF reached")
    stream.feed_eof()

    async def wait():
        return 0

    async def spawn(command, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(stdout=stream, returncode=0, wait=wait)

    monkeypatch.setattr(asyncio, "create_subprocess_shell", spawn)
    result = await terminal_exec("fixture-read-input", timeout=1)
    assert calls[0]["stdin"] == asyncio.subprocess.DEVNULL
    assert "EOF reached" in result and "[exit code: 0]" in result
