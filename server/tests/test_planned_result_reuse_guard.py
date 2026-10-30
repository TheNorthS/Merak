"""Existing scientific bundles cannot become new numeric generation via cache misses."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.services.planned_result_reuse import planned_result_evidence_mode, resolve_planned_result_reuse
from server.services.simulation_policy import SIMULATION_MANIFEST_SCHEMA, SIMULATION_RENDERER_VERSION
from server.tests._scientific_slide_fixture import write_current_slide_bundle


def _cache(root: Path) -> tuple[list[Path], dict]:
    outputs = write_current_slide_bundle(root)
    planned = root / "experiments/results/templates/PLANNED_RESULT_MANIFEST.json"
    planned.parent.mkdir()
    payload = {"schema": 5, "evidence_mode": "synthetic_preview", "input_bundle_sha256": "bound-input",
               "publication_style": {"target_venue": "ICLR"}}
    planned.write_text(json.dumps(payload), encoding="utf-8")
    return [planned, outputs["simulation_manifest"], root / "paper/tables/synthetic_preview_results.tex"], payload


def _resolve(root: Path, required: list[Path], **kwargs):
    return resolve_planned_result_reuse(root, required, mode="synthetic_preview", input_hash="bound-input",
                                       target_venue="ICLR", force=False, **kwargs)


def test_complete_current_existing_bundle_reuses_without_writing_any_input(tmp_path: Path) -> None:
    required, payload = _cache(tmp_path)
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    generated, current = _resolve(tmp_path, required)
    assert generated is False and current == payload
    assert all(path.read_bytes() == content for path, content in before.items())


@pytest.mark.parametrize("defect", ["old_schema", "old_renderer", "data_hash", "source_hash", "missing_output", "missing_cache", "cache_hash"])
def test_existing_bad_or_changed_bundle_is_rejected_not_replaced(tmp_path: Path, defect: str) -> None:
    required, _payload = _cache(tmp_path)
    manifest = required[1]
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    if defect == "old_schema":
        payload["schema"] = SIMULATION_MANIFEST_SCHEMA - 1
    elif defect == "old_renderer":
        payload["renderer_version"] = SIMULATION_RENDERER_VERSION - 1
    elif defect == "data_hash":
        (tmp_path / payload["data_files"][0]["path"]).write_bytes(b"changed")
    elif defect == "source_hash":
        (tmp_path / payload["figure_files"][0]["source"]).write_bytes(b"changed")
    elif defect == "missing_output":
        (tmp_path / payload["figure_files"][0]["outputs"]["png"]).unlink()
    elif defect == "missing_cache":
        required[0].unlink()
    else:
        planned = json.loads(required[0].read_text())
        planned["input_bundle_sha256"] = "different-scientific-input"
        required[0].write_text(json.dumps(planned))
    manifest.write_text(json.dumps(payload))
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    with pytest.raises(ValueError):
        _resolve(tmp_path, required)
    assert all(path.read_bytes() == content for path, content in before.items())


def test_force_does_not_authorize_numeric_regeneration_of_existing_bundle(tmp_path: Path) -> None:
    required, _payload = _cache(tmp_path)
    before = required[1].read_bytes()
    with pytest.raises(ValueError, match="Forced regeneration"):
        resolve_planned_result_reuse(tmp_path, required, mode="synthetic_preview", input_hash="bound-input",
                                    target_venue="ICLR", force=True)
    assert required[1].read_bytes() == before


def test_initial_empty_producer_request_can_create_its_new_templates(tmp_path: Path) -> None:
    generated, payload = _resolve(tmp_path, [tmp_path / "new_manifest.json"])
    assert generated is True and payload == {}


@pytest.mark.parametrize("mode", ["existing_results", "secondary_analysis", "unsupported"])
def test_planning_entry_rejects_imported_or_unsupported_evidence_before_writes(mode: str) -> None:
    with pytest.raises(ValueError, match="cannot replace existing"):
        planned_result_evidence_mode({"run_experiment": False, "non_experiment_evidence_mode": mode})


def test_planning_mode_normalization_is_shared_and_source_options_unchanged() -> None:
    options = {"run_experiment": False, "non_experiment_evidence_mode": " SYNTHETIC_PREVIEW "}
    assert planned_result_evidence_mode(options) == "synthetic_preview"
    assert options["non_experiment_evidence_mode"] == " SYNTHETIC_PREVIEW "
