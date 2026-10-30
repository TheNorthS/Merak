"""Paper print failures preserve asset ownership and stop before model authoring."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from server.contracts.repairs import repair_capability_for
from server.services import paper_derived_figure_rendering as rendering
from server.services import paper_print_repair as repair
from server.services.paper_failure_details import paper_failure_details
from server.services.paper_layout_errors import PaperPublicationLayoutError
from server.services.paper_print_producer_findings import print_projection_finding, scoped_print_projection_error
from server.services.paper_preparation_errors import PaperPreparationError
from server.services.semantic_table import SemanticTableContractError
from server.workflows.engine import WorkflowEngine
from server.workflows.models import WorkflowNode, WorkflowRun
from server.tests._workflow_revision_loop_support import _start_run_state


ASSET = "method_architecture"


def _entry(root: Path) -> dict:
    figures = root / "figures/diagrams"
    figures.mkdir(parents=True)
    source = figures / "method.figurespec.json"
    source.write_bytes(b'{"schema":4,"declared":"source-bound fixture"}')
    variants = {}
    for kind in ("pdf", "svg", "png"):
        path = figures / ("method." + kind)
        path.write_bytes(("Frozen original " + kind).encode())
        variants[kind] = path.relative_to(root).as_posix()
    sha = lambda path: hashlib.sha256((root / path).read_bytes()).hexdigest()
    entry = {"id": ASSET, "source_path": source.relative_to(root).as_posix(),
        "source_sha256": sha(source.relative_to(root)), "output_path": variants["pdf"],
        "output_sha256": sha(variants["pdf"]), "metadata": {
            "semantic_key": ASSET, "producer_kind": "deterministic",
            "production_strategy": "deterministic_architecture", "rendered_variants": variants,
            "rendered_variant_sha256": {key: sha(path) for key, path in variants.items()}}}
    (root / "figures/FIGURE_MANIFEST.json").write_text(json.dumps({"schema": 1, "figures": [entry]}))
    return entry


def _originals(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for directory in (root / "figures", root / "paper/sections")
            for path in directory.rglob("*") if path.is_file()}


@pytest.mark.parametrize("operation", ["font_measurement", "source_bindings", "bounded_renderer"])
@pytest.mark.asyncio
async def test_real_print_entry_boundary_retains_json_source_identity_and_runtime_targets(tmp_path, monkeypatch, operation):
    from server.services import publication_print_contract, paper_print_projection

    entry = _entry(tmp_path)
    before = _originals(tmp_path)
    contract = {"contract_sha256": "a" * 64, "placements": [{
        "graphic_relative": entry["output_path"], "width_bp": 400.0}]}
    monkeypatch.setattr(publication_print_contract, "read_publication_print_contract",
                        lambda _root: SimpleNamespace(to_dict=lambda: contract))
    monkeypatch.setattr(paper_print_projection, "restore_print_entrypoint", lambda _root: None)
    cause = rendering.PaperFigureProjectionError(ASSET, "two bounded attempts exhausted", [{"attempt": 1}, {"attempt": 2}])
    if operation == "font_measurement":
        cause = ValueError("Printed figure requires exactly one verified PDF page")
        def fail_measurement(*_args):
            raise cause
        monkeypatch.setattr(repair, "_placed_minimum", fail_measurement)
    else:
        monkeypatch.setattr(repair, "_placed_minimum", lambda *_args: 7.0)
        if operation == "source_bindings": cause = ValueError("Paper figure original input hash is missing or stale")
        async def fail_derive(*_args):
            raise cause
        monkeypatch.setattr(rendering, "derive_paper_figure", fail_derive)
    async def forbidden_compile(*_args, **_kwargs):
        pytest.fail("A failed print producer must not compile or invoke a model")
    with pytest.raises(PaperPublicationLayoutError) as caught:
        await repair.compile_print_verified_paper(SimpleNamespace(compile=forbidden_compile), tmp_path)
    details = paper_failure_details(caught.value)
    finding = details["findings"][0]
    assert finding["owner_node"] == "paper" and finding["asset_ids"] == [ASSET]
    assert finding["target_files"] == [f"paper/derived-figures/{ASSET}/PROVENANCE.json"]
    assert finding["producer_context"]["source_path"] == entry["source_path"]
    assert finding["producer_context"]["rendered_variants"] == entry["metadata"]["rendered_variants"]
    assert finding["producer_context"]["production_strategy"] == "deterministic_architecture"
    assert finding["runtime_operation"] == "derive_paper_figure" and finding["legal_write_targets"] == []
    assert finding["repair_capability"] == "paper-print-projection"
    assert details["local_layout_attempts"] == (2 if operation == "bounded_renderer" else 0)
    assert _originals(tmp_path) == before


@pytest.mark.parametrize("cause", [PermissionError("unsafe write"), TypeError("programming error"), OSError("IO failure")])
@pytest.mark.asyncio
async def test_non_contract_errors_are_not_relabelled_as_runtime_print_failures(tmp_path, monkeypatch, cause):
    from server.services import publication_print_contract, paper_print_projection

    entry = _entry(tmp_path)
    monkeypatch.setattr(publication_print_contract, "read_publication_print_contract", lambda _root: SimpleNamespace(
        to_dict=lambda: {"placements": [{"graphic_relative": entry["output_path"], "width_bp": 400.0}]}))
    monkeypatch.setattr(paper_print_projection, "restore_print_entrypoint", lambda _root: None)
    def fail_measurement(*_args):
        raise cause
    monkeypatch.setattr(repair, "_placed_minimum", fail_measurement)
    with pytest.raises(type(cause)) as caught:
        await repair.prepare_print_figures(tmp_path)
    assert caught.value is cause


@pytest.mark.asyncio
async def test_real_json_entry_binding_failure_before_renderer_retains_exact_asset_and_scope(tmp_path, monkeypatch):
    from server.services import publication_print_contract, paper_print_projection

    entry = _entry(tmp_path)
    entry["metadata"]["rendered_variants"].pop("svg")
    (tmp_path / "figures/FIGURE_MANIFEST.json").write_text(json.dumps({"schema": 1, "figures": [entry]}))
    before = _originals(tmp_path)
    monkeypatch.setattr(publication_print_contract, "read_publication_print_contract", lambda _root: SimpleNamespace(
        to_dict=lambda: {"contract_sha256": "a" * 64,
                        "placements": [{"graphic_relative": entry["output_path"], "width_bp": 400.0}]}))
    monkeypatch.setattr(paper_print_projection, "restore_print_entrypoint", lambda _root: None)
    monkeypatch.setattr(repair, "_placed_minimum", lambda *_args: 7.0)
    def forbidden_render(*_args, **_kwargs):
        pytest.fail("Invalid original bindings must fail before any renderer")
    async def forbidden_compile(*_args, **_kwargs):
        pytest.fail("Invalid original bindings must fail before compilation")
    monkeypatch.setattr(rendering, "_render_candidate", forbidden_render)
    with pytest.raises(PaperPublicationLayoutError) as caught:
        await repair.compile_print_verified_paper(SimpleNamespace(compile=forbidden_compile), tmp_path)
    error = caught.value
    assert isinstance(error.__cause__, rendering.PaperFigureProjectionError)
    assert isinstance(error.__cause__.__cause__, ValueError)
    assert "all three hash-bound" in str(error)
    finding = error.gate_details()["findings"][0]
    assert finding["asset_ids"] == [ASSET] and finding["owner_node"] == "paper"
    assert finding["target_files"] == [f"paper/derived-figures/{ASSET}/PROVENANCE.json"]
    assert finding["producer_context"]["source_path"] == entry["source_path"]
    assert _originals(tmp_path) == before


def _layout_failure(entry: dict) -> PaperPublicationLayoutError:
    cause = scoped_print_projection_error(entry, ValueError("Paper figure original input hash is missing or stale"))
    return PaperPublicationLayoutError([str(cause)], [print_projection_finding(cause)], attempts=0)


def test_normal_diagnostics_retains_known_print_classification_and_narrow_runtime_capability(tmp_path):
    error = _layout_failure(_entry(tmp_path))
    gate = {"accepted": False, "reason": "artifact preparation or verification failed",
        "summary": str(error), "details": error.gate_details()}
    diagnostics = WorkflowEngine._gate_revision_diagnostics(gate)
    assert diagnostics["error_category"] == "paper_publication_layout"
    assert diagnostics["stopped_for_deterministic_stage"] is True
    finding = diagnostics["findings"][0]
    assert finding["repair_capability"] == "paper-print-projection"
    assert finding["owner_node"] == "paper" and finding["legal_write_targets"] == []
    assert finding["producer_context"]["asset_id"] == ASSET
    assert finding["producer_context"]["source_path"] == "figures/diagrams/method.figurespec.json"
    assert finding["render_attempts"] == []
    assert diagnostics["repair_scope"]["asset_ids"] == [ASSET]
    assert "paper/main.tex" not in diagnostics["repair_scope"]["target_files"]


@pytest.mark.asyncio
async def test_real_native_revision_loop_checkpoints_print_failure_before_any_author_or_canonical_redraw(tmp_path, monkeypatch):
    entry = _entry(tmp_path)
    error = _layout_failure(entry)
    engine = WorkflowEngine()
    node = WorkflowNode(id="paper", name="Paper", skill="/paper-write")
    figure = WorkflowNode(id="figure", name="Figures", skill="/paper-figure")
    run = WorkflowRun(id="print-runtime-checkpoint", project_path=str(tmp_path), nodes=[figure, node], status="running")
    state = _start_run_state(tmp_path, run.id, run.nodes)
    state.set_status("figure", "done")
    state.accept("figure", "fixture:genuine-upstream-owner", "deterministic:figure-manifest", {})
    accepted = copy.deepcopy(state.load()["phases"]["figure"])
    before = _originals(tmp_path)
    events = []
    async def prepare(*_args, **_kwargs):
        raise error
    async def forbidden_model(*_args, **_kwargs):
        pytest.fail("A runtime print producer defect must not spend a manuscript or figure model call")
    async def emit(_run, event, data):
        events.append((event, data))
    monkeypatch.setattr(engine, "_prepare_node_for_gate", prepare)
    monkeypatch.setattr(engine, "_revise_node_from_gate", forbidden_model)
    monkeypatch.setattr(engine, "_execute_staged_paper", forbidden_model)
    monkeypatch.setattr(engine, "_emit", emit)
    gate, _result = await engine._run_node_revision_loop(node=node, run=run, initial_result="existing manuscript",
        research_direction="Local fixture only", effort="balanced", assurance="draft", opts={},
        require_fresh=False, checkpoint_timeout=30, max_revision_rounds=6)
    assert gate["accepted"] is False and gate["waiting"] is True and gate["revision_round"] == 0
    saved = state.load()
    assert saved["phases"]["figure"] == accepted
    phase = saved["phases"]["paper"]
    assert phase["status"] == "awaiting_revision"
    assert phase["details"]["revision"]["stopped_for_deterministic_stage"] is True
    assert phase["details"]["revision"]["last_gate"]["error_category"] == "paper_publication_layout"
    assert not {"node_revision_started", "node_accepted", "paper_stage_started"}.intersection(event for event, _data in events)
    assert _originals(tmp_path) == before


@pytest.mark.parametrize("invalid", ["bare_flags", "wrong_id", "missing_attempts", "accepted", "retryable"])
def test_untrusted_or_incomplete_flags_do_not_gain_a_deterministic_paper_checkpoint(tmp_path, invalid):
    details = _layout_failure(_entry(tmp_path)).gate_details()
    gate = {"accepted": False, "details": details}
    if invalid == "bare_flags": details["findings"] = []
    elif invalid == "wrong_id": details["findings"][0]["id"] = "MODEL-WRITTEN-NOTE"
    elif invalid == "missing_attempts": details.pop("local_layout_attempts")
    elif invalid == "accepted": gate["accepted"] = True
    else: details["retryable"] = True
    diagnostics = WorkflowEngine._gate_revision_diagnostics(gate)
    assert "error_category" not in diagnostics and "stopped_for_deterministic_stage" not in diagnostics


def test_existing_typed_preparation_failure_also_retains_its_known_platform_classification():
    cause = SemanticTableContractError("paragraph-length cell", table_label="tab:method-components")
    details = PaperPreparationError("table_evidence", cause).gate_details()
    diagnostics = WorkflowEngine._gate_revision_diagnostics({"accepted": False, "details": details})
    assert diagnostics["error_category"] == "paper_preparation"
    assert diagnostics["stopped_for_deterministic_stage"] is True


@pytest.mark.parametrize("target,category", [("figures/method.figurespec.json", "visual_layout"),
    ("paper/sections/03_method.tex", "visual_layout"), ("paper/derived-figures/method/PROVENANCE.json", "paper_section")])
def test_runtime_print_capability_does_not_capture_canonical_figures_or_manuscript_semantics(target, category):
    capability = repair_capability_for(message="Paper typography projection requires readable text",
        target_files=[target], category=category)
    assert capability is None or capability.identity != "paper-print-projection"


def test_ordinary_manuscript_finding_keeps_exact_method_author_route(tmp_path):
    from server.services.paper_drafting import paper_drafting_service

    finding = {"id": "PAPER-CONSISTENCY-CORE", "severity": "blocker", "category": "paper_section",
        "owner_node": "paper", "target_files": ["paper/sections/03_method.tex"],
        "message": "scientific asset is included but never referenced in prose: fig:core-mechanism; revise paper/sections/03_method.tex"}
    diagnostics = WorkflowEngine._gate_revision_diagnostics({"accepted": False, "details": {"findings": [finding]}})
    assert "error_category" not in diagnostics
    assert diagnostics["findings"][0]["repair_capability"] == "manuscript-source"
    assert diagnostics["repair_scope"]["target_files"] == ["paper/sections/03_method.tex"]
    assert paper_drafting_service.stage_for_project_relative_target(diagnostics["repair_scope"]["target_files"][0]) == "method"
