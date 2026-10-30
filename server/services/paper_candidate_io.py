"""Task-local file views for isolated paper candidates; canonical paths retain their identity."""

from contextvars import ContextVar
from pathlib import Path
from typing import Any

ACTIVE_CANDIDATE: ContextVar[Any] = ContextVar('paper_candidate', default=None)


def candidate_path(path: Path, *, writing: bool = False) -> Path:
    candidate = ACTIVE_CANDIDATE.get()
    if candidate is None:
        return path
    canonical = path.resolve()
    replacement = candidate.files.get(canonical)
    if writing and replacement is None:
        raise PermissionError('Paper candidate may write only its exact current-stage targets')
    return replacement or path


def candidate_write_guard(path: Path, old_text: str | None = None) -> None:
    candidate = ACTIVE_CANDIDATE.get()
    if candidate is None or candidate.baseline.get(path.resolve()) is None:
        return
    if old_text is None:
        raise PermissionError('Existing paper candidate requires focused Edit operations, not whole-file Write')
    current = candidate_path(path).read_text(encoding='utf-8')
    if len(old_text) > max(1200, int(len(current) * 0.6)):
        raise PermissionError('Paper Edit replaces most of an existing chapter; use a focused paragraph or formula correction')
