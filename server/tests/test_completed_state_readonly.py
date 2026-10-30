"""Completed-run detail/list APIs remain readable after a local manuscript revision."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.workflows.engine import WorkflowEngine
from server.workflows.run_state import RunState


@pytest.mark.parametrize('classified', [True, False])
def test_http_reads_do_not_audit_changed_artifacts_or_mutate_completed_state(tmp_path, monkeypatch, classified):
    from server.api import workflow
    from server.services.workflow_readiness import workflow_readiness_service
    engine = WorkflowEngine()
    state = RunState(str(tmp_path), 'finished')
    state.start([{'id': 'paper', 'name': 'Paper', 'skill': '/paper'}], {})
    state.set_status('paper', 'done')
    state.accept('paper', 'frozen-verdict', 'deterministic:test')
    state.complete({'execution_completed': True, 'submission_ready': False,
                    'completion_class': 'reviewable_draft'} if classified else None)
    path = tmp_path / '.merak/runs/finished.json'
    before = path.read_bytes()
    paper = tmp_path / 'paper/main.tex'
    paper.parent.mkdir()
    paper.write_text('A local revision differs from the historical PDF.')
    def forbidden(*_args, **_kwargs):
        raise ValueError('Current print projection differs after local editing')
    monkeypatch.setattr(workflow_readiness_service, 'needs_refresh', forbidden)
    monkeypatch.setattr(workflow_readiness_service, 'assess', forbidden)
    monkeypatch.setattr(workflow, 'workflow_engine', engine)
    monkeypatch.setattr(workflow.workflow_recovery_watchdog, 'observe_project', lambda *_: None)
    app = FastAPI()
    app.include_router(workflow.router, prefix='/api/workflow')
    with TestClient(app) as client:
        detail = client.get('/api/workflow/run-states/finished', params={'project_path': str(tmp_path)})
        listing = client.get('/api/workflow/run-states', params={'project_path': str(tmp_path)})
    assert detail.status_code == listing.status_code == 200
    assert detail.json()['status'] == 'completed'
    assert detail.json()['runtime_active'] is False
    assert listing.json()['runs'][0]['resumable'] is False
    assert path.read_bytes() == before
    assert engine.get_resumable_run_snapshot(str(tmp_path), 'finished') is None
