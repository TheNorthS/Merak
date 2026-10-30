"""An independent impact objection gets one bounded correction, never automatic acceptance."""

from types import SimpleNamespace

import pytest

from server.workflows.report_impact_followup import prepare_impact_followup, save_impact_followup
from server.workflows.report_revision_store import fingerprints


def record(root):
    names = ['literature/references.bib', 'experiments/results/analysis.md', 'NARRATIVE_REPORT.md']
    for name in names:
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('Existing content')
    return {'id': 'report', 'consumer': 'audit', 'round': 1, 'status': 'needs_attention',
            'targets': names[:2], 'expected': fingerprints(root, names[:2]), 'issues': [{'id': 'original', 'status': 'open'}],
            'before_path': 'first-before.json', 'completed_owners': ['lit', 'results'],
            'impact': {'scope': 'linked', 'unresolved': ['experiments/results/analysis.md: Narrow claim scope.',
                'NARRATIVE_REPORT.md still describes the results as pending.', 'literature/references.bib: Verify DOI.']}}


def test_preserves_review_and_consumes_round_before_granting_exact_targets(tmp_path):
    r = record(tmp_path)
    assert prepare_impact_followup(tmp_path, r, options={'run_experiment': True}, maximum=6)
    assert r['round'] == 2 and r['status'] == 'editing'
    assert r['completed_owners'] == [] and 'before_path' not in r
    assert r['impact_attempts'][0]['before_path'] == 'first-before.json'
    assert r['impact_attempts'][0]['impact']['unresolved']
    assert [g['owner'] for g in r['groups']] == ['lit', 'results', 'narrative']
    assert all(issue['status'] == 'open' for issue in r['issues'])
    r['impact'] = r['impact_attempts'][0]['impact']
    assert not prepare_impact_followup(tmp_path, r, options={'run_experiment': True}, maximum=6)


@pytest.mark.parametrize('message', ['Unknown target', 'experiments/results/summary.csv: Change values.',
                                   '.merak/state.json: Accept task.', 'NARRATIVE_REPORT.md/../private: Write'])
def test_unbounded_or_runtime_target_keeps_impact_unresolved(tmp_path, message):
    r = record(tmp_path)
    r['impact']['unresolved'] = [message]
    assert not prepare_impact_followup(tmp_path, r, options={'run_experiment': True}, maximum=6)


def test_concurrent_author_edit_is_never_overwritten(tmp_path):
    r = record(tmp_path)
    (tmp_path / r['targets'][0]).write_text('User change')
    with pytest.raises(ValueError, match='outside'):
        prepare_impact_followup(tmp_path, r, options={'run_experiment': True}, maximum=6)


def test_expanded_narrative_target_invalidates_current_status_and_retains_history(tmp_path):
    r = record(tmp_path)
    assert prepare_impact_followup(tmp_path, r, options={'run_experiment': True}, maximum=6)
    saved = {'phases': {'narrative': {'status': 'accepted', 'verdict_id': 'original'},
                         'exp-run': {'status': 'accepted', 'verdict_id': 'experiment'}}}
    save_impact_followup(SimpleNamespace(update_state=lambda update: update(saved)), r)
    assert saved['phases']['narrative']['status'] == 'pending'
    assert saved['phases']['narrative']['details']['last_accepted_execution']['verdict_id'] == 'original'
    assert saved['phases']['exp-run']['verdict_id'] == 'experiment'


def test_explicit_resume_reopens_report_before_scheduling_pending_authors(tmp_path):
    from server.workflows.report_revision_recovery import reopen_missing_source_review, active_report_consumer
    r = record(tmp_path)
    r['schema'] = 1
    saved = {'status': 'incomplete', 'config': {'options': {'run_experiment': True}},
             'report_revisions': {'report': r}}
    state = SimpleNamespace(project_path=tmp_path, update_state=lambda update: update(saved))
    reopen_missing_source_review(state)
    assert active_report_consumer(saved) == 'audit'
    assert r['round'] == 2


def test_new_comment_defect_gets_one_turn_with_entries_locked(tmp_path):
    import json
    from server.workflows.report_revision_impact import verify_unchanged_science, source_fingerprints
    r = record(tmp_path)
    bib = tmp_path / 'literature/references.bib'
    original = bib.read_text()
    (tmp_path / r['before_path']).write_text(json.dumps({'literature/references.bib': original}))
    bib.write_text('% Unsupported verification claim\n' + original)
    r.update(round=2, expected=fingerprints(tmp_path, r['targets']))
    r['impact']['unresolved'] = ['literature/references.bib, ref comment: Qualify source access.']
    assert prepare_impact_followup(tmp_path, r, options={'run_experiment': True}, maximum=6)
    assert r['round'] == 3 and r['comment_only_targets'] == ['literature/references.bib']
    r['before_path'] = 'comment-before.json'
    (tmp_path / r['before_path']).write_text(json.dumps({'literature/references.bib': bib.read_text()}))
    r['sources_before'] = source_fingerprints(tmp_path)
    bib.write_text(original)
    verify_unchanged_science(tmp_path, r)
    bib.write_text('Changed entry')
    with pytest.raises(ValueError, match='Comment-only'):
        verify_unchanged_science(tmp_path, r)


def test_issue_identifier_prefix_retains_every_explicit_author_target(tmp_path):
    r = record(tmp_path)
    targets = ['paper/sections/00_abstract.tex', 'paper/sections/01_introduction.tex']
    for name in targets:
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('Authored text')
    r['impact']['unresolved'] = ['AUDIT-DRAFT-0/2-id remains unresolved: ' + ' and '.join(targets) + ' require scope qualifiers.']
    assert prepare_impact_followup(tmp_path, r, options={'run_experiment': True}, maximum=6)
    assert r['targets'] == targets
