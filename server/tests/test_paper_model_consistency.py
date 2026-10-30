"""A model's failed consistency verdict is a blocker, including simulation manuscripts."""

from types import SimpleNamespace

import pytest

from server.services.paper_model_consistency_findings import model_consistency_findings
from server.services.paper_review_reconciliation import reconcile_reviewed_artifacts
from server.services.paper_stage_lifecycle import _validate_consistency
from server.tests._staged_paper_drafting_support import seed_project
from server.services.paper_drafting import PaperDraftingService


REPORT = """# Checks Performed
Checked controls and calibration values.
# Remaining Evidence Gaps
1. **Calibration contradicts the registered table (blocking).**
   - Responsible authored section: `paper/sections/05_results.tex`.
   - Required scientific repair: reconcile the risk values with the bound rows; do not change numerical evidence.
2. **Related-work capability comparison (non-blocking gap).**
   - Responsible authored section: `paper/sections/02_related_work.tex`.
# Final Consistency Verdict
**FAIL — revisions required before consistency approval.**
"""


@pytest.mark.parametrize("mode", ["synthetic_preview", "design_only", "executed"])
def test_explicit_fail_never_becomes_advisory_or_pass(tmp_path, mode):
    report = tmp_path / "CROSS_SECTION_REVIEW.md"
    report.write_text(REPORT, encoding="utf-8")
    result = _validate_consistency(tmp_path, {"cross_review": report}, {"mode": mode},
        lambda *a, **k: {"passed": True, "issues": []})
    assert result["passed"] is False and result["reviewer_scope_advisory"] is False
    assert result["reviewer_verdict"] == "FAIL"


def test_failed_findings_route_to_named_author_without_promoting_nonblocking_gaps(tmp_path):
    report = tmp_path / "CROSS_SECTION_REVIEW.md"
    report.write_text(REPORT, encoding="utf-8")
    specs = [SimpleNamespace(id="results", filename="05_results.tex"),
             SimpleNamespace(id="related_work", filename="02_related_work.tex")]
    findings = model_consistency_findings({"cross_review": report}, specs)
    assert len(findings) == 1 and findings[0]["stage_id"] == "results"
    assert findings[0]["target_files"] == ["paper/sections/05_results.tex"]
    assert "do not change numerical evidence" in findings[0]["message"]
    report.write_text(REPORT.replace("**FAIL —", "**PASS —"), encoding="utf-8")
    assert model_consistency_findings({"cross_review": report}, specs) == []


@pytest.mark.parametrize('heading', ['**1. Risk wording is inconsistent.**', '  **1) Risk wording is inconsistent.**'])
def test_bold_numbered_findings_route_to_authors_instead_of_repeating_review(tmp_path, heading):
    report = tmp_path / 'review.md'
    report.write_text('# Checks Performed\nChecked.\n# Remaining Evidence Gaps\n'
        + heading + '\nResponsible authored section: `paper/sections/05_results.tex`.\n'
        'Required scientific repair: describe assigned bounds without inferential claims.\n'
        '**2. Comparator gap (non-blocking).**\nResponsible authored section: `paper/sections/02_related_work.tex`.\n'
        '# Final Consistency Verdict\nFAIL\n')
    findings = model_consistency_findings({'cross_review': report}, [
        SimpleNamespace(id='results', filename='05_results.tex'),
        SimpleNamespace(id='related_work', filename='02_related_work.tex')])
    assert len(findings) == 1 and findings[0]['stage_id'] == 'results'


def test_repairs_under_edits_applied_do_not_promote_disclosed_limitations(tmp_path):
    report = tmp_path / "review.md"
    report.write_text("# Checks Performed\nChecked.\n# Edits Applied\n"
        "1. **Incorrect result wording.** Responsible authored section: `paper/sections/05_results.tex`.\n"
        "Scientific repair: describe all four methods in this table.\n"
        "# Remaining Evidence Gaps\n1. **Attribution unavailable.** `paper/sections/03_method.tex` correctly states this boundary.\n"
        "No repair may upgrade the claim.\n# Final Consistency Verdict\nFAIL\n")
    findings = model_consistency_findings({"cross_review": report}, [
        SimpleNamespace(id="results", filename="05_results.tex"), SimpleNamespace(id="method", filename="03_method.tex")])
    assert len(findings) == 1 and findings[0]["stage_id"] == "results"


def test_reconciliation_cannot_overwrite_failed_model_report(tmp_path, monkeypatch):
    seed_project(tmp_path)
    service = PaperDraftingService()
    service.prepare(tmp_path, {})
    paths = service.paths(tmp_path)
    paths["cross_review"].write_text(REPORT, encoding="utf-8")
    before = paths["cross_review"].read_bytes()
    import server.services.paper_review_reconciliation as reconciliation

    monkeypatch.setattr(reconciliation, "_validate_authored_stages", lambda *a: {"reviews": {}, "issues": []})
    result = reconcile_reviewed_artifacts(tmp_path, reviewer="fresh local checks", paths=paths,
        draft_schema=3, author_order=(), consistency_version=5, assembly_version=1,
        validate_stage=service.validate_stage, validate_complete=service.validate_complete_draft,
        assemble=lambda *_: pytest.fail("Cannot assemble a failed consistency report"),
        stage_outputs=lambda *_: [], input_signature=lambda *_: "", contract_version=lambda *_: 1)
    assert result["passed"] is False
    assert "cross-section reviewer recorded FAIL" in result["issues"]
    assert paths["cross_review"].read_bytes() == before


@pytest.mark.parametrize("changed", [False, True])
def test_unchanged_failed_review_returns_to_authors_before_another_reviewer_call(changed):
    from server.services.paper_draft_coordinator import DraftCoordinator

    calls = []
    finding = {"category": "model_consistency", "stage_id": "results", "message": "Repair risk values"}
    service = SimpleNamespace(validate_stage=lambda *_: {"passed": False, "findings": [finding]},
        stage_input_signature=lambda *_: "changed" if changed else "reviewed",
        record_review=lambda *a: calls.append("record"), mark_stage=lambda *a, **kw: calls.append("mark"))
    context = SimpleNamespace(service=service, project_path="fixture", paths={}, section_by_id={"results": None},
        error_factory=lambda stage, issues: ValueError("; ".join(issues)))
    run = SimpleNamespace(stage_id="consistency", record={"reviewed_input_signature": "reviewed"}, prior_attempts=1)
    if changed:
        DraftCoordinator._defer_consistency_to_section_authors(context, run)
        assert calls == []
    else:
        with pytest.raises(ValueError, match="Repair risk values"):
            DraftCoordinator._defer_consistency_to_section_authors(context, run)
        assert calls == ["record", "mark"]


def test_wrapped_scientific_finding_retains_explicit_author_instead_of_keyword_owner():
    from server.workflows.engine import WorkflowEngine

    finding = {"id": "consistency-risk", "category": "model_consistency", "severity": "blocker",
        "message": "Fix figure caption interpretation in paper/sections/05_results.tex; inspect paper/synthetic_preview_figures.tex",
        "owner_node": "paper", "upstream_node": "paper", "stage_id": "results",
        "target_files": ["paper/sections/05_results.tex"]}
    gate = {"accepted": False, "details": {"issues": ["staged-paper: " + finding["message"]],
        "review_findings": [finding]}}
    diagnostics = WorkflowEngine()._gate_revision_diagnostics(gate)
    assert len(diagnostics["findings"]) == 1
    assert diagnostics["findings"][0]["owner_node"] == "paper"
    assert diagnostics["findings"][0]["stage_id"] == "results"


def test_explicit_write_targets_exclude_readonly_evidence_paths():
    from server.services.paper_draft_stages import revision_target_paths

    issue = ("Target artifact: paper/sections/05_results.tex\n"
             "Read paper/tables/synthetic_preview_results.tex and paper/assembly-layout/paper/sections/05_results.tex "
             "as evidence. Repair only this author's interpretation.")
    assert revision_target_paths([issue]) == ["paper/sections/05_results.tex"]


def test_preserve_correctly_disclosed_missing_evidence_is_not_an_author_repair(tmp_path):
    report = tmp_path / "review.md"
    report.write_text("# Checks Performed\nChecked.\n# Remaining Evidence Gaps\n"
        "1. **Attribution remains intentionally unavailable.**\nResponsible authored section: `paper/sections/03_method.tex`.\n"
        "This is a correctly disclosed evidence boundary, not a request to manufacture missing results.\n"
        "Required scientific repair: No new evidence should be manufactured. Preserve the current qualified wording.\n"
        "# Final Consistency Verdict\nFAIL\n")
    assert model_consistency_findings({"cross_review": report}, [SimpleNamespace(id="method", filename="03_method.tex")]) == []


def test_real_draft_router_targets_author_despite_table_paths_in_review(tmp_path):
    from server.tests.test_paper_stage_validator_cache import _coordinator

    seed_project(tmp_path)
    service = PaperDraftingService()
    service.prepare(tmp_path, {})
    paths = service.paths(tmp_path)
    paths["cross_review"].write_text(REPORT.replace("reconcile the risk values", 
        "Read paper/tables/synthetic_preview_results.tex as immutable evidence, then reconcile the risk values"), encoding="utf-8")
    coordinator = _coordinator(tmp_path, service, paths)
    coordinator.revision_issues = ["Target artifact: paper/sections/05_results.tex", "cross-section reviewer recorded FAIL"]
    coordinator._configure_targeted_repairs()
    assert set(coordinator.target_stage_issues) == {"results", "consistency"}
    assert any("paper/tables/synthetic_preview_results.tex" in issue for issue in coordinator.target_stage_issues["results"])
    assert service.revision_target_paths(coordinator.target_stage_issues["results"]) == ["paper/sections/05_results.tex"]


def test_stale_projection_cannot_block_routing_to_its_canonical_author(tmp_path):
    report = tmp_path / "review.md"
    report.write_text(REPORT.replace("paper/sections/05_results.tex", "paper/assembly-layout/paper/sections/05_results.tex"))
    findings = model_consistency_findings({"cross_review": report, "root": tmp_path}, [
        SimpleNamespace(id="results", filename="05_results.tex")])
    assert len(findings) == 1
    assert findings[0]["legal_write_targets"] == ["paper/sections/05_results.tex"]


def test_blockers_below_final_verdict_route_to_authors_instead_of_repeating_review(tmp_path):
    report = tmp_path / "review.md"
    report.write_text("# Checks Performed\nChecked.\n# Remaining Evidence Gaps\n"
        "No empirical execution; this is disclosed.\n# Final Consistency Verdict\n"
        "**FAIL — two blocking findings remain.**\n\n"
        "1. **Unexecuted holdout presented as active.**\n"
        "**Responsible authored section:** `paper/sections/04_experiments.tex`\n"
        "**Required scientific repair:** Describe it as a future protocol schematic.\n\n"
        "2. **Unverified closest-work exclusion.**\n"
        "**Responsible authored section:** `paper/sections/02_related_work.tex`\n"
        "**Required scientific repair:** Qualify the comparison pending full-text verification.\n")
    findings = model_consistency_findings({"cross_review": report}, [
        SimpleNamespace(id="experiments", filename="04_experiments.tex"),
        SimpleNamespace(id="related_work", filename="02_related_work.tex")])
    assert {item["stage_id"] for item in findings} == {"experiments", "related_work"}


def test_responsible_author_excludes_comparison_sources_and_trailing_advisory(tmp_path):
    report = tmp_path / "review.md"
    report.write_text("# Checks Performed\nChecked.\n# Final Consistency Verdict\nFAIL\n"
        "1. **Related work overstates novelty.** Compare paper/sections/03_method.tex.\n"
        "**Responsible authored section:** `paper/sections/02_related_work.tex`\n"
        "**Required scientific repair:** Qualify exclusion claims pending verified full text.\n\n"
        "A non-blocking reconciliation is also deferred: `paper/sections/05_results.tex` could clarify terminology.\n")
    findings = model_consistency_findings({"cross_review": report}, [
        SimpleNamespace(id="related_work", filename="02_related_work.tex"),
        SimpleNamespace(id="method", filename="03_method.tex"),
        SimpleNamespace(id="results", filename="05_results.tex")])
    assert len(findings) == 1 and findings[0]["stage_id"] == "related_work"
    assert "non-blocking" not in findings[0]["message"]
