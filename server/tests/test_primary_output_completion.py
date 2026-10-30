"""Primary output delivery regressions use fake model calls and local fixtures."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from server.agent.session_models import AgentSession
from server.services.skill_registry import SkillMetadata
from server.services.workflow_inputs import workflow_input_service
from server.workflows.engine import WorkflowEngine
from server.workflows.models import WorkflowNode, WorkflowRun
from server.workflows.node_execution_completion import (
    ensure_primary_output_delivery,
    inspect_primary_outputs,
    primary_output_paths,
)
from server.workflows.node_execution_context import NodeExecutionContext
from server.workflows.node_execution_coordinator import execute_node
from server.workflows.node_execution_phases import finalize_primary


class MemoryHost(WorkflowEngine):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[tuple[str, dict]] = []
        self.delegate_calls = 0

    async def _emit(self, _run, event: str, data: dict) -> None:
        self.events.append((event, data))

    async def _execute_stage_delegates(self, **_kwargs) -> None:
        self.delegate_calls += 1

    @staticmethod
    def _persist_search_evidence(*_args):
        return None


def _context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> NodeExecutionContext:
    host = MemoryHost()
    node = WorkflowNode(id="novelty", name="Novelty", skill="/domain-novelty-check")
    run = WorkflowRun(id="delivery-fixture", project_path=str(tmp_path), nodes=[node])
    context = NodeExecutionContext(host, node, run, "EEG", "balanced", "draft", False, False, "none", "", "")
    context.project_path = str(tmp_path)
    context.skill_plan = SimpleNamespace(primary="domain-novelty-check", execution_kind="model_owned")
    context.session = AgentSession(id="same-transcript", iterations=4, max_iterations=50)
    context.result = "Now writing the report and selected-idea contract."
    context.owner_skill_prompt = "Loaded skill"
    context.observer = SimpleNamespace(state=SimpleNamespace(model_provider_used="fake", model_name_used="fake"))
    context.source_tool_contract = {}
    context.search_tool_trace = []
    context.enabled_tools = ["Read", "Write", "Edit"]

    async def flush(_force: bool = False) -> None:
        return None

    context.flush_agent_text = flush
    monkeypatch.setattr(
        "server.workflows.node_execution_completion.skill_registry.get_skill",
        lambda _name: SkillMetadata(
            "domain-novelty-check", "Novelty", "research", "", "",
            output_files=["ideas/novelty_report.md", "ideas/SELECTED_IDEA.json"],
        ),
    )
    monkeypatch.setattr(
        "server.workflows.node_execution_completion.agent_engine._persist_session_transcript",
        lambda _session: None,
    )
    return context


def _write_valid_outputs(root: Path) -> None:
    ideas = root / "ideas"
    ideas.mkdir(exist_ok=True)
    (ideas / "novelty_report.md").write_text(
        "# Montage-conditioned EEG transfer\nNearest work and surviving delta are documented.\n",
        encoding="utf-8",
    )
    payload = {
        "schema": 2, "status": "accepted", "title": "Montage-conditioned EEG transfer",
        "problem_statement": "Montage changes confound representation transfer.",
        "hypothesis": "Conditioning improves held-out EEG transfer under matched budgets.",
        "claims": [{"id": "C1", "statement": "Conditioning improves transfer.",
                    "publication_statement": "Conditioning improves transfer."}],
        "mechanisms": [{"id": "M1", "name": "Coordinate conditioning",
                        "description": "Condition tokens on electrode coordinates.",
                        "publication_name": "Coordinate conditioning",
                        "publication_description": "Conditions tokens on electrode coordinates.",
                        "publication_evaluation": "Matched conditioning removal."}],
        "falsification_conditions": ["No held-out gain under matched budgets."],
        "publication": {"language": "en", "title": "Montage-conditioned EEG transfer",
                        "method_name": "Montage-conditioned encoder",
                        "contribution_type": "model_architecture",
                        "comparator_names": ["Fixed-montage encoder"]},
    }
    (ideas / "SELECTED_IDEA.json").write_text(json.dumps(payload), encoding="utf-8")


@pytest.mark.asyncio
async def test_test102_announcement_continues_same_session_until_outputs_are_saved(tmp_path, monkeypatch):
    context = _context(tmp_path, monkeypatch)
    calls = []

    async def continue_session(ctx, *, user_message, allow_text_fallback):
        calls.append((ctx.session.id, ctx.session.max_iterations, user_message))
        assert ctx.session.iterations == 4
        assert allow_text_fallback is False
        _write_valid_outputs(tmp_path)
        ctx.session.iterations += 2
        return "Report and frozen contract saved."

    monkeypatch.setattr("server.workflows.node_execution_completion.run_primary_session", continue_session)
    await ensure_primary_output_delivery(context)
    assert len(calls) == 1 and calls[0][:2] == ("same-transcript", 12)
    assert "SELECTED_IDEA.json" in calls[0][2]
    assert context.session.max_iterations == 50 and context.session.iterations == 6
    assert context.completion_mode == "artifact_completion_continuation"
    assert inspect_primary_outputs(context).issues == ()


@pytest.mark.asyncio
async def test_valid_delivery_makes_no_extra_model_call(tmp_path, monkeypatch):
    context = _context(tmp_path, monkeypatch)
    _write_valid_outputs(tmp_path)

    async def unexpected(*_args, **_kwargs):
        raise AssertionError("completed files must not be regenerated")

    monkeypatch.setattr("server.workflows.node_execution_completion.run_primary_session", unexpected)
    await ensure_primary_output_delivery(context)
    assert context.completion_mode == "normal"
    assert context.host.events == []


def test_changed_report_does_not_hide_empty_selected_contract(tmp_path, monkeypatch):
    context = _context(tmp_path, monkeypatch)
    _write_valid_outputs(tmp_path)
    selected = tmp_path / "ideas/SELECTED_IDEA.json"
    selected.write_text(json.dumps({"schema": 2, "status": "unresolved", "title": "",
                                   "claims": [], "mechanisms": []}), encoding="utf-8")
    assert any("SELECTED_IDEA.json" in issue for issue in inspect_primary_outputs(context).issues)


@pytest.mark.asyncio
async def test_unwritten_delivery_stops_after_one_continuation_and_is_not_completed(tmp_path, monkeypatch):
    context = _context(tmp_path, monkeypatch)
    calls = 0
    records = []

    async def still_unwritten(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return "I will write the outputs."

    monkeypatch.setattr("server.workflows.node_execution_completion.run_primary_session", still_unwritten)
    monkeypatch.setattr("server.workflows.node_execution_phases.skill_orchestrator.mark_execution",
                        lambda *_args, **kwargs: records.append((_args, kwargs)))
    with pytest.raises(RuntimeError, match="PRIMARY_OUTPUT_INCOMPLETE"):
        await ensure_primary_output_delivery(context)
    await finalize_primary(context)
    assert calls == 1 and context.completion_mode == "artifact_incomplete"
    assert records[-1][0][4] == "incomplete"
    assert context.host.delegate_calls == 0
    assert "skill_invocation_incomplete" in [name for name, _data in context.host.events]
    assert "skill_invocation_completed" not in [name for name, _data in context.host.events]


@pytest.mark.asyncio
async def test_exhausted_budget_does_not_grant_extra_iterations(tmp_path, monkeypatch):
    context = _context(tmp_path, monkeypatch)
    context.session.iterations = 50
    with pytest.raises(RuntimeError, match="PRIMARY_OUTPUT_INCOMPLETE"):
        await ensure_primary_output_delivery(context)
    assert context.session.iterations == 50 and context.session.max_iterations == 50
    assert context.completion_mode == "artifact_incomplete"
    assert [name for name, _data in context.host.events] == ["node_primary_output_incomplete"]


@pytest.mark.asyncio
async def test_cancellation_restores_original_budget_and_propagates(tmp_path, monkeypatch):
    context = _context(tmp_path, monkeypatch)

    async def cancelled(*_args, **_kwargs):
        raise asyncio.CancelledError

    monkeypatch.setattr("server.workflows.node_execution_completion.run_primary_session", cancelled)
    with pytest.raises(asyncio.CancelledError):
        await ensure_primary_output_delivery(context)
    assert context.session.max_iterations == 50


@pytest.mark.parametrize("mode", ["artifact_persisted_before_timeout", "artifact_incomplete"])
@pytest.mark.asyncio
async def test_existing_recovery_mode_does_not_trigger_a_fresh_completion(tmp_path, monkeypatch, mode):
    context = _context(tmp_path, monkeypatch)
    context.completion_mode = mode
    await ensure_primary_output_delivery(context)
    assert context.host.events == []


def test_exp_design_delivery_does_not_require_later_runtime_outputs(tmp_path, monkeypatch):
    context = _context(tmp_path, monkeypatch)
    context.node.id = "exp-design"
    monkeypatch.setattr(
        "server.workflows.node_execution_completion.skill_registry.get_skill",
        lambda _name: SkillMetadata("domain-experiment-plan", "", "", "", "", output_files=[
            "experiments/EXPERIMENT_PLAN.md", "experiments/METHOD_CONTRACT.json",
            "experiments/RUN_SPEC.json", "experiments/IMPLEMENTATION_BLUEPRINT.json",
        ]),
    )
    paths = {path.relative_to(tmp_path).as_posix() for path in primary_output_paths(context)}
    assert paths == {"experiments/EXPERIMENT_PLAN.md", "experiments/METHOD_CONTRACT.json",
                     "experiments/RUN_SPEC.json", "experiments/IMPLEMENTATION_BLUEPRINT.json"}


@pytest.mark.asyncio
async def test_declared_valid_inputs_are_reused_without_writes(tmp_path, monkeypatch):
    context = _context(tmp_path, monkeypatch)
    _write_valid_outputs(tmp_path)
    context.node.artifact_baseline = context.host._snapshot_node_artifacts(context.node, context.run)
    context.run.input_baseline = workflow_input_service.capture(
        tmp_path, ["ideas/novelty_report.md", "ideas/SELECTED_IDEA.json"],
        run_id=context.run.id,
    )
    before = {path: path.read_bytes() for path in primary_output_paths(context)}
    await ensure_primary_output_delivery(context)
    assert context.completion_mode == "normal" and context.host.events == []
    assert all(path.read_bytes() == content for path, content in before.items())


@pytest.mark.asyncio
async def test_continuation_cannot_reset_remaining_tool_or_iteration_budgets(tmp_path, monkeypatch):
    context = _context(tmp_path, monkeypatch)
    context.session.iterations = 48
    context.session.tool_call_counts = {"Write": 3}
    context.session.tool_call_limits = {"Write": 3}

    async def bounded(ctx, **_kwargs):
        assert ctx.session.max_iterations == 50
        assert ctx.session.tool_call_counts == {"Write": 3}
        assert ctx.session.tool_call_limits == {"Write": 3}
        ctx.session.iterations = 50
        return "Budget exhausted; outputs not saved."

    monkeypatch.setattr("server.workflows.node_execution_completion.run_primary_session", bounded)
    with pytest.raises(RuntimeError, match="PRIMARY_OUTPUT_INCOMPLETE"):
        await ensure_primary_output_delivery(context)
    assert context.completion_mode == "artifact_incomplete"
    assert context.session.max_iterations == 50 and context.session.iterations == 50


def test_bad_selected_schema_is_delivery_failure_instead_of_parser_exception(tmp_path, monkeypatch):
    context = _context(tmp_path, monkeypatch)
    _write_valid_outputs(tmp_path)
    selected = tmp_path / "ideas/SELECTED_IDEA.json"
    payload = json.loads(selected.read_text(encoding="utf-8"))
    payload["schema"] = "not-a-version"
    selected.write_text(json.dumps(payload), encoding="utf-8")
    assert any("unsupported schema" in issue for issue in inspect_primary_outputs(context).issues)


@pytest.mark.asyncio
async def test_unsupported_saved_schema_is_not_automatically_migrated(tmp_path, monkeypatch):
    context = _context(tmp_path, monkeypatch)
    _write_valid_outputs(tmp_path)
    selected = tmp_path / "ideas/SELECTED_IDEA.json"
    payload = json.loads(selected.read_text(encoding="utf-8"))
    payload["schema"] = 1
    selected.write_text(json.dumps(payload), encoding="utf-8")
    before = selected.read_bytes()

    async def unexpected(*_args, **_kwargs):
        raise AssertionError("legacy schema must remain unchanged")

    monkeypatch.setattr("server.workflows.node_execution_completion.run_primary_session", unexpected)
    with pytest.raises(RuntimeError, match="PRIMARY_OUTPUT_INCOMPLETE"):
        await ensure_primary_output_delivery(context)
    assert context.completion_mode == "artifact_incomplete"
    assert selected.read_bytes() == before


@pytest.mark.asyncio
async def test_primary_completion_is_enforced_before_completed_trace(tmp_path, monkeypatch):
    fixture = _context(tmp_path, monkeypatch)
    records = []
    calls = []

    async def prepare(ctx):
        for field in ("project_path", "skill_plan", "session", "owner_skill_prompt",
                      "observer", "source_tool_contract", "search_tool_trace",
                      "enabled_tools", "flush_agent_text"):
            setattr(ctx, field, getattr(fixture, field))

    async def no_operation(_ctx):
        return None

    async def fake_model(ctx, **kwargs):
        calls.append(ctx.session.id)
        if "user_message" in kwargs:
            _write_valid_outputs(tmp_path)
            return "Written and checked."
        return "Now writing the outputs."

    monkeypatch.setattr("server.workflows.node_execution_coordinator.prepare_skill", prepare)
    for function in ("apply_runtime_options", "apply_research_options", "append_project_contract",
                     "run_figure_asset_delegates", "open_primary_session", "prepare_primary_message",
                     "configure_reviewer_session", "attach_observer", "resolve_tools"):
        monkeypatch.setattr(f"server.workflows.node_execution_coordinator.{function}", no_operation)
    monkeypatch.setattr("server.workflows.node_execution_coordinator.run_primary_session", fake_model)
    monkeypatch.setattr("server.workflows.node_execution_completion.run_primary_session", fake_model)
    monkeypatch.setattr("server.workflows.node_execution_phases.skill_orchestrator.mark_execution",
                        lambda *_args, **kwargs: records.append((_args, kwargs)))
    result = await execute_node(fixture.host, fixture.node, fixture.run, "EEG", "balanced", "draft")
    assert result == "Written and checked."
    assert calls == ["same-transcript", "same-transcript"]
    assert records[-1][0][4] == "completed"
    assert records[-1][1]["completion_mode"] == "artifact_completion_continuation"
    names = [name for name, _data in fixture.host.events]
    assert names.index("node_primary_output_completion_finished") < names.index("skill_invocation_completed")
