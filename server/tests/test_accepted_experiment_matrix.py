"""Selection is published only after exact current job/output verification."""
import json
from types import SimpleNamespace
import pytest
from server.services.accepted_experiment_matrix import publish_accepted_matrix
from server.services.execution_matrix import compile_execution_cells
from server.services.experiment_models import JobStatus


def fixture(root):
    spec = {'seeds': [1, 2], 'command': 'python run.py {condition} {axis} {seed} {output_dir}',
            'scheduled_runs': {'schema': 1, 'owner': 'scheduler', 'conditions': ['c'], 'holdout_axes': ['a']},
            'outputs': {'per_run_files': ['{output_dir}/metrics.json']}}
    (root / 'experiments').mkdir()
    (root / 'experiments/RUN_SPEC.json').write_text(json.dumps(spec))
    cells = compile_execution_cells(spec, execution_id='matrix-one')
    jobs = [SimpleNamespace(cell=cell, status=JobStatus.COMPLETED) for cell in cells]
    return spec, SimpleNamespace(id='matrix-one', jobs=jobs)


def test_exact_verified_matrix_preserves_old_attempt_directories(tmp_path, monkeypatch):
    spec, experiment = fixture(tmp_path)
    old = tmp_path / 'experiments/results/cells/old/failed.json'
    old.parent.mkdir(parents=True)
    old.write_text('immutable failure')
    monkeypatch.setattr('server.workflows.managed_output_validation.managed_output_issues', lambda *_: [])
    path = publish_accepted_matrix(tmp_path, spec, experiment)
    value = json.loads(path.read_text())
    assert len(value['cells']) == 2 and value['matrix_id'] == 'matrix-one'
    assert all(not row['completion_dir'].startswith('old') for row in value['cells'])
    assert old.read_text() == 'immutable failure'
    assert publish_accepted_matrix(tmp_path, spec, experiment) == path


@pytest.mark.parametrize('failure', ['coverage', 'output'])
def test_incomplete_or_invalid_matrix_cannot_publish(tmp_path, monkeypatch, failure):
    spec, experiment = fixture(tmp_path)
    if failure == 'coverage':
        experiment.jobs[0].status = JobStatus.FAILED
    monkeypatch.setattr('server.workflows.managed_output_validation.managed_output_issues',
                        lambda *_: ['changed output hash'] if failure == 'output' else [])
    with pytest.raises(ValueError, match='unverified matrix'):
        publish_accepted_matrix(tmp_path, spec, experiment)
    assert not (tmp_path / 'experiments/results/accepted_matrix.json').exists()


@pytest.mark.asyncio
async def test_aggregation_runs_only_after_selection_and_checks_runtime_output(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock
    from server.services.accepted_experiment_matrix import aggregate_accepted_matrix
    from server.services.experiment_models import GPUBackend
    from server.services.remote_experiment_runtime import experiment_runtime
    spec, experiment = fixture(tmp_path)
    spec['aggregation_command'] = 'python aggregate.py'
    spec['outputs']['aggregate_files'] = ['experiments/results/summary.csv']
    experiment.backend, experiment.timeout_seconds, experiment.env_vars = GPUBackend.LOCAL, 60, {}
    host = SimpleNamespace(_emit=AsyncMock(), _replace_local_python_launcher=lambda command, _: command)
    monkeypatch.setattr('server.workflows.managed_output_validation.managed_output_issues', lambda *_: [])
    observed = []
    async def execute(runtime):
        assert (tmp_path / 'experiments/results/accepted_matrix.json').is_file()
        observed.append(runtime)
        return SimpleNamespace(status='completed', manifest_path='receipt', error='')
    monkeypatch.setattr(experiment_runtime, 'run', execute)
    await aggregate_accepted_matrix(host, SimpleNamespace(project_path=str(tmp_path)), experiment, spec)
    assert len(observed) == 1 and observed[0].run_id.endswith('-aggregate')
    assert observed[0].gpu_required is False
    assert observed[0].env_vars['MERAK_ACCEPTED_MATRIX_SHA256']
