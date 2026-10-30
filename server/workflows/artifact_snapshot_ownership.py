"""Keep acceptance dependencies bound to their current producing stage.

Only the exact historical literature binding to the downstream paper profile
is excluded. This is a read-only validation view, not a persisted-state rewrite;
all research inputs and every other owner retain their content checks.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


_DOWNSTREAM_ONLY = {"lit": frozenset({"paper/PAPER_PROFILE.json"})}


def owner_snapshot_view(node_id: str, snapshot: Any) -> Any:
    """Exclude only canonical keys forbidden by the current owner contract."""
    excluded = _DOWNSTREAM_ONLY.get(node_id, frozenset())
    if not excluded or not isinstance(snapshot, dict):
        return snapshot
    return {key: value for key, value in snapshot.items() if key not in excluded}


def owner_snapshot_paths(root: Path, node_id: str, paths: list[Path]) -> list[Path]:
    """Never bind a later producer's profile when creating new literature proof."""
    excluded = _DOWNSTREAM_ONLY.get(node_id, frozenset())
    blocked = {(root / relative).resolve() for relative in excluded}
    return [path for path in paths if path.expanduser().resolve() not in blocked]
