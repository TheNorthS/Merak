"""Real temporary child trees are contained and joined on Windows cancellation."""

import asyncio
import ctypes
import os
from pathlib import Path
import subprocess
import sys

import pytest

from server.services.remote_experiment_runtime import _create_local_subprocess_shell, ExperimentRuntime


def _alive(pid: int) -> bool:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x00100000, False, pid)
    if not handle:
        return False
    try:
        return kernel.WaitForSingleObject(handle, 0) == 258
    finally:
        kernel.CloseHandle(handle)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process containment")
@pytest.mark.asyncio
@pytest.mark.parametrize("parent_waits", [True, False])
async def test_owned_tree_cleans_child_even_when_shell_parent_has_exited(tmp_path: Path, parent_waits):
    script = tmp_path / "parent.py"
    script.write_text("import subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "print(child.pid, flush=True)\n" + ("time.sleep(60)\n" if parent_waits else ""))
    process = await _create_local_subprocess_shell(subprocess.list2cmdline([sys.executable, "-u", str(script)]),
        cwd=str(tmp_path), env=dict(os.environ))
    child = 0
    try:
        child = int(await asyncio.wait_for(process.stdout.readline(), timeout=10))
        assert _alive(child)
        if parent_waits:
            await asyncio.wait_for(ExperimentRuntime()._stop_local_process(process, timeout=5), timeout=8)
        else:
            await asyncio.wait_for(process.communicate(), timeout=8)
        assert process.returncode is not None
        assert not _alive(child)
        assert process._owned_job.job.handle is None
    finally:
        await asyncio.to_thread(process._owned_job.stop)
        await asyncio.wait_for(process.wait(), timeout=5)
