"""Resilient atomic writes and cross-process locks for workflow state."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .path_lock_identity import canonical_lock_identity


_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()
_LOCAL = threading.local()

LOCK_TIMEOUT_SECONDS = 15.0
REPLACE_ATTEMPTS = 8
REPLACE_DELAY_SECONDS = 0.02
MAX_DELAY_SECONDS = 0.5


def _key(path: Path) -> str:
    return canonical_lock_identity(path)


def _thread_lock(path: Path) -> threading.RLock:
    key = _key(path)
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.RLock())


def _lock_file_path(path: Path) -> Path:
    namespace = Path(tempfile.gettempdir()) / "merak-ide-path-locks"
    namespace.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(_key(path).encode("utf-8")).hexdigest()
    return namespace / f"{digest}.lock"


def _depths() -> dict[str, int]:
    depths = getattr(_LOCAL, "depths", None)
    if depths is None:
        depths = {}
        _LOCAL.depths = depths
    return depths


def _open_lock_file(lock_path: Path):
    """Open a stable, non-append handle whose byte-zero can be locked.

    ``msvcrt.locking`` locks from the handle's current file position. Opening
    the shared lock file with ``a+b`` leaves first-use initialization subject
    to append-position races, so every process now locks the same initialized
    byte through an ``r+b`` handle.
    """

    try:
        with lock_path.open("xb") as initializer:
            initializer.write(b"\0")
            initializer.flush()
            os.fsync(initializer.fileno())
    except FileExistsError:
        pass

    handle = lock_path.open("r+b", buffering=0)
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        # Recover a lock file left empty if its creating process terminated
        # between exclusive creation and sentinel initialization. Concurrent
        # repairs all write the same byte at the same offset.
        handle.seek(0)
        handle.write(b"\0")
        handle.flush()
        os.fsync(handle.fileno())
    handle.seek(0)
    return handle


def _acquire_windows_mutex(path: Path, timeout_seconds: float):
    """Acquire a process-wide Windows kernel mutex for one canonical path."""

    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [
        wintypes.LPVOID,
        wintypes.BOOL,
        wintypes.LPCWSTR,
    ]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
    kernel32.ReleaseMutex.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    digest = hashlib.sha256(_key(path).encode("utf-8")).hexdigest()
    handle = kernel32.CreateMutexW(None, False, f"Local\\MERAK_IDE_{digest}")
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())

    wait_result = kernel32.WaitForSingleObject(
        handle,
        max(1, min(0xFFFFFFFE, int(timeout_seconds * 1000))),
    )
    if wait_result in {0x00000000, 0x00000080}:  # acquired or abandoned
        return kernel32, handle

    kernel32.CloseHandle(handle)
    if wait_result == 0x00000102:
        raise TimeoutError(f"Timed out waiting for cross-process state lock: {path}")
    raise OSError(f"WaitForSingleObject failed with status 0x{wait_result:08x}")


def _release_windows_mutex(mutex: tuple[Any, Any]) -> None:
    kernel32, handle = mutex
    try:
        kernel32.ReleaseMutex(handle)
    finally:
        kernel32.CloseHandle(handle)


def _try_file_lock(handle: Any) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_file(handle: Any) -> None:
    try:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


@contextmanager
def path_lock(
    path: str | Path,
    *,
    timeout_seconds: float = LOCK_TIMEOUT_SECONDS,
) -> Iterator[None]:
    """Lock one target path across threads/processes; re-entrant per thread."""

    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    key = _key(target)
    local_lock = _thread_lock(target)
    timeout = max(0.1, float(timeout_seconds))
    if not local_lock.acquire(timeout=timeout):
        raise TimeoutError(f"Timed out waiting for state lock: {target}")

    depths = _depths()
    depth = depths.get(key, 0)
    if depth:
        depths[key] = depth + 1
        try:
            yield
        finally:
            remaining = depths.get(key, 1) - 1
            if remaining:
                depths[key] = remaining
            else:
                depths.pop(key, None)
            local_lock.release()
        return

    if os.name == "nt":
        mutex = None
        try:
            mutex = _acquire_windows_mutex(target, timeout)
            depths[key] = 1
            try:
                yield
            finally:
                depths.pop(key, None)
        finally:
            if mutex is not None:
                _release_windows_mutex(mutex)
            local_lock.release()
        return

    # POSIX lock files live outside research projects so artifact
    # hashing/freshness never observes synchronization metadata as scientific
    # content. Windows uses a kernel mutex above because byte-range locking can
    # admit dual winners during first-use contention on some filesystems.
    lock_path = _lock_file_path(target)
    handle = None
    deadline = time.monotonic() + timeout
    delay = REPLACE_DELAY_SECONDS
    try:
        while True:
            try:
                handle = _open_lock_file(lock_path)
                _try_file_lock(handle)
                break
            except OSError as exc:
                if handle is not None:
                    handle.close()
                    handle = None
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"Timed out waiting for cross-process state lock: {target}"
                    ) from exc
                time.sleep(delay)
                delay = min(MAX_DELAY_SECONDS, delay * 2)
        depths[key] = 1
        try:
            yield
        finally:
            depths.pop(key, None)
            if handle is not None:
                _unlock_file(handle)
    finally:
        if handle is not None:
            handle.close()
        local_lock.release()


def _retryable_replace_error(exc: OSError) -> bool:
    return (
        isinstance(exc, PermissionError)
        or getattr(exc, "winerror", None) in {5, 32}
        or getattr(exc, "errno", None) in {errno.EACCES, errno.EBUSY}
    )


def _filesystem_path(path: Path) -> Path:
    """Keep artifact identities canonical while supporting long Windows I/O paths."""
    if os.name != "nt":
        return path
    raw = str(path)
    if raw.startswith("\\\\?\\"):
        return path
    if raw.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + raw[2:])
    return Path("\\\\?\\" + raw)


def atomic_replace_file(
    source: str | Path,
    destination: str | Path,
    *,
    replace_attempts: int = REPLACE_ATTEMPTS,
    replace_delay_seconds: float = REPLACE_DELAY_SECONDS,
) -> None:
    """Commit an already-written temporary file with target locking and retry."""

    source_path = Path(source).expanduser().resolve()
    target = Path(destination).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    attempts = max(1, int(replace_attempts))
    with path_lock(target):
        delay = max(0.0, float(replace_delay_seconds))
        for attempt in range(attempts):
            try:
                os.replace(_filesystem_path(source_path), _filesystem_path(target))
                return
            except OSError as exc:
                if attempt + 1 >= attempts or not _retryable_replace_error(exc):
                    raise
                time.sleep(delay)
                delay = min(MAX_DELAY_SECONDS, max(REPLACE_DELAY_SECONDS, delay * 2))


def atomic_write_bytes(
    path: str | Path,
    payload: bytes,
    *,
    replace_attempts: int = REPLACE_ATTEMPTS,
    replace_delay_seconds: float = REPLACE_DELAY_SECONDS,
) -> None:
    """Write via a unique sibling and retry transient Windows replace errors."""

    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    attempts = max(1, int(replace_attempts))
    with path_lock(target):
        temporary = target.with_name(
            f".{target.name}.{os.getpid()}.{threading.get_ident()}."
            f"{uuid.uuid4().hex}.tmp"
        )
        try:
            with _filesystem_path(temporary).open("xb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            delay = max(0.0, float(replace_delay_seconds))
            for attempt in range(attempts):
                try:
                    os.replace(_filesystem_path(temporary), _filesystem_path(target))
                    return
                except OSError as exc:
                    if (
                        not _retryable_replace_error(exc)
                        or attempt + 1 >= attempts
                    ):
                        raise
                    time.sleep(delay)
                    delay = min(MAX_DELAY_SECONDS, max(0.001, delay * 2))
        finally:
            try:
                _filesystem_path(temporary).unlink(missing_ok=True)
            except OSError:
                pass


def atomic_write_json(
    path: str | Path,
    payload: Any,
    *,
    indent: int | None = 2,
    separators: tuple[str, str] | None = None,
    default: Any = None,
) -> None:
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        indent=indent,
        separators=separators,
        default=default,
    )
    atomic_write_bytes(path, serialized.encode("utf-8"))


def atomic_write_text(
    path: str | Path,
    payload: str,
    *,
    encoding: str = "utf-8",
) -> None:
    atomic_write_bytes(path, str(payload).encode(encoding))
