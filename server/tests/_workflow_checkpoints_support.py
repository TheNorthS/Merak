from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from server.agent.engine import AgentEngine
from server.api.workflow import (
    WorkflowResumeRequest,
    WorkflowRunRequest,
    get_session_state,
    resume_run,
    run_workflow,
)
from server.services.experiment_placeholders import experiment_placeholder_service
from server.services.simulation_policy import SIMULATION_MANIFEST_SCHEMA
from server.services.skill_orchestrator import skill_orchestrator
from server.services.workflow_inputs import snapshot_paths, workflow_input_service
from server.services.workflow_readiness import READINESS_SCHEMA_VERSION
from server.workflows.engine import (
    AUTONOMOUS_REVISION_ROUNDS,
    NodeStatus,
    WorkflowEngine,
    WorkflowNode,
    WorkflowRun,
    normalize_workflow_illustration_mode,
    normalize_revision_rounds,
)
from server.workflows.run_state import RunState
from server.workflows.session_state import SessionState


WORKFLOW_PHASE_IDS = [
    "lit",
    "idea",
    "novelty",
    "exp-design",
    "exp-run",
    "results",
    "figure",
    "narrative",
    "paper",
    "review",
    "audit",
    "compile",
    "ppt",
]


def _write_dependency_skipped_run(tmp_path: Path, run_id: str = "dependency-skipped") -> RunState:
    run_state = RunState(str(tmp_path), run_id)
    run_state.start(
        [{"id": phase_id, "name": phase_id, "skill": f"/{phase_id}"} for phase_id in WORKFLOW_PHASE_IDS],
        {
            "direction": "EEG foundation models",
            "effort": "balanced",
            "assurance": "draft",
            "options": {"run_experiment": True},
        },
    )
    run_state.set_status("lit", "done")
    run_state.accept("lit", "artifact-exists", "deterministic")
    for phase_id in WORKFLOW_PHASE_IDS[1:]:
        run_state.set_status(phase_id, "skipped", error="dependency not accepted")

    # Reproduce the legacy false-completion record seen in the reported run.
    state = run_state.load()
    assert state is not None
    state["status"] = "completed"
    run_state.save_state(state)
    return run_state
