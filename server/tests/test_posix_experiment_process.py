"""POSIX cancellation must close inherited pipes and terminate owned descendants."""
import asyncio
import os
from pathlib import Path
import shlex
import signal
import sys

import pytest

from server.services.remote_experiment_runtime import ExperimentRuntime, _create_local_subprocess_shell

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX process-group ownership")


def _running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    stat = Path(f"/proc/{pid}/stat")
    try:
        return not stat.exists() or stat.read_text().rsplit(")", 1)[1].split()[0] != "Z"
    except FileNotFoundError:
        return False


@pytest.mark.asyncio
@pytest.mark.parametrize("parent_waits", [True, False])
async def test_stop_joins_child_even_after_shell_parent_exit(tmp_path, parent_waits):
    script = tmp_path / "parent.py"
    script.write_text("import subprocess, sys, time\n"
                      "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
                      "print(child.pid, flush=True)\n" + ("time.sleep(30)\n" if parent_waits else ""))
    process = await _create_local_subprocess_shell(
        shlex.join([sys.executable, "-u", str(script)]), cwd=str(tmp_path), env=dict(os.environ),
    )
    child = 0
    try:
        child = int(await asyncio.wait_for(process.stdout.readline(), timeout=5))
        assert process._owned_process_group == process.pid != os.getpgrp()
        if not parent_waits:
            for _ in range(100):
                if process.returncode is not None:
                    break
                await asyncio.sleep(0.01)
            assert process.returncode is not None
        await asyncio.wait_for(ExperimentRuntime()._stop_local_process(process, timeout=2), timeout=4)
        for _ in range(100):
            if not _running(child):
                break
            await asyncio.sleep(0.01)
        assert not _running(child)
        assert process.returncode is not None
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await asyncio.wait_for(process.communicate(), timeout=3)
