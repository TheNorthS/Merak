"""Targeted-node reuse of prior accepted execution evidence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from server.workflows.dependency_reuse import (
    execution_trace_only_failure,
    reusable_dependency_evidence,
)


class _Host:
    def __init__(self, issues: list[str] | None = None) -> None:
        self.issues = issues or []

    def _artifact_snapshot_issues(
        self, _project_path: str, _snapshot: Any,
    ) -> list[str]:
        return self.issues


def _write_run(root: Path, *, status: str = "accepted") -> None:
    path = root / ".merak/runs/prior.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({
        "run_id": "prior",
        "phases": {
            "narrative": {
                "status": status,
                "artifact": str(root / "NARRATIVE_REPORT.md"),
                "verdict_id": "artifact:narrative:123",
                "reviewer": "deterministic:artifact-exists",
                "details": {
                    "input_baseline_snapshot_id": "input-a",
                    "execution_evidence": {
                        "accepted": True,
                        "primary_model_execution_verified": True,
                        "runtime_execution_verified": True,
                    },
                    "artifact_snapshot": {
                        "NARRATIVE_REPORT.md": {
                            "kind": "file", "sha256": "abc", "size": 12,
                        },
                    },
                },
            },
        },
    }), encoding="utf-8")


def test_only_current_run_trace_failure_can_use_prior_evidence() -> None:
    assert execution_trace_only_failure({
        "accepted": False,
        "details": {"issues": [
            "missing verified current-run model execution for /domain-narrative",
        ]},
    }) is True
    assert execution_trace_only_failure({
        "accepted": False,
        "details": {"issues": ["artifact snapshot is stale"]},
    }) is False


def test_hash_current_prior_acceptance_is_reusable(tmp_path: Path) -> None:
    _write_run(tmp_path)

    evidence = reusable_dependency_evidence(
        _Host(), str(tmp_path), "current", "narrative", "input-a",
    )

    assert evidence is not None
    assert evidence["run_id"] == "prior"
    assert evidence["execution_evidence"]["accepted"] is True


def test_changed_or_different_input_prior_acceptance_is_not_reusable(
    tmp_path: Path,
) -> None:
    _write_run(tmp_path)

    assert reusable_dependency_evidence(
        _Host(["accepted artifact changed"]),
        str(tmp_path), "current", "narrative", "input-a",
    ) is None
    assert reusable_dependency_evidence(
        _Host(), str(tmp_path), "current", "narrative", "input-b",
    ) is None
