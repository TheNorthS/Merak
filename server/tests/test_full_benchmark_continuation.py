"""Temporary-fixture continuation policy tests; no real workflow/provider runs."""

from __future__ import annotations

import asyncio
import copy
import json
import os
from pathlib import Path
from types import SimpleNamespace
import sys
import time

import pytest

from scripts.full_benchmark_continuation import execute_same_benchmark, prepare_continuation
from scripts.full_benchmark_continuation_scope import (
    file_sha256, validate_continuation_identity, validate_project_roots, validate_stopped_run,
)
from scripts.full_benchmark_preparation import stage_target_declarations
from scripts.full_benchmark_scope import (
    FROZEN_WORKFLOW_INPUTS, MODEL_OWNER, PIPELINE_NODES,
    benchmark_method_tool_scope, install_benchmark_write_guard, scientific_method_identity,
)
from scripts.verify_full_benchmark_workflow import _pipeline_options
from server.services.workflow_inputs import workflow_input_service
from server.utils.atomic_write import atomic_write_json
from server.workflows.run_state import RunState


RUN = "123456abcdef"
SOURCE_RUN = "abcdef123456"


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _inputs(root):
    root.mkdir()
    for relative in FROZEN_WORKFLOW_INPUTS:
        path = root / relative
        if not path.suffix:
            path /= "frozen.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Unchanged registered input, never executed.")
    _write(root / "experiments/METHOD_CONTRACT.json", {"schema": 2,
        "claim_evidence_plan": [{"idea_claim_id": "C1", "outcomes": ["Registered hypothesis"]}],
        "mechanism_coverage": [], "scientific_scene": {"schema": 1}})
    _write(root / "experiments/RUN_SPEC.json", {"protocol_id": "CSFS-v1", "run_experiment_authorized": False})
    _write(root / "experiments/results/simulated/SIMULATION_MANIFEST.json", {"schema": 1, "scientific": "frozen"})
    _write(root / "experiments/results/templates/PLANNED_RESULT_MANIFEST.json", {"schema": 1, "scientific": "frozen"})
    (root / "experiments/results/simulated/result.csv").write_text("method,score\nfrozen,0.5\n")


@pytest.fixture
def stopped(tmp_path):
    root, source = tmp_path / "full-benchmark-verification-fixture", tmp_path / "protocol-implementation-fixture"
    original, reference = tmp_path / "original", tmp_path / "reference"
    for path in (root, source):
        _inputs(path)
    original.mkdir()
    reference.mkdir()
    run_spec = json.loads((root / "experiments/RUN_SPEC.json").read_text())
    _write(root / "experiments/RUN_SPEC.json", {**run_spec, "implementation_stage_targets": stage_target_declarations()})
    config = {"direction": "Registered benchmark", "effort": "balanced", "assurance": "draft",
        "options": _pipeline_options({"options": {"research_mode": "from_scratch"}}, True)}
    phases = {name: {"id": name, "status": "accepted" if index < 7 else "pending",
        "verdict_id": "genuine-fixture-" + name if index < 7 else "",
        "reviewer": "fixture-runtime-owner" if index < 7 else "", "accepted_at": 100 if index < 7 else None,
        "details": {"execution_evidence": {"accepted": index < 7, "issues": []}}}
        for index, name in enumerate(PIPELINE_NODES)}
    phases["figure"]["status"] = "awaiting_revision"
    baseline = workflow_input_service.capture(str(root), list(FROZEN_WORKFLOW_INPUTS), run_id=RUN)
    state = {"schema": 1, "run_id": RUN, "status": "incomplete", "config": config,
        "phases": phases, "input_baseline": baseline}
    _write(root / f".merak/runs/{RUN}.json", state)
    _write(root / f".merak/runs/{RUN}.skills.json", {"schema": 2, "run_id": RUN, "project_path": str(root), "stages": {}})
    _write(root / f".merak/runs/{RUN}.specialists.json", {"schema": 1, "run_id": RUN})
    evidence = {"source_run_id": SOURCE_RUN, "historical_only": True, "reusable_prior_run_installed": False}
    for label, suffix, pin_name in (("run", ".json", "source_run_sha256"), ("skills", ".skills.json", "source_trace_sha256")):
        current = original / f".merak/runs/{SOURCE_RUN}{suffix}"
        _write(current, {"run_id": SOURCE_RUN, "status": "cancelled"})
        archive = root / f".merak/source-evidence/{SOURCE_RUN}.{label}.original.json"
        archive.parent.mkdir(parents=True, exist_ok=True)
        archive.write_bytes(current.read_bytes())
        evidence[pin_name] = file_sha256(current)
    report = {"run_id": RUN, "status": "incomplete", "accepted": False, "real_model_execution": True,
        "training_authorized": False, "original_workflow_resumed": False, "originals_unchanged": True,
        "raw_numerical_and_semantic_bundle_unchanged": True, "blocked_operations": [], "source_owner_reuse": {},
        "logical_pipeline_nodes": list(PIPELINE_NODES), "snapshot_path": str(root), "source_evidence": evidence,
        "phases": {name: row["status"] for name, row in phases.items()}}
    _write(root / "FULL_BENCHMARK_REPORT.json", report)
    return SimpleNamespace(root=root, source=source, original=original, reference=reference,
        repository=tmp_path, state=state, report=report, config=config)


def _pins(value):
    return [file_sha256(value.root / name) for name in ("FULL_BENCHMARK_REPORT.json",
        f".merak/runs/{RUN}.json", f".merak/runs/{RUN}.skills.json")]


def _identity(value, pins=None):
    return validate_continuation_identity(value.root, value.source, value.original, RUN, SOURCE_RUN, *(pins or _pins(value)))


def test_readonly_admission_preserves_exact_run_and_every_accepted_owner(stopped):
    before = {path: path.read_bytes() for path in stopped.repository.rglob("*") if path.is_file()}
    assert validate_project_roots(stopped.root, stopped.source, stopped.original,
        stopped.reference, stopped.repository) == (stopped.root, stopped.source, stopped.original, stopped.reference)
    identity = _identity(stopped)
    assert identity["state"] == stopped.state
    assert [name for name, row in identity["state"]["phases"].items() if row["status"] == "accepted"] == list(PIPELINE_NODES[:7])
    assert all(path.read_bytes() == raw for path, raw in before.items())


@pytest.mark.parametrize("defect", ["numbers", "source", "science", "plan", "run_spec", "target_mapping", "archive", "trace", "report"])
def test_changed_scientific_inputs_or_observed_proof_cannot_be_accepted(stopped, defect):
    pins = _pins(stopped)
    if defect == "numbers":
        (stopped.root / "experiments/results/simulated/result.csv").write_text("method,score\nfrozen,0.9\n")
    elif defect == "source":
        (stopped.root / "experiments/src/frozen.txt").write_text("Changed implementation")
    elif defect == "plan":
        (stopped.root / "experiments/EXPERIMENT_PLAN.md").write_text("Changed registered plan")
    elif defect == "science":
        _write(stopped.root / "experiments/METHOD_CONTRACT.json", {"schema": 2, "claim_evidence_plan": [], "mechanism_coverage": []})
    elif defect in {"run_spec", "target_mapping"}:
        path = stopped.root / "experiments/RUN_SPEC.json"
        value = json.loads(path.read_text())
        value["run_experiment_authorized" if defect == "run_spec" else "implementation_stage_targets"] = True
        _write(path, value)
    elif defect == "archive":
        (stopped.root / f".merak/source-evidence/{SOURCE_RUN}.run.original.json").write_text("{}")
    elif defect == "trace":
        _write(stopped.root / f".merak/runs/{RUN}.skills.json", {"schema": 2, "run_id": RUN, "project_path": "foreign"})
    else:
        _write(stopped.root / "FULL_BENCHMARK_REPORT.json", {**stopped.report, "training_authorized": True})
    with pytest.raises(ValueError):
        _identity(stopped, pins)


@pytest.mark.parametrize("defect", ["running", "completed", "claim", "project_claim", "claim_marker", "nodes", "execution", "automatic", "baseline"])
def test_active_or_unapproved_saved_scope_refused_before_provider_setup(stopped, defect):
    state = copy.deepcopy(stopped.state)
    if defect in {"running", "completed"}:
        state["status"] = defect
    elif defect == "claim":
        state["resume_claim"] = {"token": "another-owner", "renewed_at": time.time(), "expires_at": time.time() + 60}
    elif defect == "project_claim":
        _write(stopped.root / ".merak/active-workflow.json", {"token": "another-owner",
            "renewed_at": time.time(), "expires_at": time.time() + 60})
    elif defect == "claim_marker":
        (stopped.root / ".merak/active-workflow.claim").write_text("Concurrent claim not committed yet")
    elif defect == "nodes":
        state["phases"].pop("lit")
    elif defect == "execution":
        state["config"]["options"]["run_experiment"] = True
    elif defect == "automatic":
        state["config"]["options"]["platform_auto_recovery"] = True
    else:
        state["input_baseline"] = {}
    _write(stopped.root / f".merak/runs/{RUN}.json", state)
    with pytest.raises(ValueError):
        validate_stopped_run(stopped.root, RUN)


def test_foreign_root_and_hardlinked_copy_refused(stopped):
    with pytest.raises(ValueError):
        validate_project_roots(stopped.original, stopped.source, stopped.root, stopped.reference, stopped.repository)
    linked = stopped.root / "experiments/shared-science.txt"
    try:
        os.link(stopped.source / "experiments/src/frozen.txt", linked)
    except OSError:
        pytest.skip("Hard links unavailable for temporary fixture")
    with pytest.raises(ValueError, match="hard-linked"):
        validate_project_roots(stopped.root, stopped.source, stopped.original, stopped.reference, stopped.repository)


def _guard(stopped, monkeypatch):
    hooks = []
    monkeypatch.setattr(sys, "addaudithook", hooks.append)
    install_benchmark_write_guard(stopped.root, rerun_literature=True, rerun_source_owners=True, continuing_run_id=RUN)
    assert len(hooks) == 1
    return hooks[0]


def test_continuation_guard_only_native_current_three_records_can_change(stopped, monkeypatch):
    history = stopped.root / ".merak/runs/aaaaaaaaaaaa.json"
    invocation = stopped.root / ".merak/skill-invocations/prior.json"
    search = stopped.root / f".merak/runs/{RUN}.search-evidence.json"
    for path in (history, invocation, search):
        _write(path, {"immutable": True})
    audit = _guard(stopped, monkeypatch)
    for suffix in (".json", ".skills.json", ".specialists.json"):
        path = stopped.root / f".merak/runs/{RUN}{suffix}"
        audit("open", (path, "w", 0))
        temporary = path.with_name("." + path.name + ".1.2." + "a" * 32 + ".tmp")
        audit("open", (temporary, "w", 0))
        audit("os.rename", (temporary, path))
        token = MODEL_OWNER.set("figure")
        try:
            for candidate in (path, temporary):
                with pytest.raises(PermissionError, match="runtime-owned"):
                    audit("open", (candidate, "w", 0))
            with pytest.raises(PermissionError, match="runtime-owned"):
                audit("os.rename", (temporary, path))
        finally:
            MODEL_OWNER.reset(token)
    for path in (history, invocation, search, stopped.original / "foreign.json"):
        with pytest.raises(PermissionError):
            audit("open", (path, "w", 0))
        temporary = path.with_name("." + path.name + ".1.2." + "b" * 32 + ".tmp")
        with pytest.raises(PermissionError):
            audit("os.rename", (temporary, path))


@pytest.mark.parametrize("bad_id", ["", "not-a-hex-id", "123456ABCDEF", "../123456abcdef"])
def test_continuation_guard_cannot_be_installed_for_unverified_identity(stopped, monkeypatch, bad_id):
    hooks = []
    monkeypatch.setattr(sys, "addaudithook", hooks.append)
    if bad_id == "":
        install_benchmark_write_guard(stopped.root)
        with pytest.raises(PermissionError):
            hooks[0]("open", (stopped.root / f".merak/runs/{RUN}.json", "w", 0))
    else:
        with pytest.raises(ValueError):
            install_benchmark_write_guard(stopped.root, continuing_run_id=bad_id)
        assert hooks == []


@pytest.mark.asyncio
async def test_whole_offline_receipt_rejection_precedes_any_provider_or_copy_write(stopped, monkeypatch):
    import scripts.full_benchmark_continuation as runner
    import server.agent as agent
    called = []
    def refused(_receipt):
        raise ValueError("Current whole offline receipt required")
    monkeypatch.setattr(runner, "validate_offline_receipt", refused)
    monkeypatch.setattr(agent, "init_models_from_config", lambda *_: called.append("forbidden-provider"))
    before = {path: path.read_bytes() for path in stopped.root.rglob("*") if path.is_file()}
    with pytest.raises(ValueError, match="whole offline"):
        await prepare_continuation(stopped.root, RUN, stopped.root / "offline.json", {}, _identity(stopped))
    assert called == [] and all(path.read_bytes() == raw for path, raw in before.items())


class FakeResumeHost:
    """Fixture adapter records native-resume arguments; never executes a research node."""

    def __init__(self, stopped, defect=""):
        self.root, self.defect = stopped.root, defect
        self._running_tasks, self._runs, self.calls = {}, {}, []

    def _get_default_nodes(self):
        return [SimpleNamespace(id=name) for name in PIPELINE_NODES]

    async def execute(self, **arguments):
        self.calls.append(("execute", arguments))
        async def worker():
            return None
        self._running_tasks[RUN] = asyncio.create_task(worker())
        self._runs[RUN] = SimpleNamespace(id=RUN)
        return RUN

    async def resume_persisted_run(self, run_id, root, **arguments):
        self.calls.append(("native_resume", run_id, root, arguments))
        options = {**arguments["pipeline_options"], "resume_run_id": run_id}
        if self.defect == "execution": options["run_experiment"] = True
        if self.defect == "foreign": root = str(self.root.parent / "foreign")
        return await self.execute(project_path=root, node_ids=arguments["node_ids"], pipeline_options=options)

    def _acceptance_gate(self, node, run, _assurance, _result, *, require_fresh):
        self.calls.append(("gate", node.id, run.id, require_fresh))
        return {"accepted": True, "details": {"execution_evidence": {"accepted": True, "issues": []}}}


@pytest.mark.asyncio
async def test_same_run_resume_passes_all_nodes_and_asset_feedback_without_stamping_acceptance(stopped):
    host = FakeResumeHost(stopped)
    raw = (stopped.root / f".merak/runs/{RUN}.json").read_bytes()
    feedback = "method_architecture: repair the registered source projection and split the overview."
    result = await execute_same_benchmark(host, stopped.root, RUN, stopped.config, checkpoint_feedback=feedback)
    resume = host.calls[0]
    assert resume[0:3] == ("native_resume", RUN, str(stopped.root))
    assert resume[3]["node_ids"] == list(PIPELINE_NODES) and resume[3]["resume_source"] == "explicit"
    assert resume[3]["checkpoint_feedback"] == feedback
    assert resume[3]["pipeline_options"]["run_experiment"] is False
    assert len([call for call in host.calls if call[0] == "gate"]) == 13
    assert result["accepted"] is False and result["run_id"] == RUN and result["status"] == "incomplete"
    assert (stopped.root / f".merak/runs/{RUN}.json").read_bytes() == raw


@pytest.mark.asyncio
@pytest.mark.parametrize("defect", ["execution", "foreign"])
async def test_resume_execution_scope_blocks_foreign_or_scientific_native_request(stopped, defect):
    host = FakeResumeHost(stopped, defect)
    with pytest.raises(PermissionError, match="exact non-training"):
        await execute_same_benchmark(host, stopped.root, RUN, stopped.config)
    assert not host._running_tasks and not host._runs


def test_parser_requires_model_consent_and_all_observed_pins():
    from scripts.resume_full_benchmark_workflow import _parser
    with pytest.raises(SystemExit):
        _parser().parse_args([])
    names = {action.dest for action in _parser()._actions if action.required}
    assert {"allow_real_models", "previous_report_sha256", "previous_state_sha256", "previous_trace_sha256"} <= names


def test_native_figure_feedback_does_not_blanket_reopen_two_asset_budgets(stopped):
    from server.workflows.resume_execution import _validate_figure_feedback_scope

    stopped.state["phases"]["figure"]["details"]["revision"] = {"last_gate": {
        "error_category": "figure_retry_deferred", "repair_scope": {
            "asset_ids": ["method_architecture", "evaluation_design"]}}}
    for feedback in ("Continue and make everything pass", "method_architecture and evaluation_design: repair both"):
        with pytest.raises(ValueError, match="asset ID"):
            _validate_figure_feedback_scope(list(PIPELINE_NODES), stopped.state, feedback, str(stopped.root), RUN)
    _validate_figure_feedback_scope(list(PIPELINE_NODES), stopped.state,
        "method_architecture: repair this registered source projection", str(stopped.root), RUN)


def test_runtime_state_acceptance_cannot_be_forged_by_model_under_real_atomic_writer(stopped, monkeypatch):
    import builtins
    import io

    audit = _guard(stopped, monkeypatch)
    original_open, original_io_open = builtins.open, io.open

    def adapter(original):
        def guarded(path, mode="r", *args, **kwargs):
            audit("open", (path, mode, 0))
            return original(path, mode, *args, **kwargs)
        return guarded

    monkeypatch.setattr(builtins, "open", adapter(original_open))
    monkeypatch.setattr(io, "open", adapter(original_io_open))
    durable = RunState(str(stopped.root), RUN)
    before = durable.path.read_bytes()
    token = MODEL_OWNER.set("paper")
    try:
        with pytest.raises(PermissionError, match="runtime-owned"):
            durable.accept("lit", "forged", "model-authored")
    finally:
        MODEL_OWNER.reset(token)
    assert durable.path.read_bytes() == before
    durable.record_transport_retry("figure", {"fixture_transport_error": "upstream unavailable"})
    current = durable.load()
    assert current["phases"]["lit"] == stopped.state["phases"]["lit"]
    assert current["phases"]["figure"]["details"]["transport_retry"]["fixture_transport_error"] == "upstream unavailable"


def _instrument_guard(stopped, monkeypatch):
    import builtins
    import io

    audit = _guard(stopped, monkeypatch)
    for module in (builtins, io):
        original = module.open
        def guarded(path, mode="r", *args, _original=original, **kwargs):
            audit("open", (path, mode, 0))
            return _original(path, mode, *args, **kwargs)
        monkeypatch.setattr(module, "open", guarded)
    return audit


def _real_delegate_observer(stopped):
    from server.services.skill_execution_trace import SkillExecutionTrace
    from server.workflows.models import WorkflowNode, WorkflowRun
    from server.workflows.node_agent_events import NodeAgentEventObserver

    async def emitted(*_arguments):
        return None
    host = SimpleNamespace(_agent_event_counts_as_progress=lambda _event: True,
        _emit=emitted, _tool_artifact_path=lambda _data: "",
        _skill_invocation_traces=lambda *_args: [])
    run = WorkflowRun(id=RUN, project_path=str(stopped.root))
    tracer = SkillExecutionTrace(SimpleNamespace(total_skills=0, get_skill=lambda _name: None))
    return NodeAgentEventObserver(host, run, WorkflowNode("figure", "Figure", "/paper-figure"),
        SimpleNamespace(id="fixture-parent-session"), tracer, set()), tracer


@pytest.mark.asyncio
async def test_untrusted_model_context_cannot_update_current_trace_even_via_real_repository(stopped, monkeypatch):
    _instrument_guard(stopped, monkeypatch)
    observer, _tracer = _real_delegate_observer(stopped)
    before = (stopped.root / f".merak/runs/{RUN}.skills.json").read_bytes()
    token = MODEL_OWNER.set("figure")
    try:
        with pytest.raises(PermissionError, match="runtime-owned"):
            await observer.dispatch(SimpleNamespace(type="tool_call", data={
                "name": "Skill", "args": {"skill_name": "figure-spec"}}))
    finally:
        MODEL_OWNER.reset(token)
    assert (stopped.root / f".merak/runs/{RUN}.skills.json").read_bytes() == before


@pytest.mark.asyncio
async def test_fake_skill_handler_real_delegate_trace_commits_without_science_owner_loss(stopped, monkeypatch):
    from scripts.full_benchmark_runtime_records import trusted_benchmark_runtime_records, trusted_runtime_record_target

    audit = _instrument_guard(stopped, monkeypatch)
    observer, _tracer = _real_delegate_observer(stopped)
    target = stopped.root / f".merak/runs/{RUN}.skills.json"
    state_before = (stopped.root / f".merak/runs/{RUN}.json").read_bytes()
    session = SimpleNamespace(workflow_node_id="figure")
    engine = SimpleNamespace()

    async def actual(session, tool):
        assert MODEL_OWNER.get() == "figure"
        if tool.name == "Write":
            atomic_write_json(target, {"schema": 2, "run_id": RUN, "stages": {"forged": "completed"}})
        else:
            await observer.dispatch(SimpleNamespace(type="tool_call", data={"name": "Skill", "args": {
                "skill_name": "figure-spec"}}))
            assert not trusted_runtime_record_target(target)
            with pytest.raises(PermissionError, match="runtime-owned"):
                await engine._execute_tool(session, SimpleNamespace(name="Write", arguments={"path": str(target), "content": "{}"}))
            with pytest.raises(PermissionError):
                audit("open", (stopped.root / "experiments/EXPERIMENT_PLAN.md", "w", 0))
            return "Fixture Skill begun; no model result or accepted state created"

    engine._execute_tool = actual
    with trusted_benchmark_runtime_records(stopped.root, RUN), benchmark_method_tool_scope(
            engine, stopped.root, scientific_method_identity(stopped.root)):
        await engine._execute_tool(session, SimpleNamespace(name="Skill", arguments={"skill_name": "figure-spec"}))
    value = json.loads(target.read_text())
    invocation = value["stages"]["figure"]["invocations"][-1]
    assert invocation["status"] == "running" and invocation["execution_verified"] is False
    assert value["run_id"] == RUN and invocation["role"] == "delegate"
    assert (stopped.root / f".merak/runs/{RUN}.json").read_bytes() == state_before
    assert not trusted_runtime_record_target(target) and MODEL_OWNER.get() == ""


@pytest.mark.parametrize("defect", ["foreign_run", "foreign_project", "prior_run", "other_runtime", "source_science"])
def test_trusted_trace_capability_cannot_update_other_state_or_foreign_science(stopped, monkeypatch, defect):
    from scripts.full_benchmark_runtime_records import trusted_benchmark_runtime_records
    from server.services import skill_execution_trace as traces

    _instrument_guard(stopped, monkeypatch)
    payload = json.loads((stopped.root / f".merak/runs/{RUN}.skills.json").read_text())
    target, actual_run = stopped.root / f".merak/runs/{RUN}.skills.json", RUN
    if defect == "foreign_run": actual_run = "ffffffffffff"
    if defect == "foreign_project": payload["project_path"] = str(stopped.original)
    if defect == "prior_run": target = stopped.root / ".merak/runs/ffffffffffff.skills.json"
    if defect in {"other_runtime", "source_science"}:
        forbidden = stopped.root / (f".merak/runs/{RUN}.json" if defect == "other_runtime" else "experiments/EXPERIMENT_PLAN.md")
        def attempted_wrong_record(_path, _payload):
            forbidden.write_text("forbidden replacement")
        monkeypatch.setattr(traces, "atomic_write_json", attempted_wrong_record)
    original = {path: path.read_bytes() for path in stopped.root.rglob("*") if path.is_file()}
    with trusted_benchmark_runtime_records(stopped.root, RUN):
        token = MODEL_OWNER.set("figure")
        try:
            with pytest.raises(PermissionError):
                traces.SkillExecutionTrace._write_payload(target, payload, actual_run, {}, 0)
        finally:
            MODEL_OWNER.reset(token)
    assert all(path.read_bytes() == raw for path, raw in original.items())


def _operator_fixture(stopped, monkeypatch):
    from scripts.full_benchmark_interruption import (
        EVENT, REASON, build_operator_interruption, object_sha256, operator_interruption_report,
    )
    from server.services import frozen_benchmark_authority as authority
    from server.services.workflow_event_journal import workflow_event_journal

    monkeypatch.setattr(authority, "historical_inputs_digest", lambda *_: "a" * 64)
    monkeypatch.setattr(authority, "benchmark_inventory_digest", lambda *_: "b" * 64)
    context = {"historical_inputs_pin": "a" * 64, "benchmark_inventory_pin": "b" * 64,
        "settings": {"fixture_scope": "Existing pinned structural numbers; no scientific execution"}}
    relative = f".merak/benchmark-continuations/{RUN}/0123456789abcdef/report.previous.json"
    _write(stopped.root / relative, stopped.report)
    durable = RunState(str(stopped.root), RUN)
    durable.set_status("paper", "running")
    durable.set_status("paper", "pending", error="Operator stopped only the private fixture worker")
    durable.set_run_status("cancelled")
    observation = {"terminated_worker_pid": 12345, "confirmed_inactive_pids": [12345, 12344], "observed_at": time.time() - 1}
    workflow_event_journal.record(stopped.root, RUN, EVENT, {"accepted": False,
        "operator_interruption": True, "reason": REASON, "blocked_operations": None,
        "blocked_operations_observability": "unknown", "stop_observation": observation,
        "state_sha256": file_sha256(durable.path),
        "trace_sha256": file_sha256(stopped.root / f".merak/runs/{RUN}.skills.json")})
    journal = stopped.root / f".merak/runs/{RUN}.events.jsonl"
    record = json.loads(journal.read_text().splitlines()[-1])
    receipt = build_operator_interruption(stopped.root, stopped.source, stopped.original,
        stopped.reference, RUN, relative, object_sha256(record), context, observation)
    receipt_relative = relative.replace("report.previous.json", "operator-interruption.json")
    _write(stopped.root / receipt_relative, receipt)
    receipt_pin = file_sha256(stopped.root / receipt_relative)
    report = operator_interruption_report(stopped.root, receipt, receipt_relative, receipt_pin)
    _write(stopped.root / "FULL_BENCHMARK_REPORT.json", report)
    return SimpleNamespace(receipt=receipt, receipt_path=stopped.root / receipt_relative,
        receipt_pin=receipt_pin, report=report, journal=journal, context=context)


def _operator_identity(stopped, operator, *, pin=None):
    return validate_continuation_identity(stopped.root, stopped.source, stopped.original, RUN, SOURCE_RUN,
        *_pins(stopped), reference=stopped.reference, operator_interruption_pin=pin or operator.receipt_pin)


def test_operator_interruption_truthfully_preserves_unknown_history_without_new_acceptance(stopped, monkeypatch):
    operator = _operator_fixture(stopped, monkeypatch)
    before = {path: path.read_bytes() for path in stopped.repository.rglob("*") if path.is_file()}
    identity = _operator_identity(stopped, operator)
    assert identity["state"]["status"] == "cancelled"
    assert identity["prior_blocked_operations_observability"] == "unknown"
    assert identity["prior_workflow_acceptance_granted"] is False
    assert identity["interruption_history"]["original_tree_change_observability"] == "unknown"
    assert operator.report["blocked_operations"] is operator.report["originals_unchanged"] is None
    assert operator.report["accepted"] is False and "current_gates" not in operator.report
    assert identity["state"]["phases"]["paper"]["status"] == "pending"
    for name in PIPELINE_NODES[:7]:
        assert identity["state"]["phases"][name] == stopped.state["phases"][name]
    assert all(path.read_bytes() == raw for path, raw in before.items())


def test_unknown_operator_report_requires_explicit_exact_receipt_pin(stopped, monkeypatch):
    operator = _operator_fixture(stopped, monkeypatch)
    with pytest.raises(ValueError, match="observability"):
        _identity(stopped)
    with pytest.raises(ValueError, match="receipt changed"):
        _operator_identity(stopped, operator, pin="0" * 64)


@pytest.mark.parametrize("defect", ["accepted", "blocked_empty", "trees_unchanged", "new_gate", "phase_status",
    "receipt", "journal", "new_journal_event", "state", "trace", "source", "numbers", "science", "reference", "authority"])
def test_operator_receipt_rejects_any_unobserved_or_changed_stop_evidence(stopped, monkeypatch, defect):
    operator = _operator_fixture(stopped, monkeypatch)
    if defect in {"accepted", "blocked_empty", "trees_unchanged", "new_gate", "phase_status"}:
        report = copy.deepcopy(operator.report)
        if defect == "accepted": report["accepted"] = True
        if defect == "blocked_empty": report["blocked_operations"] = []
        if defect == "trees_unchanged": report["originals_unchanged"] = True
        if defect == "new_gate": report["current_gates"] = {"figure": {"accepted": True}}
        if defect == "phase_status": report["phases"]["paper"] = "accepted"
        _write(stopped.root / "FULL_BENCHMARK_REPORT.json", report)
    elif defect == "receipt":
        _write(operator.receipt_path, {**operator.receipt, "workflow_acceptance_granted": True})
    elif defect == "journal":
        records = [json.loads(line) for line in operator.journal.read_text().splitlines()]
        records[-1]["data"]["reason"] = "unverified change"
        operator.journal.write_text("\n".join(json.dumps(record) for record in records))
    elif defect == "new_journal_event":
        with operator.journal.open("a") as handle:
            handle.write(json.dumps({"schema": 1, "run_id": RUN, "event": "node_started"}) + "\n")
    elif defect == "state":
        RunState(str(stopped.root), RUN).set_run_status("incomplete")
    elif defect == "trace":
        _write(stopped.root / f".merak/runs/{RUN}.skills.json", {"schema": 2, "run_id": RUN,
            "project_path": str(stopped.root), "stages": {"figure": {"forged": True}}})
    elif defect == "source":
        (stopped.source / "experiments/src/frozen.txt").write_text("Changed source after operator stop")
    elif defect == "numbers":
        (stopped.root / "experiments/results/simulated/result.csv").write_text("method,score\nfrozen,0.9\n")
    elif defect == "science":
        _write(stopped.root / "experiments/METHOD_CONTRACT.json", {"schema": 2, "mechanism_coverage": [], "claim_evidence_plan": []})
    elif defect == "reference":
        (stopped.reference / "changed.txt").write_text("Changed historical reference")
    else:
        from server.services import frozen_benchmark_authority as authority
        monkeypatch.setattr(authority, "historical_inputs_digest", lambda *_: "c" * 64)
    with pytest.raises(ValueError):
        _operator_identity(stopped, operator)


def test_receipt_cannot_override_active_claim_or_masquerade_as_ordinary_error(stopped, monkeypatch):
    operator = _operator_fixture(stopped, monkeypatch)
    _write(stopped.root / ".merak/active-workflow.json", {"token": "other-owner",
        "run_id": RUN, "expires_at": time.time() + 60, "renewed_at": time.time()})
    with pytest.raises(ValueError, match="active workflow"):
        _operator_identity(stopped, operator)


@pytest.mark.parametrize("defect", ["none", "erased", "false_complete"])
def test_subsequent_ordinary_continuation_retains_unknown_operator_history(stopped, monkeypatch, defect):
    operator = _operator_fixture(stopped, monkeypatch)
    identity = _operator_identity(stopped, operator)
    report = {**stopped.report, "status": "cancelled", "phases": operator.report["phases"],
        "interruption_history": identity["interruption_history"],
        "originals_unchanged_scope": "current_continuation_only",
        "continuation_identity": {"operator_interruption_receipt_sha256": operator.receipt_pin}}
    if defect == "erased": report.pop("interruption_history")
    if defect == "false_complete": report["interruption_history"]["original_tree_change_observability"] = "complete"
    _write(stopped.root / "FULL_BENCHMARK_REPORT.json", report)
    if defect == "none":
        restored = _identity(stopped)
        assert restored["interruption_history"]["original_tree_change_observability"] == "unknown"
    else:
        with pytest.raises(ValueError, match="observability"):
            _identity(stopped)
