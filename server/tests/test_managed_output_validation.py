"""Ownership checks over temporary fixture files only, never real experiments."""

import hashlib
import json
from pathlib import Path

import pytest

from server.workflows.engine import WorkflowEngine


def _manifest(root: Path, artifacts: dict[str, dict[str, object]]) -> Path:
    path = root / ".merak" / "experiments" / "job" / "run.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "status": "completed",
                "evidence_eligible": True,
                "current_attempt": 1,
                "attempts": [
                    {
                        "attempt": 1,
                        "status": "completed",
                        "evidence_eligible": True,
                        "result_artifacts": artifacts,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _facts(path: Path) -> dict[str, object]:
    return {
        "bytes": path.stat().st_size,
        "mtime": path.stat().st_mtime,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def test_valid_output_runs_the_whole_validator_without_unbound_stage_inputs(
    tmp_path: Path,
) -> None:
    result = tmp_path / "summary.csv"
    result.write_text("metric,value\naccuracy,0.7\n", encoding="utf-8")
    manifest = _manifest(tmp_path, {"summary.csv": _facts(result)})

    assert (
        WorkflowEngine._managed_experiment_output_issues(
            tmp_path,
            {"outputs": {"per_run_files": ["summary.csv"]}},
            manifest,
        )
        == []
    )


def test_declared_subdirectory_cannot_match_a_different_directory(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "wrong"
    folder.mkdir()
    result = folder / "summary.csv"
    result.write_text("metric,value\naccuracy,0.7\n", encoding="utf-8")
    manifest = _manifest(tmp_path, {"wrong/summary.csv": _facts(result)})

    issues = WorkflowEngine._managed_experiment_output_issues(
        tmp_path,
        {"outputs": {"per_run_files": ["correct/summary.csv"]}},
        manifest,
    )

    assert any("not hash-owned" in issue for issue in issues)


def test_out_of_root_provenance_is_never_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    outside = tmp_path / "provenance.json"
    outside.write_text("{}", encoding="utf-8")
    manifest = _manifest(root, {"../provenance.json": _facts(outside)})
    read_text = Path.read_text

    def guarded_read(path: Path, *args: object, **kwargs: object) -> str:
        if path.resolve() == outside.resolve():
            pytest.fail("validator must not read out-of-root provenance")
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_read)
    issues = WorkflowEngine._managed_experiment_output_issues(
        root,
        {"outputs": {"per_run_files": ["provenance.json"]}},
        manifest,
    )

    assert any("escapes" in issue for issue in issues)


def test_non_object_manifest_returns_a_finding_instead_of_crashing(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "run.json"
    manifest.write_text("[]", encoding="utf-8")
    assert WorkflowEngine._managed_experiment_output_issues(tmp_path, {}, manifest) == [
        "managed run manifest root must be a JSON object",
    ]
