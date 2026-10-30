"""Pure source-bound missing-interpretation routing, without authors or workflows."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from server.services.paper_asset_author_ownership import unreferenced_asset_author
from server.services.paper_consistency_findings import (
    complete_consistency_findings, implicated_consistency_findings, merge_complete_findings,
)
from server.services.paper_draft_coordinator import DraftCoordinator
from server.services.paper_drafting import (
    AUTHOR_STAGE_ORDER, PAPER_STAGE_LABELS, PAPER_STAGE_ORDER,
    SECTION_BY_ID, SECTION_SPECS, PaperDraftingError, PaperDraftingService,
)
from server.services.paper_stage_validator_signature import stage_validator_signature
from server.tests.test_paper_asset_placement import _figure, _fixture, _records, _table, _write


def _finding(root, paths, specs, label):
    sections = {spec.id: (paths["sections"] / spec.filename).read_text(encoding="utf-8") for spec in specs}
    return complete_consistency_findings(paths, specs, sections, {label}, set(), set(), {})[0]


def _protected(root):
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}


@pytest.mark.parametrize("label, expected", [
    ("fig:method-architecture", ("method", "paper/sections/03_method.tex")),
    ("fig:evaluation-design", ("experiments", "paper/sections/04_experiments.tex")),
    ("fig:result", ("results", "paper/sections/05_results.tex")),
])
def test_selected_assembly_assets_route_using_current_source_role_and_actual_placement(tmp_path, label, expected):
    paths, specs, _sections = _fixture(tmp_path)
    before = _protected(tmp_path)
    finding = _finding(tmp_path, paths, specs, label)
    assert finding["category"] == "unreferenced_asset"
    assert (finding["stage_id"], finding["target_files"][0]) == expected
    assert label in finding["message"] and expected[1] in finding["message"]
    assert finding["legal_write_targets"] == [expected[1]] and finding["severity"] == "blocker"
    assert "dummy reference" in finding["remediation"]
    assert _protected(tmp_path) == before


def test_label_spelling_never_selects_the_owner_and_unregistered_inline_float_remains_legal(tmp_path):
    paths, specs, _sections = _fixture(tmp_path)
    label = "fig:results-sounding-label"
    _write(tmp_path, "paper/sections/03_method.tex", _figure(label, "../figures/diagrams/method_architecture.pdf"))
    before = _protected(tmp_path)
    finding = _finding(tmp_path, paths, specs, label)
    assert finding["stage_id"] == "method"
    assert finding["target_files"] == ["paper/sections/03_method.tex"]
    assert _protected(tmp_path) == before


def test_selected_inline_float_belongs_to_actual_unique_author_even_without_known_role(tmp_path):
    paths, specs, _sections = _fixture(tmp_path)
    manifest = tmp_path / "figures/FIGURE_MANIFEST.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["figures"][0]["metadata"]["scientific_role"] = "custom-domain-role"
    _write(tmp_path, "figures/FIGURE_MANIFEST.json", json.dumps(payload))
    _write(tmp_path, "paper/sections/03_method.tex",
        _figure("fig:method-architecture", "../figures/diagrams/method_architecture.pdf"))
    assert unreferenced_asset_author(tmp_path, "fig:method-architecture", specs) == (
        "method", "paper/sections/03_method.tex")


def test_registered_table_assembly_targets_the_real_method_author(tmp_path):
    paths, specs, _sections = _fixture(tmp_path)
    _write(tmp_path, "paper/tables/components.tex", _table("tab:components"))
    _records(tmp_path, [{"label": "tab:components", "scientific_role": "method_components",
        "latex_path": "paper/tables/components.tex"}])
    finding = _finding(tmp_path, paths, specs, "tab:components")
    assert finding["stage_id"] == "method"
    assert finding["target_files"] == ["paper/sections/03_method.tex"]


@pytest.mark.parametrize("defect", ["unknown_assembly_role", "multiple_authors", "unowned_label", "conflicting_sources"])
def test_unknown_or_ambiguous_ownership_fails_closed_without_default_results(tmp_path, defect):
    paths, specs, _sections = _fixture(tmp_path)
    label = "fig:method-architecture"
    if defect == "unknown_assembly_role":
        path = tmp_path / "figures/FIGURE_MANIFEST.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["figures"][0]["metadata"]["scientific_role"] = "unsupported-domain-role"
        _write(tmp_path, "figures/FIGURE_MANIFEST.json", json.dumps(payload))
    elif defect == "multiple_authors":
        for name in ("03_method", "06_discussion"):
            _write(tmp_path, f"paper/sections/{name}.tex",
                _figure(label, "../figures/diagrams/method_architecture.pdf"))
    elif defect == "unowned_label":
        label = "fig:no-source-author"
    else:
        path = tmp_path / "figures/FIGURE_MANIFEST.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        extra = copy.deepcopy(payload["figures"][1])
        extra["metadata"]["label"] = label
        payload["figures"].append(extra)
        _write(tmp_path, "figures/FIGURE_MANIFEST.json", json.dumps(payload))
    before = _protected(tmp_path)
    with pytest.raises(ValueError):
        _finding(tmp_path, paths, specs, label)
    assert _protected(tmp_path) == before


@pytest.mark.parametrize("wrapped", [
    "scientific assets included but never referenced in prose: fig:method-architecture",
    "scientific asset is included but never referenced in prose: fig:method-architecture",
    "staged-paper: Cross-section consistency: scientific assets included but never referenced in prose: fig:method-architecture",
])
def test_plural_singular_and_wrapped_gate_findings_resolve_to_exact_author_target(tmp_path, wrapped):
    paths, specs, _sections = _fixture(tmp_path)
    finding = _finding(tmp_path, paths, specs, "fig:method-architecture")
    assert implicated_consistency_findings([wrapped], [finding]) == [finding]
    generic = {"id": "report-only-generic", "stage_id": "consistency", "message": wrapped,
        "target_files": ["paper/CROSS_SECTION_REVIEW.md"]}
    assert merge_complete_findings([generic], [finding]) == [finding]


def test_precise_missing_reference_survives_native_paper_repair_arguments_to_method_prompt(tmp_path, monkeypatch):
    import asyncio
    from server.workflows.revision_execution import _execute_paper_repairs

    paths, _specs, _sections = _fixture(tmp_path)
    service = PaperDraftingService()
    paths = {**service.paths(tmp_path), **paths}
    for name in ("contracts", "profile", "state"):
        _write(tmp_path, f"paper/{paths[name].name}", "{}")
    finding = _finding(tmp_path, paths, SECTION_SPECS, "fig:method-architecture")
    issue = "scientific asset is included but never referenced in prose: fig:method-architecture"
    report = {"passed": False, "findings": [finding], "issues": [issue]}
    monkeypatch.setattr(service, "validate_complete_draft", lambda *_args, **_kwargs: report)
    calls = []
    async def staged(**arguments):
        calls.append(arguments)
        return "Pure routing observation; no model"
    diagnostics = {"findings": [finding], "issues": [issue],
        "repair_scope": {"target_files": finding["target_files"]}}
    asyncio.run(_execute_paper_repairs(SimpleNamespace(_execute_staged_paper=staged),
        SimpleNamespace(id="paper"), SimpleNamespace(), diagnostics, "", "", {},
        [issue], diagnostics["repair_scope"], finding["target_files"], finding["target_files"], []))
    directed = calls[0]["revision_issues"]
    coordinator = DraftCoordinator(service=service, project_path=tmp_path, direction="", options={},
        invoke_stage=staged, emit=None, revision_issues=directed, paths=paths,
        author_order=AUTHOR_STAGE_ORDER, paper_stage_order=PAPER_STAGE_ORDER,
        section_by_id=SECTION_BY_ID, stage_labels=PAPER_STAGE_LABELS,
        error_factory=PaperDraftingError, directed_repair_attempts=2, semantic_stall_attempts=2)
    coordinator._configure_targeted_repairs()
    assert set(coordinator.target_stage_issues) == {"method", "consistency"}
    current = coordinator.target_stage_issues["method"]
    assert any("fig:method-architecture" in value for value in current)
    before = _protected(tmp_path)
    prompt = service.build_stage_prompt(tmp_path, "method", {}, revision_issues=current)
    assert "fig:method-architecture" in prompt and "never referenced" in prompt
    assert "paper/sections/03_method.tex" in prompt
    assert service.stage_write_targets(paths, "consistency") == [paths["cross_review"]]
    after = _protected(tmp_path)
    assert all(after[name] == body for name, body in before.items())


def test_resolved_reference_removes_only_its_obligation(tmp_path):
    paths, specs, _sections = _fixture(tmp_path)
    sections = {spec.id: (paths["sections"] / spec.filename).read_text(encoding="utf-8") for spec in specs}
    findings = complete_consistency_findings(paths, specs, sections,
        {"fig:method-architecture", "fig:evaluation-design"}, {"fig:method-architecture"}, set(), {})
    assert len(findings) == 1 and findings[0]["reference_key"] == "fig:evaluation-design"
    assert findings[0]["stage_id"] == "experiments"


def test_owner_helper_code_is_part_of_consistency_and_assembly_validator_identity(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "services/paper_asset_author_ownership.py"
    original = Path.read_bytes
    before = {name: stage_validator_signature(name) for name in ("consistency", "assembly", "method")}
    def changed(candidate):
        raw = original(candidate)
        return raw + b"\n# Fixture source identity changed" if candidate == path else raw
    monkeypatch.setattr(Path, "read_bytes", changed)
    assert stage_validator_signature("consistency") != before["consistency"]
    assert stage_validator_signature("assembly") != before["assembly"]
    assert stage_validator_signature("method") == before["method"]
