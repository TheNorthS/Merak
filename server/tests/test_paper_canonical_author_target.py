"""A reviewer may cite the compiled projection, but only its original author is writable."""

import pytest

from server.services.paper_canonical_author_target import canonical_author_target


@pytest.mark.parametrize("prefix", ["derived-figures/tex/", "derived-figures/tex/assembly-layout/paper/", "assembly-layout/paper/"])
def test_current_section_projection_routes_to_existing_author(tmp_path, prefix):
    target = tmp_path / "paper/sections/03_method.tex"
    target.parent.mkdir(parents=True)
    target.write_text("Scientific method")
    assert canonical_author_target(tmp_path, "paper/" + prefix + "sections/03_method.tex") == "paper/sections/03_method.tex"
    assert target.read_text() == "Scientific method"


def test_unknown_or_missing_projection_is_not_given_an_author_target(tmp_path):
    for target in ("paper/derived-figures/tex/sections/03_method.tex", "paper/derived-figures/tex/../secret.tex", "paper/tables/results.tex"):
        assert canonical_author_target(tmp_path, target) == target


def test_review_scope_and_feedback_use_same_original_author(tmp_path):
    from server.workflows.review_audit import build_review_fix_scope
    from server.workflows.review_models import ReviewRound
    original = tmp_path / 'paper/sections/05_results.tex'
    projected = tmp_path / 'paper/derived-figures/tex/sections/05_results.tex'
    for path in (original, projected, tmp_path / 'paper/sections/04_experiments.tex'):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('Bounded scientific claim')
    review = ReviewRound(1, 5, 'needs_work', action_items=[
        '[owner=paper] [target=paper/derived-figures/tex/sections/05_results.tex] Correct risk endpoints.'])
    actions, targets = build_review_fix_scope(tmp_path, tmp_path / 'paper/main.tex', review)
    assert targets == [original] and 'derived-figures/' not in actions[0]
    assert 'paper/sections/05_results.tex' in actions[0]


@pytest.mark.asyncio
async def test_staged_dispatch_maps_projection_feedback_and_saved_queue_to_original(tmp_path):
    from server.services.paper_draft_coordinator import DraftCoordinator
    from server.services.paper_drafting import PaperDraftingService, AUTHOR_STAGE_ORDER, PAPER_STAGE_ORDER, SECTION_BY_ID, PAPER_STAGE_LABELS, PaperDraftingError
    from server.tests._staged_paper_drafting_support import seed_project
    seed_project(tmp_path)
    service = PaperDraftingService()
    service.prepare(tmp_path, {})
    target = tmp_path / 'paper/sections/05_results.tex'
    target.write_text('Original scientific claim')
    async def invoke(*_args):
        pytest.fail('Routing check must not invoke an author')
    issue = '[owner=paper] [target=paper/derived-figures/tex/sections/05_results.tex] Correct risk bounds.'
    coordinator = DraftCoordinator(service, tmp_path, '', {}, invoke, None, [issue], service.paths(tmp_path),
        AUTHOR_STAGE_ORDER, PAPER_STAGE_ORDER, SECTION_BY_ID, PAPER_STAGE_LABELS, PaperDraftingError, 1, 2)
    coordinator._configure_targeted_repairs()
    assert set(coordinator.target_stage_issues) == {'results', 'consistency'}
    assert all('derived-figures/' not in item for item in coordinator.target_stage_issues['results'])
    coordinator.revision_issues = []
    coordinator._configure_targeted_repairs()
    assert set(coordinator.target_stage_issues) == {'results', 'consistency'}
    assert target.read_text() == 'Original scientific claim'
