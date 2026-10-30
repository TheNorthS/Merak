"""Protocol-readiness declarations never turn scaffolds into research evidence."""

import copy
import json
import math
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import yaml

from server.services import protocol_conformance as protocol
from server.services.experiment_runner import Experiment, ExperimentScheduler, GPUBackend
from server.services.experiment_models import JobStatus
from server.workflows.engine import WorkflowEngine
from server.workflows.models import WorkflowNode, WorkflowRun


@pytest.fixture
def project(tmp_path):
    files = {
        "experiments/EXPERIMENT_PLAN.md": "Accepted protocol: overlapping subsets; two spectral interventions.\n",
        "experiments/METHOD_CONTRACT.json": json.dumps({"schema": 2, "status": "implemented"}),
        "experiments/RUN_SPEC.json": json.dumps({"implementation_status": "integration_ready",
            "execution_status": "not_executed", "execution_prohibited_in_this_stage": True,
            "run_experiment_authorized": False}),
        "experiments/configs/main.yaml": yaml.safe_dump({"research_contract": {
            "implementation_status": "integration_scaffold_not_protocol_conformant", "execution_authorized": False},
            "execution": {"execution_prohibited_in_this_stage": True},
            "data": {"channel_view_size": 0, "channel_overlap": 0}}),
        "experiments/src/data.py": "raise RuntimeError('Research source must never execute during ledger checks')\n",
        "experiments/tests/test_pipeline.py": "raise RuntimeError('Project tests must not execute during ledger checks')\n",
    }
    for relative, text in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp_path


def _finding(status="mismatch"):
    return {"id": "PROTO-VIEW", "status": status, "area": "view_construction",
            "declared": "Cross both interventions into four composite views.",
            "observed": "Implementation applies each intervention separately; remains unvalidated.",
            "evidence": ["experiments/EXPERIMENT_PLAN.md", "experiments/src/data.py"]}


def _write_ledger(root, findings=None):
    payload = protocol.build_protocol_conformance_ledger(root, findings or [_finding()])
    (root / protocol.LEDGER_RELATIVE).write_text(json.dumps(payload), encoding="utf-8")
    return payload


def _files(root):
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_source_bound_producer_is_readonly_and_does_not_execute_source_or_promote_implemented_status(project):
    before = _files(project)
    payload = protocol.build_protocol_conformance_ledger(project, [_finding()])
    assert payload["status"] == "mismatch" and payload["cannot_execute"] is True
    assert payload["research_evidence"] is payload["implementation_matches_protocol"] is False
    assert set(payload["implementation_sha256"]) == {"experiments/RUN_SPEC.json", "experiments/configs/main.yaml",
        "experiments/src/data.py", "experiments/tests/test_pipeline.py"}
    assert _files(project) == before
    readiness = protocol.validate_protocol_conformance_ledger(project, payload)
    assert readiness.status == "mismatch" and readiness.cannot_execute
    assert _files(project) == before


@pytest.mark.parametrize("status", ["unvalidated", "corrected_locally"])
def test_locally_corrected_obligations_still_cannot_claim_whole_protocol_conformance(project, status):
    payload = _write_ledger(project, [_finding(status)])
    assert payload["status"] == "unvalidated"
    value = protocol.read_protocol_readiness(project)
    assert value.cannot_execute and not value.implementation_matches_protocol
    with pytest.raises(protocol.ProtocolConformanceError, match="scientific execution is prohibited"):
        protocol.require_protocol_execution_readiness(str(project))


@pytest.mark.parametrize("field,value", [("cannot_execute", False), ("research_evidence", True),
    ("implementation_matches_protocol", True), ("schema", True), ("status", "conformant"), ("owner", "model")])
def test_resigned_self_asserted_conformance_is_never_execution_authority(project, field, value):
    payload = _write_ledger(project)
    payload[field] = value
    with pytest.raises(protocol.ProtocolConformanceError):
        protocol.validate_protocol_conformance_ledger(project, payload)


@pytest.mark.parametrize("defect", ["authority", "source", "config", "run_spec", "tests", "new_source", "missing_source", "removed_inventory"])
def test_every_current_authority_implementation_config_and_inventory_binding_is_required(project, defect):
    payload = _write_ledger(project)
    relative = {"authority": "experiments/EXPERIMENT_PLAN.md", "source": "experiments/src/data.py",
                "config": "experiments/configs/main.yaml", "run_spec": "experiments/RUN_SPEC.json",
                "tests": "experiments/tests/test_pipeline.py"}.get(defect)
    if relative:
        path = project / relative
        path.write_bytes(path.read_bytes() + b"\n# changed current input\n")
    elif defect == "new_source":
        (project / "experiments/src/extra.py").write_text("new_source = True\n")
    elif defect == "missing_source":
        (project / "experiments/src/data.py").unlink()
    else:
        payload["implementation_sha256"].pop("experiments/src/data.py")
    with pytest.raises(protocol.ProtocolConformanceError):
        protocol.validate_protocol_conformance_ledger(project, payload)


@pytest.mark.parametrize("defect", ["empty", "duplicate", "pass", "unbound_evidence", "extra_field", "empty_message"])
def test_finding_must_be_typed_unique_and_bound_to_current_owned_sources(project, defect):
    values = [_finding()]
    if defect == "empty":
        values = []
    elif defect == "duplicate":
        values.append(copy.deepcopy(values[0]))
    elif defect == "pass":
        values[0]["status"] = "passed"
    elif defect == "unbound_evidence":
        values[0]["evidence"] = ["../foreign/science.csv"]
    elif defect == "extra_field":
        values[0]["execution_verified"] = True
    else:
        values[0]["observed"] = ""
    with pytest.raises(protocol.ProtocolConformanceError):
        protocol.build_protocol_conformance_ledger(project, values)


@pytest.mark.parametrize("section,key,value", [("research_contract", "execution_authorized", True),
    ("execution", "execution_prohibited_in_this_stage", False)])
def test_configuration_cannot_enable_execution_under_negative_readiness(project, section, key, value):
    path = project / "experiments/configs/main.yaml"
    config = yaml.safe_load(path.read_text())
    config[section][key] = value
    path.write_text(yaml.safe_dump(config))
    with pytest.raises(protocol.ProtocolConformanceError, match="explicitly prohibit"):
        protocol.build_protocol_conformance_ledger(project, [_finding()])


def test_missing_ledger_preserves_legacy_behavior_without_inventing_readiness(project):
    assert protocol.read_protocol_readiness(project) is None
    protocol.require_protocol_execution_readiness(str(project))
    assert "readiness is not validated" in protocol.protocol_readiness_prompt(project)


@pytest.mark.parametrize("relative", [protocol.LEDGER_RELATIVE, "../foreign.json", "", "experiments/another.json"])
def test_explicit_readiness_optin_cannot_silently_fall_back_to_absence_or_foreign_path(project, relative):
    config_path = project / "experiments/configs/main.yaml"
    config = yaml.safe_load(config_path.read_text())
    config["research_contract"]["protocol_conformance_path"] = relative
    config_path.write_text(yaml.safe_dump(config))
    with pytest.raises(protocol.ProtocolConformanceError, match="missing|canonical"):
        protocol.require_protocol_execution_readiness(str(project))
    assert "BLOCKED:" in protocol.protocol_readiness_prompt(project)


@pytest.mark.parametrize("node_id", ["exp-run", "paper", "review"])
def test_standard_workflow_inputs_consume_actual_ledger_without_claiming_execution(project, monkeypatch, node_id):
    _write_ledger(project)
    host = WorkflowEngine()
    monkeypatch.setattr(host, "_input_" + node_id.replace("-", "_"), lambda *_: "Node inputs")
    node = WorkflowNode(node_id, node_id, "current-skill")
    run = WorkflowRun(project_path=str(project), nodes=[node])
    before = _files(project)
    prompt = host._build_node_input(node, "Research", run)
    assert "proposed protocol" in prompt and "not protocol-conformant research evidence" in prompt
    assert '"implementation_matches_protocol": false' in prompt and '"cannot_execute": true' in prompt
    assert _files(project) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [False, True])
async def test_present_negative_or_malformed_ledger_blocks_before_scheduler_mutates_jobs_or_queue(project, invalid):
    _write_ledger(project)
    if invalid:
        (project / protocol.LEDGER_RELATIVE).write_text("malformed ledger")
    scheduler = ExperimentScheduler()
    experiment = Experiment(project_path=str(project), backend=GPUBackend.LOCAL,
                            command_template="must_not_execute --seed {seed}", seeds=[13])
    with pytest.raises(protocol.ProtocolConformanceError):
        await scheduler.submit_experiment(experiment)
    assert experiment.jobs == [] and scheduler._experiments == {} and scheduler._queue.empty()


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [False, True])
async def test_previously_queued_job_is_refused_if_negative_readiness_appears_before_actual_start(project, monkeypatch, invalid):
    from server.services.remote_experiment_runtime import experiment_runtime

    scheduler = ExperimentScheduler()
    experiment = Experiment(project_path=str(project), backend=GPUBackend.LOCAL,
                            command_template="must_not_execute --seed {seed}", seeds=[13])
    await scheduler.submit_experiment(experiment)
    _, _, job = scheduler._queue.get_nowait()
    assert job.status is JobStatus.QUEUED
    _write_ledger(project)
    if invalid:
        (project / protocol.LEDGER_RELATIVE).write_text("malformed new ledger")
    runtime = AsyncMock(side_effect=AssertionError("Backend runtime must never start"))
    managed = AsyncMock(side_effect=AssertionError("Managed execution must never start"))
    monkeypatch.setattr(experiment_runtime, "run", runtime)
    monkeypatch.setattr(scheduler, "_run_managed_job", managed)
    before = _files(project)
    await scheduler._run_job(job)
    assert job.status is JobStatus.FAILED and job.finished_at is not None
    assert "protocol" in job.error_message.casefold()
    assert managed.await_count == runtime.await_count == 0
    assert scheduler._running_jobs == {} and _files(project) == before


def test_invalid_ledger_is_explicitly_blocked_in_manuscript_inputs_not_silently_absent(project):
    (project / protocol.LEDGER_RELATIVE).write_text("not-json")
    prompt = protocol.protocol_readiness_prompt(project)
    assert "BLOCKED:" in prompt and "Cannot execute or claim implementation conformance" in prompt


def test_broken_link_ledger_is_not_silently_treated_as_absent(project, monkeypatch):
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == project / protocol.LEDGER_RELATIVE or original(path))
    with pytest.raises(protocol.ProtocolConformanceError, match="invalid"):
        protocol.read_protocol_readiness(project)


@pytest.mark.parametrize("population", range(8, 20))
def test_accepted_half_population_floor_and_half_view_ceil_policy_is_feasible_at_every_eligible_boundary(population):
    size, overlap = protocol.overlapping_subset_counts(population, 0, 0, minimum_population=8,
        minimum_size=4, size_fraction=(1, 2), overlap_fraction=(1, 2))
    assert size == max(4, population // 2) and overlap == (size + 1) // 2
    assert 0 < overlap < size <= population and 2 * size - overlap <= population
    shared, first_only, second_only = set(range(overlap)), set(range(overlap, size)), set(range(size, 2 * size - overlap))
    first, second = shared | first_only, shared | second_only
    assert len(first) == len(second) == size and len(first & second) == overlap


@pytest.mark.parametrize("population", [8, 16, 19])
def test_old_three_quarter_auto_rule_cannot_silently_supply_impossible_union(population):
    size = math.ceil(population * 0.75)
    with pytest.raises(protocol.ProtocolConformanceError, match=r"2\*size-overlap"):
        protocol.overlapping_subset_counts(population, size, size // 2, minimum_population=8,
            minimum_size=4, size_fraction=(1, 2), overlap_fraction=(1, 2))


@pytest.mark.parametrize("population,size,overlap", [(7, 0, 0), (8, -1, 0), (8, 0, -1), (8, 4, 4), (8, 9, 1), (8, True, 0)])
def test_invalid_auto_markers_or_ineligible_population_never_become_zero_channel_views(population, size, overlap):
    with pytest.raises(protocol.ProtocolConformanceError):
        protocol.overlapping_subset_counts(population, size, overlap, minimum_population=8,
            minimum_size=4, size_fraction=(1, 2), overlap_fraction=(1, 2))


def test_subset_sizing_is_policy_parameterized_not_an_eeg_specific_default():
    assert protocol.overlapping_subset_counts(30, 0, 0, minimum_population=10,
        minimum_size=3, size_fraction=(1, 3), overlap_fraction=(2, 3)) == (10, 7)


def test_stable_identity_seed_is_independent_of_manifest_order_but_bound_to_run_and_segment():
    identities = ["dataset-A:subject-3:segment-5", "dataset-B:segment-3", "segment-你好"]
    first = {identity: protocol.stable_identity_seed(13, identity) for identity in identities}
    reordered = {identity: protocol.stable_identity_seed(13, identity) for identity in reversed(identities)}
    assert first == reordered and all(0 <= value < 1 << 63 for value in first.values())
    assert len(set(first.values())) == len(first)
    assert first[identities[0]] != protocol.stable_identity_seed(42, identities[0])


@pytest.mark.parametrize("seed,identity", [(True, "segment"), (13.0, "segment"), (13, ""), (13, "  "), (13, None)])
def test_stable_seed_never_invents_missing_identity_or_coerces_noninteger_seed(seed, identity):
    with pytest.raises(protocol.ProtocolConformanceError):
        protocol.stable_identity_seed(seed, identity)


@pytest.mark.parametrize("mode", ["hardlink", "symlink"])
def test_linked_protocol_or_implementation_inputs_are_not_rebound_as_current_owned_files(project, mode):
    source = project / "experiments/src/data.py"
    original = project / "external.py"
    source.rename(original)
    if mode == "hardlink":
        source.hardlink_to(original)
    else:
        try:
            source.symlink_to(original)
        except OSError:
            pytest.skip("Windows symlink creation privilege is unavailable")
    with pytest.raises(protocol.ProtocolConformanceError, match="linked"):
        protocol.build_protocol_conformance_ledger(project, [_finding()])
