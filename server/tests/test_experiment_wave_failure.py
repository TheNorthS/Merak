"""A failed serial wave cannot burn the rest of an authorized experiment matrix."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from server.services.experiment_runner import ExperimentScheduler
from server.services.experiment_models import JobStatus, Experiment


@pytest.mark.asyncio
@pytest.mark.parametrize('stop,failed,expected', [(True, True, False), (True, False, True), (False, True, True)])
async def test_wave_failure_honors_stop_policy(stop, failed, expected):
    scheduler = ExperimentScheduler()
    first = SimpleNamespace(id='one', experiment_id='case', wave=1,
                            status=JobStatus.FAILED if failed else JobStatus.COMPLETED)
    second = SimpleNamespace(id='two', experiment_id='case', wave=2, status=JobStatus.PENDING, priority=0)
    experiment = Experiment(id='case', name='case', jobs=[first, second], wave_size=1,
                            auto_stop_on_anomaly=stop)
    scheduler._experiments['case'] = experiment
    scheduler._notify_listeners = AsyncMock()
    await scheduler._check_wave_completion(first)
    assert (not scheduler._queue.empty()) == expected
    if not expected:
        assert experiment.status == 'partial_failure'
        assert second.status == JobStatus.PENDING


@pytest.mark.asyncio
async def test_failure_inventory_uses_current_source_namespace(tmp_path, monkeypatch):
    import json
    from server.services.experiment_output_failure import source_bound_experiment_id
    from server.workflows.experiment_failure_repair import _failure_inventory
    identity = source_bound_experiment_id(tmp_path, 'case')
    path = tmp_path / '.merak/experiments' / (identity + '-seed-1-0') / 'run.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'run_id': path.parent.name, 'status': 'failed', 'current_attempt': 1,
        'attempts': [{'attempt': 1, 'status': 'failed', 'error': 'Windows telemetry unavailable'}]}))
    run = SimpleNamespace(id='case', project_path=str(tmp_path), options={'experiment_id': 'obsolete'})
    current, records = await _failure_inventory(None, run, {})
    assert current == identity and len(records) == 1
    assert records[0]['error'] == 'Windows telemetry unavailable'
