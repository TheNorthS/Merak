"""The full paper adapter must retain actual, current compiled-artifact bindings."""

import hashlib
import json
import os
from types import SimpleNamespace

import fitz
import pytest

from server.services.latex_bundle import latex_source_bundle
from server.services.paper_build_readiness import paper_build_issues
from server.services.paper_compiler import CompileResult, paper_compiler
from server.services.paper_drafting import paper_drafting_service
from server.workflows.engine import WorkflowEngine


def _adapter_fixture(root, monkeypatch, *, corruption=None, output="valid"):
    from server.services import paper_preparation_errors, paper_print_repair
    from server.services.paper_budget import paper_budget_service

    paper = root / "paper"
    paper.mkdir()
    source = paper / "main.tex"
    source.write_text(r"\documentclass{article}\begin{document}Current manuscript.\end{document}")
    record = paper / "PAPER_BUILD.json"
    record.write_text(corruption or json.dumps({"schema": 1, "compile": {
        "success": True, "pdf_sha256": "0" * 64, "source_bundle_sha256": "f" * 64,
        "source_files": ["paper/old.tex"], "verified_at": 1}}))
    host = WorkflowEngine()
    gates, events = [], []

    def gate(path, **options):
        gates.append(options)
        if not options.get("require_page_budget"):
            return {"accepted": True, "summary": "Fixture source gate", "details": {"issues": []}}
        current = json.loads(record.read_text())
        issues, _ = paper_build_issues(root, current)
        return {"accepted": not issues, "summary": "; ".join(issues), "details": {"issues": issues}}

    async def emit(_run, event, data):
        events.append((event, data))

    async def compile_current(_compiler, project, **_options):
        assert project == str(root)
        pdf = paper / "main.pdf"
        if output == "valid":
            with fitz.open() as document:
                document.new_page().insert_text((60, 60), "Current compiled manuscript.")
                document.save(pdf)
        elif output == "invalid":
            pdf.write_bytes(b"Not a PDF")
        if output == "stale":
            with fitz.open() as document:
                document.new_page().insert_text((60, 60), "Old compiled manuscript.")
                document.save(pdf)
            os.utime(pdf, (1, 1))
        return CompileResult(success=True, pdf_path=str(pdf), pages=1, compile_time_ms=9)

    monkeypatch.setattr(host, "_paper_acceptance_gate", gate)
    monkeypatch.setattr(host, "_emit", emit)
    monkeypatch.setattr(paper_preparation_errors, "prepare_paper_evidence",
        lambda *_args: SimpleNamespace(evidence_mode="existing_results", submission_eligible=True, synthetic_preview=False))
    monkeypatch.setattr(paper_drafting_service, "refresh_deterministic_assembly", lambda *_args: {"passed": True})
    monkeypatch.setattr(paper_compiler, "repair_common_source_dependencies", lambda *_args: [])
    monkeypatch.setattr(paper_print_repair, "compile_print_verified_paper", compile_current)
    monkeypatch.setattr(paper_budget_service, "load", lambda *_args: None)
    run = SimpleNamespace(project_path=str(root), options={})
    return host, run, record, gates, events


@pytest.mark.asyncio
async def test_complete_adapter_preserves_fresh_source_pdf_hashes_not_stale_prior_record(tmp_path, monkeypatch):
    host, run, record, gates, events = _adapter_fixture(tmp_path, monkeypatch)
    result = await host._ensure_paper_artifacts(run, "Current source", "Fixture direction")
    current = json.loads(record.read_text())
    source_hash, sources = latex_source_bundle(tmp_path / "paper")
    compiled = current["compile"]
    assert compiled["pdf_sha256"] == hashlib.sha256((tmp_path / "paper/main.pdf").read_bytes()).hexdigest()
    assert compiled["source_bundle_sha256"] == source_hash
    assert compiled["source_files"] == [path.relative_to(tmp_path).as_posix() for path in sources]
    assert compiled["verified_at"] > 1 and compiled["pages"] == 1
    assert current["mode"] == "staged-section-draft" and current["quality_gate"]["accepted"]
    assert paper_build_issues(tmp_path, current)[0] == []
    assert gates[-1]["require_staged"] and gates[-1]["require_page_budget"]
    assert events[-1][0] == "paper_artifact_repaired" and "compiled pages=1" in result


@pytest.mark.parametrize("artifact", ["source", "pdf"])
@pytest.mark.asyncio
async def test_adapter_bound_record_still_rejects_actual_later_source_or_pdf_drift(tmp_path, monkeypatch, artifact):
    host, run, record, _gates, _events = _adapter_fixture(tmp_path, monkeypatch)
    await host._ensure_paper_artifacts(run, "Current source", "Fixture direction")
    path = tmp_path / ("paper/main.tex" if artifact == "source" else "paper/main.pdf")
    path.write_bytes(path.read_bytes() + b"\nActual changed content.\n")
    issues, _ = paper_build_issues(tmp_path, json.loads(record.read_text()))
    assert any("stale relative" in issue if artifact == "source" else "does not match" in issue for issue in issues)


@pytest.mark.parametrize("corruption", ["{unreadable", "[]"])
@pytest.mark.asyncio
async def test_adapter_refuses_corrupt_existing_build_record_without_overwriting_it(tmp_path, monkeypatch, corruption):
    host, run, record, gates, _events = _adapter_fixture(tmp_path, monkeypatch, corruption=corruption)
    original = record.read_bytes()
    with pytest.raises(RuntimeError, match="refusing to overwrite"):
        await host._ensure_paper_artifacts(run, "Current source", "Fixture direction")
    assert record.read_bytes() == original
    assert len(gates) == 1


@pytest.mark.parametrize("output", ["missing", "invalid", "stale"])
@pytest.mark.asyncio
async def test_adapter_cannot_claim_a_compile_without_real_current_source_and_pdf(tmp_path, monkeypatch, output):
    host, run, record, gates, _events = _adapter_fixture(tmp_path, monkeypatch, output=output)
    original = record.read_bytes()
    with pytest.raises(RuntimeError, match="cannot be bound"):
        await host._ensure_paper_artifacts(run, "Current source", "Fixture direction")
    assert record.read_bytes() == original and len(gates) == 1
