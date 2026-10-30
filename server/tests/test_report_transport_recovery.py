"""Retry network failures only when the previous repair has no ambiguous file effects."""
import hashlib
from types import SimpleNamespace

import pytest

from server.agent.remote_errors import RemoteCallError
from server.workflows.report_revision_transport import transient_transport, reopen_transport_reports
from server.workflows.review_audit import _source_bundle


def test_transport_classification_preserves_explicit_non_retryable_errors():
    assert transient_transport(RemoteCallError('provider',502))
    assert not transient_transport(RemoteCallError('provider',401))
    assert not transient_transport(ValueError('Bad scientific formula'))
    wrapped=RuntimeError('review failed'); wrapped.__cause__=RemoteCallError('provider',503)
    assert transient_transport(wrapped)


def setup(root):
    target=root/'experiments/specialists/DOMAIN_VALIDATION.md'
    target.parent.mkdir(parents=True);target.write_text('Original')
    source=root/'experiments/METHOD_CONTRACT.json';source.write_text('{}')
    record={'status':'needs_attention','error':'RemoteCallError: REMOTE_HTTP_ERROR: openai-compatible HTTP 502',
        'round':1,'completed_owners':['lit'],'targets':[],'expected':{},'refresh_completed':[],
        'specialist_repairs':{'domain-validation':{'status':'editing',
            'before_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
            'input_hash':_source_bundle(root,[source])[0],
            'previous_entry':{'artifact':'experiments/specialists/DOMAIN_VALIDATION.md','node_id':'results'}}}}
    saved={'status':'incomplete','report_revisions':{'r':record}}
    return target,source,record,SimpleNamespace(project_path=root,update_state=lambda fn:fn(saved))


def test_unchanged_http_failure_resumes_without_consuming_revision_round(tmp_path):
    _,_,record,state=setup(tmp_path)
    reopen_transport_reports(state)
    assert record['status']=='refreshing' and record['round']==1
    assert record['completed_owners']==['lit'] and record['specialist_repairs']=={}
    assert len(record['specialist_transport_history'])==1


@pytest.mark.parametrize('changed',['target','input'])
def test_possible_write_or_external_input_change_blocks_retry(tmp_path,changed):
    target,source,record,state=setup(tmp_path)
    (target if changed=='target' else source).write_text('Changed')
    with pytest.raises(ValueError,match='uncertain|inputs changed'):
        reopen_transport_reports(state)
    assert record['specialist_repairs'] and record['round']==1


def test_exhausted_network_budget_is_not_reset_on_resume(tmp_path):
    _,_,record,state=setup(tmp_path)
    record['transport_interruptions']=3
    reopen_transport_reports(state)
    assert record['status']=='needs_attention'
    assert record['specialist_repairs']
