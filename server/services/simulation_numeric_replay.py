"""Reconstruct scenario records from declared inputs without reading recorded outputs."""

import csv
import io
import json
from pathlib import Path


INPUT_FILES = ('ideas/SELECTED_IDEA.json', 'experiments/METHOD_CONTRACT.json',
               'experiments/RUN_SPEC.json', 'experiments/configs/main.yaml')
ROW_FILES = ('main_comparison', 'ablation', 'robustness_sensitivity', 'calibration_risk_coverage', 'efficiency')


def capture_replay_inputs(root: Path, manifest: dict, direction: str) -> dict:
    """Capture planning inputs only; never infer construction rules from observed outcomes."""
    style = json.loads((root / 'paper/PUBLICATION_STYLE.json').read_bytes())
    groups = []
    for name in ROW_FILES:
        with (root / f'experiments/results/templates/{name}.csv').open(encoding='utf-8-sig', newline='') as handle:
            rows = list(csv.DictReader(handle))
        if not rows or any(row.get(key) for row in rows for key in ('value', 'ci_low', 'ci_high')):
            raise ValueError('Replay requires unfilled planning rows, not recorded numerical outcomes')
        groups.append(rows)
    config = json.loads((root / 'experiments/results/templates/PLANNED_RESULT_MANIFEST.json').read_bytes())
    curve = next(item for item in config['experiments'] if item['id'] == 'calibration_risk_coverage')
    with (root / curve['data_path']).open(encoding='utf-8-sig', newline='') as handle:
        label = next(csv.DictReader(handle))['metric']
    return {'schema': 1, 'direction': direction, 'publication_style': style, 'rows': groups,
            'primary_metric': manifest['primary_metric'], 'metric_direction': manifest['metric_direction'],
            'claim_ids': manifest['claim_ids'], 'validation_curve_labels': ['Retained coverage', label],
            'files': {name: (root / name).read_text(encoding='utf-8-sig') for name in INPUT_FILES
                      if (root / name).is_file()},
            'absent_inputs': [name for name in INPUT_FILES if not (root / name).exists()]}


def _write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    if not rows:
        return
    fields = list(dict.fromkeys(key for row in rows for key in row))
    buffer = io.StringIO(newline='')
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Match the original CSV producer's UTF-8 BOM and platform-independent bytes.
    path.write_bytes(buffer.getvalue().encode('utf-8-sig'))


def replay_numeric_records(inputs: dict, output: Path) -> list[Path]:
    """Write a new directory only. No models, rendering, network or empirical training."""
    from .simulation_benchmark import _analysis, _evidence
    from .simulation_scenario import prepare_simulation_scenario

    present, absent = set(inputs.get('files', {})), set(inputs.get('absent_inputs', []))
    if (inputs.get('schema') != 1 or present & absent or present | absent != set(INPUT_FILES)):
        raise ValueError('Unsupported simulation replay input contract')
    output.mkdir(parents=True, exist_ok=False)
    for name, content in inputs['files'].items():
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content.encode('utf-8'))
    scenario = prepare_simulation_scenario(output, inputs['publication_style'], inputs['direction'],
        tuple(inputs['validation_curve_labels']), inputs['primary_metric'], inputs['metric_direction'])
    analysis = _analysis(output, scenario, inputs['publication_style'], *inputs['rows'],
                         inputs['primary_metric'], inputs['metric_direction'])
    evidence = _evidence(output, scenario, analysis, inputs['claim_ids'], _write_rows)
    return list(evidence.runtime.data_paths.values())
