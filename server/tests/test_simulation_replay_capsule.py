"""Frozen numeric replay must reconstruct exactly without copying result rows as inputs."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from server.services import simulation_replay_capsule as capsule
from server.services.simulation_numeric_replay import INPUT_FILES, ROW_FILES, _write_rows, replay_numeric_records
from server.services.planned_result_bundle import (
    _main_rows, _ablation_rows, _robustness_rows, _calibration_rows, _efficiency_rows, _resource_labels,
)


def _fixture(root: Path) -> None:
    methods, ids = ['Reference', 'Candidate'], {'Reference': 'reference', 'Candidate': 'candidate'}
    groups = [_main_rows(methods, ids, 'accuracy', 'maximize', 'auc', 'ece', 'shift'),
        _ablation_rows(['Full', 'Without identity'], ['identity'], [], 'accuracy', 'maximize'),
        _robustness_rows(methods, ids, ['0', '0.5', '1'], 'shift', 'accuracy', 'maximize'),
        _calibration_rows(methods, ids, ('Retained coverage', 'Selective risk')),
        _efficiency_rows(methods, ids, _resource_labels('algorithm_benchmark'), 'accuracy', 'maximize')]
    files = {name: '{}' for name in INPUT_FILES}
    files['experiments/RUN_SPEC.json'] = json.dumps({'seeds': [13, 42, 73]})
    inputs = {'schema': 1, 'direction': '', 'publication_style': {'family': 'machine_learning',
        'study_archetype': 'algorithm_benchmark'}, 'rows': groups, 'files': files,
        'primary_metric': 'accuracy', 'metric_direction': 'maximize', 'claim_ids': ['C1'],
        'validation_curve_labels': ['Retained coverage', 'Selective risk']}
    records = replay_numeric_records(inputs, root)
    (root / 'paper/PUBLICATION_STYLE.json').write_text(json.dumps(inputs['publication_style']))
    for name, rows in zip(ROW_FILES, groups):
        _write_rows(root / f'experiments/results/templates/{name}.csv', rows)
    plan = {'experiments': [{'id': 'calibration_risk_coverage',
        'data_path': 'experiments/results/templates/calibration_risk_coverage.csv'}]}
    (root / 'experiments/results/templates/PLANNED_RESULT_MANIFEST.json').write_text(json.dumps(plan))
    manifest = {'primary_metric': 'accuracy', 'metric_direction': 'maximize', 'claim_ids': ['C1'],
        'data_files': [{'path': path.relative_to(root).as_posix(),
                        'sha256': hashlib.sha256(path.read_bytes()).hexdigest()} for path in records]}
    (root / capsule.MANIFEST).write_text(json.dumps(manifest))


def test_capsule_replays_exported_source_in_new_process_and_preserves_frozen_records(tmp_path, monkeypatch):
    root = tmp_path / 'source'
    _fixture(root)
    before = {path: path.read_bytes() for path in root.rglob('*') if path.is_file()}
    report_path = capsule.ensure_simulation_replay_capsule(root, '')
    report = json.loads(report_path.read_bytes())
    assert report['accepted'] and report['record_count'] >= 18
    assert all(path.read_bytes() == raw for path, raw in before.items())
    result = subprocess.run([sys.executable, '-B', str(report_path.parent / 'replay.py'),
        '--output', str(tmp_path / 'independent')], cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['exact_records'] == report['record_count']
    def forbidden(*_args):
        pytest.fail('Current capsule must not replay or rewrite')
    monkeypatch.setattr(capsule, 'replay_numeric_records', forbidden)
    assert capsule.ensure_simulation_replay_capsule(root, '') == report_path
    archive = report_path.parent / 'source.zip'
    archive.write_bytes(archive.read_bytes() + b'tampered')
    with pytest.raises(ValueError, match='capsule changed'):
        capsule.ensure_simulation_replay_capsule(root, '')


@pytest.mark.parametrize('failure', ['changed_record', 'numerical_template', 'different_construction'])
def test_capsule_refuses_unverifiable_reconstruction_without_changing_originals(tmp_path, failure):
    root = tmp_path / 'source'
    _fixture(root)
    if failure == 'changed_record':
        target = root / 'experiments/results/simulated/main_comparison.csv'
        target.write_bytes(target.read_bytes() + b'changed')
    else:
        target = root / 'experiments/results/templates/main_comparison.csv'
        text = target.read_text(encoding='utf-8-sig')
        if failure == 'numerical_template':
            import csv, io
            rows = list(csv.DictReader(io.StringIO(text)))
            rows[0]['value'] = '0.99'
            _write_rows(target, rows)
        else:
            target.write_text(text.replace('Reference', 'Other reference'), encoding='utf-8-sig')
    before = {path: path.read_bytes() for path in root.rglob('*') if path.is_file()}
    with pytest.raises(ValueError):
        capsule.ensure_simulation_replay_capsule(root, '')
    assert not (root / capsule.CAPSULE).exists()
    assert all(path.read_bytes() == raw for path, raw in before.items())
