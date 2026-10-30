"""Pure results revision and prompt routing across truthful evidence modes."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from server.services.skill_selection import apply_execution_mode
from server.workflows.engine import WorkflowEngine, WorkflowNode, WorkflowRun
from server.workflows import revision_execution


def _run(root: Path, options: dict) -> WorkflowRun:
    return WorkflowRun(id="results-semantic-routing", project_path=str(root), options=options)


@pytest.mark.parametrize("mode", ["existing_results", "secondary_analysis"])
@pytest.mark.asyncio
async def test_imported_results_revision_uses_semantic_author_not_pending_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    calls = []

    async def forbidden_runtime(*_args, **_kwargs):
        pytest.fail("Imported evidence must not be overwritten by planned-result analysis")

    async def no_specific_runtime(*_args, **_kwargs):
        return None

    async def semantic_author(*args, **kwargs):
        calls.append((args, kwargs))
        return "bounded source-grounded result revision"

    monkeypatch.setattr(revision_execution, "_results_repair", forbidden_runtime)
    monkeypatch.setattr(revision_execution, "_runtime_repair", no_specific_runtime)
    host = SimpleNamespace(_execute_node=semantic_author)
    node = WorkflowNode(id="results", name="Results", skill="/domain-results-analysis")
    opts = {"run_experiment": False, "non_experiment_evidence_mode": mode}
    result = await revision_execution._route_revision(host, node, _run(tmp_path, opts), {}, 1, 1, "", "study",
                                                       "balanced", "submission", opts, "repair the exact scientific finding", False)
    assert result == "bounded source-grounded result revision"
    assert len(calls) == 1
    assert calls[0][1]["revision_context"] == "repair the exact scientific finding"


@pytest.mark.parametrize("mode", ["design_only", "synthetic_preview"])
@pytest.mark.asyncio
async def test_runtime_owned_results_revision_still_uses_its_actual_producer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    calls = []

    async def actual_runtime(*args):
        calls.append(args)
        return "runtime producer result"

    monkeypatch.setattr(revision_execution, "_results_repair", actual_runtime)
    host = SimpleNamespace()
    opts = {"run_experiment": False, "non_experiment_evidence_mode": mode}
    node = WorkflowNode(id="results", name="Results", skill="/domain-results-analysis")
    result = await revision_execution._route_revision(host, node, _run(tmp_path, opts), {}, 1, 1, "", "study",
                                                       "balanced", "submission", opts, "repair", False)
    assert result == "runtime producer result"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_unsupported_results_revision_fails_before_specialists_or_author_calls(tmp_path: Path) -> None:
    def forbidden(*_args, **_kwargs):
        pytest.fail("Unsupported mode must stop before any operation")

    host = SimpleNamespace(_build_gate_revision_instruction=forbidden, _execute_profile_specialists=forbidden,
                           _execute_node=forbidden, _ensure_planned_results_analysis=forbidden)
    opts = {"run_experiment": False, "non_experiment_evidence_mode": "unrecognized"}
    with pytest.raises(ValueError, match="execution contract is blocked"):
        await revision_execution.revise_node_from_gate(host, WorkflowNode(id="results", name="Results", skill="/domain-results-analysis"),
                                                       _run(tmp_path, opts), {}, 1, 1, "", "study", "balanced", "submission", opts)


@pytest.mark.parametrize("mode", ["existing_results", "secondary_analysis"])
def test_imported_analysis_prompt_preserves_real_evidence_without_global_pending_downgrade(tmp_path: Path, mode: str) -> None:
    metrics = tmp_path / "experiments/results/accepted/metrics.csv"
    metrics.parent.mkdir(parents=True)
    metrics.write_text("run_id,seed,metric\nr1,13,0.72\n", encoding="utf-8")
    before = hashlib.sha256(metrics.read_bytes()).hexdigest()
    prompt = WorkflowEngine()._input_results("study", {}, _run(tmp_path, {"non_experiment_evidence_mode": mode}))
    assert str(metrics.resolve()) in prompt
    assert "本轮不启动训练" in prompt
    assert "不得因未启动新实验就把已验证结果降格" in prompt
    assert "分析报告必须把所有结论标记为 planned/pending" not in prompt
    assert "不得进行显著性检验或把模板行写成性能证据" not in prompt
    assert "当前仅有计划证据" not in prompt
    assert hashlib.sha256(metrics.read_bytes()).hexdigest() == before


def test_design_only_prompt_retains_its_explicit_pending_boundary(tmp_path: Path) -> None:
    prompt = WorkflowEngine()._input_results("study", {}, _run(tmp_path, {"non_experiment_evidence_mode": "design_only"}))
    assert "当前仅有计划证据" in prompt
    assert "分析报告必须把所有结论标记为 planned/pending" in prompt
    assert "不得进行显著性检验" in prompt


def test_synthetic_prompt_stays_hash_bound_benchmark_not_planned(tmp_path: Path) -> None:
    prompt = WorkflowEngine()._input_results("study", {}, _run(tmp_path, {"non_experiment_evidence_mode": "synthetic_preview"}))
    assert "SIMULATION_MANIFEST.json" in prompt
    assert "哈希有效" in prompt
    assert "分析报告必须把所有结论标记为 planned/pending" not in prompt


def test_unsupported_results_prompt_rejects_before_inventory_probe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine = WorkflowEngine()
    monkeypatch.setattr(engine, "_existing_file_inventory", lambda *_args: pytest.fail("Unsupported mode must not probe files"))
    with pytest.raises(ValueError, match="execution contract is blocked"):
        engine._input_results("study", {}, _run(tmp_path, {"non_experiment_evidence_mode": "unknown"}))


@pytest.mark.parametrize("mode", ["existing_results", "secondary_analysis", "synthetic_preview"])
def test_skipped_training_does_not_add_planned_evidence_specialists_to_complete_tracks(mode: str) -> None:
    reasons = []
    specialists = apply_execution_mode("results", "machine_learning", ["statistical-analysis-plan"], reasons,
                                       {"run_experiment": False, "non_experiment_evidence_mode": mode})
    assert specialists == ["statistical-analysis-plan"]
    assert not any("no executed metrics" in reason or "planned-evidence semantics" in reason for reason in reasons)


def test_design_only_still_declares_planned_evidence_specialist() -> None:
    reasons = []
    specialists = apply_execution_mode("results", "machine_learning", [], reasons, {"non_experiment_evidence_mode": "design_only"})
    assert specialists == ["experiment-plan"]
    assert any("pending-evidence" in reason for reason in reasons)
