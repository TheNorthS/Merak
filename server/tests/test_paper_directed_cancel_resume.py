"""Cancellation before review must not consume the only directed repair attempt."""

import asyncio
import json

import pytest

from server.agent.tools.file_tools import file_edit, file_read, file_write
from server.services.manuscript_text import read_text
from server.services.paper_drafting import AUTHOR_STAGE_ORDER, PaperDraftingService
from server.tests._staged_paper_drafting_support import seed_project


class SimulatedProcessLoss(BaseException):
    """Model an exit before the normal exception handler can persist cleanup."""


@pytest.mark.asyncio
@pytest.mark.parametrize("interruption", [asyncio.CancelledError, RuntimeError, SimulatedProcessLoss])
async def test_resume_interrupted_directed_author_keeps_candidate_and_restores_unreviewed_budget(tmp_path, monkeypatch, interruption):
    seed_project(tmp_path)
    service = PaperDraftingService()
    service.prepare(tmp_path, {})
    paths = service.paths(tmp_path)
    for stage in AUTHOR_STAGE_ORDER:
        for output in service.stage_outputs(paths, stage):
            output.write_text(f"Original {stage} paragraph.\n", encoding="utf-8")
        service.mark_stage(paths, stage, "completed", attempt=1, review={"passed": True, "issues": []})
    target = paths["sections"] / "03_method.tex"
    original = target.read_bytes()
    introduction = paths["sections"] / "01_introduction.tex"
    stable = introduction.read_bytes()
    calls = []

    def validate(_root, stage):
        passed = stage != "method" or "Reviewed revision" in read_text(target)
        return {"passed": passed, "issues": [] if passed else ["Clarify decoder input"]}

    monkeypatch.setattr(service, "validate_stage", validate)
    monkeypatch.setattr(service, "validate_complete_draft", lambda *_a, **_k: {"passed": True, "issues": []})

    async def author(stage, _prompt, _contract):
        if stage == "method":
            calls.append(stage)
            if len(calls) == 1:
                await file_edit(str(target), "Original method", "Interrupted revision")
                assert target.read_bytes() == original
                raise interruption("Stop before review")
            assert "Interrupted revision" in await file_read(str(target))
            await file_edit(str(target), "Interrupted revision", "Reviewed revision")
        else:
            for output in service.stage_outputs(paths, stage):
                await file_write(str(output), "Independent consistency report")
        return "Authored bounded correction"

    issues = ["Target artifact: paper/sections/03_method.tex; Clarify decoder input"]
    with pytest.raises(interruption):
        await service.draft(tmp_path, "bounded study", {}, author, revision_issues=issues)
    assert target.read_bytes() == original and introduction.read_bytes() == stable
    result = await service.draft(tmp_path, "bounded study", {}, author, revision_issues=issues)
    assert result["status"] == "completed" and calls == ["method", "method"]
    assert "Reviewed revision" in target.read_text() and introduction.read_bytes() == stable
    record = json.loads(paths["state"].read_bytes())["stages"]["method"]
    assert record["attempts"] == 2 and record["directed_attempts"] == 1
