"""Safe, persistent Overleaf Git synchronization.

Remote URLs never contain credentials. Git receives credentials only through a
short-lived GIT_ASKPASS helper and environment variables. Merge conflicts are
reported and aborted without selecting either side.
"""

from __future__ import annotations

import asyncio
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

import structlog

from ..config import settings
from .connection_verification import ConnectionVerificationStore
from .overleaf_export import copy_research_tree
from .overleaf_git_process import askpass_helper, run_git
from .overleaf_models import OverleafProject, SyncResult
from .overleaf_project_store import OverleafProjectStore
from .overleaf_pull import pull_committed
from .overleaf_repository_config import branch_from_ls_remote, configure_repository
from .overleaf_research_revision import (
    apply_publication_merge, materialize_publication_export, serialized_sync,
)

logger = structlog.get_logger()


class OverleafSync:
    """Manage credential-safe Overleaf Git links and synchronization."""

    GIT_GATEWAY = "https://git.overleaf.com"
    _PROJECT_ID = re.compile(r"^[A-Za-z0-9_-]{6,128}$")
    _LOCAL_EXCLUDES = (
        "main.pdf",
        "paper/main.pdf",
        "main.aux",
        "paper/main.aux",
        "main.log",
        "paper/main.log",
        "main.out",
        "paper/main.out",
        "main.fls",
        "paper/main.fls",
        "main.fdb_latexmk",
        "paper/main.fdb_latexmk",
        "main.synctex.gz",
        "paper/main.synctex.gz",
    )

    def __init__(
        self,
        db_path: str | Path = "./merak_ide.db",
        *,
        encryption_secret: str = "",
        git_path: str | None = None,
    ) -> None:
        self._sync_tasks: dict[str, asyncio.Task] = {}
        self._sync_locks: dict[str, asyncio.Lock] = {}
        self._sync_owners: dict[str, asyncio.Task] = {}
        self._export_fingerprints: dict[str, dict[str, str]] = {}
        self._git_path = git_path if git_path is not None else shutil.which("git")
        self._db_path = Path(db_path)
        self._verification_store = ConnectionVerificationStore(self._db_path)
        self._encryption_secret = (
            encryption_secret
            or settings.ssh_encryption_key
            or settings.jwt_secret_key
        )
        self._project_store = OverleafProjectStore(
            self._db_path, self._encryption_secret,
        )
        self._projects = self._project_store.load()

    def _get_git(self) -> str:
        if not self._git_path:
            raise RuntimeError("Git is not installed or is not available in PATH")
        return self._git_path

    @classmethod
    def _validate_project_id(cls, project_id: str) -> str:
        value = str(project_id or "").strip()
        if not cls._PROJECT_ID.fullmatch(value):
            raise ValueError("Invalid Overleaf project ID")
        return value

    @classmethod
    def _remote_url_for_id(cls, project_id: str) -> str:
        return f"{cls.GIT_GATEWAY}/{cls._validate_project_id(project_id)}"

    def _remote_url(self, project: OverleafProject) -> str:
        return self._remote_url_for_id(project.project_id)

    @staticmethod
    def _verification_payload(project: OverleafProject) -> dict:
        return {
            "project_id": project.project_id,
            "local_path": str(Path(project.local_path).resolve()),
            "token": project.token,
        }

    @staticmethod
    def _resolve_local_path(local_path: str) -> Path:
        supplied = Path(local_path).expanduser().resolve()
        paper = supplied / "paper"
        # The UI passes the project root. Restrict Git to the paper tree so
        # datasets, credentials, and experiment artifacts stay local.
        if supplied.name.lower() != "paper":
            supplied = paper
        supplied.mkdir(parents=True, exist_ok=True)
        if not supplied.is_dir():
            raise ValueError("Overleaf local path must be a directory")
        return supplied

    def _fernet(self):
        return self._project_store.fernet()

    def _encrypt(self, value: str) -> str:
        return self._project_store.encrypt(value)

    def _decrypt(self, value: str) -> str:
        return self._project_store.decrypt(value)

    def _connect_db(self):
        return self._project_store.connect()

    def _load_projects(self) -> None:
        self._projects = self._project_store.load()

    def _persist(self, project: OverleafProject) -> None:
        self._project_store.persist(project)

    def _delete_persisted(self, project_id: str) -> None:
        self._project_store.delete(project_id)

    @staticmethod
    def _askpass_helper(directory: Path) -> Path:
        return askpass_helper(directory)

    async def _run_git(
        self,
        cwd: str | Path,
        *args: str,
        timeout: int = 60,
        project: OverleafProject | None = None,
    ) -> tuple[str, str, int]:
        return await run_git(
            self._git_path, cwd, args, timeout=timeout, project=project,
        )

    async def _must_git(
        self,
        cwd: str | Path,
        *args: str,
        project: OverleafProject | None = None,
    ) -> str:
        stdout, stderr, code = await self._run_git(cwd, *args, project=project)
        if code != 0:
            detail = stderr.strip() or stdout.strip() or "git command failed"
            raise RuntimeError(detail)
        return stdout

    async def _configure_repository(self, project: OverleafProject) -> None:
        await configure_repository(self, project, self._LOCAL_EXCLUDES)

    @staticmethod
    def _copy_research_tree(
        source: Path,
        destination: Path,
        *,
        prune: bool = True,
    ) -> None:
        copy_research_tree(source, destination, prune=prune)

    def _materialize_export(self, project: OverleafProject) -> None:
        materialize_publication_export(self, project)

    def _apply_export(self, project: OverleafProject) -> None:
        """Apply a conflict-free remote merge back to canonical project paths."""
        apply_publication_merge(self, project)

    _branch_from_ls_remote = staticmethod(branch_from_ls_remote)

    async def _test_project(self, project: OverleafProject) -> SyncResult:
        stdout, stderr, code = await self._run_git(
            project.repo_path,
            "ls-remote",
            "--symref",
            self._remote_url(project),
            "HEAD",
            timeout=45,
            project=project,
        )
        if code != 0:
            message = (
                stderr.strip() or stdout.strip() or "Overleaf connection test failed"
            )
            return SyncResult(
                False, "test", message=message, branch=project.branch
            )
        project.branch = self._branch_from_ls_remote(stdout, project.branch)
        project.last_error = ""
        return SyncResult(
            True,
            "test",
            message=f"Overleaf Git access verified on branch {project.branch}",
            branch=project.branch,
        )

    async def link_project(
        self,
        project_id: str,
        local_path: str,
        email: str,
        token: str,
    ) -> SyncResult:
        try:
            project_id = self._validate_project_id(project_id)
            if not token.strip():
                raise ValueError("Overleaf token is required")
            local = self._resolve_local_path(local_path)
            project = OverleafProject(
                project_id=project_id,
                local_path=str(local),
                repo_path=str(
                    local.parent / ".merak" / "overleaf" / project_id / "repo"
                ),
                email=email.strip(),
                token=token.strip(),
            )
            await self._configure_repository(project)
            test_result = await self._test_project(project)
            if not test_result.success:
                self._verification_store.record(
                    "overleaf",
                    project.project_id,
                    self._verification_payload(project),
                    False,
                    test_result.message,
                )
                return test_result
            self._projects[project_id] = project
            self._persist(project)
            self._verification_store.record(
                "overleaf",
                project.project_id,
                self._verification_payload(project),
                True,
                test_result.message,
            )
            return SyncResult(
                True,
                "link",
                message=(
                    f"Linked MERAK paper export to Overleaf ({project.branch}); "
                    "set the Overleaf main document to paper/main.tex"
                ),
                branch=project.branch,
            )
        except Exception as exc:
            logger.warning("Overleaf link failed", project=project_id, error=str(exc))
            return SyncResult(False, "link", message=str(exc))

    async def test_connection(self, project_id: str) -> SyncResult:
        project = self._projects.get(project_id)
        if not project:
            return SyncResult(False, "test", message="Project is not linked")
        result = await self._test_project(project)
        project.last_error = "" if result.success else result.message
        self._persist(project)
        self._verification_store.record(
            "overleaf",
            project.project_id,
            self._verification_payload(project),
            result.success,
            result.message,
        )
        return result

    async def _commit_pending(
        self, project: OverleafProject, message: str
    ) -> tuple[list[str], str]:
        self._materialize_export(project)
        await self._must_git(project.repo_path, "add", "-A")
        changed, stderr, code = await self._run_git(
            project.repo_path, "diff", "--cached", "--name-only"
        )
        if code != 0:
            return [], stderr.strip() or "Unable to inspect staged changes"
        files = [line.strip() for line in changed.splitlines() if line.strip()]
        if not files:
            return [], ""
        _, stderr, code = await self._run_git(
            project.repo_path, "commit", "-m", message
        )
        if code != 0:
            return [], stderr.strip() or "Unable to commit local paper changes"
        return files, ""

    async def _pull_committed(self, project_id: str) -> SyncResult:
        return await pull_committed(self, project_id)

    @serialized_sync
    async def prepare_sync(
        self, project_id: str, message: str = "Prepare MERAK paper sync"
    ) -> SyncResult:
        """Commit local work, then safely merge the latest Overleaf revision."""
        project = self._projects.get(project_id)
        if not project:
            return SyncResult(False, "pull", message="Project is not linked")
        files, error = await self._commit_pending(project, message)
        if error:
            return SyncResult(
                False, "pull", message=error, branch=project.branch
            )
        pulled = await self._pull_committed(project_id)
        pulled.files_changed = sorted(set(files + pulled.files_changed))
        return pulled

    async def pull(self, project_id: str) -> SyncResult:
        """Preserve local source changes before fetching and merging Overleaf."""
        return await self.prepare_sync(
            project_id,
            "Preserve local paper before Overleaf pull",
        )

    @serialized_sync
    async def push(
        self, project_id: str, commit_message: str = "Update from MERAK"
    ) -> SyncResult:
        project = self._projects.get(project_id)
        if not project:
            return SyncResult(False, "push", message="Project is not linked")
        try:
            files, error = await self._commit_pending(project, commit_message)
            if error:
                return SyncResult(
                    False, "push", message=error, branch=project.branch
                )
            _, stderr, code = await self._run_git(
                project.repo_path,
                "push",
                "overleaf",
                f"HEAD:{project.branch}",
                timeout=120,
                project=project,
            )
            if code != 0:
                if (
                    "rejected" in stderr.lower()
                    or "non-fast-forward" in stderr.lower()
                ):
                    message = (
                        "Overleaf changed since the last pull; run Sync and "
                        "resolve any reported conflicts"
                    )
                else:
                    message = f"Push failed: {stderr.strip()}"
                project.last_error = message
                self._persist(project)
                return SyncResult(
                    False,
                    "push",
                    files_changed=files,
                    message=message,
                    branch=project.branch,
                )
            project.last_sync = datetime.now(timezone.utc)
            project.last_error = ""
            self._persist(project)
            return SyncResult(
                True,
                "push",
                files_changed=files,
                message=f"Pushed {len(files)} changed file(s) to Overleaf",
                branch=project.branch,
            )
        except Exception as exc:
            project.last_error = str(exc)
            self._persist(project)
            logger.error("Overleaf push failed", project=project_id, error=str(exc))
            return SyncResult(
                False, "push", message=str(exc), branch=project.branch
            )

    @serialized_sync
    async def sync(
        self, project_id: str, message: str = "Sync paper from MERAK"
    ) -> SyncResult:
        prepared = await self.prepare_sync(project_id, message)
        if not prepared.success:
            return prepared
        pushed = await self.push(project_id, message)
        return SyncResult(
            pushed.success,
            "both",
            files_changed=sorted(
                set(prepared.files_changed + pushed.files_changed)
            ),
            conflicts=prepared.conflicts,
            message=f"Pull: {prepared.message} | Push: {pushed.message}",
            branch=pushed.branch or prepared.branch,
        )

    def is_ready_for_project(self, project_id: str, project_root: str) -> bool:
        project = self._projects.get(project_id)
        if not project or not project.token:
            return False
        expected = (
            Path(project_root).expanduser().resolve() / "paper"
        ).resolve()
        return (
            Path(project.local_path).resolve() == expected
            and self._verification_store.is_verified(
                "overleaf",
                project.project_id,
                self._verification_payload(project),
            )
        )

    async def start_auto_sync(self, project_id: str) -> bool:
        project = self._projects.get(project_id)
        if (
            not project
            or not project.token
            or not self._verification_store.is_verified(
                "overleaf",
                project.project_id,
                self._verification_payload(project),
            )
        ):
            return False
        running = self._sync_tasks.get(project_id)
        if running and not running.done():
            return True
        project.auto_sync = True
        self._persist(project)

        async def loop() -> None:
            while project.auto_sync:
                try:
                    result = await self.sync(project_id)
                except Exception as exc:
                    result = SyncResult(False, "both", message=str(exc))
                if not result.success:
                    logger.warning(
                        "Overleaf auto-sync paused after failure",
                        project=project_id,
                        error=result.message,
                    )
                    project.auto_sync = False
                    self._persist(project)
                    break
                await asyncio.sleep(project.sync_interval)

        self._sync_tasks[project_id] = asyncio.create_task(loop())
        return True

    async def stop_auto_sync(self, project_id: str) -> bool:
        project = self._projects.get(project_id)
        if project:
            project.auto_sync = False
            self._persist(project)
        task = self._sync_tasks.pop(project_id, None)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        return project is not None

    async def restore_auto_sync(self) -> None:
        for project in list(self._projects.values()):
            if project.auto_sync:
                await self.start_auto_sync(project.project_id)

    async def shutdown(self) -> None:
        tasks = list(self._sync_tasks.values())
        self._sync_tasks.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def unlink(self, project_id: str) -> bool:
        await self.stop_auto_sync(project_id)
        project = self._projects.pop(project_id, None)
        if project is None:
            return False
        self._delete_persisted(project_id)
        return True

    def get_status(self, project_id: str) -> dict:
        project = self._projects.get(project_id)
        if not project:
            return {"linked": False, "project_id": project_id}
        verification = self._verification_store.status(
            "overleaf",
            project.project_id,
            self._verification_payload(project),
        )
        return {
            "linked": True,
            "project_id": project.project_id,
            "local_path": project.local_path,
            "branch": project.branch,
            "last_sync": (
                project.last_sync.isoformat() if project.last_sync else None
            ),
            "auto_sync": project.auto_sync,
            "sync_interval": project.sync_interval,
            "main_document": "paper/main.tex",
            "credentials_available": bool(project.token),
            "verified": bool(project.token) and verification["verified"],
            "verification": verification,
            "last_error": project.last_error,
        }

    def list_projects(self) -> list[dict]:
        return [
            self.get_status(project_id)
            for project_id in sorted(self._projects)
        ]


overleaf_sync = OverleafSync()
