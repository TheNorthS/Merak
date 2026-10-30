from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from server.api.workflow import WorkflowRunRequest, run_workflow
from server.workflows.engine import WorkflowEngine
from server.workflows.run_state import RunState


def _options(*input_files: str) -> dict:
    return {
        "run_experiment": False,
        "non_experiment_evidence_mode": "existing_results",
        "input_files": list(input_files),
    }


@pytest.mark.asyncio
async def test_engine_allows_submission_synthetic_preview_without_api(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()

    async def fake_execute_run(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(engine, "_execute_run", fake_execute_run)
    run_id = await engine._start_run(
        node_ids=["results", "paper", "compile"],
        project_path=str(tmp_path),
        research_direction="test",
        assurance="submission",
        pipeline_options={
            "run_experiment": False,
            "non_experiment_evidence_mode": "synthetic_preview",
        },
    )
    await engine._running_tasks[run_id]

    persisted = RunState(str(tmp_path), run_id).load()
    assert persisted is not None
    assert persisted["config"]["assurance"] == "submission"
    assert (
        persisted["config"]["options"]["non_experiment_evidence_mode"]
        == "synthetic_preview"
    )


@pytest.mark.asyncio
async def test_engine_partial_run_does_not_drop_synthetic_mode_when_real_run_default_is_true(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()

    async def fake_execute_run(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(engine, "_execute_run", fake_execute_run)
    run_id = await engine._start_run(
        node_ids=["results", "paper"],
        project_path=str(tmp_path),
        research_direction="test",
        assurance="submission",
        pipeline_options={
            "run_experiment": True,
            "non_experiment_evidence_mode": "synthetic_preview",
        },
    )
    await engine._running_tasks[run_id]

    persisted = RunState(str(tmp_path), run_id).load()
    assert persisted is not None
    options = persisted["config"]["options"]
    assert options["run_experiment"] is False
    assert options["non_experiment_evidence_mode"] == "synthetic_preview"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("node_ids", "run_experiment"),
    [
        (["paper"], True),
        (["lit", "paper"], False),
        (["exp-run", "results", "paper"], False),
    ],
    ids=[
        "single-node-default-real-run",
        "partial-no-exp-run",
        "exp-run-selected-but-disabled",
    ],
)
@pytest.mark.parametrize(
    "assurance",
    ["draft", "polished", "conference-ready", "submission"],
)
@pytest.mark.parametrize(
    "research_mode",
    ["from_scratch", "paper_code_innovation"],
)
async def test_api_preserves_synthetic_mode_across_research_assurance_and_node_contracts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    node_ids: list[str],
    run_experiment: bool,
    assurance: str,
    research_mode: str,
) -> None:
    reference_paper = tmp_path / "reference.tex"
    reference_code = tmp_path / "reference-code"
    reference_paper.write_text(
        "\\documentclass{article}\n\\begin{document}Reference\\end{document}\n",
        encoding="utf-8",
    )
    reference_code.mkdir()
    captured: dict = {}

    async def fake_execute(**kwargs) -> str:
        captured.update(kwargs)
        return "synthetic-mode-contract"

    monkeypatch.setattr(
        "server.api.workflow.workflow_engine.execute",
        fake_execute,
    )
    response = await run_workflow(
        WorkflowRunRequest(
            node_ids=node_ids,
            project_path=str(tmp_path),
            assurance=assurance,
            research_mode=research_mode,
            ref_paper=(
                str(reference_paper)
                if research_mode == "paper_code_innovation"
                else ""
            ),
            base_repo=(
                str(reference_code)
                if research_mode == "paper_code_innovation"
                else ""
            ),
            run_experiment=run_experiment,
            non_experiment_evidence_mode="synthetic_preview",
        )
    )

    assert response["run_id"] == "synthetic-mode-contract"
    assert captured["node_ids"] == node_ids
    assert captured["assurance"] == assurance
    assert captured["pipeline_options"]["run_experiment"] is False
    assert (
        captured["pipeline_options"]["non_experiment_evidence_mode"]
        == "synthetic_preview"
    )
    assert captured["pipeline_options"]["research_mode"] == research_mode


@pytest.mark.asyncio
async def test_engine_rejects_submission_when_exp_run_is_omitted(
    tmp_path: Path,
) -> None:
    engine = WorkflowEngine()

    with pytest.raises(ValueError, match="executed exp-run"):
        await engine._start_run(
            node_ids=["results", "paper", "compile"],
            project_path=str(tmp_path),
            research_direction="test",
            assurance="submission",
            pipeline_options={"run_experiment": True},
        )


@pytest.mark.asyncio
async def test_resume_cannot_upgrade_the_frozen_evidence_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = "frozen-evidence-contract"
    state = RunState(str(tmp_path), run_id)
    state.start(
        [{"id": "results", "name": "Results", "skill": "/analyze-results"}],
        {
            "direction": "test",
            "effort": "balanced",
            "assurance": "draft",
            "options": {
                "run_experiment": False,
                "non_experiment_evidence_mode": "synthetic_preview",
            },
        },
    )
    engine = WorkflowEngine()
    captured: dict = {}

    async def fake_execute(**kwargs) -> str:
        captured.update(kwargs)
        return run_id

    monkeypatch.setattr(engine, "execute", fake_execute)

    resumed = await engine.resume_persisted_run(
        run_id=run_id,
        project_path=str(tmp_path),
        assurance="submission",
        pipeline_options={
            "run_experiment": True,
            "non_experiment_evidence_mode": "existing_results",
        },
    )

    assert resumed == run_id
    assert captured["assurance"] == "draft"
    assert captured["pipeline_options"]["run_experiment"] is False
    assert (
        captured["pipeline_options"]["non_experiment_evidence_mode"]
        == "synthetic_preview"
    )


@pytest.mark.asyncio
async def test_existing_results_start_rejects_missing_explicit_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkflowEngine()
    monkeypatch.setattr(engine, "_ensure_agent_tools", lambda: None)

    with pytest.raises(ValueError, match="requires at least one explicitly selected"):
        await engine._start_run(
            node_ids=["results"],
            project_path=str(tmp_path),
            research_direction="test",
            assurance="submission",
            pipeline_options=_options(),
        )

    import_dir = tmp_path / ".merak" / "evidence-imports"
    assert not import_dir.exists() or not list(import_dir.glob("*.json"))


@pytest.mark.asyncio
async def test_existing_results_start_persists_hash_verified_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metric = tmp_path / "experiments" / "results" / "measured.csv"
    metric.parent.mkdir(parents=True)
    metric.write_text(
        "status,method,metric,value\ncompleted,Imported,accuracy,0.76\n",
        encoding="utf-8",
    )
    engine = WorkflowEngine()
    monkeypatch.setattr(engine, "_ensure_agent_tools", lambda: None)

    async def no_execution(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(engine, "_execute_run", no_execution)
    run_id = await engine._start_run(
        node_ids=["results"],
        project_path=str(tmp_path),
        research_direction="test",
        assurance="submission",
        pipeline_options=_options("experiments/results/measured.csv"),
    )
    await asyncio.sleep(0)

    manifest_path = tmp_path / ".merak" / "evidence-imports" / f"{run_id}.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["evidence_mode"] == "existing_results"
    assert list(manifest["artifacts"]) == [
        "experiments/results/measured.csv"
    ]
    assert len(manifest["artifacts"]["experiments/results/measured.csv"]["sha256"]) == 64
    assert engine._runs[run_id].options["evidence_import_manifest"] == (
        f".merak/evidence-imports/{run_id}.json"
    )
