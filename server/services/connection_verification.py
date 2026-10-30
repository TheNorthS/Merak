"""Persist connection-test results without storing credentials in the record."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from .settings_storage import settings_storage_path


class ConnectionVerificationStore:
    """Bind a successful connection test to an exact configuration fingerprint."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else settings_storage_path("merak_ide.db")

    @staticmethod
    def fingerprint(payload: Mapping[str, Any]) -> str:
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.db_path), timeout=5)
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS connection_verifications (
                scope TEXT NOT NULL,
                target TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                verified INTEGER NOT NULL DEFAULT 0,
                tested_at TEXT NOT NULL,
                message TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (scope, target)
            )
            """
        )
        connection.commit()
        return connection

    def record(
        self,
        scope: str,
        target: str,
        payload: Mapping[str, Any],
        verified: bool,
        message: str = "",
    ) -> dict[str, Any]:
        tested_at = datetime.now(timezone.utc).isoformat()
        fingerprint = self.fingerprint(payload)
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO connection_verifications
                    (scope, target, fingerprint, verified, tested_at, message)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(scope, target) DO UPDATE SET
                    fingerprint = excluded.fingerprint,
                    verified = excluded.verified,
                    tested_at = excluded.tested_at,
                    message = excluded.message
                """,
                (scope, target, fingerprint, int(verified), tested_at, message[:1000]),
            )
            connection.commit()
        return self.status(scope, target, payload)

    def status(self, scope: str, target: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        current_fingerprint = self.fingerprint(payload)
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT fingerprint, verified, tested_at, message
                FROM connection_verifications
                WHERE scope = ? AND target = ?
                """,
                (scope, target),
            ).fetchone()

        if not row:
            return {
                "tested": False,
                "verified": False,
                "stale": False,
                "tested_at": None,
                "message": "尚未测试连接",
            }

        matches = row[0] == current_fingerprint
        return {
            "tested": matches,
            "verified": bool(row[1]) and matches,
            "stale": not matches,
            "tested_at": row[2],
            "message": row[3] if matches else "配置已变更，需要重新测试",
        }

    def is_verified(self, scope: str, target: str, payload: Mapping[str, Any]) -> bool:
        return bool(self.status(scope, target, payload)["verified"])


connection_verification_store = ConnectionVerificationStore()
