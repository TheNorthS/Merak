"""Read-only proof checks against temporary fixtures; no renderer or model API."""

from pathlib import Path

from server.workflows.engine import WorkflowEngine
from server.workflows.review_visual_artifact_evidence import (
    resolve_project_file, prepare_visual_context,
)


def test_project_file_resolution_returns_normally_instead_of_aborting_validation(tmp_path: Path) -> None:
    path = tmp_path / "paper" / "main.tex"
    assert resolve_project_file(tmp_path, "paper/main.tex") == path
    assert resolve_project_file(tmp_path, None) is None
    assert resolve_project_file(tmp_path, "../outside.tex") is None


def test_missing_native_proof_returns_a_structured_rejection(tmp_path: Path) -> None:
    evidence = WorkflowEngine._review_visual_evidence_gate(
        str(tmp_path), {"managed_by": "cross_model_review_loop"}, [],
    )

    assert isinstance(evidence, dict)
    assert evidence["required"] is True
    assert evidence["verified"] is False
    assert "reviewed immutable PDF snapshot is missing from state" in evidence["issues"]
    assert "native visual-review trace directory is missing" in evidence["issues"]


def test_declared_snapshot_path_does_not_escape_the_project(tmp_path: Path) -> None:
    context = prepare_visual_context(
        str(tmp_path), {"current_round": 1, "pdf_snapshots": [{
            "round": 1, "kind": "review_round", "snapshot_path": "../outside.pdf",
        }]}, [{"round": 1, "pdf_snapshot": "../outside.pdf", "visual_review": {}}],
    )

    assert context.reviewed_snapshot is None
    assert "reviewed immutable PDF snapshot is missing from state" in context.issues


def test_non_object_visual_review_is_reported_as_missing_fields(tmp_path: Path) -> None:
    evidence = WorkflowEngine._review_visual_evidence_gate(
        str(tmp_path), {"managed_by": "cross_model_review_loop"},
        [{"round": 1, "visual_review": "invalid-adapter-payload"}],
    )

    assert evidence["verified"] is False
    assert any("lacks visual fields" in issue for issue in evidence["issues"])
