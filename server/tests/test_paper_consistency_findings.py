"""Pure, source-bound consistency findings and bounded repair routing."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from server.services.paper_complete_validation import validate_complete_draft
from server.services.paper_consistency_findings import merge_complete_findings
from server.services.paper_draft_coordinator import DraftCoordinator, StageRun
from server.services.paper_drafting import (
    AUTHOR_STAGE_ORDER, PAPER_STAGE_LABELS, PAPER_STAGE_ORDER,
    SECTION_BY_ID, SECTION_SPECS, PaperDraftingError, PaperDraftingService,
)


def _project(root: Path, *, cited: int = 29, refs: bool = True) -> tuple[PaperDraftingService, dict]:
    service = PaperDraftingService()
    paths = service.paths(root)
    paths["sections"].mkdir(parents=True)
    paths["paper"].mkdir(exist_ok=True)
    paths["contracts"].write_text(json.dumps({"evidence": {"mode": "executed"}}), encoding="utf-8")
    paths["profile"].write_text(json.dumps({"minimum_unique_citations": 30, "main_text_words": [0, 10000]}), encoding="utf-8")
    (paths["paper"] / "references.bib").write_text("\n".join(f"@article{{real{number},title={{Verified source {number}}}}}" for number in range(35)), encoding="utf-8")
    for spec in SECTION_SPECS:
        (paths["sections"] / spec.filename).write_text(f"\\section{{{spec.title}}}\nScientific {spec.id} prose.\n", encoding="utf-8")
    (paths["sections"] / "00_abstract.tex").write_text("Scientific abstract.", encoding="utf-8")
    introduction = paths["sections"] / "01_introduction.tex"
    introduction.write_text(introduction.read_text(encoding="utf-8") + "\\cite{" + ",".join(f"real{index}" for index in range(cited)) + "}", encoding="utf-8")
    if refs:
        results = paths["sections"] / "05_results.tex"
        results.write_text(results.read_text(encoding="utf-8") + r"\ref{tab:paired-testing}\ref{tab:error-slices}\ref{tab:efficiency}", encoding="utf-8")
    return service, paths


def _review(paths: dict) -> dict:
    return validate_complete_draft(paths=paths, specs=SECTION_SPECS, require_main=False,
                                   superiority_pattern=re.compile("never-matches"),
                                   section_review=lambda *_args: {"passed": True, "issues": []},
                                   front_matter_review=lambda *_args: {"passed": True, "issues": []})


def test_test105_missing_refs_target_the_real_results_author_not_report_or_tables(tmp_path: Path) -> None:
    _, paths = _project(tmp_path)
    report = _review(paths)
    findings = [item for item in report["findings"] if item["category"] == "undefined_reference"]
    assert {item["reference_key"] for item in findings} == {"tab:paired-testing", "tab:error-slices", "tab:efficiency"}
    assert all(item["stage_id"] == "results" and item["target_files"] == ["paper/sections/05_results.tex"] for item in findings)
    assert all(item["legal_write_targets"] == item["target_files"] for item in findings)
    assert report["passed"] is False
    assert any("undefined references" in issue for issue in report["issues"])


def test_29_of_30_citations_remains_blocking_and_keys_are_not_recommendations(tmp_path: Path) -> None:
    _, paths = _project(tmp_path, refs=False)
    report = _review(paths)
    finding = next(item for item in report["findings"] if item["category"] == "literature_coverage")
    assert finding["stage_id"] == "related_work"
    assert finding["target_files"] == ["paper/sections/02_related_work.tex"]
    assert finding["required_unique_citations"] == 30
    assert finding["needed_unique_citations"] == 1
    assert finding["available_unused_verified_keys"] == [f"real{index}" for index in range(29, 35)]
    assert finding["candidate_inventory_is_relevance_recommendation"] is False
    assert report["passed"] is False


def test_report_pass_cannot_bypass_references_or_citation_minimum(tmp_path: Path) -> None:
    _, paths = _project(tmp_path)
    paths["cross_review"].write_text("Checks Performed\nFinal Consistency Verdict: PASS", encoding="utf-8")
    report = _review(paths)
    assert report["passed"] is False
    assert len(report["findings"]) == 4


def test_resolved_refs_and_real_30th_citation_remove_only_their_findings(tmp_path: Path) -> None:
    _, paths = _project(tmp_path, cited=30, refs=False)
    report = _review(paths)
    assert report["passed"] is True
    assert report["findings"] == []


def test_same_missing_reference_in_two_sections_preserves_both_real_owners(tmp_path: Path) -> None:
    _, paths = _project(tmp_path, cited=30)
    method = paths["sections"] / "03_method.tex"
    method.write_text(method.read_text(encoding="utf-8") + r"\ref{tab:efficiency}", encoding="utf-8")
    findings = [item for item in _review(paths)["findings"] if item.get("reference_key") == "tab:efficiency"]
    assert {item["stage_id"] for item in findings} == {"method", "results"}
    assert len({item["id"] for item in findings}) == 2


def test_unknown_citation_routes_to_its_author_without_inventing_bibliography(tmp_path: Path) -> None:
    _, paths = _project(tmp_path, cited=30, refs=False)
    method = paths["sections"] / "03_method.tex"
    method.write_text(method.read_text(encoding="utf-8") + r"\cite{invented_key}", encoding="utf-8")
    report = _review(paths)
    finding = next(item for item in report["findings"] if item["category"] == "unknown_citation")
    assert finding["target_files"] == ["paper/sections/03_method.tex"]
    assert finding["citation_key"] == "invented_key"
    assert "never invent" in finding["remediation"]
    assert report["passed"] is False


def test_merge_replaces_generic_consistency_target_with_precise_author_targets(tmp_path: Path) -> None:
    _, paths = _project(tmp_path)
    complete = _review(paths)["findings"]
    active = [{"id": "generic", "stage_id": "consistency", "message": "Review: " + complete[0]["validation_issue"],
               "target_files": ["paper/CROSS_SECTION_REVIEW.md"]}]
    merged = merge_complete_findings(active, complete)
    assert all(item["id"] != "generic" for item in merged)
    assert {target for item in merged for target in item["target_files"]} == {
        "paper/sections/05_results.tex", "paper/sections/02_related_work.tex",
    }


def _coordinator(service: PaperDraftingService, paths: dict, issues: list[str]) -> DraftCoordinator:
    async def forbidden_model(*_args):
        raise AssertionError("pure routing verification must never invoke a model")
    return DraftCoordinator(service=service, project_path=paths["root"], direction="", options={},
                            invoke_stage=forbidden_model, emit=None, revision_issues=issues, paths=paths,
                            author_order=AUTHOR_STAGE_ORDER, paper_stage_order=PAPER_STAGE_ORDER,
                            section_by_id=SECTION_BY_ID, stage_labels=PAPER_STAGE_LABELS,
                            error_factory=PaperDraftingError, directed_repair_attempts=2, semantic_stall_attempts=2)


def test_precise_dispatch_reopens_affected_authors_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service, paths = _project(tmp_path)
    report = _review(paths)
    monkeypatch.setattr(service, "validate_complete_draft", lambda *_args, **_kwargs: report)
    state = {"stages": {stage: {"status": "completed", "review_passed": True} for stage in AUTHOR_STAGE_ORDER}}
    paths["state"].write_text(json.dumps(state), encoding="utf-8")
    before = {path.name: path.read_bytes() for path in paths["sections"].glob("*.tex")}
    coordinator = _coordinator(service, paths, report["issues"])
    coordinator._configure_targeted_repairs()
    assert set(coordinator.target_stage_issues) == {"results", "related_work", "consistency"}
    after = json.loads(paths["state"].read_text(encoding="utf-8"))["stages"]
    assert after["results"]["status"] == after["related_work"]["status"] == "pending"
    assert after["method"]["status"] == after["introduction"]["status"] == "completed"
    assert before == {path.name: path.read_bytes() for path in paths["sections"].glob("*.tex")}


def test_consistency_write_scope_is_report_only_and_authorship_failures_route_before_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service, paths = _project(tmp_path)
    report = _review(paths)
    monkeypatch.setattr(service, "validate_stage", lambda *_args: report)
    coordinator = _coordinator(service, paths, [])
    assert service.stage_write_targets(paths, "consistency") == [paths["cross_review"]]
    with pytest.raises(PaperDraftingError, match="paper/sections/05_results.tex"):
        coordinator._defer_consistency_to_section_authors(StageRun("consistency", {}, [], 0, "", False, 0, {}))
    from server.services.paper_revision_queue import pending_author_repairs
    pending = pending_author_repairs(paths['state'], AUTHOR_STAGE_ORDER)
    assert any('Target artifact: paper/sections/05_results.tex' in issue for issue in pending)
    resumed = _coordinator(service, paths, [])
    resumed._configure_targeted_repairs()
    assert 'results' in resumed.target_stage_issues
