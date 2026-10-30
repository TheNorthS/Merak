"""Publish reported per-seed intervals without replacing their registered sampling unit."""
import csv
import json
from pathlib import Path


def reported_matrix_rows(root: Path, role: str) -> list[dict[str, str]] | None:
    if not (root / 'experiments/results/accepted_matrix.json').is_file():
        return None
    from .scientific_assets import scientific_asset_service, _clean_name
    from .scientific_matrix_records import matrix_aggregate_records
    proven = scientific_asset_service._proven_sources(root)
    records = matrix_aggregate_records(scientific_asset_service, root, proven)
    if records is None:
        return None
    selected = {(item.source, item.split) for item in records if item.role == role}
    spec = json.loads((root / 'experiments/RUN_SPEC.json').read_text(encoding='utf8'))
    rows = []
    for relative in (spec.get('outputs') or {}).get('aggregate_files', []):
        if Path(relative).suffix.lower() != '.csv' or relative not in proven:
            continue
        with (root / relative).open(encoding='utf-8-sig', newline='') as stream:
            for index, row in enumerate(csv.DictReader(stream)):
                split = _clean_name(row.get('axis') or row.get('split') or '').casefold()
                required = {'seed', 'baseline', 'metric', 'mean_delta', 'sd_delta', 'ci95_low', 'ci95_high', 'n_sequences'}
                if (relative, split) not in selected or not required <= row.keys():
                    continue
                rows.append({'method': _clean_name(row['baseline']), 'metric': row['metric'] + ' (mean delta)',
                    'split': split, 'condition_name': 'condition', 'condition_value': row.get('condition', ''),
                    'seed': row['seed'], 'mean': row['mean_delta'], 'std': row['sd_delta'],
                    'n': row['n_sequences'], 'ci95_low': row['ci95_low'], 'ci95_high': row['ci95_high'],
                    'ci_method': 'reported_sequence', 'source_data': relative, 'source_row_index': str(index)})
    return rows or None
