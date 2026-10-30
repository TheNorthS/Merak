"""Fake-engine acceptance scope tests; no paid provider or real workflow runs."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.full_benchmark_evidence import archive_source_history, check_source_owners, import_source_owner_evidence, SOURCE_NODES
from scripts.full_benchmark_scope import FROZEN_WORKFLOW_INPUTS, MODEL_OWNER, PIPELINE_NODES, TEN_NODES, numerical_fingerprint, scientific_method_identity, validate_method_tool_change, write_is_allowed
from scripts.verify_full_benchmark_workflow import _pipeline_options, execute_new_benchmark, selected_nodes, validate_final_outcome


@pytest.mark.asyncio
async def test_actual_verification_engine_persists_events_and_forwards_real_callback(tmp_path):
    from scripts.full_benchmark_engine import FullBenchmarkEngine
    from server.workflows.models import WorkflowRun

    calls = []
    async def progress(event, data):
        calls.append((event, data))
    run = WorkflowRun(id="new-actual-run", project_path=str(tmp_path), on_event=progress)
    host = FullBenchmarkEngine()
    await host._emit(run, "node_started", {"node_id": "paper"})
    records = [json.loads(line) for line in (tmp_path / ".merak/runs/new-actual-run.events.jsonl").read_text().splitlines()]
    assert records[0]["run_id"] == run.id and records[0]["event"] == "node_started"
    assert calls == [("node_started", {"node_id": "paper"})]
    assert (tmp_path / ".merak/workflow_logs.json").is_file()


@pytest.mark.asyncio
async def test_verification_event_or_safety_callback_failure_cannot_be_swallowed(tmp_path, monkeypatch):
    from scripts.full_benchmark_engine import FullBenchmarkEngine, workflow_event_journal
    from server.workflows.models import WorkflowRun

    host = FullBenchmarkEngine()
    def unsafe(event, data):
        raise PermissionError("Frozen method changed")
    run = WorkflowRun(id="strict-events", project_path=str(tmp_path), on_event=unsafe)
    with pytest.raises(PermissionError, match="Frozen method"):
        await host._emit(run, "node_started", {"node_id": "paper"})
    def failed(*args):
        raise OSError("Cannot persist event")
    monkeypatch.setattr(workflow_event_journal, "record", failed)
    with pytest.raises(OSError, match="persist event"):
        await host._emit(run, "node_started", {"node_id": "paper"})


def _source_fixture(original: Path, copied: Path):
    original.mkdir()
    copied.mkdir()
    phases, stages = {}, {}
    for identity, relative in zip(SOURCE_NODES, ("literature/survey.md", "ideas/ideas.md", "ideas/novelty_report.md")):
        for root in (original, copied):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("unchanged canonical " + identity, encoding="utf-8")
        phases[identity] = {"status": "accepted", "artifact": str(original / relative), "accepted_at": 100.0,
                            "verdict_id": "prior-" + identity, "reviewer": "source-owner",
                            "details": {"execution_evidence": {"accepted": True, "issues": [],
                             "trace_path": str(original / ".merak/runs/prior.skills.json")},
                             "artifact_snapshot": {relative: {"kind": "file", "sha256": hashlib.sha256((original / relative).read_bytes()).hexdigest()}}}}
        stages[identity] = {"node_id": identity, "run_id": "prior", "invocations": [{"run_id": "prior", "session_id": "original-session", "status": "completed"}]}
    state = {"schema": 1, "run_id": "prior", "status": "cancelled", "phases": phases,
             "config": {"assurance": "draft", "options": {"run_experiment": False}}, "input_baseline": {}}
    trace = {"schema": 2, "run_id": "prior", "project_path": str(original), "stages": stages}
    for name, value in (("prior.json", state), ("prior.skills.json", trace)):
        path = original / ".merak/runs" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")
    invocation = original / ".merak/skill-invocations/raw.json"
    invocation.parent.mkdir()
    invocation.write_bytes(b'{"session_id":"original-session","immutable":true}')
    return state, trace


def test_source_import_preserves_original_ids_acceptance_and_raw_stage_bytes(tmp_path):
    original, copied = tmp_path / "original", tmp_path / "copied"
    state, trace = _source_fixture(original, copied)
    before = {path: path.read_bytes() for path in original.rglob("*") if path.is_file()}
    evidence = import_source_owner_evidence(copied, original, "prior")
    clone = json.loads((copied / ".merak/runs/prior.json").read_text())
    current_trace = json.loads((copied / ".merak/runs/prior.skills.json").read_text())
    assert clone["run_id"] == "prior" and clone["status"] == "cancelled"
    for identity in SOURCE_NODES:
        for key in ("status", "accepted_at", "verdict_id", "reviewer"):
            assert clone["phases"][identity][key] == state["phases"][identity][key]
        assert current_trace["stages"][identity] == trace["stages"][identity]
        assert str(copied) in clone["phases"][identity]["artifact"]
    assert evidence["new_accepted_phases_created"] is False
    assert (copied / ".merak/source-evidence/prior.run.original.json").read_bytes() == before[original / ".merak/runs/prior.json"]
    assert (copied / ".merak/skill-invocations/raw.json").read_bytes() == before[original / ".merak/skill-invocations/raw.json"]
    assert {path: path.read_bytes() for path in before} == before


def test_all_fresh_source_history_never_installs_old_accepted_phases_or_requires_current_report_identity(tmp_path):
    original, copied = tmp_path / "original", tmp_path / "copied"
    _source_fixture(original, copied)
    before = {path: path.read_bytes() for path in original.rglob("*") if path.is_file()}
    (copied / "literature/survey.md").write_text("legitimate new literature owner correction")
    evidence = archive_source_history(copied, original, "prior")
    assert evidence["historical_only"] and not evidence["reusable_prior_run_installed"]
    assert not (copied / ".merak/runs/prior.json").exists()
    assert not (copied / ".merak/runs/prior.skills.json").exists()
    assert (copied / ".merak/source-evidence/prior.run.original.json").read_bytes() == before[original / ".merak/runs/prior.json"]
    assert {path: path.read_bytes() for path in before} == before


@pytest.mark.parametrize("defect", ["active", "status", "trace_run", "stage_id", "changed_artifact"])
def test_source_import_cannot_promote_invalid_or_changed_original_evidence(tmp_path, defect):
    original, copied = tmp_path / "original", tmp_path / "copied"
    state, trace = _source_fixture(original, copied)
    if defect == "active": state["status"] = "running"
    elif defect == "status": state["phases"]["lit"]["status"] = "done"
    elif defect == "trace_run": trace["run_id"] = "foreign"
    elif defect == "stage_id": trace["stages"]["lit"]["run_id"] = "new"
    else: (copied / "literature/survey.md").write_text("changed")
    (original / ".merak/runs/prior.json").write_text(json.dumps(state))
    (original / ".merak/runs/prior.skills.json").write_text(json.dumps(trace))
    with pytest.raises(ValueError): import_source_owner_evidence(copied, original, "prior")
    assert not (copied / ".merak/runs/prior.json").exists()


def test_reused_owners_execute_current_gate_without_creating_new_acceptance(tmp_path):
    original, copied = tmp_path / "original", tmp_path / "copied"
    _source_fixture(original, copied)
    import_source_owner_evidence(copied, original, "prior")
    before = (copied / ".merak/runs/prior.json").read_bytes()
    calls = []
    host = SimpleNamespace(_get_default_nodes=lambda: [SimpleNamespace(id=name) for name in PIPELINE_NODES],
                           _artifact_snapshot_issues=lambda *_: [])
    def gate(node, run, *_args, **kwargs):
        calls.append((node.id, run.id, kwargs["require_fresh"]))
        return {"accepted": True, "verdict_id": "current-" + node.id, "reviewer": "actual-current-fixture-gate",
                "details": {"execution_evidence": {"accepted": True, "issues": []}}}
    host._acceptance_gate = gate
    result = check_source_owners(host, copied, "prior", SOURCE_NODES)
    assert calls == [(name, "prior", False) for name in SOURCE_NODES]
    assert set(result) == set(SOURCE_NODES) and (copied / ".merak/runs/prior.json").read_bytes() == before
    host._artifact_snapshot_issues = lambda *_: ["changed bibliography"]
    with pytest.raises(ValueError, match="changed"): check_source_owners(host, copied, "prior", SOURCE_NODES)


def test_all_fresh_execution_does_not_require_an_archived_run_to_be_installed(tmp_path):
    assert not (tmp_path / ".merak/runs/prior.json").exists()
    assert check_source_owners(SimpleNamespace(), tmp_path, "prior", ()) == {}
    with pytest.raises(FileNotFoundError):
        check_source_owners(SimpleNamespace(), tmp_path, "prior", SOURCE_NODES)


@pytest.mark.parametrize("name", ["MANIFEST.md", "NARRATIVE_REPORT.md", "FULL_BENCHMARK_REPORT.json"])
def test_owned_root_reports_allow_only_their_exact_atomic_siblings(tmp_path, name):
    from scripts.verify_offline_suite import canonical_io_path
    from server.utils.atomic_write import atomic_write_bytes
    from unittest.mock import patch
    import builtins

    original = builtins.open
    def guarded(file, mode="r", *args, **kwargs):
        if any(letter in mode for letter in "wax+"):
            assert write_is_allowed(tmp_path, canonical_io_path(file), rerun_literature=False)
        return original(file, mode, *args, **kwargs)
    with patch("pathlib.io.open", guarded):
        atomic_write_bytes(tmp_path / name, b"owned report")
    assert (tmp_path / name).read_bytes() == b"owned report"
    assert not write_is_allowed(tmp_path, tmp_path / (".foreign.json.1.2." + "a" * 32 + ".tmp"), rerun_literature=False)
    assert not write_is_allowed(tmp_path, tmp_path / ("." + name + ".forged.tmp"), rerun_literature=False)


@pytest.mark.parametrize("relative", ["ideas/SELECTED_IDEA.json", "experiments/EXPERIMENT_PLAN.md", "experiments/RUN_SPEC.json",
    "experiments/configs/main.yaml", "experiments/src/csfs_v1/train.py", "experiments/results/simulated/any.json",
    "experiments/results/templates/PLANNED_RESULT_MANIFEST.json", "paper/tables/new.csv", "figures/simulated/new.png", ".merak/source-evidence/prior.json"])
def test_frozen_numeric_plan_implementation_and_archive_writes_are_denied(tmp_path, relative):
    assert not write_is_allowed(tmp_path, tmp_path / relative, rerun_literature=True, rerun_source_owners=True)


def test_owned_reports_and_exact_source_owner_repairs_are_scoped(tmp_path):
    assert write_is_allowed(tmp_path, tmp_path / "experiments/results/analysis.md", rerun_literature=False)
    assert write_is_allowed(tmp_path, tmp_path / "paper/sections/05_results.tex", rerun_literature=False)
    assert not write_is_allowed(tmp_path, tmp_path / "literature/references.bib", rerun_literature=False)
    assert write_is_allowed(tmp_path, tmp_path / "literature/references.bib", rerun_literature=True)
    assert not write_is_allowed(tmp_path, tmp_path.parent / "foreign.txt", rerun_literature=True)
    token = MODEL_OWNER.set("idea")
    try:
        assert write_is_allowed(tmp_path, tmp_path / "ideas/ideas.md", rerun_literature=True, rerun_source_owners=True)
        assert write_is_allowed(tmp_path, tmp_path / ("ideas/.ideas.md.123.456." + "a" * 32 + ".tmp"),
                                rerun_literature=True, rerun_source_owners=True)
        assert not write_is_allowed(tmp_path, tmp_path / ("ideas/.SELECTED_IDEA.json.123.456." + "a" * 32 + ".tmp"),
                                    rerun_literature=True, rerun_source_owners=True)
        assert not write_is_allowed(tmp_path, tmp_path / "ideas/novelty_report.md", rerun_literature=True, rerun_source_owners=True)
    finally: MODEL_OWNER.reset(token)


def test_method_scene_repair_does_not_grant_permission_to_change_hypotheses(tmp_path):
    path = tmp_path / "experiments/METHOD_CONTRACT.json"
    path.parent.mkdir()
    payload = {"schema": 2, "claim_evidence_plan": [{"idea_claim_id": "C1", "outcomes": ["Frozen hypothesis"]}],
               "mechanism_coverage": [{"idea_mechanism_id": "M1", "design_requirement": "Frozen mechanism",
                                       "implementation_check_ids": ["current"], "status": "implemented"}],
               "scientific_scene": {"schema": 1}}
    path.write_text(json.dumps(payload))
    expected = scientific_method_identity(tmp_path)
    value = {**payload, "scientific_scene": {"schema": 2, "objects": ["source-bound"]}}
    tool = SimpleNamespace(name="Write", arguments={"file_path": str(path), "content": json.dumps(value)})
    validate_method_tool_change(SimpleNamespace(workflow_node_id="exp-design"), tool, tmp_path, expected)
    with pytest.raises(PermissionError): validate_method_tool_change(SimpleNamespace(workflow_node_id="paper"), tool, tmp_path, expected)
    value["claim_evidence_plan"] = []
    tool.arguments["content"] = json.dumps(value)
    with pytest.raises(PermissionError): validate_method_tool_change(SimpleNamespace(workflow_node_id="exp-design"), tool, tmp_path, expected)


def _accepted_state(run_id, selected):
    return {"run_id": run_id, "schema": 1, "status": "completed", "phases": {node: {
        "status": "accepted", "accepted_at": 123.0, "reviewer": "real-fixture-producer", "verdict_id": node,
        "details": {"execution_evidence": {"accepted": True, "issues": []}}} for node in selected}}


def test_terminal_status_or_files_alone_cannot_claim_complete_thirteen_stage_pipeline():
    source = {name: {"execution_evidence": {"accepted": True}} for name in SOURCE_NODES}
    state = _accepted_state("fresh", TEN_NODES)
    assert validate_final_outcome(state, "fresh", TEN_NODES, source)
    for defect in ("done", "missing_execution", "foreign_run", "missing_source"):
        changed = copy.deepcopy(state)
        sources = copy.deepcopy(source)
        if defect == "done": changed["phases"]["paper"]["status"] = "done"
        elif defect == "missing_execution": changed["phases"]["paper"]["details"] = {}
        elif defect == "foreign_run": changed["run_id"] = "old"
        else: sources.pop("lit")
        assert not validate_final_outcome(changed, "fresh", TEN_NODES, sources)


@pytest.mark.asyncio
@pytest.mark.parametrize("fresh_owners", [False, True])
async def test_fake_engine_exercises_fresh_execute_and_current_gates_not_resume_or_state_promotion(tmp_path, fresh_owners):
    calls = []
    selected = selected_nodes(False, fresh_owners)
    state = _accepted_state("genuine-new-fixture", selected)
    path = tmp_path / ".merak/runs/genuine-new-fixture.json"
    path.parent.mkdir(parents=True)
    source = {} if fresh_owners else {name: {"execution_evidence": {"accepted": True}} for name in SOURCE_NODES}
    class Host:
        def __init__(self): self._running_tasks, self._runs = {}, {}
        async def execute(self, **options):
            calls.append(options)
            assert "resume_run_id" not in options["pipeline_options"]
            assert options["pipeline_options"]["input_files"] == list(FROZEN_WORKFLOW_INPUTS)
            async def worker(): path.write_text(json.dumps(state))
            self._running_tasks[state["run_id"]] = asyncio.create_task(worker())
            self._runs[state["run_id"]] = SimpleNamespace(nodes=[SimpleNamespace(id=name) for name in selected])
            return state["run_id"]
        def _acceptance_gate(self, node, run, *_args, **_kwargs):
            return {"accepted": True, "details": {"execution_evidence": {"accepted": True}}}
    report = await execute_new_benchmark(Host(), tmp_path, {"options": {}}, source_gates=source,
                                         rerun_literature=False, rerun_source_owners=fresh_owners)
    assert report["accepted"] and calls[0]["node_ids"] == list(selected)
    assert set(report["phases"]) == set(selected) and set(report["source_owner_reuse"]) == set(source)
    assert len(report["current_gates"]) == len(selected)


def test_pipeline_options_never_enable_experiment_or_resume_budgets():
    options = _pipeline_options({"options": {"run_experiment": True, "resume_run_id": "old", "max_revision_rounds": 2}}, False)
    assert options["run_experiment"] is False and "resume_run_id" not in options
    assert options["max_revision_rounds"] == 2 and options["gpu_target"] == "none"
    assert not options["enable_overleaf_sync"] and not options["enable_meta_opt"]
    assert not options["wandb"] and not options["enable_meta_optimization"]


def test_frozen_materials_use_normal_input_snapshot_and_still_require_valid_content(tmp_path):
    from server.services.workflow_inputs import snapshot_paths, workflow_input_service
    from server.workflows.engine import WorkflowEngine

    for relative in FROZEN_WORKFLOW_INPUTS:
        path = tmp_path / relative
        if path.suffix:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("provided material", encoding="utf-8")
        else:
            path.mkdir(parents=True, exist_ok=True)
            (path / "existing.txt").write_text("provided material", encoding="utf-8")
    options = _pipeline_options({"options": {"input_files": ["foreign-original"]}}, True)
    baseline = workflow_input_service.capture(tmp_path, options["input_files"], run_id="fixture")
    host = WorkflowEngine()
    selected = tmp_path / "ideas/SELECTED_IDEA.json"
    snapshot = snapshot_paths(tmp_path, [selected])
    assert not workflow_input_service.validate_snapshot(tmp_path, baseline)
    assert host._artifact_check([selected], baseline=snapshot, project_path=str(tmp_path), input_baseline=baseline)[0]
    assert not host._artifact_check([selected], baseline=snapshot, project_path=str(tmp_path))[0]
    selected.write_text("modified hypothesis", encoding="utf-8")
    assert workflow_input_service.validate_snapshot(tmp_path, baseline)
    selected.unlink()
    assert not host._artifact_check([selected], baseline=snapshot, project_path=str(tmp_path), input_baseline=baseline)[0]


def _method_scope_fixture(tmp_path):
    path = tmp_path / "experiments/METHOD_CONTRACT.json"
    path.parent.mkdir()
    source = tmp_path / "experiments/src/actual.py"
    source.parent.mkdir()
    source.write_text("def shared_factor(value):\n    return value\n", encoding="utf-8")
    idea = tmp_path / "ideas/SELECTED_IDEA.json"
    idea.parent.mkdir()
    idea.write_text(json.dumps({"schema": 2, "title": "Frozen selected hypothesis"}), encoding="utf-8")
    payload = {"schema": 2, "status": "implemented", "scientific_execution_performed": False,
        "idea_contract_path": "ideas/SELECTED_IDEA.json", "idea_contract_sha256": hashlib.sha256(idea.read_bytes()).hexdigest(),
        "integration_verdict": {"validator": "implementation-integration-v1", "output_sha256": "a" * 64},
        "claim_evidence_plan": [{"idea_claim_id": "C1", "outcomes": ["Frozen registered outcome"],
                                  "failure_conditions": ["Registered falsification boundary"]}],
        "evaluation_contract": {"comparators_or_controls": ["Frozen anchor"]},
        "mechanism_coverage": [{"idea_mechanism_id": "M1", "design_requirement": "Frozen mechanism",
                                "implementation_check_ids": ["verified-current-code"], "status": "implemented"}],
        "implementation_checks": [{"id": "verified-current-code", "description": "Existing source-bound implementation",
                                    "evidence": [{"path": "experiments/src/actual.py", "symbols": ["shared_factor"]}]}],
        "scientific_scene": {"schema": 1, "objects": [{"id": "old-object", "kind": "operation",
            "label": "Shared latent factor", "source_path": "experiments/src/actual.py",
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest()}], "relations": []}}
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path, payload, scientific_method_identity(tmp_path)


@pytest.mark.parametrize("field,expected_path", [
    ("outcomes", "/claim_evidence_plan/0/outcomes/0"),
    ("failure_conditions", "/claim_evidence_plan/0/failure_conditions/0"),
    ("comparators_or_controls", "/evaluation_contract/comparators_or_controls/0"),
    ("design_requirement", "/mechanism_coverage/0/design_requirement"),
])
def test_method_scope_reports_exact_changed_science_paths_without_writing(tmp_path, field, expected_path):
    from scripts.full_benchmark_scope import MethodScopeViolation

    path, payload, expected = _method_scope_fixture(tmp_path)
    original = path.read_bytes()
    if field in {"outcomes", "failure_conditions"}:
        payload["claim_evidence_plan"][0][field][0] = "Replaced frozen rule"
    elif field == "design_requirement":
        payload["mechanism_coverage"][0][field] = "Replaced frozen rule"
    else:
        payload["evaluation_contract"][field][0] = "Replaced frozen anchor"
    tool = SimpleNamespace(name="Write", arguments={"path": str(path), "content": json.dumps(payload)})
    with pytest.raises(MethodScopeViolation) as failure:
        validate_method_tool_change(SimpleNamespace(workflow_node_id="exp-design"), tool, tmp_path, expected)
    assert expected_path in str(failure.value)
    assert " -> " in str(failure.value) and "Replaced" in str(failure.value)
    assert path.read_bytes() == original


def test_method_scope_implementation_status_change_still_preserves_scientific_identity(tmp_path):
    path, payload, expected = _method_scope_fixture(tmp_path)
    payload["status"] = "implementation_in_progress"
    payload["scientific_scene"]["objects"][0]["id"] = "authored-scene-object"
    tool = SimpleNamespace(name="Write", arguments={"path": str(path), "content": json.dumps(payload)})
    validate_method_tool_change(SimpleNamespace(workflow_node_id="exp-design"), tool, tmp_path, expected)
    assert scientific_method_identity(tmp_path) == expected
    assert json.loads(path.read_text())["status"] == "implemented"
    options = _pipeline_options({"options": {}}, False)
    assert "Keep every existing claim" in options["node_inputs"]["method_scene_repair"]
    assert "Preserve current verified implementation_checks" in options["node_inputs"]["method_scene_repair"]


def _local_method_engine(monkeypatch, calls):
    from server.agent import ModelRouter
    from server.agent.engine import AgentEngine
    from server.agent.tools.file_tools import file_edit, file_write

    engine = AgentEngine(ModelRouter())
    async def write(path, content):
        calls.append(("Write", path))
        return await file_write(path, content)
    async def edit(path, old_text, new_text):
        calls.append(("Edit", path))
        return await file_edit(path, old_text, new_text)
    for name, handler, keys in (("Write", write, ("path", "content")), ("Edit", edit, ("path", "old_text", "new_text"))):
        engine.register_tool(name, "Temporary local file boundary", {"type": "object",
            "properties": {key: {"type": "string"} for key in keys}, "required": list(keys)}, handler)
    monkeypatch.setattr(engine, "_log_tool_event", lambda *_: None)
    monkeypatch.setattr(engine, "_record_execution_provenance", lambda *_: None)
    return engine


@pytest.mark.asyncio
async def test_same_real_tool_session_receives_refusal_then_valid_local_scene_edit(tmp_path, monkeypatch):
    from scripts.full_benchmark_scope import benchmark_method_tool_scope
    from server.agent import ToolCall
    from server.agent.session_models import AgentSession, ToolResult

    path, payload, expected = _method_scope_fixture(tmp_path)
    original, calls = path.read_bytes(), []
    engine = _local_method_engine(monkeypatch, calls)
    session = AgentSession(project_path=str(tmp_path), workflow_node_id="exp-design", tool_policy="workflow_artifacts")
    changed = copy.deepcopy(payload)
    changed["claim_evidence_plan"][0]["outcomes"] = ["Different unsupported decision"]
    with benchmark_method_tool_scope(engine, tmp_path, expected):
        refused = await engine._execute_tool(session, ToolCall(id="denied-write", name="Write",
            arguments={"path": str(path), "content": json.dumps(changed)}))
        assert isinstance(refused, ToolResult) and refused.tool_call_id == "denied-write"
        assert not refused.success and refused.error.startswith("METHOD_SCOPE_VIOLATION:")
        assert refused.output == refused.error and "/claim_evidence_plan/0/outcomes/0" in refused.error
        assert path.read_bytes() == original and not calls
        corrected = await engine._execute_tool(session, ToolCall(id="corrected-edit", name="Edit", arguments={
            "path": str(path), "old_text": '"old-object"', "new_text": '"source-bound-scene-object"'}))
    assert corrected.success and corrected.tool_call_id == "corrected-edit"
    assert calls == [("Edit", str(path))]
    assert scientific_method_identity(tmp_path) == expected
    actual = json.loads(path.read_text())
    assert actual["scientific_scene"]["objects"][0]["id"] == "source-bound-scene-object"
    assert actual["implementation_checks"] == payload["implementation_checks"]
    assert not (tmp_path / ".merak/runs").exists()
    assert MODEL_OWNER.get() == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("defect", ["wrong_owner", "invalid_json", "invalid_schema", "ambiguous_edit"])
async def test_only_known_invalid_method_proposals_receive_failed_tool_results(tmp_path, monkeypatch, defect):
    from scripts.full_benchmark_scope import benchmark_method_tool_scope
    from server.agent import ToolCall
    from server.agent.session_models import AgentSession

    path, payload, expected = _method_scope_fixture(tmp_path)
    original, calls = path.read_bytes(), []
    engine = _local_method_engine(monkeypatch, calls)
    session = AgentSession(project_path=str(tmp_path), workflow_node_id="paper" if defect == "wrong_owner" else "exp-design")
    if defect == "invalid_schema":
        payload["schema"] = 1
    arguments = {"path": str(path), "content": "{" if defect == "invalid_json" else json.dumps(payload)}
    name = "Write"
    if defect == "ambiguous_edit":
        name, arguments = "Edit", {"path": str(path), "old_text": "absent source span", "new_text": "new"}
    with benchmark_method_tool_scope(engine, tmp_path, expected):
        result = await engine._execute_tool(session, ToolCall(id="known-rejection", name=name, arguments=arguments))
    assert not result.success and result.error.startswith("METHOD_SCOPE_VIOLATION:")
    assert not calls and path.read_bytes() == original
    assert MODEL_OWNER.get() == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [OSError("storage unavailable"), PermissionError("forbidden Bash or foreign write")])
async def test_unrelated_tool_or_filesystem_failure_remains_fatal(tmp_path, monkeypatch, error):
    from scripts.full_benchmark_scope import benchmark_method_tool_scope
    from server.agent import ToolCall
    from server.agent.session_models import AgentSession

    path, _payload, expected = _method_scope_fixture(tmp_path)
    calls = []
    engine = _local_method_engine(monkeypatch, calls)
    async def failing(*_args, **_kwargs):
        raise error
    monkeypatch.setattr(engine, "_execute_tool", failing)
    session = AgentSession(project_path=str(tmp_path), workflow_node_id="exp-design")
    with benchmark_method_tool_scope(engine, tmp_path, expected):
        with pytest.raises(type(error), match=str(error)):
            await engine._execute_tool(session, ToolCall(id="unrelated", name="Bash", arguments={"command": "forbidden"}))
    assert not calls and MODEL_OWNER.get() == ""
    path.unlink()
    with benchmark_method_tool_scope(engine, tmp_path, expected):
        with pytest.raises(FileNotFoundError):
            await engine._execute_tool(session, ToolCall(id="missing-source", name="Edit",
                arguments={"path": str(path), "old_text": "old", "new_text": "new"}))


@pytest.mark.asyncio
@pytest.mark.parametrize("attempt", ["new_hash", "old_baseline_hash", "remove_verdict", "extra_claim"])
async def test_runtime_verdict_changes_only_by_producer_and_same_session_scene_edit_uses_current_value(tmp_path, monkeypatch, attempt):
    from scripts.full_benchmark_scope import benchmark_method_tool_scope
    from server.agent import ToolCall
    from server.agent.session_models import AgentSession
    from server.contracts.implementation_evidence import IntegrationVerdict
    from server.services.method_contract_persistence import finalize_from_integration_verdict

    path, payload, expected = _method_scope_fixture(tmp_path)
    assert finalize_from_integration_verdict(path, tmp_path / "ideas/SELECTED_IDEA.json", Path("ideas/SELECTED_IDEA.json"),
                                             IntegrationVerdict(passed=True, report_sha256="b" * 64, issues=()))
    current = json.loads(path.read_text())
    assert current["integration_verdict"]["output_sha256"] == "b" * 64
    assert scientific_method_identity(tmp_path) == expected
    proposed = copy.deepcopy(current)
    if attempt == "remove_verdict":
        del proposed["integration_verdict"]
    elif attempt == "extra_claim":
        proposed["integration_verdict"]["claim_statement"] = "Unsupported successful transfer"
    else:
        proposed["integration_verdict"]["output_sha256"] = "a" * 64 if attempt == "old_baseline_hash" else "c" * 64
    original, calls = path.read_bytes(), []
    engine = _local_method_engine(monkeypatch, calls)
    session = AgentSession(project_path=str(tmp_path), workflow_node_id="exp-design", tool_policy="workflow_artifacts")
    with benchmark_method_tool_scope(engine, tmp_path, expected):
        result = await engine._execute_tool(session, ToolCall(id="forged-runtime-write", name="Write",
            arguments={"path": str(path), "content": json.dumps(proposed)}))
        assert not result.success and "integration_verdict is runtime-owned" in result.error
        assert not calls and path.read_bytes() == original
        repaired = await engine._execute_tool(session, ToolCall(id="scene-after-runtime", name="Edit", arguments={
            "path": str(path), "old_text": '"old-object"', "new_text": '"current-scene-object"'}))
    assert repaired.success and calls == [("Edit", str(path))]
    actual = json.loads(path.read_text())
    assert actual["integration_verdict"] == current["integration_verdict"]
    assert actual["implementation_checks"] == payload["implementation_checks"]
    assert scientific_method_identity(tmp_path) == expected
    assert not (tmp_path / ".merak/runs").exists()
