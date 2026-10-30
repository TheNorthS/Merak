"""Durable author candidates with validated, conflict-checked canonical publication."""

from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
from typing import Callable

from ..utils.atomic_write import atomic_write_bytes, atomic_write_json, path_lock
from .paper_candidate_io import ACTIVE_CANDIDATE


def _bytes(path: Path) -> bytes | None:
    return path.read_bytes() if path.is_file() else None


def _digest(value: bytes | None) -> str:
    return hashlib.sha256(value).hexdigest() if value is not None else '<missing>'


class PaperCandidate:
    """A candidate may survive cancellation; only a fresh passing check permits publication."""

    def __init__(self, root: Path, stage: str, targets: list[Path], inputs: Callable[[], str]):
        self.root, self.inputs = root.resolve(), inputs
        from .paper_candidate_recovery import recover_paper_commits
        recover_paper_commits(self.root, stage)
        self.baseline = {path.resolve(): _bytes(path) for path in targets}
        if any(not path.is_relative_to(self.root / 'paper') for path in self.baseline):
            raise ValueError('Paper candidate targets must belong to its paper directory')
        self.input_id = inputs()
        identity = {'schema': 1, 'stage': stage, 'input_id': self.input_id,
            'baseline': {path.relative_to(self.root).as_posix(): _digest(raw) for path, raw in self.baseline.items()}}
        key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        self.directory = self.root / '.merak/paper-candidates' / key
        self.receipt = self.directory / 'transaction.json'
        self.files = {path: self.directory / 'candidate' / path.relative_to(self.root) for path in self.baseline}
        self.identity = identity
        if self.receipt.exists():
            previous = json.loads(self.receipt.read_bytes())
            if previous.get('identity') != identity:
                raise ValueError('Paper candidate identity conflicts with its durable receipt')
        else:
            for path, raw in self.baseline.items():
                if raw is not None:
                    atomic_write_bytes(self.directory / 'baseline' / path.relative_to(self.root), raw)
                    atomic_write_bytes(self.files[path], raw)
            self.record('prepared')

    def record(self, status: str, **details) -> None:
        atomic_write_json(self.receipt, {'identity': self.identity, 'status': status,
            'candidate_sha256': {path.relative_to(self.root).as_posix(): _digest(_bytes(target))
                                 for path, target in self.files.items()}, **details})

    def __enter__(self):
        self.token = ACTIVE_CANDIDATE.set(self)
        self.record('authoring')
        return self

    def __exit__(self, kind, error, traceback):
        ACTIVE_CANDIDATE.reset(self.token)
        if kind is not None:
            self.record('interrupted', error_type=kind.__name__)

    def publish(self, review: dict) -> None:
        """Check source and baseline again; a failed write restores every original canonical target."""
        if review.get('passed') is not True:
            self.record('rejected', issues=review.get('issues', []))
            return
        with ExitStack() as locks:
            for path in sorted(self.baseline):
                locks.enter_context(path_lock(path))
            if self.inputs() != self.input_id or any(_bytes(path) != raw for path, raw in self.baseline.items()):
                self.record('conflict')
                raise ValueError('Paper sources or canonical text changed while candidate was being reviewed')
            outputs = {path: target.read_bytes() for path, target in self.files.items()}
            if any(not raw.strip() for raw in outputs.values()):
                raise ValueError('Paper candidate cannot publish an empty output')
            self.record('committing', review=review)
            try:
                for path, raw in outputs.items():
                    atomic_write_bytes(path, raw)
                self.record('committed', review=review)
            except BaseException:
                for path, raw in self.baseline.items():
                    if raw is None:
                        path.unlink(missing_ok=True)
                    else:
                        atomic_write_bytes(path, raw)
                self.record('commit_failed')
                raise


async def author_candidate(coordinator, run, attempt: int, directed: int, no_change: bool):
    """Author/validate locally without exposing unvalidated text to canonical readers."""
    if run.stage_id == 'consistency':
        result = await coordinator._invoke(run, attempt, directed, no_change)
        return result, coordinator.service.validate_stage(coordinator.project_path, run.stage_id)
    service, paths = coordinator.service, coordinator.paths
    def inputs():
        return json.dumps({'authoring': service.authoring_input_hashes(coordinator.project_path),
            'upstream': service.stage_input_signature(paths, run.stage_id),
            'validator': service.stage_validator_signature(run.stage_id)}, sort_keys=True)
    candidate = PaperCandidate(paths['root'], run.stage_id, service.stage_outputs(paths, run.stage_id), inputs)
    with candidate:
        result = await coordinator._invoke(run, attempt, directed, no_change)
        review = service.validate_stage(coordinator.project_path, run.stage_id)
        run.candidate_signature = service.stage_target_semantic_signature(paths, run.stage_id)
    candidate.publish(review)
    return result, review
