"""Bounded matrix expansion and no-run correctness policy; never start job workers."""
import copy
import json
from types import SimpleNamespace

import pytest

from server.services.execution_matrix import compile_execution_cells, cell_output_spec, matrix_coverage_issues
from server.services.experiment_models import Experiment, JobStatus
from server.services.experiment_runner import ExperimentScheduler
from server.services.training_review_policy import current_review_findings, review_blocks
from server.services.risk_training_review import training_check_findings
from server.workflows.training_check_result import parse_training_check_result


def matrix_spec():
    return {"schema": 1, "seeds": [13, 42, 73, 101, 211],
        "command": "python train.py --condition {condition} --axis {axis} --seed {seed} --output {output_dir}",
        "scheduled_runs": {"schema": 1, "owner": "scheduler", "conditions": [f"c{i}" for i in range(6)],
                           "holdout_axes": ["subject", "site", "montage"]},
        "outputs": {"per_run_files": ["{output_dir}/predictions.json", "{output_dir}/metrics.json"]}}


@pytest.mark.asyncio
async def test_ninety_cells_are_scheduled_with_distinct_commands_outputs_and_exact_coverage(tmp_path):
    spec = matrix_spec()
    execution_id = "matrix-fixture"
    cells = compile_execution_cells(spec, execution_id=execution_id)
    assert len(cells) == 90
    (tmp_path / "experiments").mkdir()
    (tmp_path / "experiments/RUN_SPEC.json").write_text(json.dumps(spec))
    experiment = Experiment(id=execution_id, project_path=str(tmp_path), seeds=spec["seeds"], command_template=spec["command"],
                            execution_cells=cells, work_dir=str(tmp_path))
    scheduler = ExperimentScheduler()  # Never start its worker.
    await scheduler.submit_experiment(experiment)
    assert len(experiment.jobs) == len({job.command for job in experiment.jobs}) == 90
    assert len({job.log_path for job in experiment.jobs}) == 90
    paths = [cell_output_spec(spec, cell)["outputs"]["per_run_files"][0] for cell in cells]
    assert len(set(paths)) == 90
    for job in experiment.jobs:
        job.status = JobStatus.COMPLETED
    assert matrix_coverage_issues(spec, experiment.jobs, execution_id=execution_id) == []
    assert matrix_coverage_issues(spec, experiment.jobs[:-1], execution_id=execution_id)
    assert matrix_coverage_issues(spec, [*experiment.jobs, experiment.jobs[0]], execution_id=execution_id)
    from server.services.execution_cell_binding import resolve_cell_spec, persisted_matrix_issues
    refs = [tmp_path / ".merak/experiments" / job.id / "run.json" for job in experiment.jobs]
    assert persisted_matrix_issues(spec, execution_id, refs) == []
    assert persisted_matrix_issues(spec, execution_id, refs[:-1])
    assert resolve_cell_spec(tmp_path, spec, refs[0])["outputs"]["per_run_files"][0] == paths[0]
    receipt_path = refs[0].with_name("CELL_BINDING.json")
    receipt = json.loads(receipt_path.read_text())
    receipt["cell"]["seed"] = 999
    receipt_path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="coordinates"):
        resolve_cell_spec(tmp_path, spec, refs[0])


@pytest.mark.parametrize("defect", ["owner", "seed", "axis", "output", "escape", "duplicate"])
def test_incomplete_or_unsafe_matrix_is_rejected_before_scheduling(defect):
    spec = matrix_spec()
    if defect == "owner": spec["scheduled_runs"].pop("owner")
    elif defect in {"seed", "axis"}: spec["command"] = spec["command"].replace("{" + defect + "}", "fixed")
    elif defect == "output": spec["outputs"]["per_run_files"] = ["shared.json"]
    elif defect == "escape": spec["outputs"]["per_run_files"] = ["{output_dir}/../../../shared.json"]
    else: spec["scheduled_runs"]["conditions"].append("c0")
    before = copy.deepcopy(spec)
    with pytest.raises(ValueError): compile_execution_cells(spec)
    assert spec == before


def test_multiple_seeds_without_matrix_or_binding_cannot_silently_reduce():
    with pytest.raises(ValueError, match="Multiple registered seeds"):
        compile_execution_cells({"seeds": [13, 42], "command": "python train.py"})


def test_fresh_executions_never_overwrite_same_scientific_cells():
    spec = matrix_spec()
    first = compile_execution_cells(spec, execution_id="first")
    second = compile_execution_cells(spec, execution_id="second")
    assert {cell["cell_id"] for cell in first} == {cell["cell_id"] for cell in second}
    assert {cell["output_dir"] for cell in first}.isdisjoint(cell["output_dir"] for cell in second)
    assert first == compile_execution_cells(spec, execution_id="first")


def test_readonly_review_preserves_implementation_blockers_in_no_run_mode():
    findings = [{"id": "missing-data", "severity": "blocker", "scope": "execution_prerequisite",
                 "category": "data_availability", "message": "Manifest not supplied"},
                {"id": "bad-labels", "severity": "blocker", "scope": "implementation_correctness",
                 "category": "implementation", "message": "String labels reach numeric metric"}]
    assessment = parse_training_check_result(json.dumps({"verdict": "FAIL", "summary": "review", "findings": findings}),
                                             assurance="draft", target_resolver=lambda *a: ["experiments/src/data.py"])
    opts = {"run_experiment": False, "_training_check": assessment}
    assert review_blocks(assessment, opts)
    assert [item["id"] for item in current_review_findings(assessment, opts)] == ["bad-labels"]
    assert [item["id"] for item in training_check_findings(opts)] == ["bad-labels"]
    assessment["findings"] = findings[:1]
    assert not review_blocks(assessment, opts)
    assert review_blocks(assessment, {"run_experiment": True})


def test_wrong_scope_cannot_reclassify_code_defect_as_execution_prerequisite():
    assessment = {"blocking": True, "verdict": "FAIL", "findings": [{
        "id": "label-contract", "severity": "blocker", "category": "implementation",
        "scope": "execution_prerequisite", "message": "Labels never converted to numeric types"}]}
    assert review_blocks(assessment, {"run_experiment": False})


@pytest.mark.asyncio
async def test_resumed_execution_rechecks_review_instead_of_erasing_failed_assessment(monkeypatch):
    from server.workflows import run_execution_node as runtime
    from unittest.mock import AsyncMock
    ctx = SimpleNamespace(upstream_preflight=[], code_review_enabled=True,
                          revalidate_done=True, node=SimpleNamespace(id="exp-run"))
    review, integrity, persist = AsyncMock(), AsyncMock(), AsyncMock()
    monkeypatch.setattr(runtime, "invoke_code_review", review)
    monkeypatch.setattr(runtime, "merge_code_integrity", integrity)
    monkeypatch.setattr(runtime, "persist_code_review", persist)
    await runtime.run_code_review(ctx)
    review.assert_awaited_once_with(ctx)
    integrity.assert_awaited_once_with(ctx)
    persist.assert_awaited_once_with(ctx)
