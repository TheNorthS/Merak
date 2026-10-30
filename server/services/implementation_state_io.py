"""Strict reads for staged implementation state artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_implementation_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Implementation state is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"Implementation state root must be an object: {path}")
    return value
