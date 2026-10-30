"""Schedule newly invalidated dependencies before launching a resumed consumer."""

from typing import Any

from .models import WorkflowRun
from .run_state import RunState


def include_reopened_dependencies(host: Any, run: WorkflowRun, state: RunState) -> None:
    """A second acceptance check may revoke an owner after the initial queue was chosen."""
    if not run.options.get("resume_run_id"):
        return
    from .resume_execution import _dependency_closure

    saved = state.load() or {}
    existing = {node.id: node for node in run.nodes}
    required = _dependency_closure(host, saved, list(existing))
    definitions = {node.id: node for node in host._get_default_nodes()}
    for phase_id in required:
        if phase_id not in existing and phase_id in definitions:
            existing[phase_id] = definitions[phase_id]
    ordered = [phase_id for phase_id in saved.get("phases", {}) if phase_id in existing]
    ordered.extend(phase_id for phase_id in existing if phase_id not in ordered)
    run.nodes = [existing[phase_id] for phase_id in ordered]
