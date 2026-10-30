"""A current evidence patch is a code binding, never execution or accepted-stage proof."""

import copy
import hashlib
import json
from types import SimpleNamespace

import pytest

from scripts.full_benchmark_preparation import CurrentBenchmarkPreparation, prepare_stage_targets, stage_target_declarations
from server.contracts.implementation_evidence import parse_evidence_patch_document
from server.services.frozen_benchmark_authority import _scientific_method
from server.tests.test_frozen_benchmark_authority import SETTINGS, frozen  # noqa: F401


def test_preparation_archives_stale_patch_and_writes_only_current_verified_selectors(tmp_path):
    root = tmp_path
    (root / "experiments").mkdir()
    run = {"protocol_id": "CSFS-v1", "run_experiment_authorized": False}
    (root / "experiments/RUN_SPEC.json").write_text(json.dumps(run))
    method = {"implementation_checks": [{"id":"current-M1","description":"source-bound code only",
        "evidence":[{"path":"experiments/src/csfs_v1/data.py","symbols":["channel_subsets"]}]}],
        "mechanism_coverage":[{"idea_mechanism_id":"M1","implementation_check_ids":["current-M1"]}]}
    path = root / "experiments/METHOD_CONTRACT.json"
    path.write_text(json.dumps(method))
    old = '{"schema":1,"checks":[{"check_id":"obsolete","path":"experiments/src/data.py"}]}'
    patch = root / "experiments/IMPLEMENTATION_EVIDENCE_PATCH.json"
    patch.write_text(old)
    before = path.read_bytes()
    prepare_stage_targets(root)
    current = json.loads(patch.read_text())
    parsed = parse_evidence_patch_document(current)
    assert len(parsed) == 1 and parsed[0].check_id == "current-M1"
    assert parsed[0].idea_mechanism_ids == ("M1",)
    assert parsed[0].evidence[0].path == "experiments/src/csfs_v1/data.py"
    assert path.read_bytes() == before
    assert (root / ".merak/source-evidence/implementation-evidence-patch.original.json").read_text() == old
    assert json.loads((root / "experiments/RUN_SPEC.json").read_text())["implementation_stage_targets"] == stage_target_declarations()
    assert not (root / "experiments/IMPLEMENTATION_BUILD.json").exists()
    assert not (root / ".merak/runs").exists()
    assert set(current) == {"schema", "checks"}


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bound_context(value):
    return {"schema": 1, "historical_inputs_root": str(value["history"]),
        "frozen_reference_root": str(value["reference"]), "settings": SETTINGS,
        **{name: value["pins"][name] for name in (
            "historical_inputs_pin", "benchmark_inventory_pin", "prospective_inventory_pin")}}


@pytest.mark.asyncio
async def test_scene_sources_bind_before_stage_fingerprint_and_later_consumer_is_method_byte_stable(frozen):
    root = frozen["root"]
    path = root / "experiments/METHOD_CONTRACT.json"
    method = json.loads(path.read_text())
    for index in range(4):
        identity = f"registered_mechanism_{index}"
        method["scientific_scene"]["objects"].append({"id": identity, "kind": "operation",
            "label": f"Registered scientific mechanism {index}", "source_path": "experiments/EXPERIMENT_PLAN.md"})
        method["scientific_scene"]["relations"].append({"from": "one", "to": identity, "kind": "containment"})
    path.write_text(json.dumps(method), encoding="utf-8")
    identity_before = _scientific_method(copy.deepcopy(method))
    protected = {p.relative_to(root).as_posix(): _sha(p) for p in root.rglob("*") if p.is_file()
        and (p.suffix.casefold() == ".csv" or p.is_relative_to(root / "experiments/src")
             or p.relative_to(root).as_posix() in {"experiments/EXPERIMENT_PLAN.md", "ideas/SELECTED_IDEA.json"})}
    calls, recorded_inputs = [], []
    run = SimpleNamespace(project_path=str(root), options={"run_experiment": False})

    async def original_stage(*, run, direction, opts):
        bound = json.loads(path.read_text())
        assert all(node["source_sha256"] == _sha(root / node["source_path"])
                   for node in bound["scientific_scene"]["objects"])
        calls.append(("stage", run, direction, opts))
        recorded_inputs.append(_sha(path))
        return {"blocking": False, "observed_input_sha256": recorded_inputs[-1]}

    async def original_consumer(actual_run, direction, force):
        assert _sha(path) == recorded_inputs[-1] and force is False
        calls.append(("consumer", actual_run, direction, force))
        return {"provided_evidence": True}

    preparation = CurrentBenchmarkPreparation(SimpleNamespace(_ensure_planned_result_templates=original_consumer),
        root, _bound_context(frozen), staged_implementation=original_stage)
    opts = {"run_experiment": False}
    report = await preparation.integrate(run=run, direction=SETTINGS["direction"], opts=opts)
    stage_bytes = path.read_bytes()
    assert report == {"blocking": False, "observed_input_sha256": _sha(path)}
    assert await preparation.ensure(run, SETTINGS["direction"]) == {"provided_evidence": True}
    assert await preparation.ensure(run, SETTINGS["direction"]) == {"provided_evidence": True}
    assert path.read_bytes() == stage_bytes
    assert _scientific_method(json.loads(stage_bytes)) == identity_before
    assert all(_sha(root / relative) == digest for relative, digest in protected.items())
    assert calls == [("stage", run, SETTINGS["direction"], opts),
                     ("consumer", run, SETTINGS["direction"], False),
                     ("consumer", run, SETTINGS["direction"], False)]
    proof = json.loads((root / "experiments/FROZEN_BENCHMARK_AUTHORITY.json").read_text())
    assert proof["workflow_acceptance_granted"] is proof["scientific_execution_performed"] is False
    assert not (root / "experiments/IMPLEMENTATION_BUILD.json").exists()
    assert not (root / ".merak/runs").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("violation", ["foreign_project", "run_execution", "opts_execution", "missing_handler"])
async def test_stage_preparation_rejects_out_of_scope_before_any_producer_call(tmp_path, violation):
    calls = []

    async def original_stage(**arguments):
        calls.append(arguments)
        return {"blocking": True}

    preparation = CurrentBenchmarkPreparation(SimpleNamespace(_ensure_planned_result_templates=None), tmp_path, {},
        staged_implementation=None if violation == "missing_handler" else original_stage)
    run = SimpleNamespace(project_path=str(tmp_path / "foreign" if violation == "foreign_project" else tmp_path),
        options={"run_experiment": violation == "run_execution"})
    with pytest.raises(ValueError):
        await preparation.integrate(run=run, direction="Existing study", opts={"run_experiment": violation == "opts_execution"})
    assert calls == [] and list(tmp_path.rglob("*")) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("defect", ["invalid_scene", "missing_source", "foreign_source"])
async def test_scene_binding_error_propagates_before_stage_call_and_preserves_method(tmp_path, defect):
    path = tmp_path / "experiments/METHOD_CONTRACT.json"
    path.parent.mkdir()
    scene = {"schema": 1, "objects": [{"id": "input", "kind": "input", "label": "Registered observations",
        "source_path": "../outside.md" if defect == "foreign_source" else "experiments/EXPERIMENT_PLAN.md"}], "relations": []}
    if defect == "invalid_scene":
        scene["schema"] = 0
    path.write_text(json.dumps({"scientific_scene": scene}))
    before, calls = path.read_bytes(), []

    async def original_stage(**arguments):
        calls.append(arguments)
        return {"blocking": True}

    preparation = CurrentBenchmarkPreparation(SimpleNamespace(_ensure_planned_result_templates=None), tmp_path, {},
        staged_implementation=original_stage)
    run = SimpleNamespace(project_path=str(tmp_path), options={"run_experiment": False})
    with pytest.raises(ValueError, match="unresolved scientific defects|missing, foreign or undeclared source"):
        await preparation.integrate(run=run, direction="Existing study", opts={"run_experiment": False})
    assert path.read_bytes() == before and calls == []
    assert not (tmp_path / "experiments/IMPLEMENTATION_BUILD.json").exists()


@pytest.mark.asyncio
async def test_original_stage_failure_is_not_swallowed_or_promoted_to_a_verdict(tmp_path):
    path = tmp_path / "experiments/METHOD_CONTRACT.json"
    path.parent.mkdir()
    (tmp_path / "experiments/EXPERIMENT_PLAN.md").write_text("Registered study\n")
    path.write_text(json.dumps({"scientific_scene": {"schema": 1, "objects": [{"id": "input", "kind": "input",
        "label": "Registered observations", "source_path": "experiments/EXPERIMENT_PLAN.md"}], "relations": []}}))
    calls = []

    async def original_stage(**arguments):
        calls.append(arguments)
        raise RuntimeError("Existing stage producer failed")

    preparation = CurrentBenchmarkPreparation(SimpleNamespace(_ensure_planned_result_templates=None), tmp_path, {},
        staged_implementation=original_stage)
    run = SimpleNamespace(project_path=str(tmp_path), options={"run_experiment": False})
    with pytest.raises(RuntimeError, match="Existing stage producer failed"):
        await preparation.integrate(run=run, direction="Existing study", opts={"run_experiment": False})
    assert len(calls) == 1
    assert not (tmp_path / "experiments/IMPLEMENTATION_BUILD.json").exists()
    assert not (tmp_path / "experiments/FROZEN_BENCHMARK_AUTHORITY.json").exists()
