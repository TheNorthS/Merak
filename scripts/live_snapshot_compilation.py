"""Restrict authorized snapshot compilation to local, non-shell LaTeX builds."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
import shutil
import subprocess
from unittest.mock import patch


_AUTHORIZED_SPAWN: ContextVar[tuple[tuple[str, ...], str] | None] = ContextVar("live_snapshot_compile_spawn", default=None)


def guarded_compile_command(root: Path, command: list[str], cwd: str | None) -> tuple[list[str], str]:
    if not isinstance(command, list) or not command or any(not isinstance(item, str) for item in command):
        raise ValueError("Snapshot compilation requires a concrete command argument list")
    name = Path(command[0]).name.casefold().removesuffix(".exe")
    if name not in {"latexmk", "pdfinfo"}:
        raise ValueError("Snapshot compiler cannot run scripts or arbitrary executables")
    if name == "pdfinfo" and cwd is None:
        cwd = str(Path(command[-1]).resolve().parent)
    work = Path(cwd or "").resolve()
    artifact_root = next((root / name for name in ("paper", "slides")
                          if work.is_relative_to(root / name)), None)
    if artifact_root is None:
        raise ValueError("Snapshot compilation must run inside a local artifact directory")
    allowed_flags = {"-norc", "-no-shell-escape", "-C", "-pdf", "-xelatex",
                     "-interaction=nonstopmode", "-halt-on-error", "-file-line-error"}
    artifacts = []
    for argument in command[1:]:
        if "shell-escape" in argument and argument != "-no-shell-escape" or argument in {"-e", "-r"}:
            raise ValueError("Snapshot compilation cannot enable shell escape or custom runtime code")
        if argument in allowed_flags and name == "latexmk":
            continue
        if argument.startswith("-") and not (name == "latexmk" and argument.startswith("-outdir=")):
            raise ValueError("Snapshot compiler cannot use custom runtime flags")
        value = argument.split("=", 1)[-1] if argument.startswith("-outdir=") else argument
        path = (work / value).resolve()
        if not path.is_relative_to(artifact_root):
            raise ValueError("Snapshot compiler argument leaves the authorized project")
        if not argument.startswith("-outdir="):
            artifacts.append(path)
    if len(artifacts) != 1 or artifacts[0].suffix.casefold() != (".tex" if name == "latexmk" else ".pdf"):
        raise ValueError("Snapshot compiler requires exactly one local artifact input")
    if name == "latexmk":
        command = [command[0], "-norc", "-no-shell-escape", *command[1:]]
    return command, str(work)


def _compiler_executable(root: Path, command: list[str]) -> str:
    """Resolve only the configured local compiler, never a project-named executable."""
    name = Path(command[0]).name.casefold().removesuffix(".exe")
    located = shutil.which(name)
    if not located:
        raise FileNotFoundError(f"{name} not found for authorized local artifact compilation")
    executable = Path(located).resolve()
    if executable.is_relative_to(root):
        raise ValueError("Snapshot compiler cannot execute a project-owned same-name binary")
    requested = Path(command[0])
    if requested.name != command[0] and requested.resolve() != executable:
        raise ValueError("Snapshot compiler executable differs from its configured local binary")
    return str(executable)


def validate_spawn_scope(root: Path, executable, arguments, cwd) -> None:
    """Match actual audit argv against the one explicitly authorized compiler call.

Windows emits a command-line string and ``executable=None`` for list-based
Popen. Accept only its exact trusted list2cmdline projection; never parse or
authorize an arbitrary shell string, interpreter or foreign working directory.
"""
    authorized = _AUTHORIZED_SPAWN.get()
    if authorized is None:
        raise PermissionError("Live snapshot subprocess lacks an authorized compiler context")
    trusted, work = authorized
    checked, checked_work = guarded_compile_command(root, list(trusted), work)
    expected = list(trusted)
    if Path(expected[0]).name.casefold().removesuffix(".exe") == "latexmk":
        if expected.count("-norc") != 1 or expected.count("-no-shell-escape") != 1:
            raise PermissionError("Live snapshot compiler lacks no-rc and no-shell boundaries")
        checked = [checked[0], *checked[3:]]
    if checked != expected or checked_work != work or not cwd or Path(cwd).resolve() != Path(work):
        raise PermissionError("Live snapshot compiler audit scope differs from its trusted call")
    if executable is not None and Path(str(executable)).resolve() != Path(expected[0]):
        raise PermissionError("Live snapshot compiler audit executable differs from its trusted binary")
    if (isinstance(arguments, str) and arguments == subprocess.list2cmdline(expected)
            or isinstance(arguments, (list, tuple)) and list(arguments) == expected):
        return
    raise PermissionError("Live snapshot compiler audit arguments differ from its trusted call")


@contextmanager
def restricted_snapshot_compilation(root: Path):
    """Keep the real compiler while removing external rc and shell execution."""
    from server.services.paper_compiler import paper_compiler
    original = paper_compiler._run_command

    async def run(command, *, cwd=None, **options):
        checked, work = guarded_compile_command(root, command, cwd)
        checked[0] = _compiler_executable(root, checked)
        token = _AUTHORIZED_SPAWN.set((tuple(checked), work))
        try:
            return await original(checked, cwd=work, **options)
        finally:
            _AUTHORIZED_SPAWN.reset(token)

    with patch.object(paper_compiler, "_run_command", run):
        yield
