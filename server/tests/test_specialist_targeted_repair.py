"""Specialist corrections require the owner trace and a fresh independent verdict."""

import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from server.services.specialist_targeted_repair import repair_specialist_document
from server.services.specialist_dependency_review import review_changed_specialist_inputs
from server.workflows.report_revision_recovery import reopen_missing_source_review


def fixture(root, monkeypatch):
    relative = 'experiments/specialists/DOMAIN_VALIDATION.md'
    artifact = root / relative
    artifact.parent.mkdir(parents=True)
    artifact.write_text('Missing global contrast')
    source = root / 'experiments/METHOD_CONTRACT.json'
    source.write_text('{"estimand":"Full paired interaction"}')
    entry = {'id':'domain-validation','node_id':'results','skill':'domain-validation','artifact':relative,
        'status':'completed','input_digest':'old','artifact_sha256':hashlib.sha256(artifact.read_bytes()).hexdigest(),
        'invocation_trace':'old','session_id':'old'}
    record = {'id':'report','round':1,'targets':[],'expected':{},'status':'refreshing'}
    stored = {}
    ctx = SimpleNamespace(run=SimpleNamespace(id='run',project_path=str(root)),node=SimpleNamespace(id='audit'),
        opts={},research_direction='Any research topic',
        run_state=SimpleNamespace(update_state=lambda fn:fn(stored)))
    ctx.host = SimpleNamespace(_get_default_nodes=lambda:[SimpleNamespace(id='results')], _emit=AsyncMock(),
        _agent_event_counts_as_progress=lambda e:True)
    async def wait(**kw): return await kw['task']
    ctx.host._await_agent_with_activity_watchdog = wait
    payload={'profile':{'family':'generic','study_archetype':'generic'},'subnodes':[entry]}
    committed=[]
    service=SimpleNamespace(_sha256=lambda p:hashlib.sha256(p.read_bytes()).hexdigest(),
        _latest_invocation_trace=lambda *a:{'trace_path':'new','session_id':'new','model_name':'fixed'},
        _artifact_valid=lambda *a:(True,[]),_invocation_trace_valid=lambda r,e:(bool(e.get('session_id')),''),
        load=lambda *a:payload,_selected_specs=lambda *a:[SimpleNamespace(id='domain-validation')],
        _input_digest=lambda *a:'current',plan_path=lambda *a:root/'plan.json',
        _atomic_write=lambda p,v:committed.append(json.loads(json.dumps(v))))
    monkeypatch.setattr('server.services.research_specialists.research_specialist_service',service)
    monkeypatch.setattr('server.services.publication_style.publication_style_service.prepare',lambda *a,**k:{})
    monkeypatch.setattr('server.services.specialist_inputs.input_relatives',lambda *_:('experiments/METHOD_CONTRACT.json',))
    return ctx,record,entry,artifact,source,service,committed


@pytest.mark.asyncio
async def test_only_owner_document_changes_then_independent_review_commits(tmp_path, monkeypatch):
    ctx,record,entry,artifact,source,service,committed=fixture(tmp_path,monkeypatch)
    calls=[]
    async def invoke(skill_name, arguments='', **kw):
        assert skill_name=='domain-validation'
        assert kw['allowed_write_paths']==[entry['artifact']]
        assert set(kw['allowed_tools_override'])=={'Read','Edit','Glob','Grep'}
        calls.append('author');artifact.write_text('Full paired interaction')
        return 'Corrected document'
    monkeypatch.setattr('server.agent.tools.invoke_skill',invoke)
    async def review(root,e,paths,expected):
        calls.append('review')
        valid=artifact.read_text()=='Full paired interaction'
        return {'valid':valid}, {'valid':valid,'issues':[] if valid else ['Missing global contrast']}
    monkeypatch.setattr('server.services.specialist_dependency_review._review_entry',review)
    monkeypatch.setattr('server.services.specialist_dependency_review.dependency_review_valid',lambda r,v,*a:v['valid'])
    await review_changed_specialist_inputs(ctx,record)
    assert calls==['review','author','review']
    assert entry['input_digest']=='current' and entry['session_id']=='new'
    assert record['specialist_repairs'][entry['id']]['status']=='accepted'
    assert source.read_text()=='{"estimand":"Full paired interaction"}'
    assert len(committed)==1


@pytest.mark.asyncio
async def test_failed_independent_review_does_not_commit_or_loop(tmp_path, monkeypatch):
    ctx,record,entry,artifact,source,service,committed=fixture(tmp_path,monkeypatch)
    async def invoke(skill_name, arguments='', **kw):
        artifact.write_text('Still wrong');return 'Claims success'
    monkeypatch.setattr('server.agent.tools.invoke_skill',invoke)
    monkeypatch.setattr('server.services.specialist_dependency_review._review_entry',AsyncMock(
        return_value=({'valid':False},{'valid':False,'issues':['Missing global contrast']})))
    monkeypatch.setattr('server.services.specialist_dependency_review.dependency_review_valid',lambda *a:False)
    with pytest.raises(ValueError,match='remains invalid after two verified content attempts'):
        await review_changed_specialist_inputs(ctx,record)
    assert committed==[] and entry['input_digest']=='old'
    assert record['specialist_repairs'][entry['id']]['status']=='authored'
    assert len(record['specialist_content_history'])==1


@pytest.mark.asyncio
async def test_new_findings_get_first_repair_within_existing_task_budget(tmp_path, monkeypatch):
    ctx, record, entry, artifact, source, service, committed = fixture(tmp_path, monkeypatch)
    ctx.opts['max_revision_rounds'] = 3
    calls = []
    async def invoke(skill_name, arguments='', **kw):
        calls.append(arguments)
        artifact.write_text('Candidate ' + str(len(calls)))
        return 'Submitted for verification'
    responses = iter([{'valid': False, 'issues': [issue]} for issue in
                      ['Aggregation is wrong', 'Source attribution is unsupported', 'Comparison condition is missing']]
                     + [{'valid': True, 'issues': []}])
    async def review(*args):
        response = next(responses)
        return {'valid': response['valid']}, response
    monkeypatch.setattr('server.agent.tools.invoke_skill', invoke)
    monkeypatch.setattr('server.services.specialist_dependency_review._review_entry', review)
    monkeypatch.setattr('server.services.specialist_dependency_review.dependency_review_valid', lambda r,v,*a:v['valid'])
    await review_changed_specialist_inputs(ctx, record)
    assert len(calls) == 3 and len(committed) == 1
    assert 'Comparison condition is missing' in calls[-1]
    assert len(record['specialist_content_history']) == 2


@pytest.mark.asyncio
async def test_distinct_findings_cannot_exceed_task_budget(tmp_path, monkeypatch):
    ctx, record, entry, artifact, source, service, committed = fixture(tmp_path, monkeypatch)
    ctx.opts['max_revision_rounds'] = 2
    author = AsyncMock(return_value='No independent acceptance claimed')
    monkeypatch.setattr('server.agent.tools.invoke_skill', author)
    count = 0
    async def review(*args):
        nonlocal count
        count += 1
        return {'valid': False}, {'valid': False, 'issues': ['Finding ' + str(count)]}
    monkeypatch.setattr('server.services.specialist_dependency_review._review_entry', review)
    monkeypatch.setattr('server.services.specialist_dependency_review.dependency_review_valid', lambda *a:False)
    with pytest.raises(ValueError, match='content repair budget exhausted'):
        await review_changed_specialist_inputs(ctx, record)
    assert author.await_count == 2 and not committed


@pytest.mark.asyncio
async def test_input_mutation_and_interrupted_write_are_not_accepted(tmp_path, monkeypatch):
    ctx,record,entry,artifact,source,service,committed=fixture(tmp_path,monkeypatch)
    async def invoke(skill_name, arguments='', **kw):
        source.write_text('changed scientific contract');return 'Done'
    monkeypatch.setattr('server.agent.tools.invoke_skill',invoke)
    with pytest.raises(ValueError,match='changed authoritative inputs'):
        await repair_specialist_document(ctx,record,entry,[artifact,source],['Fix'],service)
    with pytest.raises(ValueError,match='do not replay'):
        await repair_specialist_document(ctx,record,entry,[artifact,source],['Fix'],service)
    assert committed==[]


@pytest.mark.asyncio
async def test_authored_candidate_is_reused_without_duplicate_edit(tmp_path, monkeypatch):
    ctx,record,entry,artifact,source,service,committed=fixture(tmp_path,monkeypatch)
    author=AsyncMock(return_value='No change required')
    monkeypatch.setattr('server.agent.tools.invoke_skill',author)
    candidate=await repair_specialist_document(ctx,record,entry,[artifact,source],['Check'],service)
    assert await repair_specialist_document(ctx,record,entry,[artifact,source],['Check'],service)==candidate
    author.assert_awaited_once()


def test_explicit_recovery_reopens_only_document_failure_without_resetting_budget(tmp_path):
    saved={'status':'incomplete','report_revisions':{'r':{'status':'needs_attention','round':2,'targets':[],
        'expected':{},'impact':{'scope':'local','unresolved':[]},'completed_owners':['lit'],
        'error':'ValueError: Specialist requires substantive revision: domain-validation: missing term'}}}
    state=SimpleNamespace(project_path=tmp_path,update_state=lambda fn:fn(saved))
    reopen_missing_source_review(state)
    record=saved['report_revisions']['r']
    assert record['status']=='refreshing' and record['round']==2 and record['completed_owners']==['lit']
    record['status']='needs_attention'
    reopen_missing_source_review(state)
    assert record['status']=='needs_attention'


def test_results_exact_owner_write_policy_allows_only_declared_document(tmp_path):
    from server.tests.test_agent_write_scope import _engine
    from server.agent import ToolCall
    target='experiments/specialists/DOMAIN_VALIDATION.md'
    path=tmp_path/target
    path.parent.mkdir(parents=True);path.write_text('Old formula')
    engine,session=_engine(tmp_path,[target])
    session.workflow_node_id='results'
    assert engine._apply_tool_policy(session,ToolCall('edit','Edit',{
        'path':target,'old_text':'Old formula','new_text':'Corrected formula'})) is None
    blocked=engine._apply_tool_policy(session,ToolCall('bad','Edit',{
        'path':'experiments/specialists/STATISTICAL_ANALYSIS_PLAN.md','old_text':'Old','new_text':'New'}))
    assert blocked is not None and not blocked.success


def test_blocked_unchanged_repair_can_recover_once_but_not_user_modified_file(tmp_path):
    from server.services.specialist_targeted_repair import recover_blocked_specialist_write
    target=tmp_path/'experiments/specialists/DOMAIN_VALIDATION.md'
    target.parent.mkdir(parents=True);target.write_text('Unchanged')
    digest=hashlib.sha256(target.read_bytes()).hexdigest()
    path=tmp_path/'.merak/agent-sessions/session.json';path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'messages':[{'role':'tool','content':
        'BLOCKED: workflow node results cannot write outside its owned artifacts. Requested path: DOMAIN_VALIDATION.md'}]}))
    repair={'status':'authored','before_sha256':digest,'after_sha256':digest,
        'candidate':{'artifact':'experiments/specialists/DOMAIN_VALIDATION.md','session_id':'session'}}
    record={'specialist_repairs':{'domain-validation':repair}}
    target.write_text('User edit')
    with pytest.raises(ValueError,match='externally'):
        recover_blocked_specialist_write(tmp_path,record)
    target.write_text('Unchanged')
    assert recover_blocked_specialist_write(tmp_path,record)
    assert not record['specialist_repairs'] and record['specialist_repair_history']==[repair]
    assert not recover_blocked_specialist_write(tmp_path,record)
