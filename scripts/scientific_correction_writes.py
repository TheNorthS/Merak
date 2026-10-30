"""Reject raw-result, original-project and workflow writes before they occur."""

from contextlib import contextmanager
import os
from pathlib import Path
import sys

from scripts.verify_offline_suite import canonical_io_path


_OUTPUTS = (
    "experiments/PROTOCOL_CONFORMANCE.json", "experiments/results/CLAIM_DECISIONS.json",
    "experiments/results/analysis.md", "NARRATIVE_REPORT.md",
)


@contextmanager
def correction_report_write_scope(root: Path):
    root = root.resolve(strict=True)
    outputs = {root / name for name in _OUTPUTS}
    directories = {parent for path in outputs for parent in path.parents if parent.is_relative_to(root)}
    active = True

    def check(value, *, mkdir=False):
        if not isinstance(value, (str, bytes, os.PathLike)):
            raise PermissionError("Correction report writes require an explicit owned output path")
        path = canonical_io_path(value)
        temporary = any(path.parent == output.parent and path.name.startswith(f".{output.name}.")
                        and path.suffix == ".tmp" for output in outputs)
        if not (path in directories if mkdir else path in outputs or temporary):
            raise PermissionError("Correction report producer cannot modify raw data, workflow evidence or foreign files")

    def audit(event, arguments):
        if not active:
            return
        if event in {"subprocess.Popen", "socket.connect", "socket.getaddrinfo", "socket.gethostbyname"}:
            raise PermissionError("Correction reports cannot execute a process or contact a model")
        if event == "open":
            value, mode, flags = arguments
            if (isinstance(mode, str) and any(item in mode for item in "wax+")) or (
                    isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)):
                check(value)
        elif event == "os.mkdir":
            check(arguments[0], mkdir=True)
        elif event in {"os.remove", "os.chmod", "os.utime"}:
            check(arguments[0])
        elif event in {"os.rename", "os.replace"}:
            for value in arguments[:2]:
                check(value)
        elif event in {"os.rmdir", "os.link", "os.symlink"}:
            raise PermissionError("Correction reports cannot delete directories or create links")

    sys.addaudithook(audit)
    try:
        yield
    finally:
        active = False
