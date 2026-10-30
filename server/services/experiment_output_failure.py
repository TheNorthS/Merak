"""Keep post-run producer defects blocking until source changes; never rewrite failed results."""

import json
import hashlib
from pathlib import Path

from ..contracts.preparation import PreparationContractError
from ..utils.atomic_write import atomic_write_json
from .experiment_output_contract import output_provenance_instruction
from .implementation_review_receipt import review_source_hash


def _failure(message: str) -> PreparationContractError:
    return PreparationContractError(message + '\n' + output_provenance_instruction(),
        owner='exp-design', paths=('experiments/src/provenance.py', 'experiments/src/evaluation.py'))


def record_output_failure(root: Path, experiment_id: str, message: str) -> None:
    atomic_write_json(root / '.merak/quality/experiment-output-failure.json', {
        'schema': 1, 'experiment_id': experiment_id, 'source_sha256': review_source_hash(root),
        'message': message, 'meaning': 'Failed immutable output; source repair and new execution required.'})


def require_no_known_output_failure(root: Path) -> None:
    path = root / '.merak/quality/experiment-output-failure.json'
    if not path.is_file():
        _check_preserved_attempts(root)
        return
    record = json.loads(path.read_text(encoding='utf8'))
    if record.get('schema') != 1:
        raise ValueError('Unsupported experiment output failure receipt')
    if record['source_sha256'] == review_source_hash(root):
        raise _failure(record['message'])


def _check_preserved_attempts(root: Path) -> None:
    """Recognize current-source failed output receipts from before the failure index existed."""
    required = {p.relative_to(root).as_posix() for p in (root / 'experiments/src').rglob('*.py')}
    required.update(p.relative_to(root).as_posix() for p in (root / 'experiments/configs').rglob('*') if p.is_file())
    required.add('experiments/RUN_SPEC.json')
    if not (root / 'experiments/RUN_SPEC.json').is_file():
        return
    for path in sorted((root / '.merak/experiments').glob('*/run.json')):
        manifest = json.loads(path.read_text(encoding='utf8'))
        if manifest.get('status') != 'failed_validation':
            continue
        attempt = next((row for row in manifest.get('attempts', [])
                        if row.get('attempt') == manifest.get('current_attempt')), {})
        issues = attempt.get('validation_issues') or []
        snapshot_path = path.parent / 'snapshot.json'
        if not issues or not snapshot_path.is_file():
            continue
        snapshot = json.loads(snapshot_path.read_text(encoding='utf8'))
        files = {row['path']: row['sha256'] for row in snapshot.get('files', [])}
        if not required <= files.keys():
            continue
        if all(hashlib.sha256((root / name).read_bytes()).hexdigest() == files[name] for name in required):
            message = 'Managed experiment post-run validation failed: ' + '; '.join(issues)
            record_output_failure(root, manifest['run_id'], message)
            raise _failure(message)


def attempt_uses_current_sources(root: Path, job_id: str) -> bool:
    """A historical failure cannot request another edit after its producing source changed."""
    snapshot_path = root / '.merak/experiments' / job_id / 'snapshot.json'
    if not snapshot_path.is_file():
        return True
    snapshot = json.loads(snapshot_path.read_text(encoding='utf8'))
    paths = [*(root / 'experiments/src').rglob('*.py'),
             *(p for p in (root / 'experiments/configs').rglob('*') if p.is_file()),
             root / 'experiments/RUN_SPEC.json']
    current = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
               for path in paths if path.is_file()}
    original = {row['path']: row['sha256'] for row in snapshot.get('files', [])
                if row['path'].startswith(('experiments/src/', 'experiments/configs/'))
                or row['path'] == 'experiments/RUN_SPEC.json'}
    return bool(original) and original == current


def source_bound_experiment_id(root: Path, workflow_id: str) -> str:
    # Version 3 isolates attempts made before completed-run replay protection.
    identity = f'workflow-{workflow_id}-{review_source_hash(root)[:10]}-v3'
    from .experiment_runtime_state import ACTIVE_EXPERIMENT_STATES
    for path in (root / '.merak/experiments').glob(f'workflow-{workflow_id}*/run.json'):
        previous = json.loads(path.read_text(encoding='utf8'))
        if (previous.get('status') in ACTIVE_EXPERIMENT_STATES
                and not path.parent.name.startswith(identity + '-seed-')):
            raise RuntimeError('Prior experiment process exit is not confirmed; cannot start a different source version')
    return identity
