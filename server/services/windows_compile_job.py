"""Contain only an owned Windows compiler tree before its first instruction."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import time
from typing import Any


class _BasicLimits(ctypes.Structure):
    _fields_ = [
        ("process_time", ctypes.c_longlong), ("job_time", ctypes.c_longlong),
        ("flags", wintypes.DWORD), ("minimum_working_set", ctypes.c_size_t),
        ("maximum_working_set", ctypes.c_size_t), ("active_processes", wintypes.DWORD),
        ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD),
        ("scheduling", wintypes.DWORD),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in (
        "read_operations", "write_operations", "other_operations",
        "read_bytes", "write_bytes", "other_bytes",
    )]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("basic", _BasicLimits), ("io", _IoCounters),
        ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
        ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t),
    ]


class _BasicAccounting(ctypes.Structure):
    _fields_ = [
        ("total_user_time", ctypes.c_longlong), ("total_kernel_time", ctypes.c_longlong),
        ("period_user_time", ctypes.c_longlong), ("period_kernel_time", ctypes.c_longlong),
        ("page_faults", wintypes.DWORD), ("total_processes", wintypes.DWORD),
        ("active_processes", wintypes.DWORD), ("terminated_processes", wintypes.DWORD),
    ]


class _ThreadEntry(ctypes.Structure):
    _fields_ = [
        ("size", wintypes.DWORD), ("usage", wintypes.DWORD),
        ("thread_id", wintypes.DWORD), ("process_id", wintypes.DWORD),
        ("base_priority", wintypes.LONG), ("delta_priority", wintypes.LONG),
        ("flags", wintypes.DWORD),
    ]


def _kernel() -> Any:
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    declarations = {
        "CreateJobObjectW": ([ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
        "SetInformationJobObject": ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD], wintypes.BOOL),
        "AssignProcessToJobObject": ([wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
        "TerminateJobObject": ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
        "QueryInformationJobObject": ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p], wintypes.BOOL),
        "OpenProcess": ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
        "WaitForSingleObject": ([wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
        "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
        "CreateToolhelp32Snapshot": ([wintypes.DWORD, wintypes.DWORD], wintypes.HANDLE),
        "Thread32First": ([wintypes.HANDLE, ctypes.POINTER(_ThreadEntry)], wintypes.BOOL),
        "Thread32Next": ([wintypes.HANDLE, ctypes.POINTER(_ThreadEntry)], wintypes.BOOL),
        "OpenThread": ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
        "ResumeThread": ([wintypes.HANDLE], wintypes.DWORD),
    }
    for name, (arguments, result) in declarations.items():
        function = getattr(api, name)
        function.argtypes, function.restype = arguments, result
    return api


def _owned_process_handles(api: Any, job: Any, deadline: float) -> list[Any]:
    """Retain synchronization handles only for IDs enumerated by our job."""
    capacity = 16
    while True:
        if time.monotonic() >= deadline:
            raise TimeoutError("Owned compiler job enumeration exceeded cleanup grace")

        class ProcessIds(ctypes.Structure):
            _fields_ = [
                ("assigned", wintypes.DWORD), ("listed", wintypes.DWORD),
                ("process_ids", ctypes.c_size_t * capacity),
            ]

        members = ProcessIds()
        if api.QueryInformationJobObject(job, 3, ctypes.byref(members), ctypes.sizeof(members), None):
            break
        error = ctypes.get_last_error()
        if error != 234:  # ERROR_MORE_DATA: the owned tree outgrew this buffer.
            raise ctypes.WinError(error)
        capacity = max(capacity * 2, members.assigned)
    handles = []
    try:
        for process_id in members.process_ids[:members.listed]:
            handle = api.OpenProcess(0x00100000, False, process_id)
            if handle:
                handles.append(handle)
            elif ctypes.get_last_error() != 87:  # Already-exited process IDs can disappear.
                raise ctypes.WinError(ctypes.get_last_error())
        return handles
    except BaseException:
        for handle in handles:
            api.CloseHandle(handle)
        raise


def _resume_owned_thread(api: Any, process_id: int) -> None:
    snapshot = api.CreateToolhelp32Snapshot(0x00000004, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        entry = _ThreadEntry(size=ctypes.sizeof(_ThreadEntry))
        present = api.Thread32First(snapshot, ctypes.byref(entry))
        while present:
            if entry.process_id == process_id:
                thread = api.OpenThread(0x0002, False, entry.thread_id)
                if not thread:
                    raise ctypes.WinError(ctypes.get_last_error())
                try:
                    if api.ResumeThread(thread) == 0xFFFFFFFF:
                        raise ctypes.WinError(ctypes.get_last_error())
                finally:
                    api.CloseHandle(thread)
                return
            present = api.Thread32Next(snapshot, ctypes.byref(entry))
        raise OSError("Owned suspended compiler thread was not found")
    finally:
        api.CloseHandle(snapshot)


class WindowsCompileJob:
    """Fail closed if containment cannot be established for our suspended child."""

    def __init__(self) -> None:
        self.api = _kernel()
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = _ExtendedLimits()
        limits.basic.flags = 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.api.SetInformationJobObject(
            self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits),
        ):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error

    def attach_and_resume(self, process: Any) -> None:
        """Contain the newly created process before it can launch TeX children."""
        if not self.api.AssignProcessToJobObject(self.handle, int(process._handle)):
            raise ctypes.WinError(ctypes.get_last_error())
        _resume_owned_thread(self.api, process.pid)

    def terminate(self, timeout: float = 5) -> None:
        """Terminate our tree and wait for its process handles to become signaled."""
        if not self.handle:
            return
        deadline = time.monotonic() + timeout
        handles = _owned_process_handles(self.api, self.handle, deadline)
        try:
            if not self.api.TerminateJobObject(self.handle, 1):
                raise ctypes.WinError(ctypes.get_last_error())
            for handle in handles:
                wait_ms = max(0, int((deadline - time.monotonic()) * 1000))
                result = self.api.WaitForSingleObject(handle, wait_ms)
                if result == 258:
                    raise TimeoutError("Owned compiler process did not exit within cleanup grace")
                if result != 0:
                    raise ctypes.WinError(ctypes.get_last_error())
            self.wait_until_empty(timeout=max(0, deadline - time.monotonic()))
        finally:
            for handle in handles:
                self.api.CloseHandle(handle)

    def wait_until_empty(self, timeout: float) -> None:
        """Observe termination of every owned descendant, not just the parent."""
        deadline = time.monotonic() + timeout
        while self.handle:
            accounting = _BasicAccounting()
            if not self.api.QueryInformationJobObject(
                self.handle, 1, ctypes.byref(accounting), ctypes.sizeof(accounting), None,
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            if accounting.active_processes == 0:
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Owned compiler job did not terminate within cleanup grace")
            time.sleep(min(0.01, remaining))

    def close(self) -> None:
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None

    def __enter__(self) -> WindowsCompileJob:
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()
