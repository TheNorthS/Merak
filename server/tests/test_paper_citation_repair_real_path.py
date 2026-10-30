"""Global citation coverage repairs its bounded author across real cached rounds."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.services.paper_acceptance_errors import PaperAcceptanceError
from server.services.paper_complete_validation import validate_complete_draft
from server.services.paper_draft_coordinator import DraftCoordinator
from server.services.paper_drafting import (
    PAPER_STAGE_ORDER, PAPER_STAGE_LABELS, SECTION_BY_ID, SECTION_SPECS,
    SUPERIORITY_RE, PaperDraftingError, PaperDraftingService,
)
from server.workflows.engine import WorkflowEngine
from server.workflows.models import WorkflowNode, WorkflowRun
from server.workflows.revision_gate_phases import build_current_gate
from server.workflows.revision_loop_context import RevisionLoopContext
from server.workflows.revision_loop_phases import prepare_consumer_state


def _fixture(root: Path):
    service = PaperDraftingService()
    paths = service.paths(root)
    paths["sections"].mkdir(parents=True)
    paths["contracts"].write_text(json.dumps({"evidence": {"mode": "executed", "submission_eligible": True}}))
    paths["profile"].write_text(json.dumps({"minimum_unique_citations": 30, "main_text_words": [0, 10000]}))
    (paths["paper"] / "references.bib").write_text("\n".join(
        f"@article{{ref{index},title={{Verified local fixture source {index}}}}}" for index in range(1, 32)
    ))
    paths["title"].write_text("A Specific Source-Bound Local Fixture Study")
    abstract = "The controlled analysis compares registered conditions and preserves independent units and matched budgets. "
    (paths["sections"] / "00_abstract.tex").write_text((abstract * 15).rstrip() + "\n")
    related = paths["sections"] / "02_related_work.tex"
    paragraphs = []
    for index, title in enumerate(("Objective assumptions", "Evaluation assumptions", "Closest-work comparison")):
        sentence = ("The verified sources motivate distinct assumptions about transfer and matched controls. "
                    "Unlike the closest alternatives, this comparison tests an explicit mechanism under independent evaluation. ")
        paragraphs.append(r"\subsection{" + title + "}\n" + sentence * 9)
    related.write_text(r"\section{Related Work}" + "\n\n" + "\n\n".join(paragraphs)
                       + r"\cite{" + ",".join(f"ref{index}" for index in range(1, 30)) + "}")
    for spec in SECTION_SPECS:
        if spec.id != "related_work":
            (paths["sections"] / spec.filename).write_text(f"Frozen unrelated {spec.id} fixture.\n")
    service.mark_stage(paths, "related_work", "completed", attempt=1, review={"passed": True, "issues": []})
    spec = SECTION_BY_ID["related_work"]

    def complete(_root, *, require_main=False):
        return validate_complete_draft(paths=paths, specs=(spec,), require_main=False,
                                       superiority_pattern=SUPERIORITY_RE,
                                       section_review=service.section_review,
                                       front_matter_review=service.validate_front_matter)

    service.validate_complete_draft = complete
    return service, paths, related


def _coordinator(service, paths, issues, invoke):
    return DraftCoordinator(service=service, project_path=paths["root"], direction="Local citation repair", options={},
                            invoke_stage=invoke, emit=None, revision_issues=issues, paths=paths,
                            author_order=("related_work", "consistency"), paper_stage_order=PAPER_STAGE_ORDER,
                            section_by_id=SECTION_BY_ID, stage_labels=PAPER_STAGE_LABELS,
                            error_factory=PaperDraftingError, directed_repair_attempts=2, semantic_stall_attempts=2)


@pytest.mark.asyncio
async def test_typed_paper_rejection_survives_real_prepare_gate_and_owner_diagnostics(tmp_path):
    service, paths, _related = _fixture(tmp_path)
    report = service.validate_complete_draft(tmp_path, require_main=False)
    finding = next(item for item in report["findings"] if item["category"] == "literature_coverage")
    rejected = {"accepted": False, "summary": finding["message"], "details": {
        "issues": [finding["message"]], "review_findings": [finding],
        "target_files": finding["target_files"], "failed_stage": "consistency",
    }}
    failure = PaperAcceptanceError(rejected)
    host = WorkflowEngine()

    async def reject(*_args, **_kwargs):
        raise failure

    host._prepare_node_for_gate = reject
    node = WorkflowNode("paper", "Paper", "/paper-write")
    run = WorkflowRun(project_path=str(tmp_path), nodes=[node], status="running")
    context = RevisionLoopContext(host, node, run, "draft", "Local", "balanced", {}, 3, 30, "", False, 2)
    context.result = ""
    context.unchanged_revision_event = None
    await prepare_consumer_state(context)
    await build_current_gate(context)
    assert context.gate["accepted"] is False
    diagnostics = host._gate_revision_diagnostics(context.gate)
    typed = next(item for item in diagnostics["findings"] if item["category"] == "literature_coverage")
    assert typed["stage_id"] == "related_work"
    assert typed["legal_write_targets"] == ["paper/sections/02_related_work.tex"]
    assert "paper/sections/02_related_work.tex" in diagnostics["repair_scope"]["target_files"]
    assert typed["required_unique_citations"] == 30


@pytest.mark.asyncio
async def test_two_cached_rounds_reopen_only_related_work_and_never_fake_global_pass(tmp_path):
    service, paths, related = _fixture(tmp_path)
    initial = service.validate_complete_draft(tmp_path, require_main=False)
    assert not initial["passed"] and len(initial["findings"]) == 1
    protected = {path: path.read_bytes() for path in paths["sections"].glob("*.tex") if path != related}
    protected[paths["paper"] / "references.bib"] = (paths["paper"] / "references.bib").read_bytes()
    source = tmp_path / "literature/source-evidence.md"
    source.parent.mkdir()
    source.write_text("Fixture ref30 compares a distinct held-out eligibility assumption under matching controls.\n")
    calls = []

    async def first_author(stage, prompt, contract):
        assert stage == "related_work" and str(related) in contract
        assert "CROSS_SECTION_REVIEW" not in contract
        from server.agent.tools.file_tools import file_edit
        baseline = related.read_bytes()
        anchor = related.read_text().splitlines()[-1]
        await file_edit(str(related), anchor, anchor + "\nThe closest-work distinction requires registered eligibility boundaries.\n")
        assert related.read_bytes() == baseline
        calls.append(stage)
        return "Local fixture author edited and re-read the permitted related-work section."

    first = _coordinator(service, paths, [initial["findings"][0]["message"]], first_author)
    first._configure_targeted_repairs()
    assert set(first.target_stage_issues) == {"related_work", "consistency"}
    await first._run_stage("related_work")
    with pytest.raises(PaperDraftingError, match="02_related_work.tex"):
        await first._run_stage("consistency")
    assert calls == ["related_work"]
    assert not paths["cross_review"].is_file()
    deficient = service.validate_complete_draft(tmp_path, require_main=False)
    assert not deficient["passed"] and deficient["findings"][0]["needed_unique_citations"] == 1

    async def second_author(stage, prompt, contract):
        if stage == "related_work":
            assert str(related) in contract and "CROSS_SECTION_REVIEW" not in contract
            assert "eligibility assumption" in source.read_text()
            from server.agent.tools.file_tools import file_edit
            baseline = related.read_bytes()
            anchor = related.read_text().strip().splitlines()[-1]
            await file_edit(str(related), anchor, anchor + "\nThe verified eligibility comparison tests whether the matching "
                            "boundary itself explains observed transfer differences \\cite{ref30}.\n")
            assert related.read_bytes() == baseline
        elif stage == "consistency":
            assert service.validate_complete_draft(tmp_path, require_main=False)["passed"]
            assert str(paths["cross_review"]) in contract and str(related) not in contract
            paths["cross_review"].write_text("# Checks Performed\nVerified source coverage and local contracts.\n"
                                            "# Final Consistency Verdict\nPASS\n")
        else:
            pytest.fail("An unrelated accepted author must never run")
        calls.append(stage)
        return "Only the declared fixture author output was edited and re-read."

    wrapper = "Staged manuscript did not satisfy the quality contract: staged-paper: " + deficient["findings"][0]["plain_message"]
    second = _coordinator(service, paths, [wrapper], second_author)
    second._configure_targeted_repairs()
    assert set(second.target_stage_issues) == {"related_work", "consistency"}
    await second._run_stage("related_work")
    await second._run_stage("consistency")
    assert calls == ["related_work", "related_work", "consistency"]
    assert service.validate_complete_draft(tmp_path, require_main=False)["passed"]
    assert all(path.read_bytes() == content for path, content in protected.items())
    before = related.read_bytes()
    resumed = _coordinator(service, paths, [], second_author)
    await resumed._run_stage("related_work")
    assert related.read_bytes() == before and len(calls) == 3


def test_passing_gate_cannot_be_translated_into_a_rejection_error():
    with pytest.raises(ValueError, match="passing paper gate"):
        PaperAcceptanceError({"accepted": True})
