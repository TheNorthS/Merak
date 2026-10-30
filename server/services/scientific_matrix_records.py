"""Select declared, runtime-owned matrix aggregates; control settings are never measurements."""

import json
from dataclasses import replace
from pathlib import Path

import yaml


def matrix_aggregate_records(service, root: Path, proven: set[str]):
    from .scientific_assets import _clean_name
    selection = root / 'experiments/results/accepted_matrix.json'
    if not selection.is_file():
        return None
    spec = json.loads((root / 'experiments/RUN_SPEC.json').read_text(encoding='utf8'))
    sources = (spec.get('outputs') or {}).get('aggregate_files') or []
    if not sources:
        return None
    config_path = root / 'experiments/configs/main.yaml'
    config = yaml.safe_load(config_path.read_text(encoding='utf8')) if config_path.is_file() else {}
    primary = ((config.get('outputs') or {}).get('aggregation') or {}).get('primary_axis', '')
    conditions = config.get('conditions') or {}
    result = []
    for relative in sources:
        path = (root / relative).resolve()
        if not path.is_relative_to(root / 'experiments/results'):
            raise ValueError('Declared aggregate source escapes project results')
        if path.suffix.casefold() != '.csv':
            continue
        if relative not in proven:
            raise ValueError(f'Declared aggregate is not current runtime-owned evidence: {relative}')
        for record in service._records_from_csv(root, path):
            role = 'result' if not primary or record.split == _clean_name(primary).casefold() else 'robustness'
            value = conditions.get(record.condition_value)
            condition_value = str(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else record.condition_value
            result.append(replace(record, role=role, condition_value=condition_value))
    if not result:
        raise ValueError('Declared matrix aggregates contain no explicit measured metric/value records')
    return result


def administrative_result_file(path: Path) -> bool:
    name = path.stem.casefold()
    return name in {'run_manifest', 'provenance', 'completion_manifest', 'accepted_matrix',
                    'config_resolved', 'fit_provenance', 'pairing_audit', 'integrity_index',
                    'search_evidence', 'coverage_report'} or name.endswith('_build')
