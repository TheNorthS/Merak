"""Pure temporary evidence and fake native boundaries; no provider or workflow runs."""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from scripts.full_benchmark_continuation import _authorized_continuation, execute_same_benchmark
from scripts.full_benchmark_continuation_scope import file_sha256, validate_continuation_identity
from scripts.full_benchmark_failure import (
    BenchmarkContinuationFailure, ContinuationObservation, failure_observation, observe_continuation,
)
from scripts.full_benchmark_natural_failure import build_natural_failure, validate_natural_failure_history
from scripts.resume_full_benchmark_workflow import _failed_result
from server.tests.test_full_benchmark_continuation import (
    RUN, SOURCE_RUN, FakeResumeHost, _operator_fixture, _operator_identity, _pins, _write, stopped,
)


def _fixture(value, monkeypatch):
    """Declare real finite source bytes and explicit fixture-only operator observations."""
    from server.services import frozen_benchmark_authority as authority

    monkeypatch.setattr(authority, "historical_inputs_digest", lambda *_: "a" * 64)
    monkeypatch.setattr(authority, "benchmark_inventory_digest", lambda *_: "b" * 64)
    context = {"historical_inputs_pin": "a" * 64, "benchmark_inventory_pin": "b" * 64,
               "settings": {"fixture_scope": "Finite immutable local evidence; never executed"}}
    archive = value.root / f".merak/benchmark-continuations/{RUN}/{'a' * 32}/report.previous.json"
    _write(archive, value.report)
    before_report, before_state, before_trace = _pins(value)
    report = {**value.report, "continuation": True,
        "issues": ["ValueError: current table source row binding is missing"],
        "current_continuation_roots_unchanged": True, "frozen_scientific_inputs_unchanged": True,
        "originals_unchanged_scope": "current_continuation_only",
        "manual_qa_directed_revision": {"requested": True, "producer_invocation_observed": False,
                                       "quality_acceptance_granted_by_receipt": False}}
    report.pop("blocked_operations")
    _write(value.root / "FULL_BENCHMARK_REPORT.json", report)
    launcher = value.repository / "verification-logs-finite-launch" / "start_authorized_continuation.py"
    launcher.parent.mkdir()
    command = ["local-fixture-interpreter", "-B", "local-fixture-cli", "--run-id", RUN,
               "--previous-report-sha256", before_report, "--previous-state-sha256", before_state,
               "--previous-trace-sha256", before_trace, "--allow-real-models"]
    launcher.write_text("# Static source identity only; this command is never executed.\ncommand = " + repr(command))
    now = datetime.now(timezone.utc)
    observation = {"schema": 1, "kind": "post_failure_operator_launch_observation",
        "recorded_after_failure": True, "evidence_source": "prior_root_tool_results", "recorded_at": now.isoformat(),
        "launcher_path": str(launcher), "launcher_current_sha256": file_sha256(launcher),
        "source_hash_observability": "current_read_only_not_launch_time", "failure_boundary": "native_resume_prevalidation",
        "prelaunch_pins": {"run_id": RUN, "previous_report_sha256": before_report,
            "previous_state_sha256": before_state, "previous_trace_sha256": before_trace},
        "launch": {"launcher_pid": 12345, "parent_pid": 12344, "base_pid": 12346, "base_parent_pid": 12345,
            "created_at_utc": (now - timedelta(seconds=3)).isoformat(),
            "observed_at_utc": (now - timedelta(seconds=2)).isoformat(), "argv": ["-B", str(launcher)]},
        "confirmed_inactive_pids": [12345, 12346],
    }
    receipt = build_natural_failure(value.root, value.source, value.original, value.reference,
        RUN, archive, context, observation, repository=value.repository)
    path = value.root / f".merak/benchmark-natural-failures/{RUN}/{'b' * 32}/natural-failure.json"
    _write(path, receipt)
    return {"archive": archive, "observation": observation, "context": context, "receipt": receipt,
            "path": path, "pin": file_sha256(path), "report": report, "launcher": launcher}


def _identity(value, fixture, **overrides):
    return validate_continuation_identity(value.root, value.source, value.original, RUN, SOURCE_RUN,
        *_pins(value), reference=value.reference, natural_failure_receipt=overrides.get("path", fixture["path"]),
        natural_failure_pin=overrides.get("pin", fixture["pin"]))


def test_explicit_natural_failure_is_readonly_unknown_and_not_cancelled_or_accepted(stopped, monkeypatch):
    fixture = _fixture(stopped, monkeypatch)
    before = {p: p.read_bytes() for p in stopped.repository.rglob("*") if p.is_file()}
    identity = _identity(stopped, fixture)
    assert identity["state"]["status"] == "incomplete"
    assert identity["state"]["phases"] == stopped.state["phases"]
    assert identity["prior_workflow_acceptance_granted"] is False
    assert identity["natural_failure_history"]["blocked_operations"] is None
    assert identity["natural_failure_history"]["blocked_operations_observability"] == "unknown"
    assert fixture["receipt"]["accepted"] is False and fixture["receipt"]["past_quality_established"] is False
    assert fixture["receipt"]["launch_observation"]["recorded_after_failure"] is True
    assert all(p.read_bytes() == raw for p, raw in before.items())


def test_unknown_failure_does_not_enter_ordinary_observed_admission(stopped, monkeypatch):
    fixture = _fixture(stopped, monkeypatch)
    with pytest.raises(ValueError, match="observability"):
        validate_continuation_identity(stopped.root, stopped.source, stopped.original, RUN, SOURCE_RUN, *_pins(stopped))
    with pytest.raises(ValueError, match="receipt changed"):
        _identity(stopped, fixture, pin="0" * 64)
    with pytest.raises(ValueError, match="explicit receipt"):
        _identity(stopped, fixture, pin="")


@pytest.mark.parametrize("defect", ["phase", "archive", "trace", "source", "science", "numbers", "reference",
    "claim", "active", "marker", "launcher", "before_pin", "invented_launch_hash", "unsafe_error",
    "blocked", "boundaries", "producer", "accepted", "receipt", "authority", "boolean_schema",
    "invalid_pid", "invalid_datetime", "invalid_inactive", "fictional_durable_launch"])
def test_natural_receipt_refuses_stale_active_unsafe_or_unobserved_evidence(stopped, monkeypatch, defect):
    fixture = _fixture(stopped, monkeypatch)
    if defect == "phase":
        state = copy.deepcopy(stopped.state)
        state["phases"]["figure"]["status"] = "accepted"
        _write(stopped.root / f".merak/runs/{RUN}.json", state)
    elif defect == "archive":
        _write(fixture["archive"], {**stopped.report, "phases": {}})
    elif defect == "trace":
        path = stopped.root / f".merak/runs/{RUN}.skills.json"
        _write(path, {**json.loads(path.read_text()), "stages": {"new": {"completed": True}}})
    elif defect in {"source", "science", "numbers"}:
        name = {"source": "experiments/src/frozen.txt", "science": "experiments/METHOD_CONTRACT.json",
                "numbers": "experiments/results/simulated/result.csv"}[defect]
        (stopped.root / name).write_text("changed scientific input")
    elif defect == "reference":
        (stopped.reference / "changed.txt").write_text("Changed independently frozen reference")
    elif defect in {"claim", "active", "marker"}:
        if defect == "claim":
            state = copy.deepcopy(stopped.state)
            state["resume_claim"] = {"token": "other", "expires_at": 9999999999}
            _write(stopped.root / f".merak/runs/{RUN}.json", state)
        elif defect == "active":
            _write(stopped.root / ".merak/active-workflow.json", {"token": "other", "expires_at": 9999999999})
        else:
            (stopped.root / ".merak/active-workflow.claim").write_text("Uncommitted foreign claim")
    elif defect == "launcher":
        fixture["launcher"].write_text("command = []")
    elif defect in {"before_pin", "invented_launch_hash", "receipt", "boolean_schema",
                   "invalid_pid", "invalid_datetime", "invalid_inactive", "fictional_durable_launch"}:
        receipt = copy.deepcopy(fixture["receipt"])
        if defect == "before_pin": receipt["launch_observation"]["prelaunch_pins"]["previous_trace_sha256"] = "0" * 64
        elif defect == "invented_launch_hash": receipt["launch_observation"]["source_hash_observability"] = "at_launch"
        elif defect == "boolean_schema": receipt["schema"] = True
        elif defect == "invalid_pid": receipt["launch_observation"]["launch"]["launcher_pid"] = True
        elif defect == "invalid_datetime": receipt["launch_observation"]["launch"]["created_at_utc"] = None
        elif defect == "invalid_inactive": receipt["launch_observation"]["confirmed_inactive_pids"] = [{}]
        elif defect == "fictional_durable_launch": receipt["launch_observation"]["recorded_after_failure"] = False
        else: receipt["workflow_acceptance_granted"] = True
        _write(fixture["path"], receipt)
        fixture["pin"] = file_sha256(fixture["path"])
    elif defect == "authority":
        from server.services import frozen_benchmark_authority as authority
        monkeypatch.setattr(authority, "historical_inputs_digest", lambda *_: "c" * 64)
    else:
        report = copy.deepcopy(fixture["report"])
        if defect == "unsafe_error": report["issues"] = ["PermissionError: denied scientific execution"]
        elif defect == "blocked": report["blocked_operations"] = ["Bash"]
        elif defect == "boundaries": report["current_continuation_roots_unchanged"] = False
        elif defect == "producer": report["manual_qa_directed_revision"]["producer_invocation_observed"] = True
        else: report["accepted"] = True
        _write(stopped.root / "FULL_BENCHMARK_REPORT.json", report)
    with pytest.raises((ValueError, json.JSONDecodeError)):
        _identity(stopped, fixture)


@pytest.mark.parametrize("defect", ["none", "erased", "false_known"])
def test_later_fully_observed_report_keeps_prior_unknown_natural_history(stopped, monkeypatch, defect):
    fixture = _fixture(stopped, monkeypatch)
    identity = _identity(stopped, fixture)
    report = {**stopped.report, "natural_failure_history": identity["natural_failure_history"],
              "continuation_identity": {"natural_failure_receipt_sha256": fixture["pin"]}}
    if defect == "erased": report.pop("natural_failure_history")
    if defect == "false_known": report["natural_failure_history"]["blocked_operations"] = []
    _write(stopped.root / "FULL_BENCHMARK_REPORT.json", report)
    if defect == "none":
        normal = validate_continuation_identity(stopped.root, stopped.source, stopped.original, RUN, SOURCE_RUN, *_pins(stopped))
        assert normal["natural_failure_history"]["blocked_operations"] is None
    else:
        with pytest.raises(ValueError, match="observability"):
            validate_natural_failure_history(stopped.root, RUN, report)


@pytest.mark.asyncio
async def test_new_native_resume_still_uses_all_current_gates_and_does_not_stamp_phases(stopped, monkeypatch):
    fixture = _fixture(stopped, monkeypatch)
    identity = _identity(stopped, fixture)
    host = FakeResumeHost(stopped)
    before = (stopped.root / f".merak/runs/{RUN}.json").read_bytes()
    observation = ContinuationObservation(guards_entered=True)
    result = await execute_same_benchmark(host, stopped.root, RUN, stopped.config, observation=observation)
    assert identity["prior_workflow_acceptance_granted"] is False and result["accepted"] is False
    assert observation.native_resume_entered and observation.execute_entered and observation.worker_entered
    assert len([call for call in host.calls if call[0] == "gate"]) == 13
    assert (stopped.root / f".merak/runs/{RUN}.json").read_bytes() == before


@pytest.mark.asyncio
@pytest.mark.parametrize("blocked,secondary", [([], False), (["Bash"], False), ([], True)])
async def test_captured_failure_reaches_cli_without_losing_original_cause_or_guard_list(stopped, blocked, secondary):
    observation = ContinuationObservation(blocked_operations=list(blocked), guards_entered=True,
                                          native_resume_entered=True)
    primary = ValueError("Actual source prevalidation failed")
    async def operation():
        raise primary
    async def shutdown():
        if secondary:
            raise OSError("Actual cleanup storage error")
    with pytest.raises(BenchmarkContinuationFailure) as failed:
        await observe_continuation(operation, shutdown, observation)
    error = failed.value
    assert error.__cause__ is primary and error.primary is primary
    error.context["previous_report_archive"] = "actual-native-archive"
    report = _failed_result(stopped.root, RUN, {"previous_report": stopped.report}, error)
    assert report["accepted"] is False and report["issues"] == ["ValueError: Actual source prevalidation failed"]
    assert report["blocked_operations"] == blocked and report["blocked_operations_observability"] == "complete"
    assert report["failure_observation"]["execute_entered"] is False
    assert report["failure_observation"]["worker_entered"] is False
    assert bool(report["shutdown_error"]) is secondary
    assert report["previous_report_archive"] == "actual-native-archive"


@pytest.mark.asyncio
async def test_uncaptured_setup_and_unexpected_errors_never_become_empty_success_history():
    assert failure_observation(ValueError("Setup failed"))["blocked_operations"] is None
    calls = []
    async def operation():
        raise TypeError("Unexpected programmer defect")
    async def shutdown():
        calls.append("shutdown")
    with pytest.raises(TypeError, match="Unexpected"):
        await observe_continuation(operation, shutdown, ContinuationObservation())
    assert calls == ["shutdown"]


@pytest.mark.asyncio
@pytest.mark.parametrize("blocked", [False, True])
async def test_actual_authorized_guard_boundary_captures_preworker_error_and_real_denied_tool(stopped, blocked):
    from server.agent.engine import agent_engine
    from scripts.live_snapshot_safety import SnapshotSafetyError
    from unittest.mock import patch

    calls = []
    async def forbidden_handler():
        pytest.fail("The real blocked-tool guard must reject before the fixture handler")
    class Host:
        _running_tasks = {}
        async def _execute_managed_experiment(self, *_args, **_kwargs):
            pytest.fail("Pure fixture must never execute science")
        async def execute(self, **_arguments):
            pytest.fail("Native prevalidation failure must not enter any workflow worker")
        async def resume_persisted_run(self, *_args, **_kwargs):
            calls.append("native_resume")
            if blocked:
                await agent_engine._tools["Bash"]()
            raise ValueError("Actual finite fixture prevalidation refusal")
        async def shutdown(self):
            calls.append("shutdown")
    with patch.dict(agent_engine._tools, {"Bash": forbidden_handler}):
        with pytest.raises(BenchmarkContinuationFailure) as failure:
            await _authorized_continuation(Host(), stopped.root, RUN, stopped.config, "")
    observation = failure.value.observation
    assert observation["guards_entered"] is observation["native_resume_entered"] is True
    assert observation["execute_entered"] is observation["worker_entered"] is False
    assert observation["failure_boundary"] == "native_resume_prevalidation"
    assert observation["blocked_operations"] == (["Bash"] if blocked else [])
    assert observation["safety_violation"] is blocked
    assert isinstance(failure.value.primary, SnapshotSafetyError if blocked else ValueError)
    assert calls == ["native_resume", "shutdown"]
    assert (stopped.root / f".merak/runs/{RUN}.json").read_text() == json.dumps(stopped.state)


def test_natural_recovery_retains_existing_genuine_unknown_operator_history(stopped, monkeypatch):
    from server.workflows.run_state import RunState

    operator = _operator_fixture(stopped, monkeypatch)
    prior = _operator_identity(stopped, operator)
    durable = RunState(str(stopped.root), RUN)
    durable.set_run_status("incomplete")
    stopped.state = durable.load()
    stopped.report = {**stopped.report,
        "phases": {name: row["status"] for name, row in stopped.state["phases"].items()},
        "interruption_history": prior["interruption_history"],
        "continuation_identity": {"operator_interruption_receipt_sha256": operator.receipt_pin}}
    _write(stopped.root / "FULL_BENCHMARK_REPORT.json", stopped.report)
    fixture = _fixture(stopped, monkeypatch)
    before = {path: path.read_bytes() for path in stopped.repository.rglob("*") if path.is_file()}
    identity = _identity(stopped, fixture)
    assert identity["interruption_history"] == prior["interruption_history"]
    assert identity["interruption_history"]["blocked_operations_observability"] == "unknown"
    assert identity["natural_failure_history"]["blocked_operations"] is None
    assert fixture["receipt"]["interruption_history"] == prior["interruption_history"]
    assert all(path.read_bytes() == raw for path, raw in before.items())
