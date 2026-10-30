"""Publish a source-and-input capsule only after exact independent numeric reconstruction."""

import hashlib
import json
from pathlib import Path
import tempfile
import zipfile

from ..utils.atomic_write import atomic_write_bytes, atomic_write_json, path_lock
from ..utils.runtime_source_root import server_source_root
from .simulation_numeric_replay import capture_replay_inputs, replay_numeric_records

CAPSULE = 'experiments/results/simulated/reproducibility/replay'
MANIFEST = 'experiments/results/simulated/SIMULATION_MANIFEST.json'
NUMERIC_SUFFIXES = {'.csv', '.jsonl'}
CONSTRUCTORS = ('simulation_primary_comparison.py', 'simulation_analysis_rows.py',
    'simulation_evidence_helpers.py', 'simulation_statistics.py', 'simulation_ranking_evidence.py',
    'simulation_run_evidence.py', 'simulation_claim_evidence.py', 'simulation_numeric_replay.py')


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _records(root: Path, manifest: dict) -> dict[str, str]:
    records = {}
    for item in manifest['data_files']:
        name = item['path']
        if Path(name).suffix not in NUMERIC_SUFFIXES and Path(name).name != 'runtime_artifacts.json':
            continue
        path = (root / name).resolve()
        if (not path.is_relative_to(root) or path.is_symlink() or not path.is_file()
                or _sha(path.read_bytes()) != item['sha256']):
            raise ValueError('Replay cannot authenticate frozen scientific record: ' + name)
        records[name] = item['sha256']
    if not records:
        raise ValueError('Simulation replay has no authenticated numeric records')
    return records


def _source_archive(directory: Path) -> dict[str, str]:
    """Include all repository-owned Python dependencies; no settings or project data."""
    root = server_source_root()
    sources = {}
    with zipfile.ZipFile(directory / 'source.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob('*.py')):
            relative = path.relative_to(root)
            if 'tests' in relative.parts or path.is_symlink():
                continue
            name, raw = 'server/' + relative.as_posix(), path.read_bytes()
            sources[name] = _sha(raw)
            archive.writestr(name, raw)
    _write_constructor_evidence(directory)
    return sources


def _write_constructor_evidence(directory: Path) -> None:
    blocks = ['# Archived numeric construction rules\n',
        'These are source bytes from the replay archive, not empirical observations. '
        'The separate replay receipt verifies reconstruction against frozen records.\n']
    with zipfile.ZipFile(directory / 'source.zip') as archive:
        for name in CONSTRUCTORS:
            raw = archive.read('server/services/' + name)
            blocks.append(f'\n## {name} (sha256={_sha(raw)})\n```python\n' + raw.decode('utf-8') + '\n```\n')
    atomic_write_bytes(directory / 'CONSTRUCTORS.md', '\n'.join(blocks).encode('utf-8'))


def _current(root: Path, directory: Path, records: dict[str, str]) -> bool:
    receipt = directory / 'REPLAY_VERIFICATION.json'
    if not receipt.is_file():
        return False
    report = json.loads(receipt.read_bytes())
    if report.get('schema') != 1 or report.get('accepted') is not True or report.get('records') != records:
        return False
    for name, digest in report.get('capsule_files', {}).items():
        path = (directory / name).resolve()
        if not path.is_relative_to(directory) or not path.is_file() or _sha(path.read_bytes()) != digest:
            raise ValueError('Archived simulation replay capsule changed: ' + name)
    return set(report.get('capsule_files', {})) == {'source.zip', 'inputs.json', 'replay.py', 'SOURCE_INDEX.json', 'CONSTRUCTORS.md'}


def ensure_simulation_replay_capsule(root: Path, direction: str) -> Path | None:
    """Extend provenance without changing any existing manifest, figure, table or numeric value."""
    root = root.resolve()
    if not (root / MANIFEST).is_file():
        return None
    directory = root / CAPSULE
    with path_lock(directory.parent / 'replay-capsule.lock'):
        manifest = json.loads((root / MANIFEST).read_bytes())
        records = _records(root, manifest)
        if _current(root, directory, records):
            return directory / 'REPLAY_VERIFICATION.json'
        if directory.exists():
            raise ValueError('Existing replay capsule no longer matches frozen records; preserve it for review')
        inputs = capture_replay_inputs(root, manifest, direction)
        transactions = root / '.merak/transactions'
        transactions.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='numeric-replay-', dir=transactions) as temporary:
            stage = Path(temporary)
            replay_numeric_records(inputs, stage / 'reconstructed')
            observed = {name: _sha((stage / 'reconstructed' / name).read_bytes()) for name in records}
            if observed != records:
                raise ValueError('Numeric reconstruction differs from frozen records: ' + ', '.join(
                    name for name in records if observed[name] != records[name]))
            capsule = stage / 'capsule'
            capsule.mkdir()
            sources = _source_archive(capsule)
            atomic_write_json(capsule / 'inputs.json', inputs)
            atomic_write_json(capsule / 'SOURCE_INDEX.json', sources)
            runner = server_source_root() / 'services/simulation_plot_templates/replay_numeric.py.tmpl'
            atomic_write_bytes(capsule / 'replay.py', runner.read_bytes())
            report = {'schema': 1, 'accepted': True, 'record_count': len(records), 'records': records,
                'source_module_count': len(sources), 'source_kind': 'verified_reconstruction_source_snapshot',
                'capsule_files': {p.name: _sha(p.read_bytes()) for p in capsule.iterdir()},
                'scope': 'Exact numerical reconstruction only; no empirical EEG training or scientific acceptance.',
                'command': 'python ' + CAPSULE + '/replay.py --output NEW_EMPTY_DIRECTORY'}
            atomic_write_json(capsule / 'REPLAY_VERIFICATION.json', report)
            if _records(root, manifest) != records:
                raise ValueError('Frozen records changed while replaying')
            capsule.replace(directory)
    return directory / 'REPLAY_VERIFICATION.json'
