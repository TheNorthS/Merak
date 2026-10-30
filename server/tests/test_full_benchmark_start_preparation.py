"""Real fresh startup under the benchmark policy, stopped before execution.

Only temporary fixtures are written. The production audit callback is scoped to
instrumented filesystem calls rather than permanently installed in pytest.
No model, scientific producer, accepted phase, or user project is involved.
"""

from __future__ import annotations

import asyncio
import builtins
from contextlib import contextmanager
import io
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from scripts.full_benchmark_engine import FullBenchmarkEngine
from scripts.full_benchmark_evidence import check_source_owners
from scripts.full_benchmark_scope import FROZEN_WORKFLOW_INPUTS, install_benchmark_write_guard
from scripts.verify_full_benchmark_workflow import _pipeline_options, selected_nodes
from server.services.workflow_inputs import workflow_input_service
from server.utils.atomic_write import atomic_write_json
from server.workflows.run_state import ProjectRunLease, RunState


def _fixture_project(root: Path) -> dict[Path, bytes]:
    root.mkdir()
    for relative in FROZEN_WORKFLOW_INPUTS:
        target = root / relative
        if not target.suffix:
            target /= "unchanged-source.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("Frozen supplied input; never execute or regenerate.\n", encoding="utf-8")
    (root / "ideas/SELECTED_IDEA.json").write_text(json.dumps({
        "schema": 2, "title": "Fixed structural benchmark", "hypothesis": "Registered unchanged hypothesis",
        "claims": [{"id": "C1", "statement": "Prospective hypothesis, not an observed result"}],
        "mechanisms": [],
    }), encoding="utf-8")
    return {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}


def _options() -> dict:
    return _pipeline_options({"options": {
        "research_mode": "from_scratch", "target_venue": "ICLR", "target_pages": 19,
        "target_page_tolerance": 1, "research_family": "machine_learning",
        "study_archetype": "algorithm_benchmark", "max_revision_rounds": 2,
        "research_strategy": {"literature_sources": ["arxiv", "semantic_scholar"]},
    }}, True)


def _dispatch_audit(audit, evidence: dict, event: str, arguments: tuple) -> None:
    try:
        audit(event, arguments)
    except PermissionError:
        evidence["denied"].append((event, str(arguments[0])))
        raise
    evidence["observed"].append((event, str(arguments[0])))


def _open_adapter(original, audit, evidence: dict):
    def guarded(file, mode="r", *args, **kwargs):
        _dispatch_audit(audit, evidence, "open", (file, mode, 0))
        return original(file, mode, *args, **kwargs)
    return guarded


def _path_adapter(original, audit, evidence: dict, event: str):
    def guarded(*args, **kwargs):
        _dispatch_audit(audit, evidence, event, args)
        return original(*args, **kwargs)
    return guarded


@contextmanager
def _temporary_production_guard(monkeypatch: pytest.MonkeyPatch, root: Path):
    """Exercise the actual harness callback without installing a global guard."""
    hooks, evidence = [], {"observed": [], "denied": []}
    with monkeypatch.context() as scoped:
        scoped.setattr(sys, "addaudithook", hooks.append)
        install_benchmark_write_guard(root, rerun_literature=True, rerun_source_owners=True)
        assert len(hooks) == 1
        audit = hooks[0]
        scoped.setattr(builtins, "open", _open_adapter(builtins.open, audit, evidence))
        scoped.setattr(io, "open", _open_adapter(io.open, audit, evidence))
        for name in ("mkdir", "remove", "rmdir", "chmod", "utime", "rename", "replace", "link", "symlink"):
            event = "os.rename" if name == "replace" else "os." + name
            scoped.setattr(os, name, _path_adapter(getattr(os, name), audit, evidence, event))
        yield evidence


def _reject_execution(*_args, **_kwargs):
    raise AssertionError("Startup regression must not invoke a model or scientific producer")


def _isolate_execution_boundaries(monkeypatch: pytest.MonkeyPatch, host: FullBenchmarkEngine) -> None:
    from server.agent.engine import agent_engine

    monkeypatch.setattr(agent_engine, "_tools", {})
    monkeypatch.setattr(agent_engine, "_tool_definitions", [])
    monkeypatch.setattr(agent_engine, "run", _reject_execution)
    monkeypatch.setattr(host, "_acceptance_gate", _reject_execution)
    for target in (
        "server.agent.init_models_from_config",
        "server.services.experiment_placeholders.experiment_placeholder_service.ensure",
        "server.services.simulation_benchmark.build_simulation_benchmark",
    ):
        monkeypatch.setattr(target, _reject_execution)


def _assert_preparation_artifacts(root: Path, run_id: str, run) -> None:
    expected = (
        "paper/PAPER_BUDGET.json", "paper/PUBLICATION_STYLE.json",
        ".merak/research_strategy.json", ".merak/RESEARCH_WORKFLOW_CONTRACT.json",
        f".merak/runs/{run_id}.specialists.json", f".merak/runs/{run_id}.json",
    )
    assert all((root / relative).is_file() for relative in expected)
    plan = json.loads((root / f".merak/runs/{run_id}.specialists.json").read_text(encoding="utf-8"))
    assert plan["run_id"] == run_id
    assert plan["profile"]["evidence_mode"] == "synthetic_preview"
    assert plan["profile"]["family"] == "machine_learning"
    assert plan["subnodes"] and all(row["status"] == "pending" for row in plan["subnodes"])
    assert run.options["research_profile"] == plan["profile"]
    assert Path(run.options["specialist_plan_path"]) == root / f".merak/runs/{run_id}.specialists.json"
    assert not workflow_input_service.validate_snapshot(root, run.input_baseline)


@pytest.mark.asyncio
async def test_full_fresh_benchmark_uses_real_preparation_state_and_claims_before_sentinel(tmp_path, monkeypatch):
    root = tmp_path / "full-benchmark-verification-start"
    frozen = _fixture_project(root)
    host, reached = FullBenchmarkEngine(), []
    _isolate_execution_boundaries(monkeypatch, host)

    async def sentinel(run, direction, effort, assurance, options):
        reached.append(run.id)
        assert options["run_experiment"] is False and assurance == "draft"
        assert all(node.status.value == "idle" for node in run.nodes)

    monkeypatch.setattr(host, "_execute_run", sentinel)
    with _temporary_production_guard(monkeypatch, root) as guard:
        assert check_source_owners(SimpleNamespace(), root, "archived-only", ()) == {}
        run_id = await host.execute(node_ids=list(selected_nodes(False, True)), project_path=str(root),
            research_direction="Self-supervised EEG foundation model benchmark", pipeline_options=_options())
        await host._running_tasks[run_id]
        for _ in range(10):
            await asyncio.sleep(0)
        _assert_preparation_artifacts(root, run_id, host._runs[run_id])
        assert not guard["denied"], "Preparation silently swallowed a scope rejection"
        atomic_write_json(root / "FULL_BENCHMARK_REPORT.json", {"accepted": False, "execution_started": False})
    await host.shutdown()
    persisted = RunState(str(root), run_id).load()
    assert reached == [run_id] and persisted["status"] == "running"
    assert set(persisted["phases"]) == set(selected_nodes(False, True))
    assert all(row["status"] == "pending" and not row.get("accepted_at") for row in persisted["phases"].values())
    assert not ProjectRunLease(str(root)).active_claim()
    assert all(path.read_bytes() == original for path, original in frozen.items())
    assert not list((root / ".merak").glob("skill-invocations/*.json"))
    assert not (root / ".merak/runs/archived-only.json").exists()


def test_real_preparation_preserves_required_paths_without_relaxing_frozen_or_foreign_writes(tmp_path, monkeypatch):
    root = tmp_path / "full-benchmark-verification-policy"
    frozen = _fixture_project(root)
    with _temporary_production_guard(monkeypatch, root) as guard:
        for relative in ("paper/PAPER_BUDGET.json", "slides/SLIDE_BUILD.json", ".merak/RESEARCH_WORKFLOW_CONTRACT.json"):
            atomic_write_json(root / relative, {"fixture": "owned runtime record, not an accepted verdict"})
        for relative in ("ideas/SELECTED_IDEA.json", "experiments/EXPERIMENT_PLAN.md", "experiments/src/new.py",
                         "experiments/results/simulated/new.csv", "paper/tables/new.csv"):
            with pytest.raises(PermissionError):
                (root / relative).write_text("forbidden", encoding="utf-8")
        with pytest.raises(PermissionError):
            (tmp_path / "foreign.txt").write_text("forbidden", encoding="utf-8")
    assert len(guard["denied"]) == 6
    assert all(path.read_bytes() == original for path, original in frozen.items())
    assert not (tmp_path / "foreign.txt").exists()


@pytest.mark.asyncio
async def test_startup_guard_exposes_a_silently_caught_specialist_plan_write_failure(tmp_path, monkeypatch):
    from server.services.research_specialists import research_specialist_service
    from server.workflows.run_start_preparation import prepare_run_start
    from server.workflows.run_start_lifecycle import create_run

    root = tmp_path / "full-benchmark-verification-rejected-plan"
    _fixture_project(root)
    host = FullBenchmarkEngine()
    _isolate_execution_boundaries(monkeypatch, host)
    plan = await prepare_run_start(host, list(selected_nodes(False, True)), str(root), "draft", _options())
    original = research_specialist_service._atomic_write

    def foreign_plan_write(path, payload):
        original(tmp_path / "foreign-specialist.json", payload)

    monkeypatch.setattr(research_specialist_service, "_atomic_write", foreign_plan_write)
    with _temporary_production_guard(monkeypatch, root) as guard:
        run, state = create_run(host, plan, str(root), "EEG foundation model benchmark", "balanced", None)
    assert guard["denied"] and not run.options.get("specialist_plan_path")
    assert state.load()["status"] == "running"
    assert all(row["status"] == "pending" for row in state.load()["phases"].values())
    assert not (tmp_path / "foreign-specialist.json").exists()

