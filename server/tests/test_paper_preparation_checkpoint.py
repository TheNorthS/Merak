"""Deterministic preparation defects retain scope without claiming paper acceptance."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from server.services.paper_preparation_errors import PaperPreparationError, guard_paper_preparation
from server.services.semantic_table import SemanticTableContractError
from server.workflows.engine import WorkflowEngine
from server.workflows.models import NodeStatus, WorkflowNode, WorkflowRun
from server.workflows.run_execution_context import RunExecutionContext, StopRunNodes
from server.workflows.run_execution_execute import handle_node_error
from server.workflows.run_execution_final import classify_run
from server.workflows.run_state import RunState
from server.workflows.session_state import SessionState


def _cell_error() -> SemanticTableContractError:
    return SemanticTableContractError(
        "paragraph-length cells belong in prose, not tables", table_label="tab:method-components",
        row_index=1, column_key="evaluation",
    )


def test_known_preparation_error_keeps_exact_cell_and_chained_cause() -> None:
    def fail():
        raise _cell_error()

    with pytest.raises(PaperPreparationError) as caught:
        guard_paper_preparation("table_evidence", fail)
    error = caught.value
    assert isinstance(error.__cause__, SemanticTableContractError)
    details = error.gate_details()
    assert details["findings"][0]["location"] == {
        "table_label": "tab:method-components", "row_index": 1, "column_key": "evaluation",
    }
    assert details["repair_scope"]["target_files"] == [
        "paper/tables/method_components.csv", "paper/tables/method_components.tex",
        "paper/tables/TABLE_MANIFEST.json",
    ]
    assert not details["retryable"]


def test_distinct_cell_failures_have_distinct_finding_identities() -> None:
    first = PaperPreparationError("table_evidence", _cell_error())
    other = PaperPreparationError("table_evidence", SemanticTableContractError(
        str(_cell_error()), table_label="tab:method-components", row_index=2, column_key="function",
    ))
    assert first.gate_details()["findings"][0]["id"] != other.gate_details()["findings"][0]["id"]


@pytest.mark.parametrize("error", [PermissionError("denied"), TypeError("programming defect"),
                                   RuntimeError("unexpected internal failure")])
def test_security_and_programming_errors_are_not_relabelled_as_table_defects(error) -> None:
    def fail():
        raise error

    with pytest.raises(type(error)) as caught:
        guard_paper_preparation("table_evidence", fail)
    assert caught.value is error


@pytest.mark.asyncio
async def test_actual_error_handler_preserves_accepted_figure_and_paper_resume_scope(tmp_path: Path, monkeypatch):
    host = WorkflowEngine()
    figure = WorkflowNode(id="figure", name="Figures", skill="/paper-figure", status=NodeStatus.COMPLETED)
    paper = WorkflowNode(id="paper", name="Paper", skill="/paper-write", status=NodeStatus.RUNNING)
    review = WorkflowNode(id="review", name="Review", skill="/domain-review-loop")
    run = WorkflowRun(id="paper-prepare-fixture", project_path=str(tmp_path), nodes=[figure, paper, review], status="running")
    state = RunState(str(tmp_path), run.id)
    state.start([{"id": node.id, "name": node.name, "skill": node.skill} for node in run.nodes],
                {"options": {"run_experiment": False}})
    state.set_status("figure", "done")
    state.accept("figure", "fixture:accepted-figure", "deterministic:figure-manifest", {"unchanged_science": True})
    accepted = copy.deepcopy(state.load()["phases"]["figure"])
    state.set_status("paper", "running")
    events = []

    async def emit(_run, event, data):
        events.append((event, data))

    monkeypatch.setattr(host, "_emit", emit)
    context = RunExecutionContext(host, run, "Fixture", "balanced", "draft", {"run_experiment": False},
                                  run_state=state, session_state=SessionState(str(tmp_path)), node=paper)
    with pytest.raises(StopRunNodes):
        await handle_node_error(context, PaperPreparationError("table_evidence", _cell_error()))
    await classify_run(context)
    saved = state.load()
    assert run.status == saved["status"] == "incomplete"
    assert saved["phases"]["figure"] == accepted
    assert saved["phases"]["review"]["status"] == "pending"
    phase = saved["phases"]["paper"]
    assert phase["status"] == "awaiting_revision"
    assert phase["details"]["revision"]["last_gate"]["error_category"] == "paper_preparation"
    assert phase["details"]["preparation_failure"]["findings"][0]["owner_node"] == "paper"
    assert phase["details"]["revision"]["round"] == 0
    assert SessionState(str(tmp_path)).load()["current_node"] == "paper"
    assert not {"workflow_failed", "node_failed", "skill_invocation_started", "node_accepted"}.intersection(
        event for event, _ in events
    )


@pytest.mark.asyncio
async def test_unexpected_authoring_value_error_is_not_silently_checkpointed(tmp_path: Path, monkeypatch):
    host = WorkflowEngine()
    node = WorkflowNode(id="paper", name="Paper", skill="/paper-write", status=NodeStatus.RUNNING)
    run = WorkflowRun(id="ordinary-error", project_path=str(tmp_path), nodes=[node], status="running")
    state = RunState(str(tmp_path), run.id)
    state.start([{"id": node.id, "name": node.name, "skill": node.skill}], {})
    events = []

    async def emit(_run, event, _data):
        events.append(event)

    monkeypatch.setattr(host, "_emit", emit)
    context = RunExecutionContext(host, run, "Fixture", "balanced", "draft", {}, run_state=state, node=node)
    with pytest.raises(StopRunNodes):
        await handle_node_error(context, ValueError("unexpected model-tool defect"))
    assert state.load()["phases"]["paper"]["status"] == "failed"
    assert events == ["node_failed"]
