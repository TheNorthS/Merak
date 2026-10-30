from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from server.services.paper_artifacts import paper_artifact_builder
from server.services.paper_plan import paper_plan_service
from server.services.node_risk_audit import node_risk_audit_service
from server.services.simulation_policy import (
    SIMULATION_MANIFEST_SCHEMA,
)
from server.workflows.engine import WorkflowEngine, WorkflowRun


def _seed_contracts(root: Path) -> None:
    (root / "ideas").mkdir(parents=True)
    (root / "experiments").mkdir(parents=True)
    (root / "paper").mkdir(parents=True)
    (root / "ideas" / "SELECTED_IDEA.json").write_text(
        json.dumps({
            "status": "accepted",
            "title": "A bounded method",
            "hypothesis": "The method improves robustness under a declared shift",
            "claims": [{"id": "C1", "statement": "Robustness improves under the shift."}],
            "mechanisms": [{"id": "M1", "name": "Observed shift encoder", "description": "Encodes the shift.",
                            "publication_name": "Observed shift encoder", "publication_description": "Encodes the declared shift.",
                            "publication_evaluation": "Compare matched held-out robustness under the declared shift."}],
            "falsification_conditions": ["The matched baseline is not worse."],
        }),
        encoding="utf-8",
    )
    (root / "experiments" / "METHOD_CONTRACT.json").write_text(
        json.dumps({
            "status": "planned",
            "claim_evidence_plan": [{
                "idea_claim_id": "C1",
                "outcomes": ["Matched held-out comparison"],
                "failure_conditions": ["No robustness improvement"],
                "evidence_status": "pending_experiment",
            }],
        }),
        encoding="utf-8",
    )
    (root / "NARRATIVE_REPORT.md").write_text(
        "# Narrative\n\nPENDING: experiments are not run.\n", encoding="utf-8"
    )
    (root / "experiments" / "results").mkdir(parents=True)
    (root / "experiments" / "results" / "analysis.md").write_text(
        "No experiment has been run; planned evidence only.\n", encoding="utf-8"
    )
    (root / "paper" / "main.tex").write_text(
        r"""\documentclass{article}
\begin{document}
\begin{abstract}A bounded study with pending evidence.\end{abstract}
\section{Introduction}The problem and motivation.
\section{Method}The observed shift encoder.
\section{Experiments}The held-out protocol and controls.
\section{Results and Discussion}Results remain pending.
\section{Limitations}The evidence is not yet executed.
\section{Conclusion}The conclusion is bounded by pending evidence.
\end{document}
""",
        encoding="utf-8",
    )


def test_paper_plan_is_canonical_and_page_budget_is_separate(tmp_path: Path) -> None:
    _seed_contracts(tmp_path)
    from server.services.paper_budget import paper_budget_service

    paper_budget_service.prepare(tmp_path, 9, 1, "ICLR")
    result = paper_plan_service.ensure(tmp_path, "robust EEG")
    assert result["valid"] is True
    assert (tmp_path / "paper" / "PAPER_PLAN.md").is_file()
    assert (tmp_path / "paper" / "PAPER_BUDGET.json").is_file()
    assert not (tmp_path / "PAPER_PLAN.md").exists()
    assert (tmp_path / ".merak" / "PAPER_PLAN_BUILD.json").is_file()


def test_paper_plan_uses_provenance_validation_for_executed_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_contracts(tmp_path)
    monkeypatch.setattr(
        "server.services.scientific_evidence.scientific_evidence_service.validate_executed_metrics",
        lambda _root: (True, [], {"metric_count": 5}),
    )

    paper_plan_service.ensure(tmp_path, "robust EEG", force=True)

    content = (tmp_path / "paper" / "PAPER_PLAN.md").read_text(
        encoding="utf-8"
    )
    assert "**Evidence mode:** executed" in content


def test_synthetic_benchmark_plan_is_not_downgraded_to_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_contracts(tmp_path)
    figures = tmp_path / "figures"
    simulated = tmp_path / "experiments" / "results" / "simulated"
    figures.mkdir(parents=True)
    simulated.mkdir(parents=True)
    (figures / "SCIENTIFIC_ASSET_PLAN.json").write_text(
        json.dumps({"evidence_mode": "synthetic_preview", "assets": []}),
        encoding="utf-8",
    )
    (simulated / "SIMULATION_MANIFEST.json").write_text(
        json.dumps({"schema": SIMULATION_MANIFEST_SCHEMA}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "server.services.paper_plan_evidence._current_bundle",
        lambda _root: {"verified_fixture": True},
    )

    paper_plan_service.ensure(tmp_path, "robust EEG", force=True)
    content = (tmp_path / "paper" / "PAPER_PLAN.md").read_text(encoding="utf-8")

    assert "**Evidence mode:** synthetic_benchmark" in content
    assert "Experiments are not yet executed" not in content


def test_narrative_prompt_bounds_generated_records_without_promoting_scientific_claims(
    tmp_path: Path,
) -> None:
    run = WorkflowRun(
        project_path=str(tmp_path),
        options={
            "run_experiment": False,
            "non_experiment_evidence_mode": "synthetic_preview",
        },
    )

    prompt = WorkflowEngine()._input_narrative("robust EEG", {}, run)

    assert "哈希绑定只证明记录身份，不证明生成机制具有科学有效性" in prompt
    assert "数值排序只能作为该生成场景的描述性观察" in prompt
    assert "允许科学主张保持待验证" in prompt
    assert "完整的确定性仿真基准研究轨道" not in prompt
    assert "Do not invent values" in prompt


def test_evidence_map_uses_machine_claim_keys_without_requiring_ids_in_manuscript(
    tmp_path: Path,
) -> None:
    _seed_contracts(tmp_path)
    paper_artifact_builder.prepare(tmp_path, "robust EEG")
    map_path = tmp_path / ".merak" / "research_audit" / "PAPER_EVIDENCE_MAP.json"
    initial_bytes = map_path.read_bytes()
    payload = json.loads(map_path.read_text(encoding="utf-8"))
    assert payload["claim_mappings"][0]["claim_id"] == "C1"
    assert "C1" not in (tmp_path / "paper" / "main.tex").read_text(encoding="utf-8")
    report = node_risk_audit_service.audit_node(
        tmp_path, "paper", {"run_experiment": False}, persist=False
    )
    assert not any(item.get("id") == "PAPER-CLAIM-002" for item in report["findings"])
    paper_artifact_builder.refresh_evidence_map(tmp_path)
    assert map_path.read_bytes() == initial_bytes


@pytest.mark.asyncio
async def test_workflow_events_are_durable_without_a_frontend(tmp_path: Path) -> None:
    engine = WorkflowEngine()
    run = WorkflowRun(id="journal-run", project_path=str(tmp_path))
    await engine._emit(run, "node_started", {"node_id": "lit", "name": "文献调研"})
    await engine._emit(run, "agent_output", {"node_id": "lit", "text": "已完成检索"})
    events = tmp_path / ".merak" / "runs" / "journal-run.events.jsonl"
    display = tmp_path / ".merak" / "workflow_logs.json"
    records = [json.loads(line) for line in events.read_text(encoding="utf-8").splitlines()]
    assert [item["event"] for item in records] == ["node_started", "agent_output"]
    entries = json.loads(display.read_text(encoding="utf-8"))
    assert entries[-1]["message"] == "已完成检索"


@pytest.mark.asyncio
async def test_implementation_stage_events_have_visible_durable_logs(
    tmp_path: Path,
) -> None:
    engine = WorkflowEngine()
    run = WorkflowRun(id="implementation-journal", project_path=str(tmp_path))

    await engine._emit(run, "implementation_stage_started", {
        "node_id": "exp-design",
        "stage_id": "integration",
        "title": "Executable integration contract",
        "attempt": 1,
        "max_attempts": 2,
        "issues": [],
    })
    await engine._emit(run, "implementation_stage_needs_revision", {
        "node_id": "exp-design",
        "stage_id": "integration",
        "title": "Executable integration contract",
        "attempt": 1,
        "issues": ["RUN_SPEC must expose the scientific command"],
    })
    await engine._emit(run, "implementation_stage_accepted", {
        "node_id": "exp-design",
        "stage_id": "integration",
        "title": "Executable integration contract",
        "attempt": 2,
    })

    entries = json.loads(
        (tmp_path / ".merak" / "workflow_logs.json").read_text(encoding="utf-8")
    )
    messages = [entry["message"] for entry in entries]
    assert "实验实现阶段 integration：开始" in messages[0]
    assert "RUN_SPEC must expose" in messages[1]
    assert "实验实现阶段 integration：验收通过" in messages[2]


@pytest.mark.asyncio
async def test_paper_stage_events_have_readable_durable_messages(tmp_path: Path) -> None:
    engine = WorkflowEngine()
    run = WorkflowRun(id="paper-journal", project_path=str(tmp_path))
    common = {
        "node_id": "paper",
        "stage_id": "method",
        "stage_label": "Method",
        "stage_index": 4,
        "stage_total": 12,
        "attempt": 1,
    }

    await engine._emit(run, "paper_stage_started", {
        **common,
        "maximum_attempts": 2,
    })
    await engine._emit(run, "paper_stage_reviewed", {
        **common,
        "passed": False,
        "issues": ["required mechanism is not defined mathematically"],
    })

    entries = json.loads(
        (tmp_path / ".merak" / "workflow_logs.json").read_text(encoding="utf-8")
    )
    assert "论文分章 4/12" in entries[-2]["message"]
    assert "需要局部修订" in entries[-1]["message"]
    assert "required mechanism" in entries[-1]["message"]


@pytest.mark.asyncio
async def test_workflow_completion_log_names_the_evidence_class(tmp_path: Path) -> None:
    engine = WorkflowEngine()
    run = WorkflowRun(id="completion-journal", project_path=str(tmp_path))

    await engine._emit(run, "workflow_completed", {
        "completion_class": "synthetic_preview_ready",
        "submission_ready": False,
    })

    entries = json.loads(
        (tmp_path / ".merak" / "workflow_logs.json").read_text(encoding="utf-8")
    )
    assert "deterministic benchmark manuscript ready" in entries[-1]["message"]
    assert "complete submission track" in entries[-1]["message"]


@pytest.mark.asyncio
async def test_workflows_for_different_projects_are_isolated_and_cancel_exact_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    monkeypatch.setattr(engine, "_ensure_agent_tools", lambda: None)
    release = asyncio.Event()

    async def fake_execute(run, *_args, **_kwargs):
        await release.wait()

    monkeypatch.setattr(engine, "_execute_run", fake_execute)
    (tmp_path / "one").mkdir()
    (tmp_path / "two").mkdir()
    first = await engine.execute(["lit"], str(tmp_path / "one"))
    second = await engine.execute(["lit"], str(tmp_path / "two"))
    with pytest.raises(ValueError, match="active workflow"):
        await engine.execute(["lit"], str(tmp_path / "one"))
    assert first != second
    await engine.cancel_run(first)
    await asyncio.sleep(0)
    assert engine.get_run(first)["status"] == "cancelled"
    assert not engine.get_run(second)["status"] == "cancelled"
    await engine.cancel_run(second)
    release.set()
    await asyncio.sleep(0)

def test_paper_plan_hash_ignores_future_figures_but_tracks_upstream_science(tmp_path: Path) -> None:
    _seed_contracts(tmp_path)
    manifest = tmp_path / "figures" / "FIGURE_MANIFEST.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps({
            "schema": 1,
            "updated_at": 100.0,
            "figures": [{"id": "method", "output_path": "figures/method.pdf"}],
        }),
        encoding="utf-8",
    )

    first = paper_plan_service.ensure(tmp_path, "robust EEG")
    first_build = json.loads(
        (tmp_path / ".merak" / "PAPER_PLAN_BUILD.json").read_text(encoding="utf-8")
    )
    assert first["generated"] is True

    manifest.write_text(
        json.dumps({
            "schema": 1,
            "updated_at": 200.0,
            "figures": [{"id": "method", "output_path": "figures/method.pdf"}],
        }),
        encoding="utf-8",
    )
    unchanged = paper_plan_service.ensure(tmp_path, "robust EEG")
    assert unchanged["generated"] is False
    assert json.loads(
        (tmp_path / ".merak" / "PAPER_PLAN_BUILD.json").read_text(encoding="utf-8")
    ) == first_build

    manifest.write_text(
        json.dumps({
            "schema": 1,
            "updated_at": 300.0,
            "figures": [{"id": "evaluation", "output_path": "figures/evaluation.pdf"}],
        }),
        encoding="utf-8",
    )
    plan_path = tmp_path / "paper" / "PAPER_PLAN.md"
    future = plan_path.stat().st_mtime + 2.0
    os.utime(manifest, (future, future))
    assert paper_plan_service.is_current(tmp_path) is True
    method = tmp_path / "experiments/METHOD_CONTRACT.json"
    payload = json.loads(method.read_text(encoding="utf-8"))
    payload["updated_scientific_requirement"] = "A new registered contrast is required."
    method.write_text(json.dumps(payload), encoding="utf-8")
    assert paper_plan_service.is_current(tmp_path) is False
    changed = paper_plan_service.ensure(tmp_path, "robust EEG")
    assert changed["generated"] is True
    changed_build = json.loads(
        (tmp_path / ".merak" / "PAPER_PLAN_BUILD.json").read_text(encoding="utf-8")
    )
    assert (
        changed_build["source_bundle_sha256"]
        != first_build["source_bundle_sha256"]
    )
