"""Reuse successful pixel proofs only inside one validation and for identical current bytes."""

from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
from pathlib import Path
import threading
from typing import Callable

from .paper_derived_figure_binding import local_path


_PROOFS: ContextVar[dict | None] = ContextVar("paper_validation_pixel_proofs", default=None)


@contextmanager
def pixel_validation_scope():
    """No result survives a gate, and independent nested gates start with empty proof sets."""
    token = _PROOFS.set({})
    try:
        yield
    finally:
        _PROOFS.reset(token)


def _identity(root: Path, packet: dict) -> str:
    """Rehash declared scientific inputs, all variants and current renderer implementation."""
    from .paper_derived_figure_rendering import _renderer_digest

    inputs, outputs = packet["original_inputs_sha256"], packet["derived_paths"]
    if not isinstance(inputs, dict) or not inputs or set(outputs) != {"source", "pdf", "svg", "png"}:
        raise ValueError("Pixel proof has no complete current file inventory")
    paths = {*inputs, *outputs.values(), packet["source"], packet["source_path"]}
    digest = hashlib.sha256(str(root).encode())
    digest.update(json.dumps(packet, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode())
    digest.update(_renderer_digest().encode())
    for relative in sorted(paths):
        path = local_path(root, relative)
        digest.update(relative.encode() + b"\0" + hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def validate_pixels_once(root: Path, packet: dict, validate: Callable[[], list[str]]) -> list[str]:
    """Revalidate on any byte change; never memoize failed, interrupted or unstable checks."""
    cache = _PROOFS.get()
    if cache is None:
        return validate()
    try:
        key = (threading.get_ident(), _identity(root, packet))
    except (OSError, ValueError, KeyError, TypeError):
        return validate()
    if key in cache:
        return []
    issues = validate()
    if not issues:
        try:
            if key[1] != _identity(root, packet):
                return ["Paper pixel proof inputs changed during validation"]
            cache[key] = True
        except (OSError, ValueError, KeyError, TypeError):
            return ["Paper pixel proof inputs changed during validation"]
    return issues
