"""Fresh independent findings do not inherit a false no-progress stop."""

from types import SimpleNamespace

import pytest

from server.services.implementation_review_receipt import persist_review, review_source_hash
from server.workflows.implementation_review_progress import new_implementation_review_scope
from server.workflows.revision_progress_diagnostics import measure_revision_progress, revision_stall_message


@pytest.mark.parametrize('defect', ['', 'stale_source', 'unbound_finding', 'same_scope', 'wrong_owner', 'same_finding'])
def test_source_bound_new_review_scope_keeps_unexamined_findings_and_total_budget(tmp_path, defect):
    target = tmp_path / 'experiments/src/evaluation.py'
    target.parent.mkdir(parents=True)
    target.write_text('def evaluate(): return 1')
    finding = {'id': 'NEW', 'category': 'implementation_review', 'target_files': ['experiments/src/evaluation.py']}
    persist_review(tmp_path, review_source_hash(tmp_path), {'verdict': 'FAIL', 'findings': [finding]})
    context = SimpleNamespace(revision_owner=SimpleNamespace(id='exp-design'),
        run=SimpleNamespace(project_path=str(tmp_path)), last_scope_signature='old', scope_signature='new',
        diagnostics={'findings': [dict(finding)]}, max_revision_rounds=6)
    if defect == 'stale_source': target.write_text('def evaluate(): return 2')
    if defect == 'unbound_finding': context.diagnostics['findings'][0]['id'] = 'UNVERIFIED'
    if defect == 'same_scope': context.scope_signature = 'old'
    if defect == 'wrong_owner': context.revision_owner.id = 'paper'
    progress = measure_revision_progress(current={'NEW'}, previous={'NEW' if defect == 'same_finding' else 'OLD'},
        scope_signature=context.scope_signature, previous_scope_signature='old', previous_count=1,
        revision_started=True, transport_attempted=False, evaluation_complete=False,
        new_author_scope=new_implementation_review_scope(context))
    assert progress['consecutive_no_progress'] == (2 if defect else 0)
    assert progress['resolved_finding_ids'] == []
    if defect != 'same_finding': assert progress['not_evaluated_finding_ids'] == ['OLD']
    assert context.max_revision_rounds == 6


def test_changed_findings_stop_does_not_claim_unchanged_artifacts():
    summary, detail = revision_stall_message('finding_set_changed', 2)
    assert 'remain unevaluated' in summary
    assert 'No content change was detected' not in detail
