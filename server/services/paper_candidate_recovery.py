"""Recover a process interrupted during multi-file candidate publication, without erasing foreign edits."""

from contextlib import ExitStack
import hashlib
import json
from pathlib import Path

from ..utils.atomic_write import atomic_write_bytes, atomic_write_json, path_lock


def recover_paper_commits(root: Path, stage: str) -> None:
    for receipt in (root / '.merak/paper-candidates').glob('*/transaction.json'):
        data = json.loads(receipt.read_bytes())
        if data.get('status') != 'committing' or data.get('identity', {}).get('stage') != stage:
            continue
        baseline = data['identity']['baseline']
        originals = {}
        with ExitStack() as locks:
            for relative, expected in sorted(baseline.items()):
                path = (root / relative).resolve()
                if Path(relative).is_absolute() or not path.is_relative_to(root / 'paper'):
                    raise ValueError('Interrupted paper commit has a foreign path')
                locks.enter_context(path_lock(path))
                saved = receipt.parent / 'baseline' / relative
                raw = None if expected == '<missing>' else saved.read_bytes()
                digest = lambda value: hashlib.sha256(value).hexdigest() if value is not None else '<missing>'
                if digest(raw) != expected:
                    raise ValueError('Interrupted paper baseline is corrupt')
                current = path.read_bytes() if path.is_file() else None
                if digest(current) not in {expected, data.get('candidate_sha256', {}).get(relative)}:
                    raise ValueError('Interrupted paper commit conflicts with a later external edit')
                originals[path] = raw
            for path, raw in originals.items():
                if raw is None:
                    path.unlink(missing_ok=True)
                else:
                    atomic_write_bytes(path, raw)
            atomic_write_json(receipt, {**data, 'status': 'interrupted_commit_restored'})
