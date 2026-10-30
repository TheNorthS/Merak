"""Portable atomic persistence within a previously validated execution attempt."""

import json
import os
from pathlib import Path
import tempfile


def atomic_write_bytes(path: Path, value: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_write_json(path: Path, value) -> None:
    atomic_write_bytes(path, json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8"))
