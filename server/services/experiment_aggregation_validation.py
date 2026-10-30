"""Validate declared aggregation independently of successful cell execution."""

import json
from pathlib import Path

from ..contracts.preparation import PreparationContractError


def aggregation_failure(root: Path, spec: dict, manifest: Path, detail: str) -> PreparationContractError:
    log = ''
    if manifest.is_file():
        record = json.loads(manifest.read_text(encoding='utf8'))
        attempts = record.get('attempts') or []
        current = next((item for item in attempts if item.get('attempt') == record.get('current_attempt')), {})
        path = Path(current.get('local_log_path') or manifest.parent / 'missing.log').resolve()
        if path.is_relative_to(root) and path.is_file():
            log = path.read_text(encoding='utf8', errors='replace')[-2500:]
    return PreparationContractError(
        'Declared aggregation did not produce validated current-matrix results: ' + detail + '\n' + log
        + '\nRepair the aggregation producer. Preserve historical cell and aggregate outputs. '
        'Support repeated aggregation with matrix-specific immutable versions and a verified atomic '
        'publication of current declared aggregate outputs; do not delete previous evidence to pass. '
        'Raw cell execution and scientific definitions must remain unchanged.',
        owner='exp-design', paths=(str(spec.get('entrypoint') or 'experiments/src/run_analysis.py'),),
    )


def aggregation_issues(root: Path, spec: dict, experiment_id: str) -> list[str]:
    if not spec.get('aggregation_command'):
        return []
    from ..workflows.managed_output_validation import managed_output_issues
    manifest = root / '.merak/experiments' / (experiment_id + '-aggregate') / 'run.json'
    if not manifest.is_file():
        return ['Declared aggregation has no managed execution receipt']
    declared = {'outputs': {'per_run_files': (spec.get('outputs') or {}).get('aggregate_files', [])}}
    issues = managed_output_issues(root, declared, manifest)
    if issues:
        raise aggregation_failure(root, spec, manifest, '; '.join(issues[:8]))
    selection = root / 'experiments/results/accepted_matrix.json'
    if not selection.is_file() or json.loads(selection.read_text(encoding='utf8')).get('matrix_id') != experiment_id:
        return ['Aggregate execution is not bound to the current accepted matrix selection']
    return []


def require_no_failed_aggregation(root: Path, workflow_id: str) -> None:
    from .experiment_output_failure import source_bound_experiment_id
    path = root / 'experiments/RUN_SPEC.json'
    if not path.is_file():
        return
    spec = json.loads(path.read_text(encoding='utf-8-sig'))
    if not spec.get('aggregation_command'):
        return
    identity = source_bound_experiment_id(root, workflow_id)
    manifest = root / '.merak/experiments' / (identity + '-aggregate') / 'run.json'
    if manifest.is_file():
        aggregation_issues(root, spec, identity)
