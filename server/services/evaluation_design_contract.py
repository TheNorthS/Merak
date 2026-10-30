"""Source-backed condition semantics shared by evaluation planning and drawing."""

from __future__ import annotations

import re
from typing import Any


_REMOVAL_TERM = re.compile(r"\b(?:remov(?:e|al)|ablat(?:e|ion)|without)\b", re.I)
_HELDOUT_TERM = re.compile(r"(?:^|[_\s-])(?:test|held[_\s-]?out|external)(?:$|[_\s-])", re.I)

GENERIC_PLANNED_COMPARATORS = (
    "strongest declared prior work, reference condition, or alternative explanation",
    "matched design control with the same data, sampling, resources, and evaluation scope",
)


def declared_removal_conditions(conditions: Any) -> list[str]:
    """Return only explicitly declared component-removal conditions."""
    if not isinstance(conditions, list):
        return []
    return [
        value.strip() for value in conditions
        if isinstance(value, str) and _REMOVAL_TERM.search(value)
    ]


def is_heldout_split(split: Any) -> bool:
    """Classify only an explicitly named held-out/test/external split."""
    return isinstance(split, str) and bool(_HELDOUT_TERM.search(split.strip()))
