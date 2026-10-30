"""Real worklist orchestration with local fixtures; model/network calls are isolated mocks."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from server.workflows.models import WorkflowRun
from server.workflows.engine import WorkflowEngine
from server.workflows.run_state import RunState
from server.workflows.revision_loop_context import RevisionComplete
from server.workflows.report_revision_coordinator import handle_report_revision, resume_report_revision
from server.workflows.report_revision_plan import report_revision_plan
from server.workflows.report_revision_store import begin_report, fingerprints, save_report, close_reports


def fixture(tmp_path):
    for name in ('literature/references.bib', 'paper/sections/05_results.tex'):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('Original ' + name)
    host = WorkflowEngine()
    nodes = host._get_default_nodes()
    state = RunState(str(tmp_path), 'local-repair')
    state.start([{'id': n.id, 'name': n.name, 'skill': n.skill} for n in nodes], {})
    for node in nodes:
        state.set_status(node.id, 'done')
        state.accept(node.id, 'old-' + node.id, 'original-reviewer')
    findings = [{'id': 'citation', 'severity': 'blocker', 'owner_node': 'lit',
                 'target_files': ['literature/references.bib'], 'message': 'Verify author spelling'},
                {'id': 'aggregation', 'severity': 'blocker', 'owner_node': 'paper',
                 'target_files': ['paper/sections/05_results.tex'], 'message': 'Explain aggregate definition'}]
    run = WorkflowRun(id='local-repair', project_path=str(tmp_path), nodes=nodes)
    return SimpleNamespace(host=host, run=run, node=next(n for n in nodes if n.id == 'audit'),
        run_state=state, diagnostics={'findings': findings}, gate={'accepted': False}, preparation_error='',
        opts={}, max_revision_rounds=2, cycle=1, result='Unresolved audit', research_direction='General research',
        effort='balanced', assurance='draft')


def mock_producers(ctx, monkeypatch, actions):
    ctx.host._emit = AsyncMock()
    async def watchdog(**kwargs):
        return await kwargs['task']
    ctx.host._await_agent_with_activity_watchdog = watchdog
    async def invoke(skill_name, arguments='', **kwargs):
        targets = kwargs['allowed_write_paths']
        actions.append(('edit', targets[0]))
        assert not {'Bash', 'Write', 'Skill', 'reviewer_api'} & set(kwargs['allowed_tools_override'])
        for target in targets:
            path = Path(ctx.run.project_path) / target
            path.write_text(path.read_text() + '\nTargeted correction')
        return 'Author reports completion'
    monkeypatch.setattr('server.agent.tools.invoke_skill', invoke)
    monkeypatch.setattr('server.services.skill_orchestrator.skill_orchestrator.select',
                        lambda node_id, *args, **kwargs: SimpleNamespace(primary=node_id))
    async def assess(root, record, activity):
        actions.append(('impact', len(record['completed_owners'])))
        return {'scope': 'linked', 'reason': 'No changed scientific inputs', 'unresolved': []}
    async def refresh(context, record):
        actions.append(('refresh', len(record['completed_owners'])))
    monkeypatch.setattr('server.workflows.report_revision_impact.assess_impact', assess)
    monkeypatch.setattr('server.workflows.report_revision_execution.refresh_report_outputs', refresh)


@pytest.mark.asyncio
async def test_all_report_owners_edit_before_one_refresh_without_research_restart(tmp_path, monkeypatch):
    ctx = fixture(tmp_path)
    actions = []
    mock_producers(ctx, monkeypatch, actions)
    ctx.host._prepare_research_loop_restart = AsyncMock(side_effect=AssertionError('No research restart'))
    with pytest.raises(RevisionComplete) as finished:
        await handle_report_revision(ctx)
    assert actions == [('edit', 'literature/references.bib'), ('edit', 'paper/sections/05_results.tex'),
                       ('impact', 2), ('refresh', 2)]
    assert finished.value.gate_and_result[0]['restart_from_node'] == 'review'
    state = ctx.run_state.load()
    for node in ('idea', 'novelty', 'exp-design', 'exp-run', 'results'):
        assert state['phases'][node]['status'] == 'accepted'
    assert state['phases']['paper']['details']['last_accepted_execution']['verdict_id'] == 'old-paper'
    record, = state['report_revisions'].values()
    assert record['status'] == 'awaiting_review'
    assert all(i['status'] == 'open' for i in record['issues'])
    close_reports(state, 'review')
    assert record['status'] == 'awaiting_review'
    close_reports(state, 'audit')
    assert record['status'] == 'resolved'


@pytest.mark.asyncio
async def test_resume_skips_completed_owner_and_preserves_user_edits(tmp_path, monkeypatch):
    ctx = fixture(tmp_path)
    actions = []
    mock_producers(ctx, monkeypatch, actions)
    plan = report_revision_plan(tmp_path, 'audit', ctx.diagnostics['findings'])
    record = begin_report(ctx.run_state, plan, tmp_path, 2)
    from server.workflows.report_revision_impact import capture_before
    capture_before(tmp_path, record)
    bib = tmp_path / 'literature/references.bib'
    bib.write_text('Already repaired')
    record['expected'] = fingerprints(tmp_path, record['targets'])
    record['completed_owners'] = ['lit']
    save_report(ctx.run_state, record)
    with pytest.raises(RevisionComplete):
        await resume_report_revision(ctx)
    assert actions[0] == ('edit', 'paper/sections/05_results.tex')
    assert bib.read_text() == 'Already repaired'


@pytest.mark.asyncio
async def test_external_edit_stops_resume_before_any_model_call(tmp_path, monkeypatch):
    ctx = fixture(tmp_path)
    actions = []
    mock_producers(ctx, monkeypatch, actions)
    plan = report_revision_plan(tmp_path, 'audit', ctx.diagnostics['findings'])
    begin_report(ctx.run_state, plan, tmp_path, 2)
    target = tmp_path / 'paper/sections/05_results.tex'
    target.write_text('User edit')
    with pytest.raises(RevisionComplete) as stopped:
        await resume_report_revision(ctx)
    assert stopped.value.gate_and_result[0]['waiting']
    assert actions == [] and target.read_text() == 'User edit'


@pytest.mark.asyncio
@pytest.mark.parametrize('scope', ['research', 'uncertain'])
async def test_changed_scientific_meaning_cannot_take_local_shortcut(tmp_path, monkeypatch, scope):
    ctx = fixture(tmp_path)
    actions = []
    mock_producers(ctx, monkeypatch, actions)
    monkeypatch.setattr('server.workflows.report_revision_impact.assess_impact', AsyncMock(
        return_value={'scope': scope, 'reason': 'Changed claim support', 'unresolved': []}))
    with pytest.raises(RevisionComplete) as stopped:
        await handle_report_revision(ctx)
    assert stopped.value.gate_and_result[0]['waiting']
    assert not any(a[0] == 'refresh' for a in actions)


def test_scientific_and_runtime_targets_use_existing_producer_route(tmp_path):
    ctx = fixture(tmp_path)
    for owner, target in [('exp-design', 'experiments/METHOD_CONTRACT.json'), ('figure', 'figures/FIGURE_MANIFEST.json')]:
        path = tmp_path / target
        path.parent.mkdir(exist_ok=True)
        path.write_text('{}')
        assert report_revision_plan(tmp_path, 'audit', [{'owner_node': owner, 'target_files': [target]}]) is None


def test_renamed_findings_do_not_reset_report_budget(tmp_path):
    ctx = fixture(tmp_path)
    plan = report_revision_plan(tmp_path, 'audit', ctx.diagnostics['findings'])
    record = begin_report(ctx.run_state, plan, tmp_path, 1)
    record['status'] = 'needs_attention'
    save_report(ctx.run_state, record)
    plan['id'] = 'same-defect-new-wording'
    with pytest.raises(ValueError, match='budget exhausted'):
        begin_report(ctx.run_state, plan, tmp_path, 1)


@pytest.mark.asyncio
async def test_measured_analysis_and_citations_share_bounded_report_repair(tmp_path, monkeypatch):
    ctx = fixture(tmp_path)
    analysis = tmp_path / 'experiments/results/analysis.md'
    analysis.parent.mkdir(parents=True)
    analysis.write_text('Independent audit pending; fixed numerical results.')
    ctx.opts = {'run_experiment': True}
    ctx.diagnostics['findings'].append({'id': 'audit-status', 'owner_node': 'results',
        'target_files': ['experiments/results/analysis.md'], 'message': 'Describe the current audit receipt.'})
    actions = []
    mock_producers(ctx, monkeypatch, actions)
    with pytest.raises(RevisionComplete):
        await handle_report_revision(ctx)
    assert actions == [('edit', 'literature/references.bib'), ('edit', 'experiments/results/analysis.md'),
                       ('edit', 'paper/sections/05_results.tex'), ('impact', 3), ('refresh', 3)]
    assert ctx.run_state.load()['phases']['exp-run']['status'] == 'accepted'


@pytest.mark.parametrize('mode', ['design_only', 'synthetic_preview'])
def test_runtime_generated_analysis_cannot_gain_model_write_permission(tmp_path, mode):
    path = tmp_path / 'experiments/results/analysis.md'
    path.parent.mkdir(parents=True)
    path.write_text('Runtime result projection')
    findings = [{'owner_node': 'results', 'target_files': ['experiments/results/analysis.md']}]
    assert report_revision_plan(tmp_path, 'audit', findings,
                                options={'non_experiment_evidence_mode': mode}) is None


def test_report_repair_cannot_edit_measured_data_or_acceptance_receipts(tmp_path):
    for target in ('experiments/results/summary.csv', 'experiments/results/accepted_matrix.json'):
        path = tmp_path / target
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{}')
        assert report_revision_plan(tmp_path, 'audit', [{'owner_node': 'results', 'target_files': [target]}],
                                    options={'run_experiment': True}) is None


@pytest.mark.asyncio
async def test_cancelled_authoring_remains_recoverable_without_marking_owner_complete(tmp_path, monkeypatch):
    ctx = fixture(tmp_path)
    actions = []
    mock_producers(ctx, monkeypatch, actions)
    async def cancel(skill_name, arguments='', **kwargs):
        raise asyncio.CancelledError()
    monkeypatch.setattr('server.agent.tools.invoke_skill', cancel)
    with pytest.raises(asyncio.CancelledError):
        await handle_report_revision(ctx)
    record, = ctx.run_state.load()['report_revisions'].values()
    assert record['status'] == 'editing' and record['completed_owners'] == []
    assert record['active_owner'] == 'lit'
    assert not any(a[0] == 'refresh' for a in actions)


def test_completed_or_cancelled_workflow_cannot_start_repair(tmp_path):
    ctx = fixture(tmp_path)
    plan = report_revision_plan(tmp_path, 'audit', ctx.diagnostics['findings'])
    for status in ('completed', 'cancelled'):
        if status == 'completed':
            assert ctx.run_state.complete()
        else:
            ctx.run_state.set_run_status(status)
        with pytest.raises(ValueError, match='explicitly resumed'):
            begin_report(ctx.run_state, plan, tmp_path, 2)


@pytest.mark.asyncio
async def test_refresh_failure_never_resolves_findings(tmp_path, monkeypatch):
    ctx = fixture(tmp_path)
    actions = []
    mock_producers(ctx, monkeypatch, actions)
    monkeypatch.setattr('server.workflows.report_revision_execution.refresh_report_outputs',
                        AsyncMock(side_effect=ValueError('Compilation failed')))
    with pytest.raises(RevisionComplete) as failed:
        await handle_report_revision(ctx)
    assert failed.value.gate_and_result[0]['waiting']
    record, = ctx.run_state.load()['report_revisions'].values()
    assert record['status'] == 'needs_attention'
    assert all(i['status'] == 'open' for i in record['issues'])
