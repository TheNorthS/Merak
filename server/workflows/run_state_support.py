"""Shared contracts and locking helpers for durable run state."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Optional

from ..utils.atomic_write import path_lock


# Only an accepted phase is durably terminal. Executor completion is represented
# by ``done`` and must pass a gate before dependencies may consume it.
TERMINAL_PHASE_STATES = {"accepted"}

def _clean_string_list(value: Any) -> list[str]:
    """Normalize optional persisted list fields without iterating strings/null."""

    if not isinstance(value, (list, tuple, set)):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _merge_state_changes(base: Any, proposed: Any, current: Any) -> Any:
    """Apply only base-to-proposed changes to the latest persisted value."""

    if isinstance(base, dict) and isinstance(proposed, dict):
        merged = copy.deepcopy(current) if isinstance(current, dict) else {}
        for key in base.keys() - proposed.keys():
            merged.pop(key, None)
        for key, value in proposed.items():
            if key not in base:
                merged[key] = copy.deepcopy(value)
                continue
            if base[key] == value:
                continue
            merged[key] = _merge_state_changes(
                base[key],
                value,
                merged.get(key, base[key]),
            )
        return merged
    if base == proposed:
        return copy.deepcopy(current)
    return copy.deepcopy(proposed)


def _state_mutation(method):
    """Hold the run lock across each public read-modify-write operation."""

    @wraps(method)
    def locked(self, *args, **kwargs):
        with path_lock(self.path):
            return method(self, *args, **kwargs)

    return locked


@dataclass
class PhaseState:
    id: str
    name: str
    skill: str
    status: str = "pending"  # pending | running | done | awaiting_revision | accepted | skipped | failed
    artifact: str = ""
    verdict_id: str = ""
    reviewer: str = ""
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    accepted_at: Optional[float] = None
    error: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    execution_kind: str = "model_owned"
    runtime_service: str = ""
    policy_required: bool = True


_RUN_TERMINAL_FIELDS = (
    "finished_at",
    "completion",
    "completion_class",
    "execution_completed",
    "submission_ready",
    "error",
)


def _clear_run_terminal_fields(state: dict[str, Any]) -> None:
    """Remove verdicts that describe a previous terminal run lifecycle."""

    for key in _RUN_TERMINAL_FIELDS:
        state.pop(key, None)


