"""Repository bootstrap operations for Overleaf synchronization."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Protocol

from .overleaf_models import OverleafProject


class RepositoryConfigPort(Protocol):
    async def _must_git(
        self, cwd: str | Path, *args: str, project: OverleafProject | None = None,
    ) -> str: ...

    async def _run_git(
        self, cwd: str | Path, *args: str, timeout: int = 60,
        project: OverleafProject | None = None,
    ) -> tuple[str, str, int]: ...

    def _remote_url(self, project: OverleafProject) -> str: ...


async def configure_repository(
    service: RepositoryConfigPort,
    project: OverleafProject,
    local_excludes: tuple[str, ...],
) -> None:
    local = Path(project.repo_path)
    local.mkdir(parents=True, exist_ok=True)
    if not (local / ".git").exists():
        await service._must_git(local, "init")
    _stdout, _stderr, remote_code = await service._run_git(
        local, "remote", "get-url", "overleaf"
    )
    verb = "set-url" if remote_code == 0 else "add"
    await service._must_git(
        local, "remote", verb, "overleaf", service._remote_url(project)
    )
    await service._must_git(local, "config", "user.name", "Merak")
    await service._must_git(
        local, "config", "user.email", project.email or "merak@localhost"
    )
    exclude = local / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    existing = exclude.read_text(encoding="utf-8", errors="replace") if exclude.exists() else ""
    missing = [item for item in local_excludes if item not in existing.splitlines()]
    if not missing:
        return
    with exclude.open("a", encoding="utf-8", newline="\n") as handle:
        if existing and not existing.endswith("\n"):
            handle.write("\n")
        handle.write("\n".join(missing) + "\n")


def branch_from_ls_remote(output: str, fallback: str = "master") -> str:
    for line in output.splitlines():
        match = re.match(r"ref:\s+refs/heads/([^\s]+)\s+HEAD$", line.strip())
        if match:
            return match.group(1)
    return fallback or "master"
