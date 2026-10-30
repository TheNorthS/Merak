"""Actual workflow target wrapping must retain genuine local cache revalidation."""

import json
from types import SimpleNamespace

import pytest

from server.services.paper_stage_cache_revalidation import (
    AUTOMATIC_CONSISTENCY_DIRECTIVE, automatic_consistency_revalidation, stage_freshness_only,
)
from server.services.paper_drafting import AUTHOR_STAGE_ORDER
from server.tests._paper_freshness_complete_support import (
    FIXTURE_DIRECTION, completed_local_manuscript, stale_blueprint_with_changed_pending_report,
)
from server.tests.test_paper_stage_validator_cache import _completed_intro, _coordinator
from server.workflows.engine import WorkflowEngine
from server.workflows.revision_execution import _execute_paper_repairs


BLUEPRINT_STATE = "Contribution blueprint: Contribution blueprint has not passed its local section contract."


def _outer_issues():
    return ["Target artifact: paper/main.tex", "Target artifact: paper/CONTRIBUTION_BLUEPRINT.md",
            "staged-paper: " + BLUEPRINT_STATE, BLUEPRINT_STATE]


@pytest.mark.asyncio
async def test_whole_workflow_wrapper_draft_and_final_assembly_freshly_review_current_consistency_without_author(tmp_path, monkeypatch):
    service, paths = completed_local_manuscript(tmp_path)
    issues = _outer_issues()
    stale_blueprint_with_changed_pending_report(service, paths, issues)
    authored = {path: path.read_bytes() for stage in AUTHOR_STAGE_ORDER if stage != "consistency"
                for path in service.stage_outputs(paths, stage)}
    report_before = paths["cross_review"].read_bytes()
    reviews, events, drafted = [], [], []
    real_review = service.validate_stage

    def review(root, stage):
        reviews.append(stage)
        return real_review(root, stage)

    monkeypatch.setattr(service, "validate_stage", review)

    async def forbidden(*_args):
        raise _AuthorBoundary("cache-only whole repair must not invoke any author")

    async def emit(event, payload):
        events.append((event, payload))

    async def staged(**options):
        assert options["revision_issues"] == issues
        result = await service.draft(tmp_path, FIXTURE_DIRECTION, {}, forbidden,
                                     emit=emit, revision_issues=options["revision_issues"])
        drafted.append(result)
        return result

    host = WorkflowEngine()
    monkeypatch.setattr(host, "_execute_staged_paper", staged)
    findings = [{"target_files": ["paper/main.tex", "paper/CONTRIBUTION_BLUEPRINT.md"],
                 "message": "staged-paper: " + BLUEPRINT_STATE},
                {"target_files": ["paper/CONTRIBUTION_BLUEPRINT.md"], "message": BLUEPRINT_STATE}]
    targets = host._revision_target_files([item["target_files"] for item in findings])
    result = await _execute_paper_repairs(host, SimpleNamespace(id="paper"), SimpleNamespace(),
        {"findings": findings}, "fixture research", "", {}, [item["message"] for item in findings],
        {"target_files": targets}, targets, targets, [])
    assert drafted[0]["status"] == "completed" and result == str(drafted[0])
    assert "blueprint" in reviews and "consistency" in reviews
    assert any(event == "paper_stage_reused" and data.get("cache_only_consistency_reconciled")
               for event, data in events)
    assert any(event == "paper_stage_reviewed" and data["stage_id"] == "assembly" and data["passed"]
               for event, data in events)
    assert all(path.read_bytes() == original for path, original in authored.items())
    assert paths["cross_review"].read_bytes() == report_before
    state = json.loads(paths["state"].read_text())
    assert state["status"] == "completed" and service.validate_complete_draft(tmp_path)["passed"]
    for stage in ("blueprint", "consistency"):
        assert service.stage_is_current(paths, state, stage)
        assert state["stages"][stage]["directed_attempts"] == service.DIRECTED_REPAIR_ATTEMPTS
        assert state["stages"][stage]["attempts"] == 1


class _AuthorBoundary(BaseException):
    """A forbidden model call cannot be recovered as a transport failure."""


@pytest.mark.parametrize("extra", [
    "Researcher feedback: replace the mechanism.", BLUEPRINT_STATE + "; change the claimed evidence.",
    "Target artifact: paper/FOREIGN.md", "Target artifact: ../paper/CONTRIBUTION_BLUEPRINT.md",
    "Target artifact: paper/main.tex; change the causal claim.", AUTOMATIC_CONSISTENCY_DIRECTIVE,
])
def test_automatic_directive_cannot_hide_semantic_feedback_or_foreign_metadata(tmp_path, extra):
    service, paths = _completed_blueprint(tmp_path)
    coordinator = _coordinator(tmp_path, service, paths)
    coordinator.revision_issues = [*_outer_issues(), extra]
    coordinator.automatic_consistency_revalidation = True
    run = SimpleNamespace(stage_id="consistency", prior_attempts=1,
        record={"input_signature": service.stage_input_signature(paths, "consistency")},
        revision_issues=[AUTOMATIC_CONSISTENCY_DIRECTIVE, *coordinator.revision_issues])
    assert not automatic_consistency_revalidation(coordinator, run)


@pytest.mark.parametrize("defect", ["only_targets", "not_generated", "changed_inputs", "changed_authorship",
                                  "unreviewed_author", "failed_fresh_author_review", "missing_previous_input"])
def test_auto_consistency_requires_actual_current_authorship_and_genuine_cache_request(tmp_path, monkeypatch, defect):
    service, paths = completed_local_manuscript(tmp_path)
    coordinator = _coordinator(tmp_path, service, paths)
    coordinator.revision_issues = _outer_issues()
    coordinator.automatic_consistency_revalidation = True
    state = json.loads(paths["state"].read_text())
    run = SimpleNamespace(stage_id="consistency", prior_attempts=1, record=state["stages"]["consistency"],
        revision_issues=[AUTOMATIC_CONSISTENCY_DIRECTIVE, *coordinator.revision_issues])
    assert automatic_consistency_revalidation(coordinator, run)
    if defect == "only_targets":
        coordinator.revision_issues = coordinator.revision_issues[:2]
        run.revision_issues = [AUTOMATIC_CONSISTENCY_DIRECTIVE, *coordinator.revision_issues]
    elif defect == "not_generated":
        coordinator.automatic_consistency_revalidation = False
    elif defect == "changed_inputs":
        (tmp_path / "literature/survey.md").write_text("Different scientific input.")
    elif defect == "changed_authorship":
        paths["blueprint"].write_bytes(paths["blueprint"].read_bytes() + b"New causal evidence.")
    elif defect == "unreviewed_author":
        state["stages"]["blueprint"].update(status="pending", review_passed=False)
        paths["state"].write_text(json.dumps(state))
    elif defect == "failed_fresh_author_review":
        monkeypatch.setattr(service, "validate_stage", lambda *_args: {"passed": False, "issues": ["Current content rejected"]})
    else:
        run.record.pop("input_signature")
    assert not automatic_consistency_revalidation(coordinator, run)


@pytest.mark.asyncio
async def test_auto_consistency_current_invalid_report_is_not_promoted(tmp_path):
    service, paths = completed_local_manuscript(tmp_path)
    issues = _outer_issues()
    stale_blueprint_with_changed_pending_report(service, paths, issues)
    paths["cross_review"].write_text("Current report has no required checks or final verdict.")
    coordinator = _coordinator(tmp_path, service, paths)
    coordinator.revision_issues = issues
    coordinator._configure_targeted_repairs()
    await coordinator._run_stage("blueprint")
    run = coordinator._stage_run("consistency", json.loads(paths["state"].read_text()),
                                 coordinator.target_stage_issues["consistency"])
    assert automatic_consistency_revalidation(coordinator, run)
    assert not await coordinator._revalidate_without_invocation(run)
    record = json.loads(paths["state"].read_text())["stages"]["consistency"]
    assert not record["review_passed"] and record["status"] != "completed"


def _completed_blueprint(root):
    service, paths, _intro = _completed_intro(root)
    headings = ("Research Question", "Closest-Work Gap", "One-Sentence Contribution", "Mechanism Logic",
                "Claims and Required Evidence", "Alternative Explanations", "Section Narrative", "Evidence Boundary")
    prose = "The matched scientific control preserves independent units and tests the registered causal alternative. " * 8
    paths["blueprint"].write_text("\n".join("## " + heading + "\n" + prose for heading in headings), encoding="utf-8")
    review = service.validate_stage(root, "blueprint")
    assert review["passed"]
    service.mark_stage(paths, "blueprint", "completed", attempt=1, review=review)
    state = json.loads(paths["state"].read_text())
    state["stages"]["blueprint"].update({"status": "running", "review_passed": False,
        "validator_signature": "0" * 64, "directed_attempts": service.DIRECTED_REPAIR_ATTEMPTS})
    paths["state"].write_text(json.dumps(state))
    return service, paths


@pytest.mark.asyncio
async def test_actual_workflow_resolver_and_repair_wrapper_revalidate_blueprint_without_author(tmp_path, monkeypatch):
    service, paths = _completed_blueprint(tmp_path)
    coordinator = _coordinator(tmp_path, service, paths)
    before = paths["blueprint"].read_bytes()
    state = json.loads(paths["state"].read_text())
    state["stages"]["blueprint"]["directed_issue_signature"] = service.directed_issue_signature([
        "Target artifact: paper/main.tex",
        "Target artifact: paper/CONTRIBUTION_BLUEPRINT.md", "staged-paper: " + BLUEPRINT_STATE, BLUEPRINT_STATE])
    paths["state"].write_text(json.dumps(state))
    actual_reviews = []
    actual_review = service.validate_stage

    def review(root, stage):
        actual_reviews.append(stage)
        return actual_review(root, stage)

    monkeypatch.setattr(service, "validate_stage", review)
    seen = []

    async def staged(**options):
        seen.extend(options["revision_issues"])
        coordinator.revision_issues = options["revision_issues"]
        coordinator._configure_targeted_repairs()
        await coordinator._run_stage("blueprint")
        return "actual local review passed"

    host = WorkflowEngine()
    monkeypatch.setattr(host, "_execute_staged_paper", staged)
    findings = [{"target_files": ["paper/main.tex", "paper/CONTRIBUTION_BLUEPRINT.md"],
                 "message": "staged-paper: " + BLUEPRINT_STATE},
                {"target_files": ["paper/CONTRIBUTION_BLUEPRINT.md"], "message": BLUEPRINT_STATE}]
    targets = host._revision_target_files([item["target_files"] for item in findings])
    assert targets == ["paper/main.tex", "paper/CONTRIBUTION_BLUEPRINT.md"]
    result = await _execute_paper_repairs(host, SimpleNamespace(id="paper"), SimpleNamespace(),
        {"findings": findings}, "fixture research", "", {}, [item["message"] for item in findings],
        {"target_files": targets}, targets, targets, [])
    assert seen == ["Target artifact: paper/main.tex", "Target artifact: paper/CONTRIBUTION_BLUEPRINT.md",
                    "staged-paper: " + BLUEPRINT_STATE, BLUEPRINT_STATE]
    assert result == "actual local review passed" and actual_reviews == ["blueprint"]
    assert paths["blueprint"].read_bytes() == before
    state = json.loads(paths["state"].read_text())
    assert service.stage_is_current(paths, state, "blueprint")
    assert state["stages"]["blueprint"]["directed_attempts"] == service.DIRECTED_REPAIR_ATTEMPTS
    assert state["stages"]["blueprint"]["attempts"] == 1


@pytest.mark.parametrize("target", ["paper/sections/03_method.tex", "../paper/CONTRIBUTION_BLUEPRINT.md",
    "paper/CONTRIBUTION_BLUEPRINT.md; replace the hypothesis", "paper/main.tex; add causal evidence",
    "./paper/CONTRIBUTION_BLUEPRINT.md", "paper\\CONTRIBUTION_BLUEPRINT.md", "paper/FOREIGN.md"])
def test_only_exact_declared_same_stage_or_assembly_targets_can_be_neutral(tmp_path, target):
    service, paths = _completed_blueprint(tmp_path)
    coordinator = _coordinator(tmp_path, service, paths)
    run = SimpleNamespace(stage_id="blueprint", revision_issues=["Target artifact: " + target, BLUEPRINT_STATE])
    assert not stage_freshness_only(coordinator, run)


def test_target_metadata_alone_never_grants_local_revalidation(tmp_path):
    service, paths = _completed_blueprint(tmp_path)
    coordinator = _coordinator(tmp_path, service, paths)
    run = SimpleNamespace(stage_id="blueprint", revision_issues=[
        "Target artifact: paper/main.tex", "Target artifact: paper/CONTRIBUTION_BLUEPRINT.md"])
    assert not stage_freshness_only(coordinator, run)


@pytest.mark.parametrize("feedback", [BLUEPRINT_STATE + "; change the scientific mechanism",
    "Researcher feedback: revise the causal comparison", "Method: Method has not passed its local section contract."])
def test_same_stage_routing_metadata_cannot_hide_new_or_wrong_stage_scientific_feedback(tmp_path, feedback):
    service, paths = _completed_blueprint(tmp_path)
    coordinator = _coordinator(tmp_path, service, paths)
    run = SimpleNamespace(stage_id="blueprint", revision_issues=[
        "Target artifact: paper/CONTRIBUTION_BLUEPRINT.md", BLUEPRINT_STATE, feedback])
    assert not stage_freshness_only(coordinator, run)
