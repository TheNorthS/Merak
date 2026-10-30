"""Staged figure work counts as revision progress before formal commit."""

import json
from pathlib import Path

from server.services.figure_revision_progress import (
    figure_draft_progress_signature,
)
from server.workflows.engine import WorkflowEngine
from server.workflows.revision_progress_diagnostics import measure_revision_progress


def _draft(root: Path) -> Path:
    directory = root / ".merak" / "figure-drafts" / "method_architecture"
    (directory / "parts").mkdir(parents=True)
    (directory / "parts" / "001_encoder.svgfrag").write_text(
        '<g id="encoder"><path d="M0 0L2 2"/></g>', encoding="utf-8",
    )
    (directory / "method_architecture.svg").write_text(
        '<svg><g id="encoder"/></svg>', encoding="utf-8",
    )
    (directory / "manifest.json").write_text(json.dumps({
        "artifact_name": "method_architecture",
        "parts": ["001_encoder.svgfrag"],
        "composition_review": {
            "source_sha256": "a" * 64,
            "score": 6.7,
            "verdict": "refine",
            "issues": ["unclear route"],
            "reviewed_at": 10,
            "review_trace_path": "trace/one",
        },
    }), encoding="utf-8")
    return directory


def test_draft_signature_tracks_content_and_review_but_ignores_trace_churn(
    tmp_path: Path,
) -> None:
    directory = _draft(tmp_path)
    first = figure_draft_progress_signature(tmp_path, ["method_architecture"])
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["composition_review"]["reviewed_at"] = 20
    manifest["composition_review"]["review_trace_path"] = "trace/two"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert figure_draft_progress_signature(
        tmp_path, ["method_architecture"],
    ) == first

    manifest["composition_review"]["score"] = 7.1
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    reviewed = figure_draft_progress_signature(tmp_path, ["method_architecture"])
    assert reviewed != first

    (directory / "parts" / "001_encoder.svgfrag").write_text(
        '<g id="encoder"><circle r="2"/></g>', encoding="utf-8",
    )
    assert figure_draft_progress_signature(
        tmp_path, ["method_architecture"],
    ) != reviewed


def test_draft_review_change_resets_no_progress_counter() -> None:
    progress = measure_revision_progress(
        current={"FIG-VISUAL-001"}, previous={"FIG-VISUAL-001"},
        scope_signature="formal:same", previous_scope_signature="formal:same",
        previous_count=1, revision_started=True, transport_attempted=False,
        draft_review_changed=True, draft_review_signature="figure-draft:new",
    )
    assert progress["consecutive_no_progress"] == 0
    assert progress["draft_review_changed"] is True
    assert progress["stall_classification"] == "draft_review_progress"


def test_figure_waiting_signature_includes_staged_draft(tmp_path: Path) -> None:
    engine = WorkflowEngine()
    before = engine._revision_artifact_signature(str(tmp_path), "figure")
    directory = _draft(tmp_path)
    after = engine._revision_artifact_signature(str(tmp_path), "figure")
    assert after != before
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    manifest["composition_review"]["score"] = 7.3
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert engine._revision_artifact_signature(str(tmp_path), "figure") != after
