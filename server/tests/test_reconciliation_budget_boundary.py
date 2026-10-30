"""An exhausted rebuild must not launch a reviewer against stale upstream artifacts."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from server.workflows.engine import WorkflowEngine
from server.workflows.models import WorkflowRun
from server.workflows.run_state import RunState
from server.workflows.revision_attempt import _accepted_owner_followup
from server.workflows.revision_loop_context import RevisionComplete


@pytest.mark.asyncio
async def test_saved_owner_repair_pauses_without_refreshing_stale_consumer(tmp_path, monkeypatch):
    host = WorkflowEngine()
    nodes = host._get_default_nodes()
    owner = next(n for n in nodes if n.id == 'lit')
    consumer = next(n for n in nodes if n.id == 'audit')
    run = WorkflowRun(id='bounded-rebuild', project_path=str(tmp_path), nodes=nodes)
    state = RunState(str(tmp_path), run.id)
    state.start([{'id': n.id, 'name': n.name, 'skill': n.skill} for n in nodes], {})
    state.set_status('lit', 'done')
    state.accept('lit', 'repaired-owner', 'test')
    state.begin_reconciliation_transaction(owner_id='lit', artifact_signature='previous',
        reason='Earlier repair', invalidated_phase_ids=['paper'], maximum_transactions=1)
    monkeypatch.setattr(host, '_revision_artifact_signature', lambda *_: 'new-repair')
    monkeypatch.setattr(host, '_revision_runtime_signature', lambda *_: 'runtime')
    host._emit = AsyncMock()
    refresh = AsyncMock()
    monkeypatch.setattr('server.workflows.revision_attempt._require_consumer_refresh', refresh)
    context = SimpleNamespace(host=host, run=run, node=consumer, revision_owner=owner,
        opts={'max_research_loop_cycles': 1}, diagnostics={}, round_number=1, cycle=1,
        owner_rounds={'lit': 1}, result='original')
    with pytest.raises(RevisionComplete) as stopped:
        await _accepted_owner_followup(context, state, True, 'Original review')
    gate, _ = stopped.value.gate_and_result
    assert gate['waiting'] and gate['hard_limit'] and not gate['accepted']
    assert gate['reason'] == 'upstream rebuild budget exhausted'
    refresh.assert_not_awaited()
    saved = state.load()
    assert saved['phases']['lit']['status'] == 'accepted'
    assert saved['phases']['audit']['status'] == 'awaiting_revision'
    assert len(saved['reconciliation_transactions']) == 1
    assert context.opts['max_research_loop_cycles'] == 1
