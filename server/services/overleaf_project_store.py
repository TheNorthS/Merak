"""Encrypted SQLite persistence for linked Overleaf projects."""

from __future__ import annotations

import base64
import hashlib
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

import structlog
from cryptography.fernet import Fernet, InvalidToken

from .overleaf_models import OverleafProject


logger = structlog.get_logger()


class OverleafProjectStore:
    def __init__(self, db_path: str | Path, encryption_secret: str):
        self.db_path = Path(db_path)
        self.encryption_secret = encryption_secret

    def fernet(self) -> Fernet:
        digest = hashlib.sha256(self.encryption_secret.encode("utf-8")).digest()
        return Fernet(base64.urlsafe_b64encode(digest))

    def encrypt(self, value: str) -> str:
        return self.fernet().encrypt(value.encode("utf-8")).decode("ascii") if value else ""

    def decrypt(self, value: str) -> str:
        if not value:
            return ""
        try:
            return self.fernet().decrypt(value.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError):
            logger.warning("Unable to decrypt persisted Overleaf credential")
            return ""

    def connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.db_path), timeout=5)
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS overleaf_projects (
                project_id TEXT PRIMARY KEY,
                local_path TEXT NOT NULL,
                repo_path TEXT NOT NULL DEFAULT '',
                email TEXT NOT NULL DEFAULT '',
                token_encrypted TEXT NOT NULL DEFAULT '',
                branch TEXT NOT NULL DEFAULT 'master',
                last_sync TEXT,
                auto_sync INTEGER NOT NULL DEFAULT 0,
                sync_interval INTEGER NOT NULL DEFAULT 300,
                last_error TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        columns = {
            row[1] for row in connection.execute(
                "PRAGMA table_info(overleaf_projects)"
            ).fetchall()
        }
        if "repo_path" not in columns:
            connection.execute(
                "ALTER TABLE overleaf_projects ADD COLUMN repo_path TEXT NOT NULL DEFAULT ''"
            )
        connection.commit()
        return connection

    def load(self) -> dict[str, OverleafProject]:
        projects: dict[str, OverleafProject] = {}
        try:
            with closing(self.connect()) as connection:
                rows = connection.execute(
                    """SELECT project_id, local_path, repo_path, email, token_encrypted, branch,
                              last_sync, auto_sync, sync_interval, last_error
                       FROM overleaf_projects"""
                ).fetchall()
            for row in rows:
                project = self._row_to_project(row)
                projects[project.project_id] = project
        except Exception as exc:
            logger.warning("Failed to load Overleaf links", error=str(exc))
        return projects

    def _row_to_project(self, row: tuple) -> OverleafProject:
        try:
            last_sync = datetime.fromisoformat(row[6]) if row[6] else None
        except ValueError:
            last_sync = None
        return OverleafProject(
            project_id=row[0], local_path=row[1],
            repo_path=row[2] or str(
                Path(row[1]).parent / ".merak" / "overleaf" / row[0] / "repo"
            ),
            email=row[3], token=self.decrypt(row[4]), branch=row[5] or "master",
            last_sync=last_sync, auto_sync=bool(row[7]),
            sync_interval=max(30, int(row[8] or 300)), last_error=row[9] or "",
        )

    def persist(self, project: OverleafProject) -> None:
        with closing(self.connect()) as connection:
            connection.execute(
                """
                INSERT INTO overleaf_projects
                    (project_id, local_path, repo_path, email, token_encrypted, branch, last_sync,
                     auto_sync, sync_interval, last_error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                    local_path = excluded.local_path,
                    repo_path = excluded.repo_path,
                    email = excluded.email,
                    token_encrypted = excluded.token_encrypted,
                    branch = excluded.branch,
                    last_sync = excluded.last_sync,
                    auto_sync = excluded.auto_sync,
                    sync_interval = excluded.sync_interval,
                    last_error = excluded.last_error,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    project.project_id, project.local_path, project.repo_path,
                    project.email, self.encrypt(project.token), project.branch,
                    project.last_sync.isoformat() if project.last_sync else None,
                    int(project.auto_sync), project.sync_interval, project.last_error[:2000],
                ),
            )
            connection.commit()

    def delete(self, project_id: str) -> None:
        with closing(self.connect()) as connection:
            connection.execute(
                "DELETE FROM overleaf_projects WHERE project_id = ?", (project_id,)
            )
            connection.commit()
