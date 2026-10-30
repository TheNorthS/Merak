from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest
from fastapi import HTTPException

from server.api.projects import ScaffoldRequest, scaffold_project_api
from server.api.workflow import WorkflowRunRequest
from server.services.execution_provenance import execution_provenance_service
from server.services.paper_budget import paper_budget_service
from server.services.paper_length_revision import paper_length_revision_service
from server.services.project_scaffold import (
    ProjectScaffoldConflict,
    get_workflow_artifact_contract,
    scaffold_project,
)
from server.services.research_intake import research_intake_service
from server.services.scientific_evidence import scientific_evidence_service
from server.workflows.research_gates import apply_innovation_gate
from server.workflows.engine import WorkflowEngine, WorkflowNode, WorkflowRun


def _innovation_brief(snapshot_id: str) -> str:
    sections = [
        "Reference Paper Claims",
        "Reference Code Reality",
        "Paper-Code Gaps",
        "Novelty Delta",
        "Nearest Neighbors",
        "Proposed Method",
        "Baseline Reproduction",
        "Falsification and Ablations",
        "Claim-Evidence Map",
    ]
    body = []
    for section in sections:
        body.append(f"## {section}\n" + (f"Evidence for {section} with concrete file paths and falsifiable details. " * 12))
    return f"# Innovation Brief\n\nSnapshot ID: {snapshot_id}\n\n" + "\n\n".join(body)


def _seed_reference_inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    project = tmp_path / "project"
    project.mkdir()
    paper = tmp_path / "reference.tex"
    paper.write_text(
        "\\section{Method}\n" + ("A concrete scientific method and experimental claim. " * 30),
        encoding="utf-8",
    )
    code = tmp_path / "reference-code"
    (code / "src").mkdir(parents=True)
    (code / "src" / "train.py").write_text("def train():\n    return 1\n", encoding="utf-8")
    (code / "README.md").write_text("# Reference implementation\n", encoding="utf-8")
    (code / ".env").write_text("API_KEY=do-not-copy\n", encoding="utf-8")
    (code / "node_modules").mkdir()
    (code / "node_modules" / "ignored.js").write_text("ignored", encoding="utf-8")
    return project, paper, code


def test_reference_intake_snapshots_analyzable_inputs_without_secrets(tmp_path: Path) -> None:
    project, paper, code = _seed_reference_inputs(tmp_path)
    payload = research_intake_service.prepare(
        project,
        str(paper),
        str(code),
        "Improve robustness under a matched compute budget.",
    )

    assert payload["reference_paper"]["text_characters"] > 500
    assert payload["reference_code"]["file_count"] == 2
    snapshot = Path(payload["reference_code"]["snapshot_path"])
    assert (snapshot / "src" / "train.py").is_file()
    assert not (snapshot / ".env").exists()
    assert not (snapshot / "node_modules").exists()
    valid, issues, loaded = research_intake_service.validate_context(project)
    assert valid is True, issues
    assert loaded["snapshot_id"] == payload["snapshot_id"]


def test_innovation_contract_requires_brief_configs_results_and_runtime_provenance(tmp_path: Path) -> None:
    project, paper, code = _seed_reference_inputs(tmp_path)
    context = research_intake_service.prepare(project, str(paper), str(code))
    snapshot_id = context["snapshot_id"]
    (project / "ideas").mkdir()
    (project / "ideas" / "INNOVATION_BRIEF.md").write_text(_innovation_brief(snapshot_id), encoding="utf-8")

    experiment_dir = project / "experiments"
    config_dir = experiment_dir / "configs"
    config_dir.mkdir(parents=True)
    (config_dir / "reference_baseline.yaml").write_text(f"model: reference\nseed: 42\nreference_snapshot_id: {snapshot_id}\n", encoding="utf-8")
    (config_dir / "proposed_method.yaml").write_text(f"model: proposed\nseed: 42\nreference_snapshot_id: {snapshot_id}\n", encoding="utf-8")
    (experiment_dir / "EXPERIMENT_PLAN.md").write_text(
        "# Experiment Plan\nReference baseline reproduction under a matched controlled protocol.\n"
        "Proposed method comparison with ablation and falsification tests.\n",
        encoding="utf-8",
    )
    metric_paths = [
        experiment_dir / "results" / "reference_baseline" / "metrics.json",
        experiment_dir / "results" / "proposed_method" / "metrics.json",
    ]
    for index, path in enumerate(metric_paths):
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"loss": 1.0 - index * 0.1}), encoding="utf-8")

    ok, issues = research_intake_service.validate_experiment_contract(project, require_results=True)
    assert ok is False
    assert any("runtime-owned" in issue for issue in issues)

    now = time.time()
    execution_provenance_service.record(
        project, "session", "Bash",
        {"command": "python train.py --config experiments/configs/reference_baseline.yaml"},
        True, now - 5, now - 3, "[exit code: 0]",
    )
    execution_provenance_service.record(
        project, "session", "Bash",
        {"command": "python train.py --config experiments/configs/proposed_method.yaml"},
        True, now - 2, now + 1, "[exit code: 0]",
    )
    ok, issues = research_intake_service.validate_experiment_contract(project, require_results=True)
    assert ok is True, issues

    gate = apply_innovation_gate(
        {"accepted": True, "details": {}},
        "exp-run",
        str(project),
        {"research_mode": "paper_code_innovation", "run_experiment": True},
    )
    assert gate["accepted"] is True, gate


def test_paper_budget_persists_range_and_tex_revision_is_reversible(tmp_path: Path) -> None:
    budget = paper_budget_service.prepare(tmp_path, 9, 1, "ICLR")
    assert budget is not None
    assert budget.minimum_pages == 8
    assert budget.maximum_pages == 10
    assert budget.contains(9)
    assert not budget.contains(7)
    loaded = paper_budget_service.load(tmp_path)
    assert loaded == budget
    prompt = paper_budget_service.prompt(budget)
    assert "8-10" in prompt
    assert "Never" not in prompt or "invent" in prompt

    paper_dir = tmp_path / "paper"
    main = paper_dir / "main.tex"
    section = paper_dir / "sections" / "method.tex"
    section.parent.mkdir(parents=True)
    main.write_text("original main", encoding="utf-8")
    section.write_text("original method", encoding="utf-8")
    plan_path = paper_dir / "PAPER_PLAN.md"
    plan_path.write_text(
        "# Paper Plan\n\n## One-Sentence Contribution\n\nA bounded contribution.\n\n"
        "## Claims-Evidence Matrix\n\nplanned\n\n## Section Plan\n\nMethod\n\n"
        "## Figure Plan\n\nmethod\n\n## Evidence Gaps\n\npending\n",
        encoding="utf-8",
    )
    snapshot = paper_length_revision_service.snapshot(tmp_path)
    main.write_text("broken", encoding="utf-8")
    section.unlink()
    (paper_dir / "new.tex").write_text("new", encoding="utf-8")
    budget_path = paper_dir / "PAPER_BUDGET.json"
    original_budget = budget_path.read_bytes()
    original_plan = plan_path.read_bytes()
    budget_path.write_text("{}", encoding="utf-8")
    plan_path.write_text("broken plan", encoding="utf-8")
    assert paper_length_revision_service.protected_unchanged(snapshot) is False
    paper_length_revision_service.restore(snapshot)
    assert main.read_text(encoding="utf-8") == "original main"
    assert section.read_text(encoding="utf-8") == "original method"
    assert not (paper_dir / "new.tex").exists()
    assert budget_path.read_bytes() == original_budget
    assert plan_path.read_bytes() == original_plan


def test_innovation_mode_rejects_missing_or_remote_inputs(tmp_path: Path) -> None:
    issues = research_intake_service.validate_inputs(
        "paper_code_innovation",
        "https://example.com/paper.pdf",
        "https://github.com/example/repo",
    )
    assert len(issues) == 2
    assert all("local" in issue.lower() or "cloned" in issue.lower() for issue in issues)

    assert research_intake_service.validate_inputs("from_scratch", "", "") == []


def test_workflow_request_validates_page_range() -> None:
    with pytest.raises(ValueError):
        WorkflowRunRequest(node_ids=["paper"], project_path=".", target_pages=2)
    request = WorkflowRunRequest(node_ids=["paper"], project_path=".", target_pages=9)
    assert request.target_pages == 9


def test_generic_metrics_require_runtime_owned_hash_evidence(tmp_path: Path) -> None:
    results = tmp_path / "experiments" / "results"
    results.mkdir(parents=True)
    metrics = results / "metrics.json"
    metrics.write_text(json.dumps({"test_accuracy": 0.75}), encoding="utf-8")
    valid, issues, _ = scientific_evidence_service.validate_executed_metrics(tmp_path)
    assert valid is False
    assert any("runtime-owned" in issue for issue in issues)

    now = time.time()
    execution_provenance_service.record(
        tmp_path, "session", "Bash", {"command": "python train.py --config experiments/configs/main.yaml"},
        True, now - 1, now + 1, "[exit code: 0]",
    )
    valid, issues, details = scientific_evidence_service.validate_executed_metrics(tmp_path)
    assert valid is True, issues
    assert details["proven_sources"] == ["experiments/results/metrics.json"]


def test_project_scaffold_and_workflow_share_canonical_idea_artifact(tmp_path: Path) -> None:
    scaffold_project(tmp_path, name="Aligned project", venue="", direction="robust learning")

    canonical = tmp_path / "ideas" / "ideas.md"
    assert canonical.is_file()
    assert "robust learning" in canonical.read_text(encoding="utf-8")
    assert not (tmp_path / "ideas" / "IDEA_CANDIDATES.md").exists()
    assert (tmp_path / "literature" / "RESEARCH_BRIEF.md").is_file()
    project_profile = tmp_path / "MERAK_PROJECT.md"
    assert project_profile.is_file()
    profile_text = project_profile.read_text(encoding="utf-8")
    assert "research_direction: robust learning" in profile_text
    assert "target_venue:" in profile_text
    assert "- gpu: none" in profile_text

    contract = get_workflow_artifact_contract(tmp_path, "idea")
    assert contract["primary"] == str(canonical)
    assert contract["required"] == [str(canonical)]


def test_project_scaffold_creates_and_preserves_main_tex(tmp_path: Path) -> None:
    result = scaffold_project(
        tmp_path,
        name="Venue paper",
        venue="ICLR",
        direction="robust representation learning",
    )

    main_tex = tmp_path / "paper" / "main.tex"
    assert main_tex.is_file()
    assert main_tex.stat().st_size > 0
    assert "Venue paper" in main_tex.read_text(encoding="utf-8")
    assert "paper/main.tex" in result["files_created"]

    main_tex.write_text("% researcher manuscript\n", encoding="utf-8")
    scaffold_project(tmp_path, name="Changed title", venue="ICLR", mode="ensure")
    assert main_tex.read_text(encoding="utf-8") == "% researcher manuscript\n"


def test_project_scaffold_create_rejects_non_empty_target_without_deleting_data(tmp_path: Path) -> None:
    marker = tmp_path / ".merak" / "workflow_logs.json"
    marker.parent.mkdir(parents=True)
    marker.write_text('[{"message":"old project"}]', encoding="utf-8")

    with pytest.raises(ProjectScaffoldConflict, match="目标目录为空"):
        scaffold_project(tmp_path, name="New project", venue="", mode="create")

    assert marker.read_text(encoding="utf-8") == '[{"message":"old project"}]'
    assert not (tmp_path / "MERAK_PROJECT.md").exists()


def test_project_scaffold_create_accepts_empty_target_and_starts_without_run_state(tmp_path: Path) -> None:
    result = scaffold_project(tmp_path, name="Fresh project", venue="", mode="create")

    assert result["mode"] == "create"
    assert (tmp_path / ".merak").is_dir()
    assert not (tmp_path / ".merak" / "workflow_logs.json").exists()
    assert not (tmp_path / ".merak" / "active-workflow.json").exists()


def test_project_scaffold_ensure_preserves_existing_project_artifacts(tmp_path: Path) -> None:
    marker = tmp_path / ".merak" / "state.json"
    marker.parent.mkdir(parents=True)
    marker.write_text('{"run_id":"existing"}', encoding="utf-8")

    result = scaffold_project(tmp_path, name="Existing project", venue="", mode="ensure")

    assert result["mode"] == "ensure"
    assert marker.read_text(encoding="utf-8") == '{"run_id":"existing"}'
    assert (tmp_path / "MERAK_PROJECT.md").is_file()


def test_project_scaffold_api_returns_conflict_for_reused_project_directory(tmp_path: Path) -> None:
    (tmp_path / "paper").mkdir()
    (tmp_path / "paper" / "DRAFT_STATE.json").write_text("{}", encoding="utf-8")

    with pytest.raises(HTTPException) as caught:
        from server.services.access_identity import Principal
        principal = Principal("fixture", "fixture", "fixture@example.org", "Fixture", True)
        asyncio.run(scaffold_project_api(ScaffoldRequest(path=str(tmp_path)), principal=principal))

    assert caught.value.status_code == 409
    assert "打开项目" in str(caught.value.detail)


def test_misplaced_output_is_not_migrated_or_deleted(tmp_path: Path) -> None:
    from server.services.artifact_contract import artifact_write_error

    canonical = tmp_path / "ideas/ideas.md"
    canonical.parent.mkdir(parents=True)
    canonical.write_text("", encoding="utf-8")
    misplaced = tmp_path / "idea-stage/IDEA_REPORT.md"
    misplaced.parent.mkdir(parents=True)
    misplaced.write_text("# Ranked research ideas\n", encoding="utf-8")
    supporting = misplaced.parent / "pilot.py"
    supporting.write_text("print('pilot')\n", encoding="utf-8")
    assert "ARTIFACT_CONTRACT_ERROR" in artifact_write_error(tmp_path, misplaced)
    passed, missing = WorkflowEngine()._artifact_check([canonical])
    assert passed is False and str(canonical) in missing
    assert canonical.read_text(encoding="utf-8") == ""
    assert misplaced.read_text(encoding="utf-8") == "# Ranked research ideas\n"
    assert supporting.is_file()
