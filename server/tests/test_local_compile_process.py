"""Owned local compiler jobs stop only their own tree and preserve diagnostics."""

from __future__ import annotations

import asyncio
import ctypes
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from server.services.local_compile_process import run_local_compile_process
from server.services.paper_compiler import PaperCompiler
from server.services.windows_compile_job import WindowsCompileJob


def _command(script: str) -> list[str]:
    return [sys.executable, "-B", "-c", script]


def test_owned_command_returns_real_exit_code_and_output(tmp_path: Path) -> None:
    result = run_local_compile_process(
        _command("print('compiler fixture output', flush=True); raise SystemExit(7)"),
        cwd=str(tmp_path), timeout=10,
    )
    assert result.returncode == 7
    assert b"compiler fixture output" in result.stdout


def test_owned_tree_cleanup_shares_one_five_second_budget(monkeypatch) -> None:
    from server.services import local_compile_process

    events = []

    class Process:
        def poll(self):
            return None

        def kill(self):
            events.append(("kill",))

        def wait(self, timeout):
            events.append(("wait", timeout))

    class Job:
        def terminate(self, timeout):
            events.append(("terminate", timeout))

    ticks = iter((0, 1, 3))
    monkeypatch.setattr(local_compile_process.time, "monotonic", lambda: next(ticks))
    local_compile_process._stop_owned_compile(Process(), Job())
    assert events == [("kill",), ("terminate", 4), ("wait", 2)]


def _windows_process_running(process_id: int) -> bool:
    from ctypes import wintypes

    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    api.OpenProcess.restype = wintypes.HANDLE
    api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    api.WaitForSingleObject.restype = wintypes.DWORD
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = api.OpenProcess(0x00100000, False, process_id)
    if not handle:
        if ctypes.get_last_error() == 87:
            return False
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return api.WaitForSingleObject(handle, 0) == 258
    finally:
        api.CloseHandle(handle)


@pytest.mark.skipif(os.name != "nt", reason="Windows installer process-tree boundary")
def test_timeout_stops_owned_child_not_unrelated_process(tmp_path: Path) -> None:
    child = _command("import time; time.sleep(30)")
    script = (
        "import subprocess,json,time; "
        f"child=subprocess.Popen({child!r}); "
        "print(json.dumps({'child_pid':child.pid}),flush=True); time.sleep(30)"
    )
    unrelated = subprocess.Popen(
        child, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        started = time.monotonic()
        with pytest.raises(subprocess.TimeoutExpired) as failure:
            run_local_compile_process(_command(script), cwd=str(tmp_path), timeout=4)
        assert time.monotonic() - started < 12
        child_id = json.loads(failure.value.output.decode().strip())["child_pid"]
        assert not _windows_process_running(child_id)
        assert unrelated.poll() is None
    finally:
        unrelated.terminate()
        unrelated.wait(timeout=5)


@pytest.mark.skipif(os.name != "nt", reason="Windows suspended launch contract")
def test_failed_job_assignment_never_runs_child_instructions(tmp_path: Path, monkeypatch) -> None:
    marker = tmp_path / "unexpected-child-execution.txt"

    def fail_assignment(_job, _process):
        raise OSError("fixture refuses owned job assignment")

    monkeypatch.setattr(WindowsCompileJob, "attach_and_resume", fail_assignment)
    script = f"from pathlib import Path; Path({str(marker)!r}).write_text('ran')"
    with pytest.raises(OSError, match="job assignment"):
        run_local_compile_process(_command(script), cwd=str(tmp_path), timeout=10)
    assert not marker.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows job accounting contract")
def test_job_waits_for_zero_active_processes(monkeypatch) -> None:
    from server.services import windows_compile_job

    active_counts = iter((2, 1, 0))
    queries = []
    waits = []

    class AccountingApi:
        def QueryInformationJobObject(self, handle, kind, buffer, size, returned):
            queries.append((handle, kind))
            buffer._obj.active_processes = next(active_counts)
            return True

    job = WindowsCompileJob.__new__(WindowsCompileJob)
    job.handle, job.api = 91, AccountingApi()
    monkeypatch.setattr(windows_compile_job.time, "sleep", waits.append)
    job.wait_until_empty(timeout=1)
    assert queries == [(91, 1)] * 3
    assert len(waits) == 2


@pytest.mark.skipif(os.name != "nt", reason="Windows bounded cleanup contract")
def test_job_wait_has_bounded_failure_instead_of_claiming_cleanup(monkeypatch) -> None:
    from server.services import windows_compile_job

    class AccountingApi:
        def QueryInformationJobObject(self, handle, kind, buffer, size, returned):
            buffer._obj.active_processes = 1
            return True

    job = WindowsCompileJob.__new__(WindowsCompileJob)
    job.handle, job.api = 92, AccountingApi()
    ticks = iter((0, 5))
    monkeypatch.setattr(windows_compile_job.time, "monotonic", lambda: next(ticks))
    with pytest.raises(TimeoutError, match="cleanup grace"):
        job.wait_until_empty(timeout=1)


@pytest.mark.skipif(os.name != "nt", reason="Windows process-signaled cleanup contract")
def test_termination_waits_for_owned_handles_not_only_accounting_zero() -> None:
    events = []

    class AccountingApi:
        def QueryInformationJobObject(self, handle, kind, buffer, size, returned):
            events.append(("query", kind))
            if kind == 3:
                buffer._obj.assigned = buffer._obj.listed = 2
                buffer._obj.process_ids[0], buffer._obj.process_ids[1] = 101, 102
            else:
                buffer._obj.active_processes = 0
            return True

        def OpenProcess(self, access, inherit, process_id):
            assert access == 0x00100000
            return process_id + 1000

        def TerminateJobObject(self, handle, code):
            events.append(("terminate_job", handle))
            return True

        def WaitForSingleObject(self, handle, milliseconds):
            assert 0 <= milliseconds <= 1000
            events.append(("wait", handle))
            return 0

        def CloseHandle(self, handle):
            events.append(("close", handle))
            return True

    job = WindowsCompileJob.__new__(WindowsCompileJob)
    job.handle, job.api = 93, AccountingApi()
    job.terminate(timeout=1)
    assert events == [
        ("query", 3), ("terminate_job", 93), ("wait", 1101), ("wait", 1102),
        ("query", 1), ("close", 1101), ("close", 1102),
    ]


@pytest.mark.skipif(os.name != "nt", reason="Windows nested owned-tree boundary")
def test_timeout_stops_nested_owned_descendants(tmp_path: Path) -> None:
    sleeper = _command("import time; time.sleep(30)")
    child = _command(
        "import subprocess,json,time; "
        f"descendant=subprocess.Popen({sleeper!r}); "
        "print(json.dumps({'descendant_pid':descendant.pid}),flush=True); time.sleep(30)"
    )
    parent = (
        "import subprocess,json,time; "
        f"child=subprocess.Popen({child!r}); "
        "print(json.dumps({'child_pid':child.pid}),flush=True); time.sleep(30)"
    )
    with pytest.raises(subprocess.TimeoutExpired) as failure:
        run_local_compile_process(_command(parent), cwd=str(tmp_path), timeout=4)
    records = [json.loads(line) for line in failure.value.output.decode().splitlines()]
    process_ids = {key: value for record in records for key, value in record.items()}
    assert set(process_ids) == {"child_pid", "descendant_pid"}
    assert all(not _windows_process_running(pid) for pid in process_ids.values())


@pytest.mark.skipif(os.name != "nt", reason="Windows success-path owned-tree cleanup")
def test_completed_parent_cannot_leave_owned_descendant_running(tmp_path: Path) -> None:
    child = _command("import time; time.sleep(30)")
    parent = (
        "import subprocess,json; "
        f"child=subprocess.Popen({child!r}); "
        "print(json.dumps({'child_pid':child.pid}),flush=True)"
    )
    result = run_local_compile_process(_command(parent), cwd=str(tmp_path), timeout=4)
    assert result.returncode == 0
    child_id = json.loads(result.stdout.decode().strip())["child_pid"]
    assert not _windows_process_running(child_id)


@pytest.mark.parametrize("clean", [False, True])
def test_compiler_timeout_preserves_output_and_does_not_accept_existing_pdf(
    tmp_path: Path, monkeypatch, clean: bool,
) -> None:
    from server.services import latex_compile_execution

    (tmp_path / "main.tex").write_text(
        r"\documentclass{article}\begin{document}Fixture\end{document}", encoding="utf-8",
    )
    (tmp_path / "main.pdf").write_bytes(b"existing stale PDF")
    compiler = PaperCompiler()

    async def timeout(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"], output=b"TeX phase before timeout\n")

    monkeypatch.setattr(compiler, "_run_command", timeout)
    monkeypatch.setattr(latex_compile_execution, "_elapsed_ms", lambda _start: 417)
    result = asyncio.run(compiler.compile(str(tmp_path), clean=clean))
    assert result.success is False
    assert result.pdf_path is None
    assert "TeX phase before timeout" in result.log_output
    assert result.compile_time_ms == 417
    assert "timed out" in result.errors[0].message


def test_compiler_returns_failed_result_when_containment_is_unavailable(
    tmp_path: Path, monkeypatch,
) -> None:
    (tmp_path / "main.tex").write_text(
        r"\documentclass{article}\begin{document}Fixture\end{document}", encoding="utf-8",
    )
    compiler = PaperCompiler()

    async def containment_failure(*_args, **_kwargs):
        raise OSError("Owned compiler process cannot join job")

    monkeypatch.setattr(compiler, "_run_command", containment_failure)
    result = asyncio.run(compiler.compile(str(tmp_path)))
    assert result.success is False
    assert "cannot join job" in result.errors[0].message
