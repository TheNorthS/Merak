"""Contribution-selected decks retain strict complete-bundle scientific bindings."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from server.services.evidence_asset_portfolio import selected_evidence_asset_ids
from server.services.node_risk_audit import node_risk_audit_service
from server.services.scientific_slides import scientific_slide_service
from server.services.slide_figures import required_synthetic_figure_ids
from server.tests._scientific_slide_fixture import write_current_slide_bundle
from server.workflows.engine import WorkflowEngine, WorkflowRun


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _files(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*") if path.is_file()}


def _bundle(root: Path, contribution: str = "objective_mechanism") -> dict[str, Path]:
    outputs = write_current_slide_bundle(root)
    idea = root / "ideas/SELECTED_IDEA.json"
    payload = _read(idea)
    payload["publication"]["contribution_type"] = contribution
    _write(idea, payload)
    selected = selected_evidence_asset_ids(contribution)
    registry = root / "figures/FIGURE_MANIFEST.json"
    payload = _read(registry)
    for entry in payload["figures"]:
        entry["paper_ready"] = entry["id"] in selected
        entry["metadata"]["paper_selected"] = entry["id"] in selected
    _write(registry, payload)
    return outputs


def _audit(root: Path) -> list[dict]:
    return node_risk_audit_service._audit_ppt(root, {
        "run_experiment": False, "non_experiment_evidence_mode": "synthetic_preview",
    })


def _prompt(root: Path) -> str:
    return WorkflowEngine()._input_ppt("Finite benchmark", {}, WorkflowRun(
        project_path=str(root), options={
            "run_experiment": False, "non_experiment_evidence_mode": "synthetic_preview",
        },
    ))


def test_missing_bundle_input_is_diagnostic_and_never_supplies_default_required_ids(tmp_path):
    before = _files(tmp_path)
    prompt = _prompt(tmp_path)
    assert prompt.startswith("BLOCKED:") and "证据尚未通过" in prompt
    assert "不启动训练或模型" in prompt and "不更改 selection 位" in prompt
    assert "synthetic_preview_main_comparison" not in prompt
    assert _files(tmp_path) == before
    from server.services.risk_stage_ppt import _simulation_portfolio_findings
    findings = _simulation_portfolio_findings(tmp_path, "", {"selected_figures": []})
    assert any(item["id"] == "PPT-SIM-004" and item["severity"] == "blocker" for item in findings)


@pytest.mark.parametrize("contribution", [
    "model_architecture", "objective_mechanism", "experimental_protocol", "system_architecture",
    "dataset_benchmark", "empirical_discovery", "theory_proof",
    "clinical_biological_mechanism", "qualitative_framework",
])
def test_deck_matches_frozen_contribution_and_preserves_unselected_evidence(tmp_path, contribution):
    outputs = _bundle(tmp_path, contribution)
    before = _files(tmp_path)
    required = set(required_synthetic_figure_ids(tmp_path))
    assert required == selected_evidence_asset_ids(contribution)
    assert len(required) in {3, 4}
    scientific_slide_service.ensure(tmp_path, "Finite benchmark")
    text = (tmp_path / "slides/main.tex").read_text(encoding="utf-8")
    plan = _read(tmp_path / "slides/SLIDE_PLAN.json")
    assert set(plan["selected_figures"]) == required
    assert set(scientific_slide_service.referenced_figure_ids(tmp_path, text)) == required
    assert all(("../" + path.relative_to(tmp_path).as_posix() in text) is (identity in required)
               for identity, path in outputs.items() if identity.startswith("synthetic_preview_"))
    assert not any(item["id"] in {"PPT-SIM-001", "PPT-SIM-004"} for item in _audit(tmp_path))
    assert all((tmp_path / relative).read_bytes() == content for relative, content in before.items())
    entries = _read(tmp_path / "figures/FIGURE_MANIFEST.json")["figures"]
    assert len(entries) == 7
    assert all(entry["metadata"]["paper_selected"] is (entry["id"] in required) for entry in entries)


@pytest.mark.parametrize("defect", ["data", "source", "pdf", "svg", "png"])
def test_unselected_evidence_drift_blocks_instead_of_reducing_required_portfolio(tmp_path, defect):
    outputs = _bundle(tmp_path)
    scientific_slide_service.ensure(tmp_path, "Finite benchmark")
    required = set(required_synthetic_figure_ids(tmp_path))
    simulation = _read(outputs["simulation_manifest"])
    record = next(item for item in simulation["figure_files"] if item["id"] not in required)
    if defect == "data":
        entry = next(item for item in _read(tmp_path / "figures/FIGURE_MANIFEST.json")["figures"]
                     if item["id"] == record["id"])
        relative = entry["metadata"]["source_data"][0]
    else:
        relative = record["source"] if defect == "source" else record["outputs"][defect]
    (tmp_path / relative).write_bytes(b"Edited after freezing")
    before = _files(tmp_path)
    assert scientific_slide_service.qualified_synthetic_figures(tmp_path) == []
    assert any(item["id"] == "PPT-SIM-004" and item["severity"] == "blocker"
               for item in _audit(tmp_path))
    assert _files(tmp_path) == before


@pytest.mark.parametrize("field", ["paper_selected", "manuscript_eligible", "submission_eligible",
                                   "simulation_manifest_sha256", "source_sha256", "rendered_variant_sha256"])
def test_unqualified_required_figure_remains_required_and_blocking(tmp_path, field):
    _bundle(tmp_path)
    scientific_slide_service.ensure(tmp_path, "Finite benchmark")
    required = set(required_synthetic_figure_ids(tmp_path))
    registry = tmp_path / "figures/FIGURE_MANIFEST.json"
    payload = _read(registry)
    identity = sorted(required)[0]
    entry = next(item for item in payload["figures"] if item["id"] == identity)
    if field == "source_sha256":
        entry[field] = "0" * 64
    elif field == "rendered_variant_sha256":
        entry["metadata"][field]["png"] = "0" * 64
    elif field == "submission_eligible":
        entry["metadata"][field] = True  # A synthetic preview must never be promoted to submission evidence.
    else:
        entry["metadata"][field] = "0" * 64 if field.endswith("sha256") else False
    _write(registry, payload)
    before = _files(tmp_path)
    assert set(required_synthetic_figure_ids(tmp_path)) == required
    assert any(item["id"] == "PPT-SIM-001" and identity in item["message"]
               for item in _audit(tmp_path))
    assert _files(tmp_path) == before


@pytest.mark.parametrize("defect", ["missing_idea", "schema", "unknown_contribution", "missing_bundle"])
def test_missing_or_unsupported_portfolio_never_passes_with_empty_expected_set(tmp_path, defect):
    outputs = _bundle(tmp_path)
    scientific_slide_service.ensure(tmp_path, "Finite benchmark")
    idea = tmp_path / "ideas/SELECTED_IDEA.json"
    if defect == "missing_idea":
        idea.unlink()
    elif defect == "missing_bundle":
        outputs["simulation_manifest"].unlink()
    else:
        payload = _read(idea)
        if defect == "schema":
            payload["schema"] = 1
        else:
            payload["publication"]["contribution_type"] = "unsupported"
        _write(idea, payload)
    before = _files(tmp_path)
    prompt = _prompt(tmp_path)
    assert prompt.startswith("BLOCKED:") and "证据尚未通过" in prompt
    assert "按冻结贡献与论文相同的图集完整引用以下必需结果图" not in prompt
    assert any(item["id"] == "PPT-SIM-004" and item["severity"] == "blocker"
               for item in _audit(tmp_path))
    assert _files(tmp_path) == before


def test_empty_qualification_cannot_lower_required_figure_set(tmp_path):
    _bundle(tmp_path)
    scientific_slide_service.ensure(tmp_path, "Finite benchmark")
    required = set(required_synthetic_figure_ids(tmp_path))
    registry = tmp_path / "figures/FIGURE_MANIFEST.json"
    payload = _read(registry)
    payload["figures"] = [entry for entry in payload["figures"] if entry["id"] not in required]
    _write(registry, payload)
    assert set(required_synthetic_figure_ids(tmp_path)) == required
    finding = next(item for item in _audit(tmp_path) if item["id"] == "PPT-SIM-001")
    assert finding["severity"] == "blocker"
    assert all(identity in finding["message"] for identity in required)


def test_available_method_figure_is_still_required_with_selected_results(tmp_path):
    outputs = _bundle(tmp_path)
    method = tmp_path / "figures/method.pdf"
    method.write_bytes(outputs["synthetic_preview_main_comparison"].read_bytes())
    registry = tmp_path / "figures/FIGURE_MANIFEST.json"
    payload = _read(registry)
    payload["figures"].append({
        "id": "method", "paper_ready": True, "output_path": "figures/method.pdf",
        "output_sha256": hashlib.sha256(method.read_bytes()).hexdigest(),
        "metadata": {"scientific_role": "method", "paper_selected": True},
    })
    _write(registry, payload)
    scientific_slide_service.ensure(tmp_path, "Finite benchmark")
    assert {entry["id"] for entry in scientific_slide_service.qualified_standard_figures(tmp_path)} == {"method"}
    main = tmp_path / "slides/main.tex"
    main.write_text(main.read_text(encoding="utf-8").replace("../figures/method.pdf", ""), encoding="utf-8")
    assert any(item["id"] == "PPT-FIG-003" and item["severity"] == "blocker"
               for item in _audit(tmp_path))
