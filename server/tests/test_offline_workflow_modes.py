"""Offline golden workflow modes using only fake providers and temporary state."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from server.tests.test_workflow_end_to_end import _build_run, _install_pipeline_fakes
from server.workflows.engine import WorkflowEngine


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "classification", "submission_ready"),
    [
        ("design_only", "design_only_ready", False),
        ("existing_results", "existing_results_ready", False),
        ("secondary_analysis", "secondary_analysis_ready", False),
    ],
)
async def test_no_run_modes_reach_all_acceptance_transitions_offline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    classification: str,
    submission_ready: bool,
) -> None:
    engine = WorkflowEngine()
    options = {
        "run_experiment": False,
        "non_experiment_evidence_mode": mode,
        "human_checkpoint": False,
        "code_review": False,
        "research_quality_mode": "off",
    }
    run, state = _build_run(engine, tmp_path, f"offline-{mode}", options)
    events: list[tuple[str, dict[str, Any]]] = []
    executions: list[str] = []
    accepted: list[str] = []
    _install_pipeline_fakes(
        engine,
        monkeypatch,
        events=events,
        executions=executions,
        classification=classification,
        submission_ready=submission_ready,
    )

    async def fake_node(node, *_args, **_kwargs) -> str:
        return f"{node.id} complete"

    async def accept_node(**kwargs):
        node = kwargs["node"]
        accepted.append(node.id)
        state.set_status(node.id, "done")
        return ({
            "accepted": True,
            "verdict_id": f"offline:{mode}:{node.id}",
            "reviewer": "deterministic:offline-golden",
            "summary": "accepted",
            "details": {},
        }, kwargs["initial_result"])

    monkeypatch.setattr(engine, "_execute_node", fake_node)
    monkeypatch.setattr(engine, "_run_node_revision_loop", accept_node)
    monkeypatch.setattr(
        engine,
        "_ensure_planned_results_analysis",
        lambda _run, _direction, result="": result or "planned",
    )

    await engine._execute_run(
        run, "offline contract research", "lite", "draft", options,
    )

    assert accepted == [node.id for node in engine._get_default_nodes()]
    assert run.status == "completed"
    assert run.completion["completion_class"] == classification
    assert run.completion["submission_ready"] is submission_ready
