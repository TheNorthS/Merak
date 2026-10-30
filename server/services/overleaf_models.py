"""Data contracts shared by Overleaf synchronization components."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass(slots=True)
class OverleafProject:
    project_id: str
    local_path: str
    repo_path: str = ""
    email: str = ""
    token: str = ""
    branch: str = "master"
    last_sync: Optional[datetime] = None
    auto_sync: bool = False
    sync_interval: int = 300
    last_error: str = ""
    last_imported_files: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SyncResult:
    success: bool
    direction: str
    files_changed: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    message: str = ""
    branch: str = ""
