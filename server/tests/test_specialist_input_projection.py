"""Exact planned-manifest presentation projection preserves scientific identity."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from server.services.specialist_catalog import selected_specialists
from server.services.specialist_inputs import canonical_scientific_input_bytes, scientific_input_bytes, specialist_input_digest


MANIFEST = "experiments/results/templates/PLANNED_RESULT_MANIFEST.json"


def _manifest() -> dict:
    return {
        "schema": 5, "evidence_mode": "synthetic_preview", "primary_metric": "balanced_accuracy",
        "metric_direction": "maximize", "claim_ids": ["C1"], "methods": ["Reference", "Proposed"],
        "experiments": [{"id": "main_comparison", "data_path": "experiments/results/simulated/main.csv"}],
        "figures": [{"id": "result", "metadata": {
            "paper_selected": True, "claim_ids": ["C1"], "source_data": ["experiments/results/simulated/main.csv"],
            "source_data_sha256": {"experiments/results/simulated/main.csv": "a" * 64},
            "scientific_question": "Does the matched contrast reject the stated null?", "producer_kind": "deterministic",
        }}],
    }


def _bytes(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _project(root: Path, payload: dict, relative: str = MANIFEST) -> bytes:
    return canonical_scientific_input_bytes(root / relative, _bytes(payload))


def test_exact_current_planned_manifest_selection_does_not_change_source_projection(tmp_path):
    original, selected = _manifest(), _manifest()
    selected["figures"][0]["metadata"]["paper_selected"] = False
    assert _project(tmp_path, original) == _project(tmp_path, selected)
    assert original["figures"][0]["metadata"]["paper_selected"] is True
    assert selected["figures"][0]["metadata"]["paper_selected"] is False


def test_selection_removal_is_not_a_persisted_manifest_edit(tmp_path):
    path = tmp_path / MANIFEST
    path.parent.mkdir(parents=True)
    path.write_bytes(_bytes(_manifest()))
    before = path.read_bytes()
    stat = path.stat().st_mtime_ns
    projected = scientific_input_bytes(path)
    assert path.read_bytes() == before and path.stat().st_mtime_ns == stat
    assert "paper_selected" not in json.loads(projected)["figures"][0]["metadata"]


def test_source_and_copy_specialist_digests_match_after_only_paper_selection_changes(tmp_path):
    source, copied = tmp_path / "source", tmp_path / "copy"
    payload = _manifest()
    for root in (source, copied):
        path = root / MANIFEST
        path.parent.mkdir(parents=True)
        path.write_bytes(_bytes(payload))
    payload["figures"][0]["metadata"]["paper_selected"] = False
    (copied / MANIFEST).write_bytes(_bytes(payload))
    spec = next(item for item in selected_specialists("machine_learning", "algorithm_benchmark") if item.id == "domain-validation")
    style = {"family": "machine_learning", "study_archetype": "algorithm_benchmark", "target_venue": "ICLR"}
    options = {"run_experiment": False, "non_experiment_evidence_mode": "synthetic_preview"}
    assert specialist_input_digest(source, style, spec, options) == specialist_input_digest(copied, style, spec, options)


@pytest.mark.parametrize("relative", ["PLANNED_RESULT_MANIFEST.json", "fixtures/PLANNED_RESULT_MANIFEST.json",
                                     "experiments/results/simulated/PLANNED_RESULT_MANIFEST.json",
                                     "experiments/results/templates/OTHER_MANIFEST.json",
                                     "experiments/results/templates/planned_result_manifest.json",
                                     "experiments/METHOD_CONTRACT.json"])
def test_other_json_paths_keep_same_named_selection_as_input_identity(tmp_path, relative):
    first, second = _manifest(), _manifest()
    second["figures"][0]["metadata"]["paper_selected"] = False
    assert _project(tmp_path, first, relative) != _project(tmp_path, second, relative)


@pytest.mark.parametrize("schema", [4, 6, "5", True, None])
def test_other_or_untyped_schemas_do_not_silently_adopt_current_projection(tmp_path, schema):
    first, second = _manifest(), _manifest()
    first["schema"] = second["schema"] = schema
    second["figures"][0]["metadata"]["paper_selected"] = False
    assert _project(tmp_path, first) != _project(tmp_path, second)


@pytest.mark.parametrize("location", ["top", "nested_science", "figure", "nested_metadata"])
def test_same_named_key_outside_exact_figure_metadata_stays_scientific(tmp_path, location):
    first = _manifest()
    if location == "top":
        first["paper_selected"] = True
        second = copy.deepcopy(first)
        second["paper_selected"] = False
    elif location == "nested_science":
        first["method_contract"] = {"paper_selected": True}
        second = copy.deepcopy(first)
        second["method_contract"]["paper_selected"] = False
    elif location == "figure":
        first["figures"][0]["paper_selected"] = True
        second = copy.deepcopy(first)
        second["figures"][0]["paper_selected"] = False
    else:
        first["figures"][0]["metadata"]["study_parameters"] = {"paper_selected": True}
        second = copy.deepcopy(first)
        second["figures"][0]["metadata"]["study_parameters"]["paper_selected"] = False
    assert _project(tmp_path, first) != _project(tmp_path, second)


@pytest.mark.parametrize("field", ["claim", "data_path", "source_data", "source_data_hash", "metric", "direction",
                                 "methods", "scientific_question", "producer", "schema", "figure_count", "figure_id"])
def test_scientific_claim_source_schema_and_inventory_changes_still_invalidate(tmp_path, field):
    first, second = _manifest(), _manifest()
    figure, metadata = second["figures"][0], second["figures"][0]["metadata"]
    if field == "claim":
        metadata["claim_ids"] = ["C2"]
    elif field == "data_path":
        second["experiments"][0]["data_path"] = "experiments/results/simulated/changed.csv"
    elif field == "source_data":
        metadata["source_data"] = ["experiments/results/simulated/changed.csv"]
    elif field == "source_data_hash":
        metadata["source_data_sha256"]["experiments/results/simulated/main.csv"] = "b" * 64
    elif field == "metric":
        second["primary_metric"] = "auroc"
    elif field == "direction":
        second["metric_direction"] = "minimize"
    elif field == "methods":
        second["methods"] = ["Reference", "Different mechanism"]
    elif field == "scientific_question":
        metadata["scientific_question"] = "A different estimand"
    elif field == "producer":
        metadata["producer_kind"] = "model"
    elif field == "schema":
        second["schema"] = 6
    elif field == "figure_count":
        extra = copy.deepcopy(figure)
        extra["id"] = "additional-result"
        second["figures"].append(extra)
    else:
        figure["id"] = "changed-result"
    assert _project(tmp_path, first) != _project(tmp_path, second)


@pytest.mark.parametrize("defect", ["empty_id", "duplicate_id", "untyped_flag", "string_flag", "metadata_list", "empty_figures"])
def test_malformed_figure_contract_cannot_gain_selection_exclusion(tmp_path, defect):
    first = _manifest()
    if defect == "empty_id":
        first["figures"][0]["id"] = ""
    elif defect == "duplicate_id":
        first["figures"].append(copy.deepcopy(first["figures"][0]))
    elif defect == "untyped_flag":
        first["figures"][0]["metadata"]["paper_selected"] = 1
    elif defect == "string_flag":
        first["figures"][0]["metadata"]["paper_selected"] = "yes"
    elif defect == "metadata_list":
        first["figures"][0]["metadata"] = []
    else:
        first["figures"] = []
    before = copy.deepcopy(first)
    projected = json.loads(_project(tmp_path, first))
    assert projected == before


def test_original_volatile_hash_behavior_remains_unchanged(tmp_path):
    first, second = _manifest(), _manifest()
    first["simulation_manifest_sha256"] = "a" * 64
    second["simulation_manifest_sha256"] = "b" * 64
    first["updated_at"] = 1
    second["updated_at"] = 2
    assert _project(tmp_path, first) == _project(tmp_path, second)


@pytest.mark.parametrize("raw", [b'{"invalid"', b'[]', b'null'])
def test_nonobject_or_unreadable_json_is_not_a_valid_planned_manifest_projection(tmp_path, raw):
    actual = canonical_scientific_input_bytes(tmp_path / MANIFEST, raw)
    assert actual == raw


def test_non_json_source_bytes_are_preserved_exactly(tmp_path):
    raw = b"paper_selected = True\nscientific_parameter = 17\n"
    assert canonical_scientific_input_bytes(tmp_path / "experiments/src/model.py", raw) == raw
