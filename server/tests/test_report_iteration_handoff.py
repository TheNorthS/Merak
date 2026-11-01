"""Exhausted report authors hand off verified writes, never replay ambiguous side effects."""
import hashlib
import json

import pytest

from server.workflows.report_iteration_handoff import recover_joined_report_edits


def checkpoint(root):
    before = root / '.merak/report-revisions/report/1/before.json'
    before.parent.mkdir(parents=True)
    before.write_text(json.dumps({'literature/references.bib': 'Old author'}))
    target = root / 'literature/references.bib'
    target.parent.mkdir()
    target.write_text('New author')
    record = {'status': 'needs_attention', 'error': 'AgentIterationLimit: exhausted', 'active_owner': 'lit',
        'completed_owners': [], 'targets': ['literature/references.bib'], 'started_at': 1,
        'before_path': before.relative_to(root).as_posix(), 'before_sha256': hashlib.sha256(before.read_bytes()).hexdigest(),
        'sources_before': {}}
    traces = root / '.merak/skill-invocations'
    traces.mkdir()
    trace = traces / 'trace.json'
    trace.write_text(json.dumps({'workflow_run_id': 'run', 'parent_context': 'report-revision', 'started_at': 2,
        'status': 'failed', 'error': 'AGENT_ITERATION_LIMIT', 'allowed_write_paths': record['targets'], 'session_id': 'session'}))
    sessions = root / '.merak/agent-sessions'
    sessions.mkdir()
    session = sessions / 'session.json'
    messages = [{'role': 'assistant', 'tool_calls': [{'id': 'edit', 'name': 'Edit',
        'arguments': {'path': str(target), 'old_text': 'Old author', 'new_text': 'New author'}}]},
        {'role': 'tool', 'tool_call_id': 'edit', 'content': 'Edited ' + str(target)}]
    session.write_text(json.dumps({'messages': messages}))
    return record, target, session


@pytest.mark.parametrize('fault', ['', 'user_edit', 'unjoined', 'foreign_run', 'failed_tool'])
def test_recovery_requires_exact_joined_edit_evidence(tmp_path, monkeypatch, fault):
    record, target, session = checkpoint(tmp_path)
    monkeypatch.setattr('server.workflows.report_iteration_handoff.verify_unchanged_science', lambda *a: None)
    if fault == 'user_edit':
        target.write_text('User edit')
    elif fault in {'unjoined', 'failed_tool'}:
        payload = json.loads(session.read_text())
        if fault == 'unjoined': payload['messages'].pop()
        else: payload['messages'][-1]['content'] = 'Error: write failed'
        session.write_text(json.dumps(payload))
    before = target.read_bytes()
    if fault:
        with pytest.raises(ValueError):
            recover_joined_report_edits(tmp_path, 'other' if fault == 'foreign_run' else 'run', record)
        assert record['status'] == 'needs_attention'
    else:
        assert recover_joined_report_edits(tmp_path, 'run', record)
        assert record['status'] == 'verifying' and record['completed_owners'] == ['lit']
        assert record['iteration_handoffs'][0]['status'] == 'requires_independent_impact_review'
    assert target.read_bytes() == before


@pytest.mark.asyncio
async def test_live_exhaustion_reaches_impact_review_without_second_author_call(tmp_path, monkeypatch):
    from server.tests.test_report_revision_workflow import fixture, mock_producers
    from server.workflows.report_revision_coordinator import handle_report_revision
    from server.workflows.revision_loop_context import RevisionComplete
    from server.agent.iteration_budget import AgentIterationLimit
    from server.agent import tools
    ctx = fixture(tmp_path)
    actions = []
    mock_producers(ctx, monkeypatch, actions)
    original = tools.invoke_skill
    async def exhausted(*args, **kwargs):
        await original(*args, **kwargs)
        raise AgentIterationLimit('fixture', 24, 24)
    monkeypatch.setattr(tools, 'invoke_skill', exhausted)
    with pytest.raises(RevisionComplete):
        await handle_report_revision(ctx)
    record, = ctx.run_state.load()['report_revisions'].values()
    assert record['status'] == 'awaiting_review'
    assert len(record['iteration_handoffs']) == 2
    assert actions == [('edit', 'literature/references.bib'), ('edit', 'paper/sections/05_results.tex'),
                       ('impact', 2), ('refresh', 2)]
