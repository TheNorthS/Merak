"""Contain local experiment descendants before the Windows command shell starts."""

import subprocess
from threading import Lock
from typing import Any

from .windows_compile_job import WindowsCompileJob


class OwnedExperimentJob:
    """Serialize cancellation and normal-exit cleanup for one OS-owned process tree."""

    def __init__(self, job: WindowsCompileJob) -> None:
        self.job = job
        self.lock = Lock()

    def stop(self) -> None:
        with self.lock:
            if self.job.handle:
                try:
                    self.job.terminate(timeout=5)
                finally:
                    self.job.close()


def create_owned_experiment(command: str, *, cwd: str, env: dict[str, str]) -> tuple[Any, OwnedExperimentJob]:
    """Reject launch if containment fails; no child can escape during attachment."""
    job = WindowsCompileJob()
    process = None
    try:
        process = subprocess.Popen(command, cwd=cwd, env=env, shell=True,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW | 0x00000004)
        job.attach_and_resume(process)
        return process, OwnedExperimentJob(job)
    except BaseException:
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
        job.close()
        raise
