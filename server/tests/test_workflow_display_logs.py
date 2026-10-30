"""Regression tests for durable workflow-log recovery."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from server.services.workflow_display_logs import read_workflow_display_logs
from server.services.workflow_event_journal import WorkflowEventJournal


def test_recovery_uses_full_event_journal_instead_of_bounded_cache(
    tmp_path: Path,
) -> None:
    journal = WorkflowEventJournal()
    journal.max_display_entries = 2
    for index in range(4):
        journal.record(
            tmp_path,
            "run-88",
            "agent_output",
            {"node_id": "paper", "text": f"durable message {index}"},
        )

    cached = json.loads(
        (tmp_path / ".merak" / "workflow_logs.json").read_text(encoding="utf-8")
    )
    recovered = read_workflow_display_logs(tmp_path, "run-88")

    assert len(cached) == 2
    assert [entry["message"] for entry in recovered.entries] == [
        "durable message 0",
        "durable message 1",
        "durable message 2",
        "durable message 3",
    ]
    assert recovered.source == "event-journal"
    assert recovered.truncated is False


def test_recovery_ignores_one_malformed_journal_line(tmp_path: Path) -> None:
    journal = WorkflowEventJournal()
    journal.record(
        tmp_path,
        "interrupted-run",
        "node_started",
        {"node_id": "figure", "name": "画图"},
    )
    events_path = tmp_path / ".merak" / "runs" / "interrupted-run.events.jsonl"
    with events_path.open("a", encoding="utf-8") as handle:
        handle.write("{interrupted\n")
    journal.record(
        tmp_path,
        "interrupted-run",
        "agent_output",
        {"node_id": "figure", "text": "recovered after interruption"},
    )

    recovered = read_workflow_display_logs(tmp_path, "interrupted-run")

    assert [entry["message"] for entry in recovered.entries] == [
        "Running: 画图",
        "recovered after interruption",
    ]


def test_recovery_uses_latest_run_when_run_id_is_omitted(tmp_path: Path) -> None:
    journal = WorkflowEventJournal()
    journal.record(tmp_path, "older", "agent_output", {"text": "old"})
    journal.record(tmp_path, "newer", "agent_output", {"text": "new"})
    older_path = tmp_path / ".merak" / "runs" / "older.events.jsonl"
    newer_path = tmp_path / ".merak" / "runs" / "newer.events.jsonl"
    os.utime(older_path, (1, 1))
    os.utime(newer_path, (2, 2))

    recovered = read_workflow_display_logs(tmp_path)

    assert recovered.run_id == "newer"
    assert recovered.entries[-1]["message"] == "new"


@pytest.mark.parametrize("run_id", ["..", "../escape", "bad/run", "bad\\run"])
def test_recovery_rejects_unsafe_run_ids(tmp_path: Path, run_id: str) -> None:
    with pytest.raises(ValueError, match="Invalid workflow run id"):
        read_workflow_display_logs(tmp_path, run_id)
