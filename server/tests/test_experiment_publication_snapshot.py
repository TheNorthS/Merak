"""Runtime publication metadata must not trigger scientific re-execution."""
from server.services.experiment_runtime_state import ProjectSnapshot, RuntimeSpec, RunManifestStore


def test_publication_updates_do_not_change_execution_snapshot_but_inputs_do(tmp_path):
    (tmp_path / 'paper').mkdir()
    (tmp_path / 'experiments/src').mkdir(parents=True)
    source = tmp_path / 'experiments/src/run.py'
    source.write_text('print(1)')
    (tmp_path / 'MANIFEST.md').write_text('Current workflow state')
    style = tmp_path / 'paper/PUBLICATION_STYLE.json'
    style.write_text('{"generated_at":1}')
    spec = RuntimeSpec(run_id='snapshot', project_path=str(tmp_path), command='python experiments/src/run.py')
    snapshot = ProjectSnapshot(spec, RunManifestStore(tmp_path, 'snapshot'))
    before = snapshot.build(persist=False)
    (tmp_path / 'MANIFEST.md').write_text('New workflow state')
    style.write_text('{"generated_at":2}')
    assert snapshot.build(persist=False)['snapshot_hash'] == before['snapshot_hash']
    source.write_text('print(2)')
    assert snapshot.build(persist=False)['snapshot_hash'] != before['snapshot_hash']
