"""Resolve workflow evidence modes independently of validators and repositories."""

from __future__ import annotations

from typing import Any

from .simulation_policy import is_complete_evidence_mode


def workflow_evidence_mode(options: dict[str, Any]) -> str:
    if options.get("run_experiment") is True:
        return "executed"
    return str(options.get("non_experiment_evidence_mode") or "design_only").casefold()


def has_complete_manuscript_evidence(options: dict[str, Any]) -> bool:
    """A complete evidence track includes the provenance-bound simulation bundle."""
    return is_complete_evidence_mode(workflow_evidence_mode(options))
