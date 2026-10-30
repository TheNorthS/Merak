"""Compare producer-generated evidence before publishing a provenance-only replacement."""

import csv
import hashlib
import json
from pathlib import Path


ADDED_FIELDS = frozenset({'planned_split_protocol', 'construction_scope', 'not_primary_grid_replicate',
                         'source_table', 'not_primary_grid_contrast', 'construction_note'})


def capture_scientific_rows(root: Path) -> dict[str, list[dict]]:
    """Authenticate every recorded tabular observation against its old manifest."""
    manifest = json.loads((root / 'experiments/results/simulated/SIMULATION_MANIFEST.json').read_bytes())
    result = {}
    for item in manifest['data_files']:
        name = item['path']
        path = (root / name).resolve()
        if not path.is_relative_to(root.resolve()) or path.is_symlink():
            raise ValueError('Evidence source escapes project')
        if hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
            raise ValueError('Evidence record changed before version creation: ' + name)
        if path.suffix == '.csv':
            with path.open(encoding='utf-8-sig', newline='') as stream:
                result[name] = list(csv.DictReader(stream))
        elif path.suffix == '.jsonl':
            result[name] = [json.loads(line) for line in path.read_text(encoding='utf-8-sig').splitlines() if line.strip()]
    if not result:
        raise ValueError('No authenticated scientific rows to preserve')
    return result


def verify_provenance_only(root: Path, previous: dict[str, list[dict]]) -> dict:
    """Keep row order, every numeric value and every non-provenance field identical."""
    current = capture_scientific_rows(root)
    if set(current) != set(previous):
        raise ValueError('Provenance repair changed the scientific table inventory')
    changed_fields = set()
    for name, before in previous.items():
        after = current[name]
        if len(before) != len(after):
            raise ValueError('Provenance repair changed row count: ' + name)
        for index, (old, new) in enumerate(zip(before, after)):
            if set(old) - set(new) or (set(new) - set(old)) - ADDED_FIELDS:
                raise ValueError(f'Unexpected provenance columns: {name} row {index}')
            for key, value in old.items():
                if new[key] == value:
                    continue
                allowed = (name.endswith('/claim_evidence.csv') and key == 'split_protocol'
                    and new[key] == 'not_applicable_deterministic_scenario'
                    and new.get('planned_split_protocol') == value)
                if name.endswith('/run_ledger.csv') and key == 'run_level_table_sha256':
                    reference = new.get('run_level_table', '')
                    allowed = (reference in current and reference == old.get('run_level_table')
                        and new[key] == hashlib.sha256((root / reference).read_bytes()).hexdigest())
                if not allowed:
                    raise ValueError(f'Provenance repair changed scientific content: {name} row {index} field {key}')
                changed_fields.add(name + ':' + key)
    return {'tables': len(current), 'rows': sum(map(len, current.values())),
            'scientific_content_unchanged': True, 'changed_fields': sorted(changed_fields)}
