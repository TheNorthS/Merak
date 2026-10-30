"""Preserve completed runs as historical deliveries while Chat edits a working revision."""

import hashlib
from pathlib import Path

from ..utils.atomic_write import atomic_write_bytes, atomic_write_json


def _delivery_files(root: Path, state: dict) -> list[Path]:
    from .latex_bundle import latex_source_bundle
    files = set()
    for name in ('paper', 'slides'):
        if (root / name / 'main.tex').is_file():
            files.update(latex_source_bundle(root / name)[1])
        files.add(root / name / 'main.pdf')
    for phase in state.get('phases', {}).values():
        for name in (phase.get('details') or {}).get('artifact_snapshot', {}):
            files.add((root / name).resolve())
    return sorted(path for path in files if path.is_file() and not path.is_symlink()
                  and path.is_relative_to(root) and '.merak' not in path.relative_to(root).parts)


def preserve_completed_version(root: Path, state: dict) -> str:
    """Snapshot existing delivery bytes before editing; never grant new acceptance."""
    run_id = str(state['run_id'])
    if not run_id or any(char not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for char in run_id):
        raise ValueError('Invalid completed run identity')
    directory = root / '.merak/completed-versions' / run_id
    manifest = directory / 'manifest.json'
    if manifest.is_file():
        return manifest.relative_to(root).as_posix()
    hashes = {}
    for path in _delivery_files(root, state):
        relative = path.relative_to(root).as_posix()
        raw = path.read_bytes()
        atomic_write_bytes(directory / 'artifacts' / relative, raw)
        hashes[relative] = hashlib.sha256(raw).hexdigest()
    atomic_write_json(directory / 'run.json', state)
    atomic_write_json(manifest, {'schema': 1, 'run_id': run_id, 'status': 'completed',
        'artifact_sha256': hashes, 'meaning': 'Historical completed delivery; later working edits are separate.'})
    return manifest.relative_to(root).as_posix()


def record_completed_revision(root: Path, state: dict, receipt: dict) -> None:
    """Record a local edit without changing completed status or scheduling a workflow."""
    manifest = preserve_completed_version(root, state)
    run_id = state['run_id']
    completed = receipt.setdefault('completed_runs', [])
    if run_id not in completed:
        completed.append(run_id)
    receipt.update(revision_mode='local', workflow_restart_required=False,
        revision_validation='not_independently_reviewed')
    path = root / '.merak/local-revisions' / f"{receipt['id']}-{run_id}.json"
    receipt_path = (f".merak/overleaf-revisions/{receipt['id']}/revision.json"
                    if receipt.get('source') == 'overleaf' else f".merak/research-edits/{receipt['id']}.json")
    if not path.is_file():
        atomic_write_json(path, {'schema': 1, 'revision_id': receipt['id'], 'base_run_id': run_id,
            'baseline_manifest': manifest, 'change_receipt': receipt_path,
            'path': receipt['path'], 'source': receipt.get('source', 'chat'),
            'created_at': receipt['created_at'], 'validation': 'not_independently_reviewed',
            'workflow_restart_required': False, 'scheduled_nodes': []})


def preserve_edit_before(root: Path, receipt: dict, raw: bytes | None) -> None:
    """Retain the exact pre-edit bytes for inspecting or reverting one local revision."""
    if raw is not None:
        path = root / '.merak/research-edits' / f"{receipt['id']}.before"
        if not path.exists():
            atomic_write_bytes(path, raw)
