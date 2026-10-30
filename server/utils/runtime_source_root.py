"""Resolve owned source mirrors without probing a system Python or current cwd."""

from __future__ import annotations

import sys
from pathlib import Path


def server_source_root() -> Path:
    """The frozen backend carries canonical source bytes beside its runtime."""
    if not getattr(sys, "frozen", False):
        return Path(__file__).resolve().parents[1]
    resource = getattr(sys, "_MEIPASS", None)
    if not isinstance(resource, str) or not resource.strip():
        raise RuntimeError("Frozen backend source verification requires its bundle resource root")
    bundle = Path(resource).resolve()
    sources = (bundle / "merak-source/server").resolve()
    if not sources.is_relative_to(bundle) or not sources.is_dir():
        raise RuntimeError("Frozen backend canonical source mirror is missing or outside its bundle")
    return sources


def implementation_source_path(loaded_path: Path) -> Path:
    """Map only this package's implementation files, never external skill assets."""
    path = loaded_path.resolve()
    if not getattr(sys, "frozen", False):
        return path
    loaded_root = Path(__file__).resolve().parents[1]
    try:
        relative = path.relative_to(loaded_root)
    except ValueError:
        return path
    canonical = (server_source_root() / relative).resolve()
    if not canonical.is_relative_to(server_source_root()):
        raise RuntimeError("Frozen backend implementation source escapes its canonical mirror")
    return canonical
