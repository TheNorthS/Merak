"""Real-shape static recovery: guarded imports, nested run seeds, finalization."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.services.experiment_implementation import experiment_implementation_service
from server.services.experiment_implementation_build import experiment_implementation_build_service as service
from server.services.method_contract import method_contract_service
from server.tests.test_experiment_implementation_build import _seed_contracts, _write_complete_pipeline
from server.workflows.models import WorkflowNode, WorkflowRun
from server.workflows.staged_implementation_coordinator import StagedImplementationCoordinator


DIRECTION = "classification research"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _save(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def real_shape(root: Path) -> WorkflowRun:
    _seed_contracts(root)
    _write_complete_pipeline(root)
    train = root / "experiments/src/train.py"
    source = train.read_text(encoding="utf-8")
    imports, body = source.split("\n\ndef train():", 1)
    guarded = "try:\n" + "\n".join("    " + line for line in imports.splitlines())
    relative = "\n".join("    " + line.replace("from ", "from .", 1) for line in imports.splitlines())
    train.write_text(guarded + "\nexcept ImportError:\n" + relative + "\n\ndef train():" + body, encoding="utf-8")
    spec_path = root / "experiments/RUN_SPEC.json"
    spec = _json(spec_path)
    seeds = spec.pop("repetitions")["seeds"]
    spec.update(schema=1, implementation_family="machine_learning", budgets={"seeds": seeds})
    _save(spec_path, spec)
    stages = service.stages(root, DIRECTION)
    for stage in stages[:-1]:
        report = service.validate_stage(root, stage.id, DIRECTION)
        assert report["passed"], report
        service.record_stage(root, stage.id, report, DIRECTION, attempts=1, session_summaries=["Model-owned fixture attempt"])
    method_path = root / "experiments/METHOD_CONTRACT.json"
    method = _json(method_path)
    method["status"] = "scaffold_only"
    _save(method_path, method)
    service.record_stage(root, "integration", service.validate_stage(root, "integration", DIRECTION), DIRECTION, attempts=1)
    return WorkflowRun(
        id="real-shape-recovery", project_path=str(root), status="running",
        nodes=[WorkflowNode("exp-design", "Design", "/experiment-plan")],
    )


@pytest.mark.asyncio
async def test_real_shape_recovers_without_model_and_keeps_all_stage_fingerprints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = real_shape(tmp_path)
    sources = {path: path.read_bytes() for path in (tmp_path / "experiments/src").glob("*.py")}
    events = []

    async def forbidden_model(_self):
        pytest.fail("Valid existing implementation must finalize without a model rewrite")

    class Host:
        async def _emit(self, _run, event, _payload):
            events.append(event)

    monkeypatch.setattr("server.workflows.implementation_model_invocation.StageModelInvocation.run", forbidden_model)
    report = await StagedImplementationCoordinator(Host(), run, DIRECTION).execute()
    assert not report["blocking"], report["issues"]
    assert "implementation_pipeline_revalidated" in events
    assert _json(tmp_path / "experiments/METHOD_CONTRACT.json")["status"] == "implemented"
    for stage in service.stages(tmp_path, DIRECTION):
        assert service.can_reuse(tmp_path, stage.id, DIRECTION)
        assert service.load_build(tmp_path)["stages"][stage.id]["attempts"] == 1
    assert all(path.read_bytes() == payload for path, payload in sources.items())
    before_build = service.build_path(tmp_path).read_bytes()
    before_method = (tmp_path / "experiments/METHOD_CONTRACT.json").read_bytes()
    repeated = await StagedImplementationCoordinator(Host(), run, DIRECTION).execute()
    assert not repeated["blocking"]
    assert service.build_path(tmp_path).read_bytes() == before_build
    assert (tmp_path / "experiments/METHOD_CONTRACT.json").read_bytes() == before_method


@pytest.mark.parametrize("defect", ["seeds", "mechanism_links", "owner_source_changed", "unknown_patch_mechanism"])
def test_existing_invalid_candidate_is_never_finalized(tmp_path: Path, defect: str) -> None:
    real_shape(tmp_path)
    if defect == "seeds":
        path = tmp_path / "experiments/RUN_SPEC.json"
        payload = _json(path)
        payload.pop("budgets")
        _save(path, payload)
    elif defect == "mechanism_links":
        path = tmp_path / "experiments/METHOD_CONTRACT.json"
        payload = _json(path)
        payload["mechanism_coverage"][0]["implementation_check_ids"] = []
        _save(path, payload)
    elif defect == "owner_source_changed":
        path = tmp_path / "experiments/src/models.py"
        path.write_text(path.read_text(encoding="utf-8") + "\nCHANGED_AFTER_ACCEPTANCE = True\n", encoding="utf-8")
    else:
        path = tmp_path / "experiments/IMPLEMENTATION_EVIDENCE_PATCH.json"
        payload = _json(path)
        payload["checks"][0]["idea_mechanism_ids"] = ["M999"]
        _save(path, payload)
    before = (tmp_path / "experiments/METHOD_CONTRACT.json").read_bytes()
    result = service.revalidate_existing_build(tmp_path, DIRECTION)
    assert not result["complete"] and result["issues"]
    assert (tmp_path / "experiments/METHOD_CONTRACT.json").read_bytes() == before


def test_restart_between_evidence_write_and_runtime_merge_recovers_without_new_content(tmp_path: Path) -> None:
    real_shape(tmp_path)
    method_path = tmp_path / "experiments/METHOD_CONTRACT.json"
    method = _json(method_path)
    method["implementation_checks"] = []
    method["mechanism_coverage"][0]["implementation_check_ids"] = []
    _save(method_path, method)
    patch_path = tmp_path / "experiments/IMPLEMENTATION_EVIDENCE_PATCH.json"
    patch = _json(patch_path)
    patch["checks"][0]["idea_mechanism_ids"] = ["M1"]
    _save(patch_path, patch)
    before_source = {path: path.read_bytes() for path in (tmp_path / "experiments/src").glob("*.py")}
    result = service.revalidate_existing_build(tmp_path, DIRECTION)
    assert result["complete"], result["issues"]
    assert _json(method_path)["status"] == "implemented"
    assert _json(method_path)["mechanism_coverage"][0]["implementation_check_ids"] == ["I1"]
    assert all(path.read_bytes() == data for path, data in before_source.items())


def test_a_real_missing_head_has_specific_legal_cross_stage_repair_targets(tmp_path: Path) -> None:
    real_shape(tmp_path)
    model_path = tmp_path / "experiments/src/models.py"
    model_path.write_text(
        "def accepted_mechanism(value):\n    return value\n\n"
        "class Model:\n"
        "    def forward(self, batch):\n        return accepted_mechanism(batch)\n"
        "    def parameters(self):\n        return []\n"
        "    def eval(self):\n        return self\n", encoding="utf-8",
    )
    for name in ("train.py", "objectives.py"):
        path = tmp_path / "experiments/src" / name
        path.write_text(path.read_text(encoding="utf-8").replace("logits", "representation"), encoding="utf-8")
    method = _json(tmp_path / "experiments/METHOD_CONTRACT.json")
    audit = experiment_implementation_service.audit(tmp_path, method_contract={**method, "status": "implemented"})
    head = next(item for item in audit["findings"] if item["id"] == "IMPL-INFERENCE-001")
    assert "experiments/src/models.py" in head["target_files"]
    assert "experiments/src/train.py" in head["target_files"]
    assert "experiments/src" not in head["target_files"]
    stage = service.validate_stage(tmp_path, "integration", DIRECTION)
    assert set(("experiments/src/models.py", "experiments/src/train.py")) <= set(stage["repair_targets"])
    assert "experiments/METHOD_CONTRACT.json" not in stage["repair_targets"]
    assert not service.revalidate_existing_build(tmp_path, DIRECTION)["complete"]


def test_parse_finding_targets_only_the_malformed_source_file(tmp_path: Path) -> None:
    real_shape(tmp_path)
    (tmp_path / "experiments/src/models.py").write_text("def malformed(:\n", encoding="utf-8")
    audit = experiment_implementation_service.audit(tmp_path)
    issue = next(item for item in audit["findings"] if item["id"] == "IMPL-PARSE-001")
    assert issue["target_files"] == ["experiments/src/models.py"]


def test_blocked_stage_is_primary_and_downstream_gates_are_not_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.workflows import acceptance_coordinator
    from server.workflows.engine import WorkflowEngine

    run = real_shape(tmp_path)
    report = service.audit(tmp_path, DIRECTION)
    assert report["blocking"]
    run.options["_staged_implementation_report"] = report

    def forbidden(*_args, **_kwargs):
        pytest.fail("Downstream preview/risk validation must wait for its prerequisite owner")

    monkeypatch.setattr(acceptance_coordinator, "finalize_gate", forbidden)
    gate = WorkflowEngine()._acceptance_gate(run.nodes[0], run, "draft", "blocked", require_fresh=False)
    assert not gate["accepted"]
    assert gate["reason"] == "staged experiment implementation is blocked"
    assert "experiments/EXPERIMENT_PLAN.md" not in gate["details"]["repair_scope"]["target_files"]
