"""Dependency verification may refresh a receipt but must never execute scientific producers."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from server.services.specialist_dependency_review import dependency_review_valid
from server.services.review_evidence_packet import build_managed_evidence_packet
from server.workflows.report_revision_execution import refresh_report_outputs
from server.workflows.report_revision_recovery import active_report_consumer, protect_report_recovery
from server.workflows.report_revision_store import begin_report
from server.workflows.report_revision_plan import report_revision_plan
from server.tests.test_report_revision_workflow import fixture


@pytest.mark.asyncio
@pytest.mark.parametrize('include_analysis', [False, True])
async def test_local_refresh_never_executes_experiment_results_or_narrative_primary(tmp_path, monkeypatch, include_analysis):
    ctx = fixture(tmp_path)
    if include_analysis:
        path = tmp_path / 'experiments/results/analysis.md'
        path.parent.mkdir(parents=True)
        path.write_text('Bounded interpretation of unchanged measurements')
        ctx.opts = {'run_experiment': True}
        ctx.diagnostics['findings'].append({'owner_node': 'results',
            'target_files': ['experiments/results/analysis.md'], 'message': 'Correct interpretation'})
    plan = report_revision_plan(tmp_path, 'audit', ctx.diagnostics['findings'], options=ctx.opts)
    record = begin_report(ctx.run_state, plan, tmp_path, 2)
    if include_analysis:
        record['impact_attempts'] = [{'completed_owners': ['results']}]
        record['groups'] = [group for group in record['groups'] if group['owner'] != 'results']
    calls = []
    ctx.host._execute_node = AsyncMock(side_effect=AssertionError('No full node authoring'))
    ctx.host._execute_managed_experiment = AsyncMock(side_effect=AssertionError('No compute'))
    ctx.host._execute_stage_delegates = AsyncMock()
    ctx.host._execute_staged_paper = AsyncMock()
    async def prepare(node, *args):
        calls.append(node.id)
        return 'Prepared current artifacts'
    ctx.host._prepare_node_for_gate = prepare
    ctx.host._acceptance_gate = lambda *args, **kwargs: {'accepted': True, 'verdict_id': 'fresh', 'reviewer': 'gate'}
    ctx.host._bind_gate_artifact_snapshot = lambda *args: None
    monkeypatch.setattr('server.services.paper_plan.paper_plan_service.is_current', lambda *_: True)
    independent = AsyncMock()
    monkeypatch.setattr('server.services.specialist_dependency_review.review_changed_specialist_inputs', independent)
    await refresh_report_outputs(ctx, record)
    assert calls == (['lit', 'results', 'paper'] if include_analysis else ['lit', 'paper'])
    ctx.host._execute_stage_delegates.assert_not_awaited()
    ctx.host._execute_staged_paper.assert_awaited_once()
    ctx.host._execute_node.assert_not_awaited()
    ctx.host._execute_managed_experiment.assert_not_awaited()
    assert independent.await_count == 1
    await refresh_report_outputs(ctx, record)
    assert independent.await_count == 1
    ctx.host._execute_staged_paper.assert_awaited_once()


def test_interrupted_worklist_schedules_only_consumer_until_repair_closes(tmp_path):
    ctx = fixture(tmp_path)
    plan = report_revision_plan(tmp_path, 'audit', ctx.diagnostics['findings'])
    begin_report(ctx.run_state, plan, tmp_path, 2)
    original = ctx.run_state.load()
    assert protect_report_recovery(ctx.host, ctx.run, ctx.run_state)
    assert [node.id for node in ctx.run.nodes] == ['audit']
    assert ctx.run_state.load() == original
    assert active_report_consumer({'report_revisions': {}}) == ''


def _receipt(root):
    source, artifact = root / 'references.bib', root / 'validation.md'
    source.write_text('Corrected citation')
    artifact.write_text('Unchanged scientific validation')
    directory = root / '.merak/model-api-reviewer/independent'
    directory.mkdir(parents=True)
    _, packet = build_managed_evidence_packet(root, [source, artifact], maximum_files=192,
        maximum_bytes=6000000, maximum_file_bytes=1000000)
    raw = json.dumps({'valid': True, 'issues': []}).encode()
    (directory / 'response.txt').write_bytes(raw)
    (directory / 'meta.json').write_text(json.dumps({'success': True,
        'purpose': 'specialist-dependency-review', 'invocation_id': 'independent',
        'evidence_packet': packet, 'response_sha256': hashlib.sha256(raw).hexdigest()}))
    review = {'input_digest': 'new-digest', 'trace_path': str(directory), 'invocation_id': 'independent',
        'artifact_sha256': hashlib.sha256(artifact.read_bytes()).hexdigest(), 'paths': ['references.bib', 'validation.md']}
    return source, artifact, directory, review


def test_independent_dependency_review_invalidates_on_source_or_output_change(tmp_path):
    source, artifact, directory, review = _receipt(tmp_path)
    assert dependency_review_valid(tmp_path, review, 'new-digest', artifact)
    source.write_text('Source replaced')
    assert not dependency_review_valid(tmp_path, review, 'new-digest', artifact)
    source.write_text('Corrected citation')
    artifact.write_text('Changed scientific conclusion')
    assert not dependency_review_valid(tmp_path, review, 'new-digest', artifact)


def test_tampered_or_negative_dependency_verdict_cannot_rebind_sources(tmp_path):
    _, artifact, directory, review = _receipt(tmp_path)
    assert not dependency_review_valid(tmp_path, review, 'unrelated-digest', artifact)
    (directory / 'response.txt').write_text('{"valid":false,"issues":["Changed evidence"]}')
    assert not dependency_review_valid(tmp_path, review, 'new-digest', artifact)
    meta = json.loads((directory / 'meta.json').read_bytes())
    meta['response_sha256'] = hashlib.sha256((directory / 'response.txt').read_bytes()).hexdigest()
    (directory / 'meta.json').write_text(json.dumps(meta))
    assert not dependency_review_valid(tmp_path, review, 'new-digest', artifact)


@pytest.mark.asyncio
async def test_state_write_failure_stops_before_producer_call(tmp_path, monkeypatch):
    from server.workflows.report_revision_coordinator import handle_report_revision
    ctx = fixture(tmp_path)
    ctx.run_state.update_state = lambda *_: (_ for _ in ()).throw(OSError('disk full'))
    invoke = AsyncMock()
    monkeypatch.setattr('server.agent.tools.invoke_skill', invoke)
    with pytest.raises(OSError, match='disk full'):
        await handle_report_revision(ctx)
    invoke.assert_not_called()


def test_paper_gate_failure_never_reopens_completed_bibliography_impact(tmp_path):
    from server.workflows.report_revision_recovery import reopen_missing_source_review
    from server.workflows.report_revision_impact import source_fingerprints
    record={'status':'needs_attention','round':2,'targets':[],'expected':{},'groups':[{'owner':'lit'}],
        'impact':{'scope':'local','unresolved':[]},'refresh_completed':['specialists','plan','paper'],
        'refresh_snapshot':source_fingerprints(tmp_path),'error':'PaperAcceptanceError: inconsistent introduction'}
    saved={'status':'incomplete','report_revisions':{'r':record}}
    state=SimpleNamespace(project_path=tmp_path,update_state=lambda fn:fn(saved))
    reopen_missing_source_review(state)
    assert record['status']=='awaiting_review' and record['round']==2
    assert 'source_review_version' not in record


def test_external_paper_change_blocks_refresh_checkpoint_recovery(tmp_path):
    from server.workflows.report_revision_recovery import reopen_missing_source_review
    record={'status':'needs_attention','targets':[],'expected':{},'refresh_completed':['paper'],
        'refresh_snapshot':{'paper/main.tex':'old'},'error':'PaperAcceptanceError: stopped'}
    saved={'status':'incomplete','report_revisions':{'r':record}}
    with pytest.raises(ValueError,match='outside the saved'):
        reopen_missing_source_review(SimpleNamespace(project_path=tmp_path,update_state=lambda fn:fn(saved)))
