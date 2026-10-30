"""No-edit review handoffs preserve real printed pixels; changed sources need review."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest

from server.services import paper_print_repair
from server.services.paper_compiler import CompileResult, paper_compiler
from server.services.paper_pdf_quality import inspect_compiled_paper
from server.workflows import review_execution, review_loop
from server.workflows.review_audit import CrossModelReviewer, review_source_bundle
from server.workflows.review_models import ReviewRound, ReviewState
from server.workflows.review_snapshot_reuse import preserve_reviewed_snapshot
from server.workflows.review_visual_evidence import review_visual_evidence_gate
from server.workflows.review_visuals import ReviewSnapshotRequest


def _pdf(path, text="Readable current scientific manuscript."):
    with fitz.open() as document:
        document.new_page().insert_text((72, 90), text, fontsize=12)
        document.save(path)


async def _reviewed_fixture(root, monkeypatch):
    paper = root / "paper/main.tex"
    paper.parent.mkdir()
    section = root / "paper/sections/03_method.tex"
    section.parent.mkdir()
    section.write_text("Frozen reviewed method content.", encoding="utf-8")
    paper.write_text(r"\documentclass{article}\begin{document}\input{sections/03_method}\end{document}", encoding="utf-8")
    pdf = paper.with_suffix(".pdf")
    _pdf(pdf)
    inspect_compiled_paper(paper_compiler, root, pdf)
    calls = []

    async def print_compile(compiler, project, **_options):
        calls.append((compiler, project))
        return CompileResult(success=True, pdf_path=str(pdf), pages=1)

    monkeypatch.setattr(paper_print_repair, "compile_print_verified_paper", print_compile)
    reviewer = CrossModelReviewer()
    state = ReviewState(run_id="local-print-handoff", current_round=1, evidence_mode="existing_results")
    original = await reviewer._compile_review_snapshot(state, ReviewSnapshotRequest(
        str(root), str(paper), 0, True, "round-1-review-input", None))
    current_hash, _ = review_source_bundle(root)
    state.source_bundle_sha256 = current_hash
    visual = {key: "Fixture independent reviewer assessment" for key in (
        "pdf_path", "figure_quality", "caption_alignment", "page_layout", "table_formatting", "visual_consistency")}
    visual.update({"pdf_path": "paper/main.pdf", "_coordinator_verified": "true",
        "_source_bundle_sha256": current_hash, "_pdf_sha256": original["pdf_sha256"],
        "_visual_bundle_sha256": original["visual_bundle_sha256"],
        "_visual_content_sha256": original["visual_content_sha256"],
        "_review_image_paths": json.dumps(original["page_preview_paths"] + original["contact_sheet_paths"]),
        "_review_image_bundle_sha256": "fixture-native-image-binding", "_review_response_sha256": "fixture-response",
        "_review_transport": "independent-model-api-native-vision-v1", "_review_trace_path": "fixture-no-model-trace",
        "_review_invocation_id": "model-api:fixture", "_review_model_identity": "fixture/reviewer"})
    state.rounds.append(ReviewRound(1, 4, "major_revision", pdf_snapshot=original["snapshot_path"], visual_review=visual))
    reviewer._save_state(state, str(root))
    return reviewer, state, paper, section, original, calls


@pytest.mark.parametrize("reason", ["upstream_research_revision_required", "revision_scope_unresolved",
                                  "runtime_presentation_revision_required"])
@pytest.mark.asyncio
async def test_no_fix_handoff_preserves_source_pdf_and_reviewed_pixel_bindings(tmp_path, monkeypatch, reason):
    reviewer, state, paper, section, original, calls = await _reviewed_fixture(tmp_path, monkeypatch)
    watched = [paper, section, paper.with_suffix(".pdf")]
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in watched}
    context = SimpleNamespace(reviewer=reviewer, project_path=str(tmp_path), paper_path=str(paper), on_progress=None)
    assert await review_loop._complete_without_fix(context, state, 1, reason, "no-edit-handoff", "stop")
    assert len(calls) == 1  # Only the original snapshot required the print producer.
    final = state.pdf_snapshots[-1]
    assert final["kind"] == "review_round" and final["round"] == 1
    assert final["preserved_reviewed_snapshot"] == original["snapshot_path"]
    assert final["pdf_sha256"] == original["pdf_sha256"]
    assert final["visual_content_sha256"] == original["visual_content_sha256"]
    assert (tmp_path / final["snapshot_path"]).read_bytes() == paper.with_suffix(".pdf").read_bytes()
    monkeypatch.setattr(review_execution.paper_drafting_service, "reconcile_reviewed_artifacts",
                        lambda *_a, **_k: pytest.fail("No-edit handoff cannot invoke an author assembler"))
    monkeypatch.setattr(review_execution.paper_drafting_service, "gate_report",
                        lambda *_a, **_k: {"passed": True, "issues": []})
    host = SimpleNamespace(_review_visual_evidence_gate=review_visual_evidence_gate)
    await review_execution._bind_reconciled_state(host, SimpleNamespace(project_path=str(tmp_path), options={}), state, str(paper))
    assert before == {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in watched}
    payload = json.loads((tmp_path / "review-stage/REVIEW_STATE.json").read_text())
    issues = payload["visual_evidence"]["issues"]
    assert not any("current paper source bundle" in issue or "snapshot is stale" in issue
                   or "pixels changed" in issue or "snapshot is missing" in issue for issue in issues)
    # Fixture has no actual native-model trace: this must not grant acceptance.
    assert not payload["visual_evidence"]["verified"] and not payload["threshold_met"]


@pytest.mark.parametrize("defect", ["missing_report", "changed_pixels", "changed_source", "missing_quality",
                                  "changed_current_pdf", "incomplete_pages", "missing_snapshot", "old_visual_hash"])
@pytest.mark.asyncio
async def test_snapshot_reuse_refuses_missing_or_stale_real_proof(tmp_path, monkeypatch, defect):
    _reviewer, state, paper, section, original, _calls = await _reviewed_fixture(tmp_path, monkeypatch)
    request = ReviewSnapshotRequest(str(tmp_path), str(paper), 1, False, "handoff", None)
    if defect == "missing_report":
        (tmp_path / original["layout_report_path"]).unlink()
    elif defect == "changed_pixels":
        (tmp_path / original["page_preview_paths"][0]).write_bytes(b"Changed actual pixels")
    elif defect == "changed_source":
        section.write_text("Actual scientific source change.")
    elif defect == "missing_quality":
        (tmp_path / ".merak/quality/paper-layout.json").unlink()
    elif defect == "changed_current_pdf":
        paper.with_suffix(".pdf").unlink()
        _pdf(paper.with_suffix(".pdf"), "Different compiled manuscript.")
    elif defect == "incomplete_pages":
        state.pdf_snapshots[0]["pages"] = 2
    elif defect == "missing_snapshot":
        (tmp_path / original["snapshot_path"]).unlink()
    else:
        state.rounds[-1].visual_review["_visual_bundle_sha256"] = "0" * 64
    assert preserve_reviewed_snapshot(state, request, paper) is None
    assert not (tmp_path / "paper/main_round1.pdf").exists()


@pytest.mark.asyncio
async def test_changed_authored_content_uses_print_producer_but_cannot_rebind_prior_native_review(tmp_path, monkeypatch):
    reviewer, state, paper, section, original, calls = await _reviewed_fixture(tmp_path, monkeypatch)
    old_visual = dict(state.rounds[-1].visual_review)
    section.write_text("Actual revised scientific reasoning.")
    paper.with_suffix(".pdf").unlink()
    _pdf(paper.with_suffix(".pdf"), "New revised scientific manuscript.")
    record = await reviewer._compile_review_snapshot(state, ReviewSnapshotRequest(
        str(tmp_path), str(paper), 1, False, "targeted-fix", None))
    assert len(calls) == 2 and record["source_bundle_sha256"] != original["source_bundle_sha256"]
    assert record["visual_content_sha256"] != original["visual_content_sha256"]
    assert state.rounds[-1].visual_review == old_visual
    reviewer._save_state(state, str(tmp_path))
    payload = json.loads((tmp_path / "review-stage/REVIEW_STATE.json").read_text())
    gate = review_visual_evidence_gate(str(tmp_path), payload, payload["rounds"])
    assert not gate["verified"] and any("pixels changed" in issue for issue in gate["issues"])
    assert any("stale" in issue for issue in gate["issues"])


@pytest.mark.asyncio
async def test_next_native_round_receives_new_printed_snapshot_after_real_author_edit(tmp_path, monkeypatch):
    reviewer, state, paper, section, original, calls = await _reviewed_fixture(tmp_path, monkeypatch)
    section.write_text("Changed scientific argument authored during the bounded repair.")
    paper.with_suffix(".pdf").unlink()
    _pdf(paper.with_suffix(".pdf"), "Revised argument after matched local typography repair.")
    current = await reviewer._compile_review_snapshot(state, ReviewSnapshotRequest(
        str(tmp_path), str(paper), 1, False, "targeted-fix", None))
    seen = []

    async def native(_context, current_state, number, snapshot, digest, paths):
        assert number == 2 and snapshot["snapshot_path"] == current["snapshot_path"]
        assert digest == snapshot["source_bundle_sha256"] == review_source_bundle(tmp_path)[0]
        assert snapshot["visual_content_sha256"] != original["visual_content_sha256"]
        assert digest != state.rounds[-1].visual_review["_source_bundle_sha256"]
        assert section.resolve() in paths and current_state.source_bundle_sha256 == digest
        seen.append((digest, snapshot["pdf_sha256"]))
        return SimpleNamespace(score=7, verdict="ready")

    async def stop(*_args):
        return True

    monkeypatch.setattr(review_loop, "_invoke_independent_review", native)
    monkeypatch.setattr(review_loop, "_accept_threshold", stop)
    context = SimpleNamespace(reviewer=reviewer, project_path=str(tmp_path), paper_path=str(paper), on_progress=None)
    assert await review_loop._run_round(context, state, 2)
    assert len(seen) == 1 and len(calls) == 2


@pytest.mark.asyncio
async def test_native_review_input_freezes_sources_after_print_preparation_not_before(tmp_path, monkeypatch):
    paper = tmp_path / "paper/main.tex"
    paper.parent.mkdir()
    paper.write_text("Original manuscript before typography overlay.")
    state = ReviewState(current_round=0)
    observed = []

    async def prepare(_context, _state, _round, old_hash):
        paper.write_text("Printed manuscript after exact same-science typography overlay.")
        current, _ = review_source_bundle(tmp_path)
        assert current != old_hash
        return {"source_bundle_sha256": current}

    async def review(_context, current_state, _round, snapshot, digest, paths):
        assert digest == snapshot["source_bundle_sha256"] == review_source_bundle(tmp_path)[0]
        assert current_state.source_bundle_sha256 == digest and paper.resolve() in paths
        observed.append(digest)
        return SimpleNamespace(score=4, verdict="major_revision")

    async def stop(*_args):
        return True

    monkeypatch.setattr(review_loop, "_review_input_snapshot", prepare)
    monkeypatch.setattr(review_loop, "_invoke_independent_review", review)
    monkeypatch.setattr(review_loop, "_accept_threshold", stop)
    assert await review_loop._run_round(SimpleNamespace(project_path=str(tmp_path), on_progress=None), state, 1)
    assert len(observed) == 1


@pytest.mark.asyncio
async def test_native_review_is_not_called_when_printed_snapshot_source_is_stale(tmp_path, monkeypatch):
    paper = tmp_path / "paper/main.tex"
    paper.parent.mkdir()
    paper.write_text("Current manuscript.")

    async def stale(*_args):
        return {"source_bundle_sha256": "0" * 64}

    async def forbidden(*_args):
        pytest.fail("Stale snapshot must stop before model invocation")

    monkeypatch.setattr(review_loop, "_review_input_snapshot", stale)
    monkeypatch.setattr(review_loop, "_invoke_independent_review", forbidden)
    with pytest.raises(RuntimeError, match="snapshot is stale"):
        await review_loop._run_round(SimpleNamespace(project_path=str(tmp_path)), ReviewState(), 1)
