"""Pure progress policy for isolated implementation model attempts."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class StageProgressSnapshot:
    findings: frozenset[str]
    artifact_sha256: str


def progress_snapshot(
    root: Path, targets: list[str], report: dict[str, Any],
) -> StageProgressSnapshot:
    digest = hashlib.sha256()
    for relative in sorted(set(targets)):
        path = root / relative
        digest.update(relative.encode("utf-8"))
        if path.is_file():
            digest.update(path.read_bytes())
        else:
            digest.update(b"missing")
    return StageProgressSnapshot(
        frozenset(str(item) for item in report.get("issues") or []),
        digest.hexdigest(),
    )


def stage_stop_reason(
    before: StageProgressSnapshot, after: StageProgressSnapshot, report: dict[str, Any],
) -> str:
    """A passing gate or resolved finding is progress; prose/byte churn is not."""
    if report.get("passed") or not before.findings or before.findings - after.findings:
        return ""
    if before.findings != after.findings:
        return ""
    return (
        "no_artifact_progress"
        if before.artifact_sha256 == after.artifact_sha256
        else "ineffective_content_change"
    )
