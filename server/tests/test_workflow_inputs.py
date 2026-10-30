from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from pathlib import Path

import pytest

import server.services.workflow_inputs as workflow_inputs_module
from server.services.workflow_inputs import (
    MAX_INPUT_TOTAL_BYTES,
    snapshot_paths,
    workflow_input_service,
)
from server.workflows.engine import (
    MANAGED_EXPERIMENT_SNAPSHOT_MODE,
    WorkflowEngine,
    WorkflowNode,
    WorkflowRun,
)
from server.workflows.run_state import RunState


def _empty_input_baseline(tmp_path: Path, run_id: str) -> dict:
    return workflow_input_service.capture(tmp_path, [], run_id=run_id)


def test_resume_never_reuses_generated_but_unaccepted_downstream_phases(
    tmp_path: Path,
) -> None:
    run_id = "resume-unaccepted-downstream"
    engine = WorkflowEngine()
    definitions = engine._get_default_nodes()
    state = RunState(str(tmp_path), run_id)
    state.start(
        [
            {"id": node.id, "name": node.name, "skill": node.skill}
            for node in definitions
        ],
        {"options": {"run_experiment": False}},
    )
    phase_ids = [node.id for node in definitions]
    narrative_index = phase_ids.index("narrative")
    for phase_id in phase_ids[:narrative_index]:
        state.set_status(phase_id, "done")
        state.accept(phase_id, f"accepted-{phase_id}", "deterministic:test")
    state.set_status("narrative", "running")
    state.set_status("figure", "done")
    state.set_status("paper", "done")

    persisted = state.load()
    assert persisted is not None
    assert engine._resumable_phase_ids(persisted) == phase_ids[narrative_index:]

    run = WorkflowRun(
        id=run_id,
        project_path=str(tmp_path),
        nodes=list(definitions),
        options={"run_experiment": False},
    )
    accepted = engine._validated_accepted_phase_ids(run, state)

    assert accepted == phase_ids[:narrative_index]
    assert "figure" not in accepted
    assert "paper" not in accepted


def test_explicit_workflow_inputs_must_stay_inside_project(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("external", encoding="utf-8")

    paths, issues = workflow_input_service.resolve(project, [str(outside)])

    assert paths == []
    assert any("inside the current project" in issue for issue in issues)


def test_oversized_input_is_rejected_before_content_hashing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    large = tmp_path / "large-reference.bin"
    with large.open("wb") as handle:
        handle.truncate(MAX_INPUT_TOTAL_BYTES + 1)
    monkeypatch.setattr(
        workflow_inputs_module,
        "_sha256",
        lambda _path: pytest.fail("oversized input must not be hashed"),
    )

    with pytest.raises(ValueError, match="256 MiB"):
        workflow_input_service.capture(tmp_path, [large], run_id="oversized")


def test_input_directory_rejects_symbolic_links(tmp_path: Path) -> None:
    selected = tmp_path / "selected"
    selected.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    link = selected / "linked.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symbolic links are unavailable in this Windows environment")

    with pytest.raises(ValueError, match="symbolic links"):
        workflow_input_service.capture(tmp_path, [selected], run_id="symlink")


def test_unchanged_explicit_input_can_satisfy_freshness(tmp_path: Path) -> None:
    artifact = tmp_path / "literature" / "survey.md"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("# Researcher survey\n", encoding="utf-8")
    baseline = workflow_input_service.capture(
        tmp_path,
        [str(artifact)],
        run_id="explicit-input",
    )
    node_start = snapshot_paths(tmp_path, [artifact])

    accepted, issues = WorkflowEngine()._artifact_check(
        [artifact],
        baseline=node_start,
        project_path=str(tmp_path),
        input_baseline=baseline,
    )

    assert accepted is True
    assert issues == []


def test_no_changed_undeclared_output_is_not_fresh(tmp_path: Path) -> None:
    artifact = tmp_path / "ideas" / "ideas.md"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("# Old ideas\n", encoding="utf-8")
    node_start = snapshot_paths(tmp_path, [artifact])

    accepted, issues = WorkflowEngine()._artifact_check(
        [artifact],
        baseline=node_start,
        project_path=str(tmp_path),
        input_baseline=_empty_input_baseline(tmp_path, "new-run"),
    )

    assert accepted is False
    assert "no canonical output changed by content" in issues[0]


def test_one_changed_required_output_is_enough_when_siblings_remain_valid(
    tmp_path: Path,
) -> None:
    survey = tmp_path / "literature" / "survey.md"
    references = tmp_path / "literature" / "references.bib"
    survey.parent.mkdir(parents=True)
    survey.write_text("# Old survey\n", encoding="utf-8")
    references.write_text("@article{old, title={Old}}\n", encoding="utf-8")
    node_start = snapshot_paths(tmp_path, [survey, references])

    survey.write_text("# New survey\n", encoding="utf-8")
    accepted, issues = WorkflowEngine()._artifact_check(
        [survey, references],
        baseline=node_start,
        project_path=str(tmp_path),
        input_baseline=_empty_input_baseline(tmp_path, "partial-output"),
    )

    assert accepted is True
    assert issues == []


def test_unchanged_required_output_may_be_an_explicit_input(tmp_path: Path) -> None:
    survey = tmp_path / "literature" / "survey.md"
    references = tmp_path / "literature" / "references.bib"
    survey.parent.mkdir(parents=True)
    survey.write_text("# Old survey\n", encoding="utf-8")
    references.write_text("@article{curated, title={Curated}}\n", encoding="utf-8")
    node_start = snapshot_paths(tmp_path, [survey, references])
    input_baseline = workflow_input_service.capture(
        tmp_path,
        [references],
        run_id="mixed-output",
    )

    survey.write_text("# New survey\n", encoding="utf-8")
    accepted, issues = WorkflowEngine()._artifact_check(
        [survey, references],
        baseline=node_start,
        project_path=str(tmp_path),
        input_baseline=input_baseline,
    )

    assert accepted is True
    assert issues == []


def test_content_change_is_fresh_even_when_mtime_is_old(tmp_path: Path) -> None:
    artifact = tmp_path / "literature" / "survey.md"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("# Placeholder\n", encoding="utf-8")
    node_start = snapshot_paths(tmp_path, [artifact])

    artifact.write_text("# Retrieved evidence\n", encoding="utf-8")
    old = time.time() - 3600
    os.utime(artifact, (old, old))

    accepted, issues = WorkflowEngine()._artifact_check(
        [artifact],
        baseline=node_start,
        project_path=str(tmp_path),
        input_baseline=_empty_input_baseline(tmp_path, "copied-output"),
    )

    assert accepted is True
    assert issues == []


def test_explicit_input_drift_is_detected(tmp_path: Path) -> None:
    artifact = tmp_path / "ideas" / "seed.md"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("frozen question", encoding="utf-8")
    baseline = workflow_input_service.capture(
        tmp_path,
        ["ideas/seed.md"],
        run_id="input-drift",
    )

    artifact.write_text("changed question", encoding="utf-8")

    issues = workflow_input_service.validate_snapshot(tmp_path, baseline)
    assert issues == [
        "Explicit workflow input changed after the run started: ideas/seed.md"
    ]


def test_refresh_accepted_details_rebinds_reviewed_artifact(
    tmp_path: Path,
) -> None:
    paper = tmp_path / "paper" / "main.tex"
    paper.parent.mkdir(parents=True)
    paper.write_text("reviewed version one\n", encoding="utf-8")
    run_id = "reviewed-paper-rebind"
    input_baseline = _empty_input_baseline(tmp_path, run_id)
    state = RunState(str(tmp_path), run_id)
    state.start(
        [{"id": "paper", "name": "Paper", "skill": "/paper-write"}],
        {"options": {}},
        input_baseline=input_baseline,
    )
    state.set_status("paper", "done")
    state.accept(
        "paper",
        "paper-verdict",
        "deterministic:paper",
        {
            "artifact_snapshot": snapshot_paths(tmp_path, [paper]),
            "input_baseline_snapshot_id": input_baseline["snapshot_id"],
        },
    )

    paper.write_text("reviewed version two\n", encoding="utf-8")
    assert state.refresh_accepted_details(
        "paper",
        {
            "artifact_snapshot": snapshot_paths(tmp_path, [paper]),
            "input_baseline_snapshot_id": input_baseline["snapshot_id"],
        },
        reason="accepted cross-model review edit",
    ) is True

    run = WorkflowRun(
        id=run_id,
        project_path=str(tmp_path),
        input_baseline=input_baseline,
    )
    assert WorkflowEngine()._validated_accepted_phase_ids(run, state) == [
        "paper"
    ]
    phase = state.load()["phases"]["paper"]
    assert phase["status"] == "accepted"
    assert phase["verdict_id"] == "paper-verdict"
    assert phase["details"]["acceptance_rebindings"][-1]["reason"] == (
        "accepted cross-model review edit"
    )

def test_content_bound_acceptance_invalidates_downstream_phase(tmp_path: Path) -> None:
    survey = tmp_path / "literature" / "survey.md"
    bib = tmp_path / "literature" / "references.bib"
    ideas = tmp_path / "ideas" / "ideas.md"
    survey.parent.mkdir(parents=True)
    ideas.parent.mkdir(parents=True)
    survey.write_text("# Survey\n", encoding="utf-8")
    bib.write_text("@article{a, title={A}}\n", encoding="utf-8")
    ideas.write_text("# Ideas\n", encoding="utf-8")

    run_id = "accepted-hashes"
    input_baseline = _empty_input_baseline(tmp_path, run_id)
    state = RunState(str(tmp_path), run_id)
    state.start(
        [
            {"id": "idea", "name": "Idea", "skill": "/idea-discovery"},
            {"id": "lit", "name": "Literature", "skill": "/research-lit"},
        ],
        {"options": {}},
        input_baseline=input_baseline,
    )
    for node_id, paths in (
        ("lit", [survey, bib]),
        ("idea", [ideas]),
    ):
        state.set_status(node_id, "done")
        state.accept(
            node_id,
            f"artifact:{node_id}",
            "deterministic:test",
            {
                "artifact_snapshot": snapshot_paths(tmp_path, paths),
                "input_baseline_snapshot_id": input_baseline["snapshot_id"],
            },
        )
        state.record_revision_gate(
            node_id,
            round_number=6,
            cycle=2,
            gate={"accepted": False, "issues": ["superseded issue"]},
        )

    survey.write_text("# Changed survey\n", encoding="utf-8")
    run = WorkflowRun(
        id=run_id,
        project_path=str(tmp_path),
        options={},
        input_baseline=input_baseline,
    )

    accepted = WorkflowEngine()._validated_accepted_phase_ids(run, state)
    phases = state.load()["phases"]

    assert accepted == []
    assert phases["lit"]["status"] == "done"
    assert phases["idea"]["status"] == "done"
    assert "accepted artifact changed" in phases["lit"]["details"]["acceptance_invalidations"][-1]["reason"]
    assert "upstream dependency changed" in phases["idea"]["details"]["acceptance_invalidations"][-1]["reason"]
    assert phases["lit"]["details"]["revision"]["round"] == 0
    assert phases["idea"]["details"]["revision"]["round"] == 0
    assert phases["lit"]["details"]["acceptance_invalidations"][-1][
        "previous_revision_round"
    ] == 6


def test_direct_canonical_output_uses_content_change_not_mtime(tmp_path: Path) -> None:
    canonical = tmp_path / "ideas/ideas.md"
    canonical.parent.mkdir(parents=True)
    canonical.write_text("", encoding="utf-8")
    node = WorkflowNode(id="idea", name="Idea", skill="/idea-discovery")
    baseline = _empty_input_baseline(tmp_path, "canonical-content")
    run = WorkflowRun(id="canonical-content", project_path=str(tmp_path),
                      nodes=[node], input_baseline=baseline)
    engine = WorkflowEngine()
    node.artifact_baseline = engine._snapshot_node_artifacts(node, run)
    canonical.write_text("# Ranked research ideas\n", encoding="utf-8")
    old = time.time() - 3600
    os.utime(canonical, (old, old))
    assert canonical in engine._changed_nonempty_node_artifacts(node, run)
    assert engine._artifact_check([canonical], baseline=node.artifact_baseline,
                                 project_path=str(tmp_path), input_baseline=baseline) == (True, [])


def test_downstream_analysis_does_not_invalidate_experiment_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results = tmp_path / "experiments" / "results"
    results.mkdir(parents=True)
    metrics = results / "metrics.json"
    metrics.write_text('{"accuracy": 0.7}\n', encoding="utf-8")
    engine = WorkflowEngine()
    monkeypatch.setattr(
        engine,
        "_managed_experiment_acceptance_gate",
        lambda *_args, **_kwargs: {"accepted": True, "details": {"issues": []}},
    )
    run_id = "owned-results"
    input_baseline = _empty_input_baseline(tmp_path, run_id)
    state = RunState(str(tmp_path), run_id)
    state.start(
        [{"id": "exp-run", "name": "Run", "skill": "/experiment-bridge"}],
        {"options": {"run_experiment": True}},
        input_baseline=input_baseline,
    )
    state.set_status("exp-run", "done")
    state.accept(
        "exp-run",
        "artifact:exp-run",
        "deterministic:test",
        {
            "artifact_snapshot": snapshot_paths(
                tmp_path,
                [results],
                directory_exclusions=engine._artifact_directory_exclusions(
                    "exp-run"
                ),
            ),
            "input_baseline_snapshot_id": input_baseline["snapshot_id"],
        },
    )
    run = WorkflowRun(
        id=run_id,
        project_path=str(tmp_path),
        options={"run_experiment": True},
        input_baseline=input_baseline,
    )

    (results / "analysis.md").write_text("# Analysis\n", encoding="utf-8")
    assert engine._validated_accepted_phase_ids(run, state) == ["exp-run"]

    metrics.write_text('{"accuracy": 0.8}\n', encoding="utf-8")
    assert engine._validated_accepted_phase_ids(run, state) == []
    assert state.load()["phases"]["exp-run"]["status"] == "done"


def test_managed_experiment_acceptance_snapshot_never_hashes_results_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results = tmp_path / "experiments" / "results"
    results.mkdir(parents=True)
    (results / "predictions.jsonl").write_text('{"y": 1}\n', encoding="utf-8")
    run_spec = tmp_path / "experiments" / "RUN_SPEC.json"
    run_spec.write_text('{"outputs": {}}\n', encoding="utf-8")
    manifest = tmp_path / ".merak" / "experiments" / "job" / "run.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text('{"status": "completed"}\n', encoding="utf-8")
    original_artifact_state = workflow_inputs_module.artifact_state
    visited: list[Path] = []

    def tracking_artifact_state(path: str | Path, **kwargs):
        resolved = Path(path).resolve()
        visited.append(resolved)
        if resolved == results.resolve():
            pytest.fail("managed experiment snapshot must not hash the results directory")
        return original_artifact_state(path, **kwargs)

    monkeypatch.setattr(
        workflow_inputs_module,
        "artifact_state",
        tracking_artifact_state,
    )
    run = WorkflowRun(
        id="managed-snapshot",
        project_path=str(tmp_path),
        options={"run_experiment": True},
        input_baseline=_empty_input_baseline(tmp_path, "managed-snapshot"),
    )
    gate = {"details": {"manifest_paths": [str(manifest)]}}

    WorkflowEngine()._bind_gate_artifact_snapshot(
        WorkflowNode(id="exp-run", name="Run", skill="/experiment-bridge"),
        run,
        gate,
    )

    details = gate["details"]
    assert details["artifact_snapshot_mode"] == MANAGED_EXPERIMENT_SNAPSHOT_MODE
    assert set(details["artifact_snapshot"]) == {
        "experiments/RUN_SPEC.json",
        ".merak/experiments/job/run.json",
    }
    assert results.resolve() not in visited


def test_changed_directory_snapshot_is_invalidated_not_rebound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    results = tmp_path / "experiments/results"
    results.mkdir(parents=True)
    (results / "predictions.jsonl").write_text('{"y": 1}\n', encoding="utf-8")
    baseline = _empty_input_baseline(tmp_path, "snapshot-check")
    state = RunState(str(tmp_path), "snapshot-check")
    state.start([{"id": "exp-run", "name": "Run", "skill": "/experiment-bridge"}],
                {"options": {"run_experiment": True}}, input_baseline=baseline)
    state.set_status("exp-run", "done")
    snapshot = snapshot_paths(tmp_path, [results])
    snapshot["experiments/results"]["size"] = 512 * 1024 * 1024
    state.accept("exp-run", "artifact:exp-run", "deterministic:test", {
        "artifact_snapshot": snapshot,
        "input_baseline_snapshot_id": baseline["snapshot_id"],
    })
    engine = WorkflowEngine()
    monkeypatch.setattr(engine, "_managed_experiment_acceptance_gate",
                        lambda *_args: pytest.fail("Changed snapshots cannot be rebound."))
    run = WorkflowRun(id="snapshot-check", project_path=str(tmp_path),
                      options={"run_experiment": True}, input_baseline=baseline)
    assert engine._validated_accepted_phase_ids(run, state) == []
    details = state.load()["phases"]["exp-run"]["details"]
    assert details["artifact_snapshot"] == snapshot
    assert "acceptance_rebindings" not in details


def test_managed_experiment_rehashes_small_declared_outputs(
    tmp_path: Path,
) -> None:
    result = tmp_path / "experiments" / "results" / "run-1" / "summary.csv"
    result.parent.mkdir(parents=True)
    result.write_text("metric,value\naccuracy,0.7\n", encoding="utf-8")
    stat = result.stat()
    relative = result.relative_to(tmp_path).as_posix()
    owned_hash = hashlib.sha256(result.read_bytes()).hexdigest()
    manifest = tmp_path / ".merak" / "experiments" / "job" / "run.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps({
            "status": "completed",
            "evidence_eligible": True,
            "current_attempt": 1,
            "attempts": [{
                "attempt": 1,
                "status": "completed",
                "evidence_eligible": True,
                "result_artifacts": {
                    relative: {
                        "bytes": stat.st_size,
                        "mtime": stat.st_mtime,
                        "sha256": owned_hash,
                    }
                },
            }],
        }),
        encoding="utf-8",
    )
    result.write_text("metric,value\naccuracy,0.8\n", encoding="utf-8")
    os.utime(result, (stat.st_atime, stat.st_mtime))

    issues = WorkflowEngine._managed_experiment_output_issues(
        tmp_path,
        {"outputs": {"per_run_files": ["summary.csv"]}},
        manifest,
    )

    assert any("sha256" in issue for issue in issues)


def test_durable_resume_invalidates_accepted_exp_run_with_bad_runtime_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results = tmp_path / "experiments" / "results"
    results.mkdir(parents=True)
    metrics = results / "metrics.json"
    metrics.write_text('{"accuracy": 0.7}\n', encoding="utf-8")
    run_id = "invalid-managed-evidence"
    input_baseline = _empty_input_baseline(tmp_path, run_id)
    state = RunState(str(tmp_path), run_id)
    state.start(
        [{"id": "exp-run", "name": "Run", "skill": "/experiment-bridge"}],
        {"options": {"run_experiment": True}},
        input_baseline=input_baseline,
    )
    state.set_status("exp-run", "done")
    state.accept(
        "exp-run",
        "artifact:exp-run",
        "deterministic:test",
        {
            "artifact_snapshot": snapshot_paths(tmp_path, [results]),
            "input_baseline_snapshot_id": input_baseline["snapshot_id"],
        },
    )
    run = WorkflowRun(
        id=run_id,
        project_path=str(tmp_path),
        options={"run_experiment": True},
        input_baseline=input_baseline,
    )
    engine = WorkflowEngine()
    monkeypatch.setattr(
        engine,
        "_managed_experiment_acceptance_gate",
        lambda *_args, **_kwargs: {
            "accepted": False,
            "summary": "paired_differences.csv has no data rows",
            "details": {"issues": ["paired_differences.csv has no data rows"]},
        },
    )

    assert engine._validated_accepted_phase_ids(run, state) == []
    phase = state.load()["phases"]["exp-run"]
    assert phase["status"] == "done"
    assert "paired_differences.csv has no data rows" in phase["details"][
        "acceptance_invalidations"
    ][-1]["reason"]


def test_bound_acceptance_reruns_node_risk_audit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = tmp_path / "ideas" / "ideas.md"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("# Ideas\n", encoding="utf-8")
    run_id = "bound-risk"
    input_baseline = _empty_input_baseline(tmp_path, run_id)
    state = RunState(str(tmp_path), run_id)
    state.start(
        [{"id": "idea", "name": "Idea", "skill": "/idea-discovery"}],
        {"options": {}},
        input_baseline=input_baseline,
    )
    state.set_status("idea", "done")
    state.accept(
        "idea",
        "artifact:idea",
        "deterministic:test",
        {
            "artifact_snapshot": snapshot_paths(tmp_path, [artifact]),
            "input_baseline_snapshot_id": input_baseline["snapshot_id"],
            "risk_audit_bound": True,
        },
    )
    from server.services.node_risk_audit import node_risk_audit_service

    monkeypatch.setattr(
        node_risk_audit_service,
        "audit_node",
        lambda *_args, **_kwargs: {
            "findings": [{
                "severity": "blocker",
                "plain_message": "Frozen Idea no longer matches its evidence.",
            }],
        },
    )
    run = WorkflowRun(
        id=run_id,
        project_path=str(tmp_path),
        input_baseline=input_baseline,
    )

    assert WorkflowEngine()._validated_accepted_phase_ids(run, state) == []
    invalidation = state.load()["phases"]["idea"]["details"][
        "acceptance_invalidations"
    ][-1]
    assert "Frozen Idea no longer matches" in invalidation["reason"]


def test_unchanged_bound_acceptance_reuses_matching_risk_audit_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = tmp_path / "ideas" / "ideas.md"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("# Ideas\n", encoding="utf-8")
    run_id = "cached-bound-risk"
    options: dict = {}
    input_baseline = _empty_input_baseline(tmp_path, run_id)
    state = RunState(str(tmp_path), run_id)
    state.start(
        [{"id": "idea", "name": "Idea", "skill": "/idea-discovery"}],
        {"options": options},
        input_baseline=input_baseline,
    )
    engine = WorkflowEngine()
    state.set_status("idea", "done")
    state.accept(
        "idea",
        "artifact:idea",
        "deterministic:test",
        {
            "artifact_snapshot": snapshot_paths(tmp_path, [artifact]),
            "input_baseline_snapshot_id": input_baseline["snapshot_id"],
            "risk_audit_bound": True,
            "risk_audit_validator_signature": (
                engine._risk_audit_validator_signature(options)
            ),
            "node_risk_audit": {"findings": [], "status": "passed"},
        },
    )
    from server.services.node_risk_audit import node_risk_audit_service

    monkeypatch.setattr(
        node_risk_audit_service,
        "audit_node",
        lambda *_args, **_kwargs: pytest.fail(
            "unchanged accepted risk audit must be reused"
        ),
    )
    run = WorkflowRun(
        id=run_id,
        project_path=str(tmp_path),
        options=options,
        input_baseline=input_baseline,
    )

    assert engine._validated_accepted_phase_ids(run, state) == ["idea"]
