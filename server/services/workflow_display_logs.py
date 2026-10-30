"""Read-only reconstruction of workflow display logs from durable events.

The event journal is authoritative.  The small project-level JSON file is only
a rendering cache and is used when a project has no per-run journal.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

from .workflow_event_display import format_display_entry
from .workflow_event_journal import WorkflowEventJournal


RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
DEFAULT_DISPLAY_LOG_LIMIT = 5000
MAX_DISPLAY_LOG_LIMIT = 10000


@dataclass(frozen=True)
class WorkflowDisplayLogs:
    """A bounded display projection and the durable source used to build it."""

    run_id: str
    entries: list[dict[str, str]]
    source: str
    truncated: bool


def _validated_run_id(run_id: str) -> str:
    normalized = str(run_id or "").strip()
    if normalized in {".", ".."} or not RUN_ID_PATTERN.fullmatch(normalized):
        raise ValueError("Invalid workflow run id")
    return normalized


def _latest_journal(runs_dir: Path) -> Path | None:
    candidates: list[tuple[float, Path]] = []
    for candidate in runs_dir.glob("*.events.jsonl"):
        try:
            candidates.append((candidate.stat().st_mtime, candidate))
        except OSError:
            continue
    return max(candidates, default=(0.0, None), key=lambda item: item[0])[1]


def _display_entry(record: dict[str, Any]) -> dict[str, str] | None:
    event = record.get("event")
    data = record.get("data")
    if not isinstance(event, str) or not isinstance(data, dict):
        return None
    timestamp = record.get("timestamp")
    return format_display_entry(
        event,
        data,
        WorkflowEventJournal._compact,
        timestamp if isinstance(timestamp, (int, float)) else None,
    )


def _read_journal(path: Path, limit: int) -> tuple[list[dict[str, str]], bool]:
    entries: deque[dict[str, str]] = deque(maxlen=limit)
    display_count = 0
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict):
                    continue
                entry = _display_entry(record)
                if entry is not None:
                    display_count += 1
                    entries.append(entry)
    except (OSError, UnicodeError) as exc:
        raise RuntimeError(f"Unable to read workflow event journal: {path.name}") from exc
    return list(entries), display_count > limit


def _read_cache(path: Path, limit: int) -> tuple[list[dict[str, str]], bool]:
    if not path.is_file():
        return [], False
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Unable to read workflow display-log cache") from exc
    valid = [
        entry for entry in payload if isinstance(entry, dict)
        and all(isinstance(entry.get(key), str) for key in ("time", "source", "message", "level"))
    ] if isinstance(payload, list) else []
    return valid[-limit:], len(valid) > limit


def read_workflow_display_logs(
    project_path: str | Path,
    run_id: str = "",
    limit: int = DEFAULT_DISPLAY_LOG_LIMIT,
) -> WorkflowDisplayLogs:
    """Return logs for one run without mutating project state.

    Malformed individual journal lines are ignored so one interrupted write
    cannot hide the remaining durable history.  Invalid identifiers and
    unreadable files fail explicitly.
    """

    bounded_limit = max(1, min(int(limit), MAX_DISPLAY_LOG_LIMIT))
    root = Path(project_path).expanduser().resolve()
    runs_dir = root / ".merak" / "runs"
    journal: Path | None
    if run_id:
        selected_run_id = _validated_run_id(run_id)
        journal = runs_dir / f"{selected_run_id}.events.jsonl"
        if not journal.is_file():
            raise FileNotFoundError(f"Workflow event journal not found: {selected_run_id}")
    else:
        journal = _latest_journal(runs_dir)
        selected_run_id = journal.name.removesuffix(".events.jsonl") if journal else ""

    if journal is not None:
        entries, truncated = _read_journal(journal, bounded_limit)
        return WorkflowDisplayLogs(selected_run_id, entries, "event-journal", truncated)

    entries, truncated = _read_cache(root / ".merak" / "workflow_logs.json", bounded_limit)
    return WorkflowDisplayLogs("", entries, "display-cache", truncated)
