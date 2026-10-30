"""Detect canonical Overleaf changes and preserve research acceptance integrity."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import hashlib
from pathlib import Path
import time
import uuid

from ..utils.atomic_write import atomic_write_json, path_lock
from .overleaf_export import BLOCKED_DIRECTORIES, BLOCKED_FILES, GENERATED_FILES
from .research_change_application import _invalidate_runs, affected_phases

_workflow_run = ContextVar("overleaf_workflow_run", default="")


@contextmanager
def workflow_sync(run_id: str):
    token = _workflow_run.set(run_id)
    try:
        yield
    finally:
        _workflow_run.reset(token)


def serialized_sync(method):
    """Serialize nested sync/pull/push operations for one linked project."""
    @wraps(method)
    async def execute(self, project_id, *args, **kwargs):
        task = asyncio.current_task()
        if self._sync_owners.get(project_id) is task:
            return await method(self, project_id, *args, **kwargs)
        lock = self._sync_locks.setdefault(project_id, asyncio.Lock())
        async with lock:
            self._sync_owners[project_id] = task
            try:
                return await method(self, project_id, *args, **kwargs)
            finally:
                self._sync_owners.pop(project_id, None)
    return execute


def publication_fingerprints(root: Path) -> dict[str, str]:
    result = {}
    for directory in ("paper", "figures"):
        base = root / directory
        if base.exists() and (base.is_symlink() or not base.resolve().is_relative_to(root.resolve())):
            raise ValueError("Publication directory escapes the research project")
        for path in sorted(base.rglob("*")):
            if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
                raise ValueError("Publication synchronization rejects linked paths")
            if not path.is_file() or path.name in GENERATED_FILES | BLOCKED_FILES:
                continue
            if set(path.relative_to(root).parts).intersection(BLOCKED_DIRECTORIES):
                continue
            result[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def assert_sync_scope(root: Path) -> None:
    from ..workflows.workflow_lease import ProjectRunLease

    claim = ProjectRunLease(str(root)).active_claim()
    if claim and claim.get("run_id") != _workflow_run.get():
        raise RuntimeError("A workflow is active; its owner must synchronize publication changes")


def materialize_publication_export(service, project) -> None:
    from ..workflows.workflow_lease import ProjectRunLease

    root = Path(project.local_path).resolve().parent
    repository = Path(project.repo_path)
    with path_lock(ProjectRunLease(str(root)).path):
        assert_sync_scope(root)
        from .overleaf_revision_recovery import recover_publication_imports
        recover_publication_imports(service, root)
        before = publication_fingerprints(root)
        for name in ("paper", "figures"):
            service._copy_research_tree(root / name, repository / name)
        if publication_fingerprints(root) != before:
            raise RuntimeError("Local publication changed during Overleaf export")
        service._export_fingerprints[project.project_id] = before


def apply_publication_merge(service, project) -> None:
    """Check concurrent edits, invalidate before copying, and rollback failed copies."""
    import shutil
    from ..workflows.workflow_lease import ProjectRunLease

    root = Path(project.local_path).resolve().parent
    repository = Path(project.repo_path).resolve()
    lease = ProjectRunLease(str(root))
    with path_lock(lease.path):
        assert_sync_scope(root)
        before = publication_fingerprints(root)
        expected = service._export_fingerprints.get(project.project_id)
        if expected is None or before != expected:
            raise RuntimeError("Overleaf merge conflict: local publication changed during synchronization")
        remote = publication_fingerprints(repository)
        changed = [key for key in sorted(before.keys() | remote.keys()) if before.get(key) != remote.get(key)]
        project.last_imported_files = changed
        if not changed:
            return
        receipt = {"schema_version": 1, "id": uuid.uuid4().hex[:12], "status": "prepared",
                   "path": ", ".join(changed), "created_at": time.time(), "source": "overleaf",
                   "project_id": project.project_id, "before": before, "after": remote}
        directory = root / ".merak/overleaf-revisions" / receipt["id"]
        for name in ("paper", "figures"):
            source = root / name
            if source.exists():
                shutil.copytree(source, directory / "backup" / name)
        atomic_write_json(directory / "revision.json", receipt)
        affected = set().union(*(set(affected_phases(path)) for path in changed))
        from ..contracts.workflow_nodes import WORKFLOW_NODES
        phases = [node["id"] for node in WORKFLOW_NODES if node["id"] in affected]
        receipt["affected_runs"] = _invalidate_runs(root, phases, receipt)
        for name in ("paper", "figures"):
            (directory / "backup" / name).mkdir(parents=True, exist_ok=True)
            (repository / name).mkdir(parents=True, exist_ok=True)
        try:
            for name in ("paper", "figures"):
                service._copy_research_tree(repository / name, root / name)
        except BaseException:
            for name in ("paper", "figures"):
                service._copy_research_tree(directory / "backup" / name, root / name)
            receipt["status"] = "rolled_back"
            atomic_write_json(directory / "revision.json", receipt)
            raise
        receipt["status"] = "applied"
        atomic_write_json(directory / "revision.json", receipt)
        service._export_fingerprints[project.project_id] = publication_fingerprints(root)
