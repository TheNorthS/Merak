"""Real source declarations cross the design/figure boundary without scientific rewriting."""
import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from server.contracts.preparation import PreparationContractError
from server.services.evaluation_protocol_validation import evaluation_contract_findings
from server.services.evaluation_protocol_projection import project_evaluation_protocol
from server.services.evaluation_design_content import evaluation_content
from server.workflows import run_execution_coordinator as coordinator
from server.tests._workflow_revision_loop_support import WorkflowEngine, WorkflowNode, WorkflowRun, _accepted, _start_run_state


def config_fixture():
    return {"data": {"active_holdout_axis": "subject", "split_manifests": {"subject": "s.json", "site": "d.json"}},
            "evaluation": {"protocol_schema": 1, "holdout_axes": ["subject", "site"],
                           "primary_split": "Registered two-axis audit", "primary_metric": "balanced_accuracy",
                           "analysis_unit": "participant", "analysis_unit_key": "participant_id"}}


def test_config_metric_and_scientific_scope_survive_active_axis_selection():
    config = config_fixture()
    before = copy.deepcopy(config)
    projected = project_evaluation_protocol({}, config)
    assert projected["primary_split"] == "Registered two-axis audit"
    assert projected["primary_metric_publication"] == "Balanced accuracy"
    assert projected["active_holdout_axis"] == "subject"
    assert len(projected["declared_splits"]) == 2
    content = evaluation_content({"method_brief": {"evaluation_protocol": projected,
        "publication": {"method_name": "Focal"}, "evaluation_contract": {
            "primary_comparator": "Control", "comparators_or_controls": ["Control"]}}})
    assert content.primary_split == projected["primary_split"]
    assert config == before


def test_no_primary_scope_is_inferred_from_one_active_axis_of_many():
    config = config_fixture()
    del config["evaluation"]["primary_split"]
    assert "primary_split" not in project_evaluation_protocol({}, config)


def test_dictionary_axes_fail_at_design_owner_before_rendering(tmp_path):
    config = config_fixture()
    config["evaluation"]["holdout_axes"] = {axis: {"unit": "participant"} for axis in ["subject", "site"]}
    path = tmp_path / "experiments/configs/main.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(config))
    before = path.read_bytes()
    findings = evaluation_contract_findings(tmp_path)
    assert len(findings) == 1 and findings[0]["owner_node"] == "exp-design"
    assert "experiments/configs/main.yaml" in findings[0]["target_files"]
    assert path.read_bytes() == before
    from server.contracts.writers import versioned_artifact_write_error
    assert "holdout_axes" in versioned_artifact_write_error(tmp_path, path, before.decode())
    assert versioned_artifact_write_error(tmp_path, path, json.dumps(config_fixture())) == ""


@pytest.mark.asyncio
async def test_prepare_failure_enters_real_revision_owner_loop(tmp_path, monkeypatch):
    engine = WorkflowEngine()
    design = WorkflowNode("exp-design", "Design", "/experiment-plan")
    figure = WorkflowNode("figure", "Figure", "/paper-figure")
    run = WorkflowRun(id="protocol-loop", project_path=str(tmp_path), nodes=[design, figure], status="running")
    _start_run_state(tmp_path, run.id, run.nodes)
    config = config_fixture()
    config["evaluation"]["holdout_axes"] = {"subject": {}, "site": {}}
    path = tmp_path / "experiments/configs/main.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(config))
    revised = []
    async def prepare(_node, _run, result, *_args, **_kwargs):
        return result
    async def repair(**kwargs):
        revised.append(kwargs["node"].id)
        path.write_text(json.dumps(config_fixture()))
        return "producer repaired"
    monkeypatch.setattr(engine, "_prepare_node_for_gate", prepare)
    monkeypatch.setattr(engine, "_acceptance_gate", lambda *a, **k: _accepted())
    monkeypatch.setattr(engine, "_revise_node_from_gate", repair)
    monkeypatch.setattr(engine, "_changed_nonempty_node_artifacts", lambda *a: False)
    monkeypatch.setattr(engine, "_emit", AsyncMock())
    gate, _ = await engine._run_node_revision_loop(node=figure, run=run, initial_result="preparation failed",
        research_direction="fixture", effort="balanced", assurance="draft", opts={}, require_fresh=False,
        checkpoint_timeout=30, max_revision_rounds=2)
    assert gate["accepted"] and revised == ["exp-design"]
    assert project_evaluation_protocol({}, json.loads(path.read_text()))["primary_split"] == "Registered two-axis audit"


@pytest.mark.asyncio
async def test_first_primary_preparation_failure_does_not_skip_acceptance_loop(monkeypatch):
    events = []
    context = SimpleNamespace(node=SimpleNamespace(id="figure"), run=SimpleNamespace(id="fixture"), resume_stage="",
                              host=SimpleNamespace(_emit=AsyncMock()), run_state=SimpleNamespace(load=lambda: {}))
    for name in ["prepare_node", "load_resume_state", "consume_checkpoint", "prepare_revalidation",
                 "initialize_preflight", "load_node_preflight", "prepare_node_inputs", "run_code_review",
                 "persist_node_acceptance", "refresh_node_audits", "emit_node_acceptance"]:
        monkeypatch.setattr(coordinator, name, AsyncMock())
    monkeypatch.setattr("server.workflows.interruption_checkpoint.mark_boundary", lambda *args, **kwargs: None)
    monkeypatch.setattr(coordinator, "run_primary_execution", AsyncMock(side_effect=PreparationContractError("bad axes")))
    async def acceptance(ctx):
        events.append(ctx.upstream_preflight[0]["owner_node"])
    monkeypatch.setattr(coordinator, "run_acceptance_loop", acceptance)
    failure = AsyncMock()
    monkeypatch.setattr(coordinator, "handle_node_error", failure)
    await coordinator._execute_one_node(context)
    assert events == ["exp-design"]
    failure.assert_not_called()
