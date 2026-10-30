"""Bind independent reviewer sessions to the caller's project with read-only capabilities."""

from pathlib import Path
from typing import Any


REVIEW_READ_TOOLS = ["Read", "Glob", "Grep"]


def review_root(project_path: str, file_path: str = "") -> Path | None:
    if project_path:
        root = Path(project_path).expanduser().resolve()
        if not root.is_dir():
            raise ValueError("Reviewer project directory does not exist")
        return root
    if file_path:
        return Path(file_path).expanduser().resolve().parent
    return None


def bind_review_scope(session: Any, root: Path | None, *, new_session: bool = False) -> list[str]:
    if root is None:
        session.allowed_write_paths = []
        return []
    existing = str(getattr(session, "project_path", "") or "")
    if existing and not new_session and Path(existing).resolve() != root:
        raise ValueError("Reviewer thread belongs to a different project")
    session.project_path = str(root)
    session.tool_policy = "workflow_artifacts"
    session.allowed_write_paths = []
    session.max_iterations = min(int(session.max_iterations), 20)
    return list(REVIEW_READ_TOOLS)
