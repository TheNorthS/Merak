"""Run a local compiler with bounded, non-interactive, owned-tree cleanup."""

from __future__ import annotations

import os
import subprocess
import tempfile
import time

from .windows_compile_job import WindowsCompileJob


def _stop_owned_compile(process: subprocess.Popen, job: WindowsCompileJob) -> None:
    """Share one cleanup budget across the owned job and suspended parent."""
    deadline = time.monotonic() + 5
    if process.poll() is None:
        process.kill()
    job.terminate(timeout=max(0, deadline - time.monotonic()))
    process.wait(timeout=max(0, deadline - time.monotonic()))


def run_local_compile_process(
    command: list[str], *, cwd: str | None, timeout: int,
    stderr: int = subprocess.STDOUT,
) -> subprocess.CompletedProcess[bytes]:
    """Preserve output on failure; never accept a PDF from an unfinished process."""
    if os.name != "nt":
        return subprocess.run(
            command, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=stderr, timeout=timeout, check=False,
        )
    # Capture output in the caller-owned artifact directory, not global TEMP.
    with tempfile.TemporaryFile(dir=cwd) as output, WindowsCompileJob() as job:
        process = subprocess.Popen(
            command, cwd=cwd, stdin=subprocess.DEVNULL, stdout=output,
            stderr=stderr, creationflags=subprocess.CREATE_NO_WINDOW | 0x00000004,
        )
        try:
            job.attach_and_resume(process)
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            _stop_owned_compile(process, job)
            output.seek(0)
            raise subprocess.TimeoutExpired(command, timeout, output=output.read()) from exc
        except BaseException:
            _stop_owned_compile(process, job)
            raise
        else:
            _stop_owned_compile(process, job)
        finally:
            job.close()
        output.seek(0)
        return subprocess.CompletedProcess(command, process.returncode, stdout=output.read())
