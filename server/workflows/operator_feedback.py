"""Keep operator continuation instructions for the entire owning node lifecycle."""

from __future__ import annotations

import time

from .run_state import RunState


def record_operator_feedback(state: RunState, node_id: str, text: str) -> None:
    """Persist before a checkpoint is consumed; newer explicit guidance replaces the current text."""
    text = str(text or "").strip()
    if not text:
        return

    def update(saved: dict) -> None:
        phase = saved.get("phases", {}).get(node_id)
        if phase is None:
            raise ValueError(f"Cannot attach operator feedback to unknown node: {node_id}")
        details = phase.setdefault("details", {})
        previous = details.get("operator_feedback") or {}
        if previous.get("text") == text:
            return
        if previous:
            history = details.setdefault("operator_feedback_history", [])
            history.append(previous)
            del history[:-20]
        details["operator_feedback"] = {"schema": 1, "text": text, "recorded_at": time.time()}

    state.update_state(update)


def current_operator_feedback(run, node_id: str) -> str:
    """Read fresh in-memory guidance or its durable node-scoped value after restart."""
    if run.checkpoint_node_id == node_id and run.checkpoint_feedback:
        return str(run.checkpoint_feedback).strip()
    saved = RunState(run.project_path, run.id).load() or {}
    details = saved.get("phases", {}).get(node_id, {}).get("details", {})
    return str((details.get("operator_feedback") or {}).get("text") or "").strip()


def operator_feedback_context(run, node_id: str) -> str:
    feedback = current_operator_feedback(run, node_id)
    if not feedback:
        return ""
    return (
        "\n\n## Operator continuation instructions\n"
        "Apply this intent within the stage's declared write scope. Report any upstream "
        "change required outside that scope to its owner; never discard the instruction "
        "or bypass a scientific gate.\n" + feedback
    )
