"""Stable lock identities for resolved paths, independent of Windows I/O prefixes.

Resolution remains the owner of symlink/junction identity. Windows may retain an
extended prefix when resolving a file concurrently replaced by another process;
that I/O spelling must not create a second mutex for the same canonical file.
"""

from __future__ import annotations

import os
from pathlib import Path


def resolved_lock_identity(spelling: str, *, windows: bool) -> str:
    """Normalize only equivalent Windows extended DOS/UNC path spellings."""
    if windows:
        folded = spelling.casefold()
        if folded.startswith("\\\\?\\unc\\"):
            spelling = "\\\\" + spelling[8:]
        elif folded.startswith("\\\\?\\"):
            drive_path = spelling[4:]
            if (len(drive_path) >= 3 and drive_path[0].isascii()
                    and drive_path[0].isalpha() and drive_path[1:3] == ":\\"):
                spelling = drive_path
    return spelling.replace("\\", "/").casefold()


def canonical_lock_identity(path: Path) -> str:
    """Resolve aliases first, then derive one key for equivalent I/O spellings."""
    return resolved_lock_identity(str(path.resolve()), windows=os.name == "nt")
