"""Durable settings snapshots ordered by save revision, never database activity."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import threading
import time

import structlog

from .settings_models import UserSettings
from .settings_storage import settings_storage_path
from ..utils.atomic_write import atomic_write_json

logger = structlog.get_logger()
REVISION_KEY = "_snapshot_revision_ns"
_lock = threading.RLock()
_last_revision = 0


def snapshot_order(payload: dict, modified: float) -> tuple[int, int]:
    """Explicit revisions supersede unversioned snapshots without rewriting them."""
    revision = payload.get(REVISION_KEY)
    try:
        value = int(revision) if revision is not None else 0
    except (TypeError, ValueError):
        value = 0
    return (1, value) if value > 0 else (0, int(modified * 1_000_000_000))


def read_database(database: Path) -> tuple[dict, float] | None:
    if not database.is_file():
        return None
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
        rows = connection.execute(
            "SELECT key, value, updated_at FROM user_settings WHERE user_id = ?", ("default",),
        ).fetchall()
        updated = connection.execute(
            "SELECT MAX((julianday(updated_at) - 2440587.5) * 86400.0) "
            "FROM user_settings WHERE user_id = ?", ("default",),
        ).fetchone()[0]
    if not rows:
        return None
    payload: dict = {}
    for key, value, _timestamp in rows:
        section, separator, field = key.partition(".")
        if separator:
            payload.setdefault(section, {})[field] = value
        else:
            payload[section] = value
    return payload, float(updated or 0)


def _candidates(config_file: Path) -> list[tuple[tuple[int, int], str, dict]]:
    candidates = []
    try:
        stored = read_database(settings_storage_path("merak_ide.db"))
        if stored:
            payload, modified = stored
            candidates.append((snapshot_order(payload, modified), "sqlite", payload))
    except (OSError, sqlite3.Error, ValueError) as exc:
        logger.warning("Settings database read failed", error_type=type(exc).__name__)
    if config_file.is_file():
        try:
            payload = json.loads(config_file.read_text(encoding="utf-8-sig"))
            if isinstance(payload, dict):
                candidates.append((snapshot_order(payload, config_file.stat().st_mtime), "json", payload))
        except (OSError, ValueError) as exc:
            logger.warning("Settings JSON read failed", error_type=type(exc).__name__)
    return candidates


def load(config_file: Path) -> UserSettings:
    with _lock:
        candidates = _candidates(config_file)
        for _order, source, payload in sorted(candidates, key=lambda item: item[:2], reverse=True):
            try:
                return UserSettings.model_validate(payload)
            except ValueError as exc:
                logger.warning("Stored settings snapshot is invalid", source=source, error_type=type(exc).__name__)
    return UserSettings()


def write_database(payload: dict) -> None:
    database = settings_storage_path("merak_ide.db")
    database.parent.mkdir(parents=True, exist_ok=True)
    pairs = []
    for section, fields in payload.items():
        if isinstance(fields, dict):
            pairs.extend((f"{section}.{key}", str(value) if value is not None else "")
                         for key, value in fields.items())
        else:
            pairs.append((section, str(fields) if fields is not None else ""))
    with closing(sqlite3.connect(str(database))) as connection, connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT 'default',
                key TEXT NOT NULL, value TEXT NOT NULL DEFAULT '',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, key)
            )
        """)
        connection.executemany(
            "INSERT INTO user_settings (user_id, key, value, updated_at) "
            "VALUES ('default', ?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP",
            pairs,
        )


def save(config_file: Path, settings: UserSettings) -> None:
    """Commit one revision to both stores; one durable copy is sufficient."""
    global _last_revision
    with _lock:
        previous = max((order[1] for order, _source, _payload in _candidates(config_file) if order[0]), default=0)
        revision = max(time.time_ns(), previous + 1, _last_revision + 1)
        _last_revision = revision
        payload = {**settings.model_dump(), REVISION_KEY: revision}
        succeeded = []
        failures = []
        for backend, write in (("sqlite", lambda: write_database(payload)),
                               ("json", lambda: atomic_write_json(config_file, payload))):
            try:
                write()
                succeeded.append(backend)
            except (OSError, sqlite3.Error, ValueError) as exc:
                failures.append(f"{backend}: {type(exc).__name__}")
                logger.warning("Settings snapshot write failed", backend=backend, error_type=type(exc).__name__)
        if not succeeded:
            raise RuntimeError("Settings could not be persisted (" + "; ".join(failures) + ")")
