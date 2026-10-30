"""A repair's runtime record reflects a real scheduler outcome, never an artifact-only gate."""
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from server.workflows.managed_experiment_repair_execution import execute_repaired_experiment


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', [False, True])
async def test_recorded_completion_follows_scheduler_result(failure):
    host = SimpleNamespace(_runtime_execution_started=AsyncMock(return_value=('op', 'experiment_scheduler')),
        _execute_managed_experiment=AsyncMock(return_value='verified result'),
        _runtime_execution_finished=AsyncMock(), _exception_summary=str)
    if failure:
        host._execute_managed_experiment.side_effect = RuntimeError('outputs invalid')
        with pytest.raises(RuntimeError, match='outputs invalid'):
            await execute_repaired_experiment(host, 'node', 'run', {})
        host._runtime_execution_finished.assert_awaited_once_with('node', 'run', 'op', 'experiment_scheduler', error='outputs invalid')
    else:
        assert await execute_repaired_experiment(host, 'node', 'run', {}) == 'verified result'
        host._runtime_execution_finished.assert_awaited_once_with('node', 'run', 'op', 'experiment_scheduler', output='verified result')
    host._execute_managed_experiment.assert_awaited_once()
