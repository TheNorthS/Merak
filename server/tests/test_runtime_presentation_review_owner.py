"""Reviewer findings cannot grant authors writes to deterministic print output."""

from types import SimpleNamespace

import pytest

from server.workflows import review_loop
from server.workflows.draft_audit_routing import draft_blocker_findings
from server.workflows.review_models import ReviewRound, ReviewState


def _target(root):
    target = root / 'paper/derived-figures/tex/synthetic_preview_figures.tex'
    target.parent.mkdir(parents=True)
    target.write_text('Runtime-owned source-bound caption')
    return target


@pytest.mark.asyncio
async def test_actual_review_repair_dispatch_hands_print_caption_to_runtime_without_author(tmp_path, monkeypatch):
    target = _target(tmp_path)
    issue = '[owner=paper] [target=paper/derived-figures/tex/synthetic_preview_figures.tex] Disclose generated scenario bounds.'
    review = ReviewRound(1, 5, 'needs_work', draft_blockers=[issue])
    context = SimpleNamespace(project_path=str(tmp_path), paper_path=str(tmp_path / 'paper/main.tex'),
                              delivery_goal='reviewable_draft', on_progress=None)
    handoffs = []
    async def stop(_context, _state, _round, reason, *_rest):
        handoffs.append(reason)
        return True
    async def forbidden(*_args):
        pytest.fail('A reviewer may not dispatch a model to overwrite a derived print caption')
    monkeypatch.setattr(review_loop, '_complete_without_fix', stop)
    monkeypatch.setattr(review_loop, '_perform_fix', forbidden)
    assert await review_loop._repair_round(context, ReviewState(run_id='local'), review, 1)
    assert handoffs == ['runtime_presentation_revision_required']
    assert target.read_text() == 'Runtime-owned source-bound caption'


def test_audit_and_review_findings_preserve_runtime_owner_and_empty_author_write_scope(tmp_path):
    from server.workflows.engine import WorkflowEngine
    from server.workflows.review_acceptance_findings import review_revision_findings
    target = _target(tmp_path)
    issue = '[owner=paper] [target=paper/derived-figures/tex/synthetic_preview_figures.tex] Correct evidence label.'
    audit, = draft_blocker_findings(tmp_path, [issue])
    context = SimpleNamespace(project_path=str(tmp_path), rounds=[{'draft_blockers': [issue]}],
                              state={'delivery_goal': 'reviewable_draft'})
    review, = review_revision_findings(WorkflowEngine(), context, SimpleNamespace(active_layout_findings=[]))
    for finding in (audit, review):
        assert finding['owner_node'] == 'paper'
        assert finding['producer_kind'] == 'deterministic'
        assert finding['legal_write_targets'] == []
        assert finding['repair_capability'] == 'paper-print-projection'
        assert finding['target_files'] == [target.relative_to(tmp_path).as_posix()]
        diagnostics = WorkflowEngine()._gate_revision_diagnostics({'accepted': False, 'details': {'findings': [finding]}})
        normalized = next(item for item in diagnostics['findings'] if item['id'] == finding['id'])
        assert normalized['owner_node'] == 'paper'
        assert normalized['repair_capability'] == 'paper-print-projection'
        assert normalized['legal_write_targets'] == []
