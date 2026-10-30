"""Attempt-exclusive persistence for genuine authorized execution, never previews."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
import hashlib
import json
from pathlib import Path
import uuid

from .persistence import atomic_write_bytes, atomic_write_json
from .protocol import ProtocolError, owned_output_directory


def source_inventory(package: Path) -> dict[str, str]:
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(package.glob("*.py"))}


def content_hash(value) -> str:
    return hashlib.sha256(json.dumps(serializable(value), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def serializable(value):
    if is_dataclass(value):
        return serializable(asdict(value))
    if isinstance(value, dict):
        return {str(key): serializable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [serializable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


class AttemptWriter:
    """New UUID attempt paths; no overwrite, fabricated success, or old result reuse."""

    def __init__(self, project: Path, identity: dict):
        output = owned_output_directory(project, "experiments/results/executed")
        output.mkdir(parents=True, exist_ok=True)
        self.root = output / uuid.uuid4().hex
        self.root.mkdir(exist_ok=False)
        self.identity = dict(identity)
        self.json("attempt.json", {"schema": 1, "status": "running", **self.identity})

    def _path(self, relative: str) -> Path:
        path = self.root / relative
        if (not isinstance(relative, str) or not relative or path.resolve().parent != self.root.resolve()
                or path.is_symlink() or path.exists() and path.stat().st_nlink > 1):
            raise ProtocolError("Attempt outputs require direct, unlinked owned filenames")
        return path

    def json(self, name: str, value) -> str:
        path = self._path(name)
        atomic_write_json(path, serializable(value))
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def checkpoint(self, name: str, state: dict) -> str:
        import io
        import torch

        path = self._path(name)
        buffer = io.BytesIO()
        torch.save(state, buffer)
        atomic_write_bytes(path, buffer.getvalue())
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def finish(self, *, success: bool, outputs: dict, failure: str = "") -> None:
        if success and failure or not success and not failure:
            raise ProtocolError("Actual attempt completion requires an unambiguous outcome")
        self.json("attempt.json", {"schema": 1, **self.identity,
                  "status": "completed" if success else "failed", "outputs": outputs, "failure": failure,
                  "artifact_sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                                      for path in sorted(self.root.iterdir()) if path.is_file() and path.name != "attempt.json"}})
