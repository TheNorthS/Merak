"""Explicit nested-package target declarations retain every real stage validator."""

from copy import deepcopy
import json
import os
from pathlib import Path

import pytest

from server.services.impl_stage_targets import project_stages, target_declaration
from server.services.experiment_implementation_build import experiment_implementation_build_service as service
from server.services.implementation_stages import ML_STAGES
from server.tests.test_experiment_implementation_build import _seed_contracts, _write_complete_pipeline
from server.workflows.implementation_execution_contracts import ImplementationContext
from server.workflows.implementation_reconciliation import capture_protected_inputs, prepare_stage, reconcile_attempt
from server.workflows.models import WorkflowNode, WorkflowRun


def _save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _mapping():
    return {"data": ["experiments/src/package/data.py", "experiments/src/package/data_contract.py"],
            "method": ["experiments/src/package/models.py", "experiments/src/package/objectives.py"],
            "training": ["experiments/src/package/train.py"],
            "evaluation": ["experiments/src/package/metrics.py", "experiments/src/package/evaluation.py", "experiments/src/package/provenance.py"],
            "integration": ["experiments/src/package/test_pipeline.py", "experiments/IMPLEMENTATION_EVIDENCE_PATCH.json",
                            "experiments/RUN_SPEC.json", "experiments/configs/main.yaml"]}


def _nested_project(root):
    _seed_contracts(root)
    _write_complete_pipeline(root)
    src = root / "experiments/src"
    nested = src / "package"
    nested.mkdir()
    for path in list(src.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for name in ("data", "evaluation", "models", "objectives", "provenance"):
            text = text.replace("from " + name + " import", "from ." + name + " import")
        (nested / path.name).write_text(text, encoding="utf-8")
        path.unlink()
    for name in ("METHOD_CONTRACT.json", "IMPLEMENTATION_EVIDENCE_PATCH.json"):
        path = root / "experiments" / name
        value = json.loads(path.read_text(encoding="utf-8"))
        value = json.loads(json.dumps(value).replace("experiments/src/models.py", "experiments/src/package/models.py"))
        _save(path, value)
    path = root / "experiments/RUN_SPEC.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value.update(entrypoint="experiments/src/package/train.py", command="python experiments/src/package/train.py",
                 implementation_stage_targets=_mapping())
    _save(path, value)
    return value


def test_absent_declaration_preserves_default_paths_and_no_artifacts_are_created(tmp_path):
    assert project_stages(tmp_path, "machine_learning") == ML_STAGES
    assert list(tmp_path.rglob("*")) == []


def test_declared_package_paths_thread_blueprint_real_validators_hashes_audit_and_prompt(tmp_path):
    _nested_project(tmp_path)
    declared = target_declaration(tmp_path)
    blueprint = service.ensure_blueprint(tmp_path, "classification research")
    assert blueprint["entrypoint"] == "experiments/src/package/train.py"
    assert {row["id"]: row["targets"] for row in blueprint["stages"]} == declared
    assert [(row.id, row.title, row.purpose) for row in service.stages(tmp_path)] == [(row.id, row.title, row.purpose) for row in ML_STAGES]
    for stage in service.stages(tmp_path):
        report = service.validate_stage(tmp_path, stage.id)
        assert report["passed"], report["issues"]
        assert report["targets"] == declared[stage.id] and set(report["existing_targets"]) == set(declared[stage.id])
    assert not service.build_path(tmp_path).exists()
    missing_build = service.audit(tmp_path)
    assert missing_build["blocking"] and any("acceptance record is missing" in issue for issue in missing_build["issues"])
    assert service.revalidate_existing_build(tmp_path)["complete"] is False
    for stage in service.stages(tmp_path):
        service.record_stage(tmp_path, stage.id, service.validate_stage(tmp_path, stage.id), attempts=1,
                             session_summaries=["Fixture actual model-owned stage attempt"])
    assert service.audit(tmp_path)["blocking"] is False
    assert all(service.can_reuse(tmp_path, stage.id) for stage in service.stages(tmp_path))
    prompt = service.stage_prompt(tmp_path, "method", "classification research")
    assert "experiments/src/package/models.py" in prompt and "experiments/src/models.py" not in prompt
    before = service.output_hash(tmp_path, "data")
    (tmp_path / "experiments/src/package/data.py").write_text("Changed split-safe source.\n")
    assert service.output_hash(tmp_path, "data") != before and not service.can_reuse(tmp_path, "data")
    assert not (tmp_path / "experiments/src/models.py").exists()


def test_existing_blueprint_target_metadata_changes_do_not_fake_accept_new_source_inventory(tmp_path):
    _seed_contracts(tmp_path)
    _write_complete_pipeline(tmp_path)
    old = service.ensure_blueprint(tmp_path)
    assert old["stages"][0]["targets"] == list(ML_STAGES[0].targets)
    path = tmp_path / "experiments/RUN_SPEC.json"
    value = json.loads(path.read_text())
    value["implementation_stage_targets"] = _mapping()
    value["entrypoint"] = "experiments/src/package/train.py"
    _save(path, value)
    new = service.ensure_blueprint(tmp_path)
    assert new["stages"][0]["targets"] == _mapping()["data"]
    report = service.validate_stage(tmp_path, "data")
    assert not report["passed"] and any("missing or empty" in issue for issue in report["issues"])
    assert not service.build_path(tmp_path).exists()


@pytest.mark.parametrize("invalid", ["/outside.py", "D:/outside.py", "experiments/src/../outside.py",
    "./experiments/src/a.py", "experiments\\src\\a.py", "experiments/src//a.py", "experiments/src/a.py ",
    "experiments/METHOD_CONTRACT.json", "experiments/results/analysis.md", "paper/main.tex", "experiments/src/a.txt"])
def test_declared_stage_paths_reject_foreign_retired_alias_or_runtime_owned_targets(tmp_path, invalid):
    mapping = _mapping()
    mapping["data"][0] = invalid
    _save(tmp_path / "experiments/RUN_SPEC.json", {"implementation_stage_targets": mapping})
    with pytest.raises(ValueError):
        project_stages(tmp_path, "machine_learning")
    assert not service.blueprint_path(tmp_path).exists()


@pytest.mark.parametrize("defect", ["missing_stage", "extra_stage", "empty_stage", "duplicate", "cross_stage", "wrong_config_scope", "no_config", "no_patch"])
def test_complete_mapping_and_unique_ownership_are_required(tmp_path, defect):
    mapping = _mapping()
    if defect == "missing_stage":
        mapping.pop("data")
    elif defect == "extra_stage":
        mapping["foreign"] = ["experiments/src/foreign.py"]
    elif defect == "empty_stage":
        mapping["data"] = []
    elif defect == "duplicate":
        mapping["data"].append(mapping["data"][0])
    elif defect == "cross_stage":
        mapping["method"].append(mapping["data"][0])
    elif defect == "wrong_config_scope":
        mapping["data"].append("experiments/configs/other.yaml")
    elif defect == "no_config":
        mapping["integration"].remove("experiments/configs/main.yaml")
    else:
        mapping["integration"].remove("experiments/IMPLEMENTATION_EVIDENCE_PATCH.json")
    _save(tmp_path / "experiments/RUN_SPEC.json", {"implementation_stage_targets": mapping})
    with pytest.raises(ValueError):
        project_stages(tmp_path, "machine_learning")


def test_existing_hardlinked_target_is_rejected_before_any_stage_or_blueprint_write(tmp_path):
    mapping = _mapping()
    owned = tmp_path / mapping["data"][0]
    owned.parent.mkdir(parents=True)
    other = tmp_path / "retained.py"
    other.write_text("retained = True\n")
    os.link(other, owned)
    _save(tmp_path / "experiments/RUN_SPEC.json", {"implementation_stage_targets": mapping})
    with pytest.raises(ValueError, match="linked"):
        project_stages(tmp_path, "machine_learning")
    assert other.read_text() == "retained = True\n" and not service.blueprint_path(tmp_path).exists()


def test_integration_cannot_change_runtime_target_ownership_even_when_run_spec_is_a_write_target(tmp_path):
    _nested_project(tmp_path)
    run = WorkflowRun(id="mapping-guard", project_path=str(tmp_path))
    stages = service.stages(tmp_path)
    context = ImplementationContext(object(), run, "", WorkflowNode("exp-design", "Design", "/experiment-plan"), stages, service)
    state = prepare_stage(context, stages[-1])
    before = capture_protected_inputs(context, state)
    spec = tmp_path / "experiments/RUN_SPEC.json"
    changed = json.loads(spec.read_text())
    changed["implementation_stage_targets"]["data"] = ["experiments/src/package/foreign.py"]
    _save(spec, changed)
    report = reconcile_attempt(context, state, before)
    assert not report["passed"] and any("runtime-owned" in issue for issue in report["issues"])


def test_broad_integration_finding_expands_only_declared_current_package_source_targets(tmp_path, monkeypatch):
    _nested_project(tmp_path)
    from server.services.experiment_implementation import experiment_implementation_service

    monkeypatch.setattr(experiment_implementation_service, "audit", lambda *_a, **_k: {"findings": [
        {"severity": "blocker", "message": "Current integration flow missing", "target_files": ["experiments/src"]}]})
    report = service.validate_stage(tmp_path, "integration")
    expected = {path for targets in _mapping().values() for path in targets if path.startswith("experiments/src/")}
    assert not report["passed"] and set(report["repair_targets"]) == expected
    assert "experiments/src/models.py" not in report["repair_targets"]


@pytest.mark.asyncio
async def test_real_coordinator_uses_declared_package_stages_and_requires_fresh_actual_attempts_not_old_build(tmp_path, monkeypatch):
    from server.workflows.staged_implementation_coordinator import StagedImplementationCoordinator
    from server.workflows.implementation_model_invocation import StageModelInvocation

    _nested_project(tmp_path)
    before = {path: path.read_bytes() for path in (tmp_path / "experiments/src").rglob("*.py")}
    stages = service.stages(tmp_path, "classification research")
    assert not service.build_path(tmp_path).exists()
    calls, events = [], []

    class Host:
        async def _emit(self, _run, event, payload):
            events.append((event, payload))

    async def review(invocation):
        assert invocation.state.effective_targets == list(invocation.state.stage.targets)
        calls.append(invocation.state.stage.id)
        # Only a fixture actual model attempt is substituted; real semantic
        # validation, reconciliation and record creation execute normally.
        return "Current declared source reviewed without altering valid code."

    monkeypatch.setattr(StageModelInvocation, "run", review)
    run = WorkflowRun(id="declared-current-run", project_path=str(tmp_path),
                      nodes=[WorkflowNode("exp-design", "Design", "/experiment-plan")])
    report = await StagedImplementationCoordinator(Host(), run, "classification research").execute()
    assert not report["blocking"], report["issues"]
    assert calls == [stage.id for stage in stages]
    assert all(service.load_build(tmp_path)["stages"][stage.id]["attempts"] == 1 for stage in stages)
    assert all(service.load_build(tmp_path)["stages"][stage.id]["targets"] == list(stage.targets) for stage in stages)
    assert {path: path.read_bytes() for path in before} == before
    assert any(event == "implementation_stage_accepted" for event, _payload in events)


def test_stage_target_declaration_changes_invalidate_current_hashes_without_changing_other_stage_semantics(tmp_path):
    _nested_project(tmp_path)
    service.ensure_blueprint(tmp_path)
    first = service.output_hash(tmp_path, "data")
    later_input = service.input_hash(tmp_path, "training")
    spec = tmp_path / "experiments/RUN_SPEC.json"
    value = json.loads(spec.read_text())
    value["implementation_stage_targets"]["data"].append("experiments/src/package/additional_contract.py")
    _save(spec, value)
    assert service.output_hash(tmp_path, "data") != first
    assert service.input_hash(tmp_path, "training") != later_input
    assert not service.validate_stage(tmp_path, "data")["passed"]


def test_fresh_valid_declared_stage_prompt_reviews_without_needless_code_edits_only_after_real_validator(tmp_path):
    _nested_project(tmp_path)
    assert service.validate_stage(tmp_path, "data")["passed"]
    before = {path: path.read_bytes() for path in (tmp_path / "experiments/src").rglob("*.py")}
    prompt = service.stage_prompt(tmp_path, "data", "classification research")
    assert "Fresh deterministic validation has passed every current canonical stage target" in prompt
    assert "do not rewrite correct source merely to produce byte changes" in prompt
    assert {path: path.read_bytes() for path in before} == before and not service.build_path(tmp_path).exists()
    (tmp_path / "experiments/src/package/data_contract.py").unlink()
    assert not service.validate_stage(tmp_path, "data")["passed"]
    invalid = service.stage_prompt(tmp_path, "data", "classification research")
    assert "Implement or repair the listed missing/invalid targets" in invalid
    assert "Fresh deterministic validation has passed every current canonical stage target" not in invalid
