"""A successful control manifest is not a scientific metric; selected aggregates remain authoritative."""
import json
from server.services.scientific_assets import scientific_asset_service


def test_registered_aggregate_not_health_settings_drives_primary_plot(tmp_path, monkeypatch):
    results = tmp_path / 'experiments/results'
    results.mkdir(parents=True)
    (tmp_path / 'experiments/configs').mkdir()
    (tmp_path / 'experiments/configs/main.yaml').write_text('conditions: {noise0: 0.0, noise1: 1.0}\noutputs:\n  aggregation:\n    primary_axis: primary_axis\n')
    (results / 'accepted_matrix.json').write_text('{"schema":1}')
    relative = 'experiments/results/summary.csv'
    (tmp_path / 'experiments/RUN_SPEC.json').write_text(json.dumps({'outputs': {'aggregate_files': [relative]}}))
    (tmp_path / relative).write_text('condition,axis,seed,baseline,metric,mean_delta\nnoise0,primary_axis,1,persistence,RMSE,0\nnoise1,primary_axis,1,linear,RMSE,0.3\nnoise1,robustness,1,linear,RMSE,0.5\n')
    (results / 'run_manifest.json').write_text('{"policy":{"zero_loss_epsilon":1e-12}}')
    monkeypatch.setattr(scientific_asset_service, '_proven_sources', lambda _: {relative, 'experiments/results/run_manifest.json'})
    records = scientific_asset_service.collect_records(tmp_path)
    assert len(records) == 3
    assert {record.method for record in records} == {'persistence', 'linear'}
    assert records[0].condition_value == '0.0' and records[1].condition_value == '1.0'
    assert [record.role for record in records] == ['result', 'result', 'robustness']
    assert all('epsilon' not in record.metric for record in records)


def test_unbound_aggregate_is_not_replaced_with_manifest_metrics(tmp_path, monkeypatch):
    import pytest
    results = tmp_path / 'experiments/results'
    results.mkdir(parents=True)
    (results / 'accepted_matrix.json').write_text('{}')
    (tmp_path / 'experiments/RUN_SPEC.json').write_text(json.dumps({'outputs': {'aggregate_files': ['experiments/results/metrics.csv']}}))
    monkeypatch.setattr(scientific_asset_service, '_proven_sources', lambda _: set())
    with pytest.raises(ValueError, match='not current runtime-owned'):
        scientific_asset_service.collect_records(tmp_path)


def test_generic_results_ignore_runtime_configuration_numbers(tmp_path, monkeypatch):
    results = tmp_path / 'experiments/results'
    results.mkdir(parents=True)
    (results / 'run_manifest.json').write_text('{"policy":{"zero_loss_epsilon":1e-12}}')
    (results / 'metrics.csv').write_text('method,metric,value\nlinear,RMSE,0.3\n')
    monkeypatch.setattr(scientific_asset_service, '_proven_sources', lambda _: {
        'experiments/results/run_manifest.json', 'experiments/results/metrics.csv',
    })
    records = scientific_asset_service.collect_records(tmp_path)
    assert len(records) == 1
    assert records[0].metric == 'RMSE' and records[0].value == 0.3
