"""Pure runner-scope checks; no provider, real workflow or LaTeX process runs."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import verify_live_remaining_snapshot as runner


def test_paid_cli_flag_is_compulsory_before_snapshot_creation_or_imports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(sys, "argv", ["verify_live_remaining_snapshot.py", "--project", str(tmp_path), "--run-id", "source-run"])
    monkeypatch.setattr(runner.tempfile, "mkdtemp", lambda **_kwargs: calls.append("forbidden creation"))
    with pytest.raises(SystemExit) as failure:
        runner.main()
    assert failure.value.code == 2
    assert calls == []


def test_offline_receipt_cli_flag_is_compulsory_before_paid_work(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["verify_live_remaining_snapshot.py", "--project", str(tmp_path),
                                     "--run-id", "source-run", "--allow-real-models"])
    monkeypatch.setattr(runner.tempfile, "mkdtemp", lambda **_kwargs: pytest.fail("No snapshot may be created before offline evidence"))
    with pytest.raises(SystemExit) as failure:
        runner.main()
    assert failure.value.code == 2


def test_narrative_revalidation_requires_its_explicit_cli_authorization(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["verify_live_remaining_snapshot.py", "--project", str(tmp_path),
                                     "--run-id", "source-run", "--allow-real-models", "--offline-report", "not-read.json"])
    monkeypatch.setattr(runner.tempfile, "mkdtemp", lambda **_kwargs: pytest.fail("Missing scope authorization must stop before copying"))
    with pytest.raises(SystemExit) as failure:
        runner.main()
    assert failure.value.code == 2


class _FakeHost:
    instances = []
    requested_options = None
    run_managed = False

    def __init__(self):
        self.executions = []
        self.managed_experiments = []
        self.shutdowns = 0
        self._running_tasks = {}
        self.instances.append(self)

    async def execute(self, **kwargs):
        self.executions.append(kwargs)
        return "source-run"

    async def _execute_managed_experiment(self, *_args, **_kwargs):
        self.managed_experiments.append("forbidden experiment")
        return "not authorized"

    async def resume_persisted_run(self, run_id, project_path, **kwargs):
        if self.run_managed:
            await self._execute_managed_experiment(SimpleNamespace(project_path=project_path))
        options = self.requested_options or {"node_ids": list(runner.REMAINING_NODES), "project_path": project_path,
                                             "pipeline_options": {"run_experiment": False, "resume_run_id": run_id}}
        await self.execute(**options)
        self._running_tasks[run_id] = asyncio.create_task(asyncio.sleep(0))
        return run_id

    async def shutdown(self):
        self.shutdowns += 1


def _fake_runtime(monkeypatch: pytest.MonkeyPatch, root: Path, options: dict | None = None, *, run_managed: bool = False) -> None:
    from server.workflows import engine, run_state

    _FakeHost.instances.clear()
    _FakeHost.requested_options = options
    _FakeHost.run_managed = run_managed
    monkeypatch.setattr(engine, "WorkflowEngine", _FakeHost)
    monkeypatch.setattr(run_state, "RunState", lambda *_args: SimpleNamespace(load=lambda: {
        "status": "completed", "phases": {name: {"status": "accepted"} for name in runner.REMAINING_NODES},
    }))


def test_only_remaining_nodes_execute_once_under_fake_body(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_runtime(monkeypatch, tmp_path)
    result = asyncio.run(runner.run_remaining(tmp_path, "source-run"))
    host = _FakeHost.instances[-1]
    assert len(host.executions) == 1
    assert host.executions[0]["node_ids"] == list(runner.REMAINING_NODES)
    assert host.executions[0]["pipeline_options"]["run_experiment"] is False
    assert host.shutdowns == 1
    assert result["accepted"] is True  # Runner aggregation only; the body/gates here are fixture boundaries.


def test_upstream_node_selection_is_rejected_before_fake_execution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_runtime(monkeypatch, tmp_path, {"node_ids": ["results", "paper"], "project_path": str(tmp_path),
                                       "pipeline_options": {"run_experiment": False}})
    with pytest.raises(RuntimeError, match="cannot restart upstream"):
        asyncio.run(runner.run_remaining(tmp_path, "source-run"))
    host = _FakeHost.instances[-1]
    assert host.executions == []
    assert host.shutdowns == 1


def test_scientific_execution_blocker_has_no_fake_success() -> None:
    with pytest.raises(RuntimeError, match="prohibits training, experiments and new simulation data"):
        runner.reject_scientific_execution()


def test_suppressed_notifications_are_explicitly_not_delivered() -> None:
    result = asyncio.run(runner.suppress_notification(channel="fixture"))
    assert result["delivered"] is False
    assert "disabled" in result["reason"]


@pytest.mark.parametrize("fault", ["foreign-project", "foreign-run", "training-true"])
def test_selected_execution_refuses_foreign_scope_before_any_fake_worker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str) -> None:
    options = {"node_ids": list(runner.REMAINING_NODES), "project_path": str(tmp_path),
               "pipeline_options": {"run_experiment": False, "resume_run_id": "source-run"}}
    if fault == "foreign-project":
        options["project_path"] = str(tmp_path / "original-project")
    elif fault == "foreign-run":
        options["pipeline_options"]["resume_run_id"] = "foreign-run"
    else:
        options["pipeline_options"]["run_experiment"] = True
    _fake_runtime(monkeypatch, tmp_path, options)
    with pytest.raises(RuntimeError, match="cannot restart upstream"):
        asyncio.run(runner.run_remaining(tmp_path, "source-run"))
    assert _FakeHost.instances[-1].executions == []


def test_actual_managed_experiment_entry_is_blocked_under_fake_body(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_runtime(monkeypatch, tmp_path, run_managed=True)
    with pytest.raises(RuntimeError, match="prohibits training"):
        asyncio.run(runner.run_remaining(tmp_path, "source-run"))
    host = _FakeHost.instances[-1]
    assert host.managed_experiments == host.executions == []
    assert host.shutdowns == 1


def _receipt_fixture(root: Path, monkeypatch: pytest.MonkeyPatch, **changes) -> Path:
    from scripts import verify_offline_suite

    repository = root / "repository"
    tests = repository / "server/tests"
    tests.mkdir(parents=True)
    (tests / "test_first.py").write_text("# pure fixture inventory", encoding="utf-8")
    (tests / "test_second.py").write_text("# pure fixture inventory", encoding="utf-8")
    report = root / "junit.xml"
    report.write_text('<testsuites><testsuite tests="2" failures="0" errors="0" skipped="0"/></testsuites>', encoding="utf-8")
    receipt = {"pytest_exit_code": 0, "excluded_test_files": [], "start_after": "", "test_files": 2,
               "selected_test_files": ["test_first.py", "test_second.py"],
               "code_unchanged": True, "code_sha256": "current-fixture-source", "network_allowed": False,
               "shared_mutations_allowed": False, "report_path": str(report), **changes}
    path = root / "receipt.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")
    monkeypatch.setattr(runner, "REPOSITORY", repository)
    monkeypatch.setattr(verify_offline_suite, "verification_code_sha256", lambda: "current-fixture-source")
    return path


def test_current_complete_zero_failure_offline_receipt_permits_only_the_next_authorization_step(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    receipt = _receipt_fixture(tmp_path, monkeypatch)
    result = runner.validate_offline_receipt(receipt)
    assert result["test_files"] == 2
    assert result["code_sha256"] == "current-fixture-source"


@pytest.mark.parametrize("selected", [None, [], ["test_first.py"], ["test_first.py", "test_first.py"],
                                      ["test_first.py", "test_foreign.py"], ["test_first.py", 2]])
def test_missing_partial_duplicate_or_foreign_inventory_blocks_paid_execution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, selected) -> None:
    receipt = _receipt_fixture(tmp_path, monkeypatch, selected_test_files=selected)
    with pytest.raises(ValueError, match="passing, current, complete"):
        runner.validate_offline_receipt(receipt)


def test_absent_inventory_blocks_even_when_counts_and_junit_claim_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    receipt = _receipt_fixture(tmp_path, monkeypatch)
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    payload.pop("selected_test_files")
    receipt.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="passing, current, complete"):
        runner.validate_offline_receipt(receipt)


@pytest.mark.parametrize("shard", [{"shard_count": 2, "shard_index": 0}, {"shard_count": 1, "shard_index": 1}])
def test_unmerged_shard_cannot_claim_whole_suite_even_with_overridden_inventory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, shard: dict) -> None:
    receipt = _receipt_fixture(tmp_path, monkeypatch, **shard)
    with pytest.raises(ValueError, match="passing, current, complete"):
        runner.validate_offline_receipt(receipt)


@pytest.mark.parametrize("changes", [
    {"pytest_exit_code": 1}, {"excluded_test_files": ["test_first.py"]}, {"start_after": "test_first.py"},
    {"test_files": 1}, {"code_unchanged": False}, {"code_sha256": "dirty-source"},
    {"network_allowed": True}, {"shared_mutations_allowed": True},
])
def test_incomplete_dirty_or_nonisolated_offline_receipt_blocks_paid_execution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changes: dict) -> None:
    receipt = _receipt_fixture(tmp_path, monkeypatch, **changes)
    with pytest.raises(ValueError, match="passing, current, complete"):
        runner.validate_offline_receipt(receipt)


@pytest.mark.parametrize("attribute", ["failures", "errors"])
def test_junit_failed_or_errored_tests_block_despite_claimed_exit_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, attribute: str) -> None:
    receipt = _receipt_fixture(tmp_path, monkeypatch)
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    report = Path(payload["report_path"])
    report.write_text(f'<testsuites><testsuite tests="2" {attribute}="1"/></testsuites>', encoding="utf-8")
    with pytest.raises(ValueError, match="failures or errors"):
        runner.validate_offline_receipt(receipt)


@pytest.mark.parametrize(("tests", "skipped"), [(0, 0), (2, 2), (1, 0)])
def test_zero_all_skipped_or_incomplete_junit_inventory_blocks_paid_execution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tests: int, skipped: int) -> None:
    receipt = _receipt_fixture(tmp_path, monkeypatch)
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    Path(payload["report_path"]).write_text(f'<testsuites><testsuite tests="{tests}" failures="0" errors="0" skipped="{skipped}"/></testsuites>', encoding="utf-8")
    with pytest.raises(ValueError, match="no meaningful complete test inventory"):
        runner.validate_offline_receipt(receipt)


def test_offline_code_is_rechecked_after_preparation_before_model_configuration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import live_snapshot_copy, live_snapshot_safety, live_snapshot_revalidation, verify_figure_snapshot
    from server import agent

    calls = []
    monkeypatch.setattr(live_snapshot_copy, "relocate_specialist_plan_same_run", lambda *_args: {})
    monkeypatch.setattr(live_snapshot_revalidation, "revalidate_upstream_acceptance", lambda *_args: calls.append("upstream-gates"))
    monkeypatch.setattr(verify_figure_snapshot, "snapshot_run", lambda *_args: (SimpleNamespace(), {"direction": "Fixture"}))

    async def prepared_projection(*_args):
        calls.append("offline-projection")
        return False

    monkeypatch.setattr(verify_figure_snapshot.SnapshotEngine, "_refresh_simulation_renderer_before_revalidation", prepared_projection)

    async def valid_offline_figure(*_args, **_kwargs):
        calls.append("offline-figure")
        return {"accepted": True}

    def dirty_receipt(_path):
        calls.append("offline-code-recheck")
        raise ValueError("source changed after offline preparation")

    monkeypatch.setattr(verify_figure_snapshot, "verify", valid_offline_figure)
    monkeypatch.setattr(runner, "validate_offline_receipt", dirty_receipt)
    monkeypatch.setattr(live_snapshot_safety, "load_current_model_config_readonly", lambda *_args: pytest.fail("Must not load keys after dirty receipt"))
    monkeypatch.setattr(agent, "init_models_from_config", lambda *_args: pytest.fail("Must not configure providers after dirty receipt"))
    with pytest.raises(ValueError, match="source changed"):
        asyncio.run(runner.prepare_and_run(tmp_path, tmp_path / "original", "source-run", tmp_path / "receipt.json"))
    assert calls == ["offline-projection", "offline-figure", "upstream-gates", "offline-code-recheck"]
