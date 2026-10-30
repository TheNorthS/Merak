"""A stale validator stamp rechecks unchanged authorship without invoking its author."""

import json

import pytest

from server.tests.test_paper_stage_validator_cache import _completed_intro, _coordinator
from server.services.paper_drafting import PaperDraftingError
from server.services.paper_gate_reporting import _active_stage_issues
from server.services.paper_stage_validator_signature import stage_validator_signature


FRESHNESS = "Introduction requires deterministic revalidation under the current paper validator."
PANEL = "scientific asset is included but never referenced in prose: tab:preview-main-results-panel-2"


class _AuthorBoundary(BaseException):
    """Fixture sentinel cannot be mistaken for a recoverable model transport error."""


def _stale_stamp(paths):
    state = json.loads(paths["state"].read_text())
    state["stages"]["introduction"]["validator_signature"] = "0" * 64
    paths["state"].write_text(json.dumps(state))


@pytest.mark.asyncio
async def test_mixed_global_asset_findings_do_not_send_a_valid_stale_section_back_to_a_model(tmp_path, monkeypatch):
    service, paths, introduction = _completed_intro(tmp_path)
    _stale_stamp(paths)
    before = introduction.read_bytes()
    coordinator = _coordinator(tmp_path, service, paths)
    coordinator.revision_issues = [FRESHNESS, PANEL]
    coordinator._configure_targeted_repairs()
    assert coordinator.target_stage_issues["introduction"] == [FRESHNESS]
    assert PANEL in coordinator.target_stage_issues["consistency"]
    assert json.loads(paths["state"].read_text())["stages"]["introduction"]["status"] == "pending"
    checks = []
    actual = service.validate_stage

    def review(root, stage):
        checks.append(stage)
        return actual(root, stage)

    monkeypatch.setattr(service, "validate_stage", review)
    await coordinator._run_stage("introduction")
    assert checks == ["introduction"] and introduction.read_bytes() == before
    state = json.loads(paths["state"].read_text())
    assert state["stages"]["introduction"]["status"] == "completed"
    assert state["stages"]["introduction"]["validator_signature"] == stage_validator_signature("introduction")


def test_gate_reports_validator_freshness_not_an_invented_failed_content_review(tmp_path):
    service, paths, _introduction = _completed_intro(tmp_path)
    _stale_stamp(paths)
    state = json.loads(paths["state"].read_text())
    assert _active_stage_issues("introduction", state["stages"]["introduction"],
                                {"introduction": "Introduction"}, service.stage_contract_version) == [FRESHNESS]


@pytest.mark.asyncio
async def test_explicit_scientific_feedback_cannot_be_satisfied_by_a_passing_local_syntax_review(tmp_path):
    service, paths, introduction = _completed_intro(tmp_path)
    _stale_stamp(paths)
    coordinator = _coordinator(tmp_path, service, paths)
    coordinator.revision_issues = [FRESHNESS, "Introduction: replace the proposed scientific mechanism with a new causal argument."]
    coordinator._configure_targeted_repairs()
    calls = []

    async def author(stage, _prompt, _contract):
        calls.append(stage)
        raise _AuthorBoundary("fixture model boundary reached")

    coordinator.invoke_stage = author
    with pytest.raises(_AuthorBoundary, match="fixture model boundary"):
        await coordinator._run_stage("introduction")
    assert calls == ["introduction"]


@pytest.mark.asyncio
async def test_changed_authored_bytes_prevent_stale_cache_revalidation_shortcut(tmp_path):
    service, paths, introduction = _completed_intro(tmp_path)
    _stale_stamp(paths)
    introduction.write_bytes(introduction.read_bytes() + b"\nNew scientific content absent from reviewed identity.\n")
    coordinator = _coordinator(tmp_path, service, paths)
    coordinator.revision_issues = [FRESHNESS]
    coordinator._configure_targeted_repairs()
    calls = []

    async def author(stage, _prompt, _contract):
        calls.append(stage)
        raise _AuthorBoundary("changed source requires author boundary")

    coordinator.invoke_stage = author
    with pytest.raises(_AuthorBoundary, match="author boundary"):
        await coordinator._run_stage("introduction")
    assert calls == ["introduction"]


@pytest.mark.asyncio
async def test_real_scientific_input_change_never_uses_old_unchanged_section_for_freeze(tmp_path):
    service, paths, _introduction = _completed_intro(tmp_path)
    _stale_stamp(paths)
    (tmp_path / "literature/survey.md").write_text("Changed scientific review source")
    coordinator = _coordinator(tmp_path, service, paths)
    coordinator.revision_issues = [FRESHNESS]
    coordinator._configure_targeted_repairs()
    run = coordinator._stage_run("introduction", json.loads(paths["state"].read_text()), [FRESHNESS])
    from server.services.paper_stage_cache_revalidation import bound_stage_content
    assert not bound_stage_content(coordinator, run)


@pytest.mark.parametrize("text", ["Introduction has not passed its local section contract; alter the causal claim.",
                                  "Introduction requires deterministic revalidation under the current paper validator. Add a new mechanism.",
                                  "Researcher says the introduction is scientifically wrong."])
def test_freshness_recognizer_does_not_truncate_semantic_feedback(text):
    from server.services.paper_stage_cache_revalidation import freshness_only_issue
    assert not freshness_only_issue(text, "Introduction")


@pytest.mark.asyncio
async def test_failed_actual_local_review_does_not_stamp_stale_validity(tmp_path):
    service, paths, _introduction = _completed_intro(tmp_path, valid=False)
    _stale_stamp(paths)
    coordinator = _coordinator(tmp_path, service, paths)
    coordinator.revision_issues = [FRESHNESS]
    coordinator._configure_targeted_repairs()
    async def author(*_args):
        raise _AuthorBoundary("invalid content requires its author")
    coordinator.invoke_stage = author
    with pytest.raises(_AuthorBoundary, match="invalid content"):
        await coordinator._run_stage("introduction")
    record = json.loads(paths["state"].read_text())["stages"]["introduction"]
    assert not record.get("review_passed") and record.get("validator_signature") != stage_validator_signature("introduction")


@pytest.mark.asyncio
async def test_blueprint_validator_only_change_with_global_panels_gets_one_real_local_review(tmp_path, monkeypatch):
    service, paths, _introduction = _completed_intro(tmp_path)
    headings = ("Research Question", "Closest-Work Gap", "One-Sentence Contribution", "Mechanism Logic",
                "Claims and Required Evidence", "Alternative Explanations", "Section Narrative", "Evidence Boundary")
    prose = "The matched scientific control preserves independent units and tests the registered causal alternative. " * 8
    paths["blueprint"].write_text("\n".join("## " + heading + "\n" + prose for heading in headings), encoding="utf-8")
    actual_review = service.validate_stage(tmp_path, "blueprint")
    assert actual_review["passed"]
    service.mark_stage(paths, "blueprint", "completed", attempt=1, review=actual_review)
    state = json.loads(paths["state"].read_text())
    state["stages"]["blueprint"]["validator_signature"] = "0" * 64
    paths["state"].write_text(json.dumps(state))
    before = paths["blueprint"].read_bytes()
    coordinator = _coordinator(tmp_path, service, paths)
    issue = "Contribution blueprint requires deterministic revalidation under the current paper validator."
    coordinator.revision_issues = [issue, PANEL]
    coordinator._configure_targeted_repairs()
    assert coordinator.target_stage_issues["blueprint"] == [issue]
    calls = []
    actual = service.validate_stage

    def validate(root, stage):
        calls.append(stage)
        return actual(root, stage)

    monkeypatch.setattr(service, "validate_stage", validate)
    await coordinator._run_stage("blueprint")
    assert calls == ["blueprint"] and paths["blueprint"].read_bytes() == before
    updated = json.loads(paths["state"].read_text())
    assert service.stage_is_current(paths, updated, "blueprint")


@pytest.mark.parametrize("prefix", ["", "Staged manuscript did not satisfy the quality contract: "])
@pytest.mark.asyncio
async def test_typed_freshness_contract_upgrade_is_revalidated_before_exhausted_directed_budget(tmp_path, prefix):
    service, paths, introduction = _completed_intro(tmp_path)
    state = json.loads(paths["state"].read_text())
    issue = prefix + "Introduction requires deterministic revalidation under the current paper contract."
    record = state["stages"]["introduction"]
    record.update({"status": "revision_required", "review_passed": False,
                   "contract_version": service.stage_contract_version("introduction") - 1,
                   "directed_issue_signature": service.directed_issue_signature([issue]),
                   "directed_attempts": service.DIRECTED_REPAIR_ATTEMPTS})
    paths["state"].write_text(json.dumps(state))
    coordinator = _coordinator(tmp_path, service, paths)
    coordinator.revision_issues = [issue]
    coordinator._configure_targeted_repairs()
    before = introduction.read_bytes()
    await coordinator._run_stage("introduction")
    updated = json.loads(paths["state"].read_text())
    assert service.stage_is_current(paths, updated, "introduction")
    assert introduction.read_bytes() == before


@pytest.mark.parametrize("issue", [
    "Staged manuscript did not satisfy the quality contract: Staged manuscript did not satisfy the quality contract: " + FRESHNESS,
    "Some arbitrary prefix: " + FRESHNESS,
    "Staged manuscript did not satisfy the quality contract: " + FRESHNESS + "; replace the scientific mechanism.",
    "staged manuscript did not satisfy the quality contract: " + FRESHNESS,
])
def test_fixed_aggregate_prefix_is_removed_exactly_once_and_cannot_hide_scientific_feedback(issue):
    from server.services.paper_stage_cache_revalidation import freshness_only_issue
    assert not freshness_only_issue(issue, "Introduction")
