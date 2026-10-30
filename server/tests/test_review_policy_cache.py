"""A current paper cannot reuse a verdict produced under obsolete review instructions."""

from types import SimpleNamespace

import pytest

from server.workflows import review_loop, review_policy_fingerprint as policy
from server.workflows.review_models import ReviewState


@pytest.mark.parametrize('complete', [True, False])
def test_changed_policy_discards_finished_and_interrupted_review_but_not_paper(tmp_path, monkeypatch, complete):
    from server.workflows import review_audit
    paper = tmp_path/'paper/main.tex';paper.parent.mkdir();paper.write_text('Frozen manuscript')
    persisted = ReviewState(run_id='same-run', is_complete=complete, source_bundle_sha256='science',
        current_round=2, review_policy_sha256='old-policy')
    monkeypatch.setattr(review_audit, 'review_source_bundle', lambda *_: ('science', [paper]))
    monkeypatch.setattr(policy, 'review_policy_fingerprint', lambda _: 'new-policy')
    route = ('model', object(), 'provider/model')
    monkeypatch.setattr(review_loop.model_router, 'get_provider_route', lambda *_: route)
    monkeypatch.setattr(review_loop.model_router, 'get_isolated_provider_route', lambda *_: route)
    context = review_loop.ReviewContext(
        reviewer=SimpleNamespace(_load_state=lambda *_args, **_kw: persisted),
        paper_path=str(paper), project_path=str(tmp_path), max_rounds=4, difficulty='hard',
        on_progress=None, run_id='same-run', researcher_feedback='', evidence_mode='design_only', transport_retry=None)
    state, cached = review_loop._initialize_state(context)
    assert not cached and state is not persisted
    assert state.review_policy_sha256 == 'new-policy' and state.current_round == 0
    assert paper.read_text() == 'Frozen manuscript'


def test_matching_policy_keeps_valid_cached_verdict_and_mismatch_rejects_it():
    snapshot_calls = []
    round_value = SimpleNamespace(has_complete_visual_review=lambda: True,
        visual_review={'_source_bundle_sha256': 'science'})
    state = ReviewState(is_complete=True, rounds=[round_value], source_bundle_sha256='science',
        executor_model='same-model', reviewer_model='same-model', review_policy_sha256='current')
    context = SimpleNamespace(review_policy_sha256='current', executor_identity='same-model',
        reviewer_identity='same-model', project_path='fixture', reviewer=SimpleNamespace(
            _pdf_snapshot_for_source=lambda *_args, **_kw: snapshot_calls.append(1) or {'current': True}))
    assert review_loop._cached_state_valid(context, state, 'science')
    context.review_policy_sha256 = 'new'
    assert not review_loop._cached_state_valid(context, state, 'science')
    assert snapshot_calls == [1]


def test_policy_fingerprint_survives_state_roundtrip(tmp_path):
    from server.workflows.review_state_store import save_review_state, load_review_state
    state = ReviewState(run_id='same-run', review_policy_sha256='actual-policy', max_rounds=4)
    save_review_state(state, str(tmp_path), source_bundle=lambda _: ('science', []))
    loaded = load_review_state(str(tmp_path), run_id='same-run', max_rounds=4, evidence_mode='executed')
    assert loaded.review_policy_sha256 == 'actual-policy'
