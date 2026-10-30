"""Stale authored interpretation reaches its real owner without fallback overwrite."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time

import pytest

from server.services import narrative_source_bindings
from server.services.node_risk_audit import node_risk_audit_service as risk
from server.services.scientific_narrative import scientific_narrative_service as service
from server.services.workflow_inputs import artifact_state
from server.workflows.engine import WorkflowEngine
from server.workflows.models import WorkflowNode, WorkflowRun
from server.workflows.node_gate_preparation import _prepare_narrative


OPTIONS = {"run_experiment": False, "gpu_target": "none", "non_experiment_evidence_mode": "design_only"}
BODY = "# Matched narrative preservation\nC1 remains pending: no experiment was run.\n## Limitations\nEvidence is not yet observed.\n"


def _json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _seed(root: Path, generator: str) -> tuple[Path, Path]:
    _json(root / "ideas/SELECTED_IDEA.json", {"title": "Matched narrative preservation", "claims": [{"id": "C1"}]})
    _json(root / "experiments/METHOD_CONTRACT.json", {})
    _json(root / "experiments/configs/main.json", {"execution_authorized": False})
    source = root / "experiments/src/model.py"
    source.parent.mkdir(parents=True)
    source.write_text("REGISTERED_CONSTANT = 1\n", encoding="utf-8")
    survey = root / "literature/survey.md"
    survey.parent.mkdir()
    survey.write_text("Registered initial survey.\n", encoding="utf-8")
    path = root / "NARRATIVE_REPORT.md"
    path.write_text(BODY, encoding="utf-8")
    service.record_existing(root, generator=generator)
    return path, root / service.build_relative_path


def _provenance_findings(root: Path) -> list[dict]:
    return [item for item in risk._audit_narrative(root, OPTIONS) if item["id"].startswith("NAR-PROV-")]


def _risk_gate(root: Path) -> dict:
    return risk.apply_gate({"accepted": True, "summary": "Artifact prerequisite only", "details": {}}, root, "narrative", OPTIONS)


@pytest.mark.parametrize("generator", ["model-authored:narrative-node", "researcher-authored:source-bound"])
@pytest.mark.parametrize("drift", ["implementation", "science"])
def test_legacy_authored_body_and_build_are_preserved_but_stale_risk_gate_rejects(tmp_path, monkeypatch, generator, drift):
    narrative, build = _seed(tmp_path, generator)
    before = narrative.read_bytes(), build.read_bytes()
    if drift == "implementation":
        original = narrative_source_bindings.narrative_implementation_sha256()
        monkeypatch.setattr(narrative_source_bindings, "narrative_implementation_sha256", lambda: hashlib.sha256(original.encode()).hexdigest())
    else:
        (tmp_path / "literature/survey.md").write_text("Changed scientific evidence.\n", encoding="utf-8")
    result = service.ensure(tmp_path, "Matched narrative preservation", preserve_researcher_authored=False)
    assert result["generated"] is False and result["source_drift"] is True
    assert (narrative.read_bytes(), build.read_bytes()) == before
    assert json.loads(build.read_text())["schema"] == 1
    assert [item["id"] for item in _provenance_findings(tmp_path)] == ["NAR-PROV-003"]
    gate = _risk_gate(tmp_path)
    assert gate["accepted"] is False
    finding = next(item for item in gate["details"]["node_risk_audit"]["findings"] if item["id"] == "NAR-PROV-003")
    assert finding["owner_node"] == "narrative" and finding["target_files"] == ["NARRATIVE_REPORT.md"]
    assert (narrative.read_bytes(), build.read_bytes()) == before


@pytest.mark.parametrize("generator", ["model-authored:narrative-node", "researcher-authored:source-bound"])
def test_current_authored_cache_is_byte_idempotent_even_in_automatic_workflow(tmp_path, generator):
    narrative, build = _seed(tmp_path, generator)
    before = narrative.read_bytes(), build.read_bytes()
    for _ in range(2):
        assert service.ensure(tmp_path, preserve_researcher_authored=False)["generated"] is False
    assert (narrative.read_bytes(), build.read_bytes()) == before
    assert _provenance_findings(tmp_path) == []


@pytest.mark.parametrize("change", ["add", "remove"])
def test_current_discovered_source_inventory_changes_remain_blocking(tmp_path, change):
    narrative, build = _seed(tmp_path, "model-authored:narrative-node")
    before = narrative.read_bytes(), build.read_bytes()
    source = tmp_path / "experiments/configs/main.json"
    if change == "add":
        _json(source.with_name("new.json"), {"new_registered_condition": "unexecuted"})
    else:
        source.unlink()
    assert service.ensure(tmp_path, preserve_researcher_authored=False)["source_drift"] is True
    assert [item["id"] for item in _provenance_findings(tmp_path)] == ["NAR-PROV-003"]
    assert _risk_gate(tmp_path)["accepted"] is False
    assert (narrative.read_bytes(), build.read_bytes()) == before


def test_foreign_recorded_source_is_rejected_without_reading_or_rebinding_it(tmp_path, monkeypatch):
    narrative, build = _seed(tmp_path, "model-authored:narrative-node")
    foreign = tmp_path.parent / "foreign-narrative-source.txt"
    foreign.write_bytes(b"Foreign private source must never be read by this gate.")
    payload = json.loads(build.read_text())
    payload["sources"].append("../foreign-narrative-source.txt")
    build.write_text(json.dumps(payload), encoding="utf-8")
    before = narrative.read_bytes(), build.read_bytes()
    original = Path.read_bytes

    def guarded(path):
        if path.resolve() == foreign.resolve():
            raise AssertionError("Foreign source content was read")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", guarded)
    assert [item["id"] for item in _provenance_findings(tmp_path)] == ["NAR-PROV-003"]
    assert (narrative.read_bytes(), build.read_bytes()) == before


def test_tampered_authored_output_cannot_enter_the_preservation_branch_or_be_resigned_as_researcher(tmp_path):
    narrative, build = _seed(tmp_path, "model-authored:narrative-node")
    narrative.write_text("Unverified tampered text.\n", encoding="utf-8")
    before = narrative.read_bytes(), build.read_bytes()
    assert service._reuse_existing(tmp_path, narrative, build, service._source_paths(tmp_path),
        force=False, preserve_researcher_authored=False) is None
    assert [item["id"] for item in _provenance_findings(tmp_path)] == ["NAR-PROV-004"]
    assert (narrative.read_bytes(), build.read_bytes()) == before
    assert service.ensure(tmp_path, preserve_researcher_authored=False)["generated"] is True
    assert json.loads(build.read_text())["generator"] == "deterministic:evidence-bounded-narrative"


def test_explicit_force_still_rebuilds_authored_text_with_honest_deterministic_identity(tmp_path):
    narrative, build = _seed(tmp_path, "model-authored:narrative-node")
    before = narrative.read_bytes()
    result = service.ensure(tmp_path, force=True)
    assert result["generated"] is True and narrative.read_bytes() != before
    assert json.loads(build.read_text())["generator"] == "deterministic:evidence-bounded-narrative"


def test_stale_deterministic_fallback_still_rebuilds_and_then_is_idempotent(tmp_path):
    _seed(tmp_path, "model-authored:narrative-node")
    service.ensure(tmp_path, force=True)
    (tmp_path / "literature/survey.md").write_text("Updated bounded evidence.\n", encoding="utf-8")
    assert service.ensure(tmp_path, preserve_researcher_authored=False)["generated"] is True
    paths = (tmp_path / service.narrative_relative_path, tmp_path / service.build_relative_path)
    before = tuple(path.read_bytes() for path in paths)
    assert service.ensure(tmp_path, preserve_researcher_authored=False)["generated"] is False
    assert tuple(path.read_bytes() for path in paths) == before and _provenance_findings(tmp_path) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("writes_revision", [False, True])
async def test_native_revision_routes_to_author_and_preparation_binds_only_actual_new_text(tmp_path, monkeypatch, writes_revision):
    narrative, build = _seed(tmp_path, "model-authored:narrative-node")
    before = narrative.read_bytes(), build.read_bytes()
    (tmp_path / "literature/survey.md").write_text("Changed evidence awaiting author review.\n", encoding="utf-8")
    node = WorkflowNode(id="narrative", name="Narrative", skill="/narrative-writer", started_at=time.time(),
        artifact_baseline={"NARRATIVE_REPORT.md": artifact_state(narrative)})
    run = WorkflowRun(id="temp-narrative-owner", project_path=str(tmp_path), nodes=[node], options=dict(OPTIONS))
    engine = WorkflowEngine()
    from server.contracts.preparation import PreparationContractError
    with pytest.raises(PreparationContractError, match='sources changed'):
        await _prepare_narrative(engine, node, run, "Matched narrative preservation", OPTIONS)
    assert (narrative.read_bytes(), build.read_bytes()) == before
    gate = _risk_gate(tmp_path)
    assert gate["accepted"] is False
    upstream = {item["id"] for item in gate["details"]["node_risk_audit"]["findings"]
                if item["severity"] == "blocker" and item["id"].startswith("UPSTREAM-")}
    assert upstream, "This stage-local fixture does not claim complete upstream acceptance"
    diagnostics = engine._gate_revision_diagnostics(gate)
    called = []

    async def author(actual_node, actual_run, *_args, **kwargs):
        assert actual_node is node and actual_run is run
        assert "NAR-PROV-003" in kwargs["revision_context"] and "NARRATIVE_REPORT.md" in kwargs["revision_context"]
        assert (narrative.read_bytes(), build.read_bytes()) == before
        called.append(True)
        if writes_revision:
            narrative.write_text(BODY + "The revised survey is now reflected in this interpretation.\n", encoding="utf-8")
        return "Temporary fake model boundary only; no real model was called."

    monkeypatch.setattr(engine, "_execute_node", author)
    await engine._revise_node_from_gate(node, run, diagnostics, 1, 1, "", "Matched narrative preservation", "balanced", "draft", OPTIONS)
    assert called == [True]
    if writes_revision:
        # This stage-local fixture has no paper plan; repaired narrative
        # provenance must pass before the separate plan requirement blocks.
        with pytest.raises(PreparationContractError, match='paper plan is missing or stale'):
            await _prepare_narrative(engine, node, run, "Matched narrative preservation", OPTIONS)
    else:
        with pytest.raises(PreparationContractError, match='sources changed'):
            await _prepare_narrative(engine, node, run, "Matched narrative preservation", OPTIONS)
    fresh = _risk_gate(tmp_path)
    assert fresh["accepted"] is False
    assert {item["id"] for item in fresh["details"]["node_risk_audit"]["findings"]
            if item["severity"] == "blocker" and item["id"].startswith("UPSTREAM-")} == upstream
    assert any(item["id"] == "NAR-PROV-003" for item in fresh["details"]["node_risk_audit"]["findings"]) is not writes_revision
    if writes_revision:
        assert json.loads(build.read_text())["generator"] == "model-authored:narrative-node"
        assert json.loads(build.read_text())["output_sha256"] == hashlib.sha256(narrative.read_bytes()).hexdigest()
        assert _provenance_findings(tmp_path) == []
    else:
        assert (narrative.read_bytes(), build.read_bytes()) == before
        assert [item["id"] for item in _provenance_findings(tmp_path)] == ["NAR-PROV-003"]
