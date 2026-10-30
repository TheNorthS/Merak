"""Conflict-safe pull transaction for an Overleaf repository."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

import structlog

from .overleaf_models import OverleafProject, SyncResult


logger = structlog.get_logger()


class OverleafSyncPort(Protocol):
    _projects: dict[str, OverleafProject]

    async def _run_git(
        self, cwd: str | Path, *args: str, timeout: int = 60,
        project: OverleafProject | None = None,
    ) -> tuple[str, str, int]: ...

    def _persist(self, project: OverleafProject) -> None: ...
    def _apply_export(self, project: OverleafProject) -> None: ...


async def _local_state(
    service: OverleafSyncPort, project: OverleafProject,
) -> tuple[str, int, SyncResult | None]:
    dirty, stderr, code = await service._run_git(project.repo_path, "status", "--porcelain")
    if code != 0:
        return "", code, SyncResult(
            False, "pull", message=stderr.strip() or "Unable to inspect local changes",
        )
    if dirty.strip():
        return "", 1, SyncResult(
            False, "pull",
            message="Local paper changes are uncommitted; run Sync to commit them before pulling",
            branch=project.branch,
        )
    before, _stderr, before_code = await service._run_git(
        project.repo_path, "rev-parse", "HEAD"
    )
    return before.strip(), before_code, None


async def _fetch(
    service: OverleafSyncPort, project: OverleafProject,
) -> SyncResult | None:
    _stdout, stderr, code = await service._run_git(
        project.repo_path, "fetch", "overleaf", project.branch,
        timeout=120, project=project,
    )
    if code == 0:
        return None
    return SyncResult(
        False, "pull", message=f"Fetch failed: {stderr.strip()}",
        branch=project.branch,
    )


async def _initial_checkout(
    service: OverleafSyncPort, project: OverleafProject,
) -> tuple[list[str], SyncResult | None]:
    _stdout, stderr, code = await service._run_git(
        project.repo_path, "checkout", "-B", project.branch,
        f"overleaf/{project.branch}",
    )
    if code != 0:
        return [], SyncResult(
            False, "pull", message=f"Checkout failed: {stderr.strip()}",
            branch=project.branch,
        )
    listed, _stderr, _code = await service._run_git(project.repo_path, "ls-files")
    return [line.strip() for line in listed.splitlines() if line.strip()], None


async def _merge_existing(
    service: OverleafSyncPort, project: OverleafProject, before: str,
) -> tuple[list[str], SyncResult | None]:
    _stdout, stderr, code = await service._run_git(
        project.repo_path, "merge", f"overleaf/{project.branch}",
        "--no-edit", "--allow-unrelated-histories",
    )
    if code != 0:
        return [], await _abort_conflict(service, project, stderr)
    after, _stderr, _code = await service._run_git(project.repo_path, "rev-parse", "HEAD")
    if before == after.strip():
        return [], None
    changed, _stderr, _code = await service._run_git(
        project.repo_path, "diff", "--name-only", f"{before}..{after.strip()}",
    )
    return [line.strip() for line in changed.splitlines() if line.strip()], None


async def _abort_conflict(
    service: OverleafSyncPort, project: OverleafProject, stderr: str,
) -> SyncResult:
    output, _error, _code = await service._run_git(
        project.repo_path, "diff", "--name-only", "--diff-filter=U",
    )
    conflicts = [line.strip() for line in output.splitlines() if line.strip()]
    await service._run_git(project.repo_path, "merge", "--abort")
    message = (
        "Merge conflict detected; local and Overleaf versions were left unchanged"
        if conflicts else f"Merge failed and was aborted: {stderr.strip()}"
    )
    project.last_error = message
    service._persist(project)
    return SyncResult(
        False, "pull", conflicts=conflicts, message=message, branch=project.branch,
    )


async def pull_committed(service: OverleafSyncPort, project_id: str) -> SyncResult:
    project = service._projects.get(project_id)
    if not project:
        return SyncResult(False, "pull", message="Project is not linked")
    before, before_code, importing = "", 1, False
    try:
        before, before_code, failure = await _local_state(service, project)
        if failure:
            return failure
        failure = await _fetch(service, project)
        if failure:
            return failure
        if before_code != 0:
            files, failure = await _initial_checkout(service, project)
        else:
            files, failure = await _merge_existing(service, project, before)
        if failure:
            return failure
        importing = True
        service._apply_export(project)
        importing = False
        project.last_sync = datetime.now(timezone.utc)
        project.last_error = ""
        service._persist(project)
        return SyncResult(
            True, "pull", files_changed=files,
            message=f"Pulled {len(files)} changed file(s)", branch=project.branch,
        )
    except Exception as exc:
        if importing and before_code == 0 and before:
            _, rollback_error, rollback_code = await service._run_git(
                project.repo_path, "reset", "--hard", before,
            )
            if rollback_code:
                exc = RuntimeError(f"{exc}; unable to restore isolated export repository: {rollback_error}")
        project.last_error = str(exc)
        service._persist(project)
        logger.error("Overleaf pull failed", project=project_id, error=str(exc))
        return SyncResult(False, "pull", message=str(exc), branch=project.branch)
