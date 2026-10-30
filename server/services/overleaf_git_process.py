"""Credential-safe subprocess transport for Overleaf Git operations."""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

from .overleaf_models import OverleafProject


def askpass_helper(directory: Path) -> Path:
    if os.name == "nt":
        helper = directory / "askpass.cmd"
        helper.write_text(
            "@echo off\r\n"
            '"%MERAK_OVERLEAF_PYTHON%" -c "import os,sys; '
            "print(os.environ.get('MERAK_OVERLEAF_USERNAME' if 'username' in sys.argv[1].lower() "
            "else 'MERAK_OVERLEAF_TOKEN', ''))\" \"%~1\"\r\n",
            encoding="ascii",
        )
    else:
        helper = directory / "askpass.sh"
        helper.write_text(
            "#!/bin/sh\n"
            "case \"$1\" in\n"
            "  *[Uu]sername*) printf '%s\\n' \"$MERAK_OVERLEAF_USERNAME\" ;;\n"
            "  *) printf '%s\\n' \"$MERAK_OVERLEAF_TOKEN\" ;;\n"
            "esac\n",
            encoding="ascii",
        )
        helper.chmod(0o700)
    return helper


def git_environment(
    project: OverleafProject | None,
) -> tuple[dict[str, str], tempfile.TemporaryDirectory[str] | None]:
    environment = os.environ.copy()
    environment["GIT_TERMINAL_PROMPT"] = "0"
    if project is None:
        return environment, None
    if not project.token:
        raise ValueError("Overleaf token is unavailable; relink the project")
    temporary = tempfile.TemporaryDirectory(prefix="merak-overleaf-")
    helper = askpass_helper(Path(temporary.name))
    environment.update({
        "GIT_ASKPASS": str(helper), "GIT_ASKPASS_REQUIRE": "force",
        "MERAK_OVERLEAF_USERNAME": "git", "MERAK_OVERLEAF_TOKEN": project.token,
        "MERAK_OVERLEAF_PYTHON": sys.executable,
    })
    return environment, temporary


async def run_git(
    git_path: str | None,
    cwd: str | Path,
    args: tuple[str, ...],
    *,
    timeout: int = 60,
    project: OverleafProject | None = None,
) -> tuple[str, str, int]:
    if not git_path:
        raise RuntimeError("Git is not installed or is not available in PATH")
    try:
        environment, temporary = git_environment(project)
    except ValueError as exc:
        return "", str(exc), 2
    try:
        process = await asyncio.create_subprocess_exec(
            git_path, *args,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd), env=environment,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            process.kill()
            await process.communicate()
            return "", f"Git command timed out after {timeout}s", 124
        return (
            stdout.decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"),
            process.returncode or 0,
        )
    finally:
        if temporary is not None:
            temporary.cleanup()
