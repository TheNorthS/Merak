"""First-run method tables acquire source-bound author prose without rewriting science."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from server.services.method_table_presentation import PRESENTATION, _hashes, write_method_presentation
from server.services.paper_submission_tables import write_submission_tables
from server.tests.test_method_table_presentation import ready
from server.workflows.paper_method_presentation import refresh_method_presentation


def _reviewer(monkeypatch, invoke, prepare):
    from server.services.api_visual_reviewer import ApiVisualReviewer
    from server.services import paper_preparation_errors

    monkeypatch.setattr(ApiVisualReviewer, "invoke", invoke)
    monkeypatch.setattr(paper_preparation_errors, "prepare_paper_evidence", prepare)


@pytest.mark.asyncio
async def test_first_method_presentation_uses_actual_producer_and_then_reuses(tmp_path, monkeypatch):
    evidence, rows = ready(tmp_path)
    write_submission_tables(evidence)
    before = (tmp_path / "ideas/SELECTED_IDEA.json").read_bytes()
    calls = []

    async def invoke(_self, **kwargs):
        calls.append(kwargs)
        assert tmp_path / "paper/tables/method_components.tex" in kwargs["evidence_paths"]
        assert tmp_path / "paper/sections/03_method.tex" in kwargs["evidence_paths"]
        return SimpleNamespace(text=json.dumps({"rows": rows}), invocation_id="fixture-call", trace_path="fixture-trace")

    _reviewer(monkeypatch, invoke, lambda root: write_submission_tables(evidence))
    run = SimpleNamespace(project_path=str(tmp_path))
    assert await refresh_method_presentation(run) is True
    value = json.loads((tmp_path / PRESENTATION).read_bytes())
    assert value["source_sha256"] == _hashes(tmp_path) and value["author"] == "fixture-call"
    assert rows[0]["evaluation"] in (tmp_path / "paper/tables/method_components.tex").read_text()
    assert (tmp_path / "ideas/SELECTED_IDEA.json").read_bytes() == before
    receipt = json.loads((tmp_path / ".merak/method-table-authoring/initial/receipt.json").read_bytes())
    assert receipt["independent_acceptance"] is False
    assert await refresh_method_presentation(run) is False
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["cancel", "malformed", "note_pointer", "source_changed", "prepare_failed"])
@pytest.mark.parametrize("existing", [False, True])
async def test_interrupted_method_author_leaves_prior_presentation_and_science(tmp_path, monkeypatch, failure, existing):
    _evidence, rows = ready(tmp_path)
    path = tmp_path / PRESENTATION
    if existing:
        write_method_presentation(tmp_path, rows, author="previous-author")
        (tmp_path / "paper/sections/03_method.tex").write_text("Current author revision")
    baseline = path.read_bytes() if existing else None
    original_science = (tmp_path / "ideas/SELECTED_IDEA.json").read_bytes()

    async def invoke(_self, **kwargs):
        if failure == "cancel":
            raise asyncio.CancelledError()
        if failure == "source_changed":
            (tmp_path / "paper/sections/03_method.tex").write_text("Concurrent user revision")
        if failure == "note_pointer":
            rows[0]["evaluation"] = "Prospective evaluation details (Note 1)"
        return SimpleNamespace(text=json.dumps({"rows": [] if failure == "malformed" else rows}),
                               invocation_id="attempt", trace_path="attempt-trace")

    def prepare(root):
        if failure == "prepare_failed":
            raise ValueError("Table producer rejected changed rows")
        pytest.fail("Invalid author must not reach publication")

    _reviewer(monkeypatch, invoke, prepare)
    with pytest.raises(asyncio.CancelledError if failure == "cancel" else ValueError):
        await refresh_method_presentation(SimpleNamespace(project_path=str(tmp_path)))
    assert (path.read_bytes() if path.is_file() else None) == baseline
    assert (tmp_path / "ideas/SELECTED_IDEA.json").read_bytes() == original_science
    assert not list((tmp_path / ".merak/method-table-authoring").glob("*/receipt.json"))


@pytest.mark.asyncio
async def test_existing_projection_pointer_requires_fresh_author_with_original_cells(tmp_path, monkeypatch):
    evidence, rows = ready(tmp_path)
    write_method_presentation(tmp_path, rows, author="previous-author")
    path = tmp_path / PRESENTATION
    value = json.loads(path.read_bytes())
    value["rows"][0]["evaluation"] = "Initial comparison checklist details (Note 1)"
    path.write_text(json.dumps(value), encoding="utf-8")

    async def invoke(_self, **kwargs):
        for mechanism in evidence.selected_idea["mechanisms"]:
            assert mechanism["publication_evaluation"] in kwargs["prompt"]
        return SimpleNamespace(text=json.dumps({"rows": rows}), invocation_id="corrected-author", trace_path="trace")

    _reviewer(monkeypatch, invoke, lambda root: write_submission_tables(evidence))
    assert await refresh_method_presentation(SimpleNamespace(project_path=str(tmp_path))) is True
    assert json.loads(path.read_bytes())["rows"] == rows
    assert rows[0]["evaluation"] in (tmp_path / "paper/tables/method_components.tex").read_text()
