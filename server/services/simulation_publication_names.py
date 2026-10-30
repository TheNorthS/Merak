"""Bind generic comparison wording to the frozen named focal study condition."""

from __future__ import annotations

import re
from typing import Any


_FOCAL_WORDING = re.compile(r"\b(?:full method|full specification)\b", re.IGNORECASE)


def named_focal_caption(value: str, focal_name: str) -> str:
    """Replace only generic focal references, never scientific clauses or quantities."""
    if not focal_name.strip() or _FOCAL_WORDING.search(focal_name):
        raise ValueError("Simulation comparison caption requires a declared non-generic focal condition")
    return _FOCAL_WORDING.sub(lambda _match: focal_name.strip(), str(value))


def bind_profile_focal_names(profile: dict[str, Any], focal_name: str) -> None:
    """The scenario producer uses the selected public method name in its captions."""
    if not focal_name.strip():
        return
    for asset in (profile.get("assets") or {}).values():
        for key in ("description", "table_description", "visual_encoding", "intended_comparison"):
            if key in asset:
                asset[key] = named_focal_caption(str(asset[key]), focal_name)
