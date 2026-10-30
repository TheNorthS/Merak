"""Deterministic figure labels follow the same scoped scene as their producer."""

import json
from copy import deepcopy

import pytest

from server.services.figure_artifacts import figure_artifact_registry
from server.services.figure_scientific_alignment import candidate_scientific_alignment_issues, _projected_relation_issues
from server.services.scientific_scene_figure import compile_scientific_scene_figure
from server.tests.test_deterministic_architecture_integration import _asset


def test_method_figure_does_not_require_a_downstream_test_label_without_scene_object(tmp_path):
    asset = _asset()
    asset["publication_labels"].append({"schema": 1, "id": "method.mechanism.3", "kind": "concept", "display_text": "Shift-specific mechanism test"})
    asset["method_brief"] = {"mechanism_nodes": [
        {"id": "M1", "name": "Patch encoder"}, {"id": "M3", "name": "Shift-specific mechanism test"},
    ]}
    (tmp_path / "ideas").mkdir()
    (tmp_path / "ideas/SELECTED_IDEA.json").write_text(json.dumps({
        "title": "Patch encoder", "mechanisms": [
            {"id": "M1", "publication_name": "Patch encoder"},
            {"id": "M3", "publication_name": "Shift-specific mechanism test"},
        ],
    }))
    (tmp_path / "figures").mkdir()
    (tmp_path / "figures/FIGURE_SPECS.json").write_text(json.dumps({"figures": [asset]}))
    compiled = compile_scientific_scene_figure(asset)
    source = tmp_path / "figures/method.json"
    source.write_text(json.dumps(compiled.spec))
    metadata = {**asset, "architecture_compiler": compiled.profile, "element_mappings": compiled.element_mappings}
    issues = candidate_scientific_alignment_issues(figure_artifact_registry, tmp_path, metadata, source)
    assert not any("Shift-specific mechanism test" in item for item in issues), issues


@pytest.mark.parametrize("mutation", ["label", "object", "relation"])
def test_projected_science_cannot_be_relabelled_removed_or_rewired(tmp_path, mutation):
    asset = _asset()
    payload = deepcopy(compile_scientific_scene_figure(asset).spec)
    if mutation == "label": payload["nodes"][1]["label"] = "Unrelated intervention"
    elif mutation == "object": payload["nodes"].pop()
    else: payload["edges"].pop()
    source = tmp_path / "method.json"
    source.write_text(json.dumps(payload))
    assert _projected_relation_issues("method_architecture", asset, source)
