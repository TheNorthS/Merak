"""Real consistency findings route to bounded paper authors, not scientific data."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.verify_figure_snapshot import SnapshotEngine
from scripts.verify_paper_repair_snapshot import FirstRepairBoundary, _model_boundary
from server.tests.test_paper_preparation_snapshot import _fixture as prepare_fixture
from server.services.paper_complete_validation import _included_fragments, _reference_issues
from server.services.paper_consistency_findings import complete_consistency_findings
from server.services.paper_drafting import SectionSpec, paper_drafting_service
from server.workflows.models import WorkflowRun


def _fixture(root: Path) -> tuple[dict, str, dict]:
    paper = root / "paper"
    sections = paper / "sections"
    sections.mkdir(parents=True)
    bibliography = "\n".join(f"@article{{ref{index}, title={{Verified fixture source {index}}}}}" for index in range(1, 31))
    (paper / "references.bib").write_text(bibliography)
    result_text = "\\section{Results}\nTable~\\ref{tab:registered-endpoint} explains matched effects.\n"
    related = "\\section{Related Work}\n" + "\n".join(
        f"Verified source {index} supports an assumption comparison \\cite{{ref{index}}}." for index in range(1, 30)
    )
    (sections / "05_results.tex").write_text(result_text)
    (sections / "02_related_work.tex").write_text(related)
    paths = {"root": root, "paper": paper, "sections": sections}
    specs = (SectionSpec("results", "05_results.tex", "Results", 0, 1000, 0, "Fixture", ()),
             SectionSpec("related_work", "02_related_work.tex", "Related Work", 0, 1000, 0, "Fixture", ()))
    report = _report(paths, specs)
    return paths, bibliography, report


def _report(paths: dict, specs: tuple) -> dict:
    sections = {spec.id: (paths["sections"] / spec.filename).read_text() for spec in specs}
    issues = []
    labels, refs, citations = _reference_issues(
        paths, "\n".join(sections.values()) + _included_fragments(paths, specs), issues,
    )
    findings = complete_consistency_findings(paths, specs, sections, labels, refs, citations,
                                             {"minimum_unique_citations": 30})
    return {"accepted": not findings, "reason": "cross-section consistency failed",
            "summary": "; ".join(item["message"] for item in findings),
            "details": {"issues": [item["message"] for item in findings], "findings": findings}}


@pytest.mark.asyncio
async def test_actual_diagnostics_and_dispatch_use_only_owning_author_outputs(tmp_path):
    paths, bibliography, gate = _fixture(tmp_path)
    host = SnapshotEngine()
    run = WorkflowRun(id="fixture-bounded-paper-repair", project_path=str(tmp_path),
                      nodes=host._get_default_nodes(), options={"run_experiment": False})
    node = next(item for item in run.nodes if item.id == "paper")
    diagnostics = host._gate_revision_diagnostics(gate)
    owner = host._revision_owner_for_gate(node, run, gate)
    assert owner.id == "paper"
    assert set(diagnostics["repair_scope"]["target_files"]) == {
        "paper/sections/05_results.tex", "paper/sections/02_related_work.tex",
    }
    assert "paper/SCIENTIFIC_FREEZE.json" not in diagnostics["repair_scope"]["target_files"]
    with patch("server.agent.tools.invoke_skill", _model_boundary):
        with pytest.raises(FirstRepairBoundary) as stopped:
            await host._revise_node_from_gate(owner, run, diagnostics, 1, 1, "", "Fixture", "balanced", "draft", run.options)
    assert "SCIENTIFIC_FREEZE" not in stopped.value.contract
    assert "experiments/results/analysis" not in stopped.value.contract
    assert (paths["paper"] / "references.bib").read_text() == bibliography


def test_explicit_fixture_author_repair_resolves_only_real_obligations(tmp_path):
    paths, bibliography, before = _fixture(tmp_path)
    assert len(before["details"]["findings"]) == 2
    related = paths["sections"] / "02_related_work.tex"
    related.write_text(related.read_text() + "\nVerified source thirty explicitly tests a different matching assumption \\cite{ref30}.\n")
    result = paths["sections"] / "05_results.tex"
    result.write_text(result.read_text().replace("Table~\\ref{tab:registered-endpoint}", "The registered endpoint analysis"))
    specs = (SectionSpec("results", "05_results.tex", "Results", 0, 1000, 0, "Fixture", ()),
             SectionSpec("related_work", "02_related_work.tex", "Related Work", 0, 1000, 0, "Fixture", ()))
    after = _report(paths, specs)
    assert after["accepted"] and after["details"]["findings"] == []
    assert (paths["paper"] / "references.bib").read_text() == bibliography


@pytest.mark.asyncio
async def test_actual_repair_dispatch_executes_declared_fake_author_then_fresh_findings_clear(tmp_path, monkeypatch):
    """The only substitute is author transport; routing and fresh validators are real."""
    paths, bibliography, _gate = _fixture(tmp_path)
    table = paths["paper"] / "tables/registered.tex"
    table.parent.mkdir()
    table.write_text("\\begin{table}\\caption{Registered fixture endpoint comparison}"
                     "\\label{tab:registered-primary}\\end{table}\n")
    results = paths["sections"] / "05_results.tex"
    results.write_text(results.read_text() + "\\input{tables/registered}\n")
    literature = tmp_path / "literature/source-evidence.md"
    literature.parent.mkdir()
    literature.write_text("Verified fixture source ref30 examines a distinct matching assumption.\n")
    freeze = paths["paper"] / "SCIENTIFIC_FREEZE.json"
    freeze.write_text('{"fixture":"runtime-owned, must not change"}')
    analysis = tmp_path / "experiments/results/analysis.md"
    analysis.parent.mkdir(parents=True)
    analysis.write_text("Registered fixture results are unchanged.\n")
    specs = (SectionSpec("results", "05_results.tex", "Results", 0, 1000, 0, "Fixture", ()),
             SectionSpec("related_work", "02_related_work.tex", "Related Work", 0, 1000, 0, "Fixture", ()))
    gate = _report(paths, specs)
    assert {item["category"] for item in gate["details"]["findings"]} == {
        "undefined_reference", "unreferenced_asset", "literature_coverage",
    }
    assert len(gate["details"]["findings"]) == 3
    unreferenced = next(item for item in gate["details"]["findings"] if item["category"] == "unreferenced_asset")
    assert unreferenced["reference_key"] == "tab:registered-primary"
    assert unreferenced["target_files"] == ["paper/sections/05_results.tex"]
    protected = {path: path.read_bytes() for path in (table, literature, freeze, analysis, paths["paper"] / "references.bib")}
    calls = []

    async def fake_provider(stage, targets, contract):
        assert len(targets) == 1 and str(targets[0]) in contract
        assert "SCIENTIFIC_FREEZE" not in contract and "analysis.md" not in contract
        target = targets[0]
        if stage == "related_work":
            assert "ref30" in bibliography and "distinct matching assumption" in literature.read_text()
            target.write_text(target.read_text() + "\nVerified source thirty tests a distinct matching assumption \\cite{ref30}.\n")
        elif stage == "results":
            assert "\\label{tab:registered-primary}" in table.read_text()
            # Correct the undefined label and interpret the existing real table;
            # one bounded author edit resolves both genuine obligations.
            target.write_text(target.read_text().replace("tab:registered-endpoint", "tab:registered-primary"))
        else:
            pytest.fail("Only the implicated bounded authors may run")
        calls.append(stage)
        return "Declared fixture author output written and re-read."

    async def isolated_author_adapter(**kwargs):
        targets = paper_drafting_service.revision_target_paths(kwargs["revision_issues"])
        assert set(targets) == {"paper/sections/02_related_work.tex", "paper/sections/05_results.tex"}
        draft_paths = paper_drafting_service.paths(tmp_path)
        for target in targets:
            stage = paper_drafting_service.stage_for_project_relative_target(target)
            writes = paper_drafting_service.stage_write_targets(draft_paths, stage)
            await fake_provider(stage, writes, paper_drafting_service.invocation_contract(stage, writes))
        return "Completed both declared fixture author repairs."

    host = SnapshotEngine()
    monkeypatch.setattr(host, "_execute_staged_paper", isolated_author_adapter)
    run = WorkflowRun(project_path=str(tmp_path), nodes=host._get_default_nodes(), options={"run_experiment": False})
    node = next(item for item in run.nodes if item.id == "paper")
    diagnostics = host._gate_revision_diagnostics(gate)
    owner = host._revision_owner_for_gate(node, run, gate)
    assert owner.id == "paper"
    await host._revise_node_from_gate(owner, run, diagnostics, 1, 1, "", "Fixture", "balanced", "draft", run.options)
    after = _report(paths, specs)
    assert set(calls) == {"related_work", "results"}
    assert after["accepted"] and after["details"]["findings"] == []
    assert all(path.read_bytes() == content for path, content in protected.items())


def test_missing_content_is_not_marked_paper_accepted_by_snapshot_guard():
    assert issubclass(FirstRepairBoundary, BaseException)
    assert not issubclass(FirstRepairBoundary, Exception)


@pytest.mark.asyncio
async def test_real_runtime_refresh_revalidates_freeze_without_changing_science(tmp_path, monkeypatch):
    from server.services.node_risk_audit import node_risk_audit_service
    from server.services.paper_drafting import paper_drafting_service
    from server.services.paper_artifacts import paper_artifact_builder
    from server.workflows.paper_repair_runtime import refresh_paper_runtime_inputs

    prepare_fixture(tmp_path, long_labels=True)
    host = SnapshotEngine()
    run = WorkflowRun(id="fixture-paper-runtime", project_path=str(tmp_path), nodes=host._get_default_nodes(),
                      options={"run_experiment": False, "non_experiment_evidence_mode": "design_only",
                               "target_venue": "ICLR", "target_pages": 11})
    paper_artifact_builder.prepare(tmp_path, "Fixture direction")
    paper_drafting_service.prepare(tmp_path, run.options)
    manifest = tmp_path / "paper/tables/TABLE_MANIFEST.json"
    payload = json.loads(manifest.read_text())
    payload["runtime_regression_marker"] = "changed-but-source-bound-fixture"
    manifest.write_text(json.dumps(payload))
    before = paper_drafting_service.validate_scientific_freeze(tmp_path, run.options)
    assert not before["passed"] and "paper/tables/TABLE_MANIFEST.json" in before["changed_inputs"]
    protected = {path: path.read_bytes() for folder in (tmp_path / "experiments", tmp_path / "ideas", tmp_path / "literature")
                 for path in folder.rglob("*") if path.is_file()}
    # Explicit current/upstream fixture attestation; no paper, freeze, table or
    # repair implementation is mocked. Negative companion checks the refusal.
    monkeypatch.setattr(node_risk_audit_service, "preflight_node", lambda *_a, **_k: [])
    monkeypatch.setattr(node_risk_audit_service, "protected_upstream_findings", lambda *_a, **_k: [])
    result = await refresh_paper_runtime_inputs(host, next(node for node in run.nodes if node.id == "paper"),
                                               run, "Fixture direction", run.options)
    assert result["passed"] and paper_drafting_service.validate_scientific_freeze(tmp_path, run.options)["passed"]
    assert all(path.read_bytes() == content for path, content in protected.items())


@pytest.mark.asyncio
async def test_runtime_refresh_stops_before_any_binding_when_upstream_is_stale(tmp_path, monkeypatch):
    from server.services.node_risk_audit import node_risk_audit_service
    from server.services.paper_drafting import paper_drafting_service
    from server.workflows import paper_repair_runtime

    frozen = tmp_path / "paper/SCIENTIFIC_FREEZE.json"
    frozen.parent.mkdir()
    frozen.write_text("{\"source\":\"must-remain-exact\"}")
    original = frozen.read_bytes()
    blocker = {"id": "FIXTURE-NARRATIVE-STALE", "severity": "blocker", "upstream_node": "narrative",
               "message": "Narrative is not bound to the current analysis"}
    monkeypatch.setattr(node_risk_audit_service, "preflight_node", lambda *_a, **_k: [blocker])
    monkeypatch.setattr(node_risk_audit_service, "protected_upstream_findings", lambda *_a, **_k: [])

    def forbidden(*_a, **_k):
        pytest.fail("Stale upstream evidence must prevent runtime preparation and freeze rebinding")

    monkeypatch.setattr(paper_repair_runtime, "prepare_paper_evidence", forbidden)
    monkeypatch.setattr(paper_drafting_service, "prepare", forbidden)
    host = SnapshotEngine()
    run = WorkflowRun(project_path=str(tmp_path), nodes=host._get_default_nodes())
    result = await paper_repair_runtime.refresh_paper_runtime_inputs(
        host, next(node for node in run.nodes if node.id == "paper"), run, "Fixture", {},
    )
    assert not result["passed"] and result["findings"] == [blocker]
    assert frozen.read_bytes() == original
