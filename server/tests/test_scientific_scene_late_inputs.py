"""Independent inputs joining a later stage must not cross unrelated stages."""

from copy import deepcopy

import pytest

from server.services.figurespec_layout_policy import figurespec_layout_issues_payload
from server.services.scientific_scene_figure import compile_scientific_scene_figure
from server.services.scientific_scene_labels import projected_public_labels


def late_input_scene() -> dict:
    labels = [
        ("recordings", "input", "Lawfully sourced subject/session EEG with montage and license identity; pending"),
        ("annotations", "input", "Independently timed focal and global episodes and blinded relevant-electrode annotation; pending"),
        ("split", "input", "Subject-disjoint manifest with audited pretraining exclusion; pending"),
        ("objectives", "operation", "Matched structured EMA versus waveform and target/alignment ablations"),
        ("intervention", "operation", "Paired independently selected event versus matched non-event deletion"),
        ("contrast", "output", "Subject-cluster three-factor interaction and disaggregated transfer"),
    ]
    return {
        "id": "method_architecture", "scientific_role": "method",
        "scene_contract": {"complexity_budget": {"maximum_primary_objects": 8}},
        "scientific_scene": {"schema": 1, "objects": [
            {"id": key, "kind": kind, "label": label, "source_path": "experiments/METHOD_CONTRACT.json"}
            for key, kind, label in labels
        ], "relations": [{"from": source, "to": target, "kind": "data"} for source, target in [
            ("recordings", "split"), ("split", "objectives"), ("annotations", "intervention"),
            ("objectives", "intervention"), ("intervention", "contrast"),
        ]]},
    }


@pytest.mark.parametrize("reverse_objects", [False, True])
def test_late_independent_input_preserves_full_labels_and_relations(reverse_objects):
    asset = late_input_scene()
    if reverse_objects:
        asset["scientific_scene"]["objects"].reverse()
    original = deepcopy(asset)
    result = compile_scientific_scene_figure(asset)
    assert asset == original
    assert figurespec_layout_issues_payload(result.spec) == []
    assert {node["id"] for node in result.spec["nodes"]} == {
        obj["id"] for obj in asset["scientific_scene"]["objects"]
    }
    assert {(edge["from"], edge["to"], edge["scientific_kind"]) for edge in result.spec["edges"]} == {
        (edge["from"], edge["to"], edge["kind"]) for edge in asset["scientific_scene"]["relations"]
    }
    labels = projected_public_labels(asset)
    assert {item["source_label"] for item in result.element_mappings} == {
        obj["label"] for obj in original["scientific_scene"]["objects"]
    }
    assert labels["annotations"] == (
        "Independently timed focal and global episodes and blinded relevant-electrode annotation"
    )
    for node in result.spec["nodes"]:
        assert " ".join(filter(None, [node["label"], node.get("sublabel")])) == labels[node["id"]]
        assert node["font_size"] * 468 / result.spec["canvas"]["width"] >= 8


def test_public_projection_retains_science_while_keeping_contract_ids_in_provenance():
    from server.services.scientific_scene_labels import public_scene_text

    asset = {"claim_ids": ["C1", "C2"], "method_brief": {
        "mechanism_nodes": [{"id": "M1"}, {"id": "M3"}],
    }}
    obj = {"id": "objectives", "kind": "operation", "label": "M1/M3 matched objective comparison"}
    assert public_scene_text(asset, obj, {}) == "matched objective comparison"
    obj["label"] = "C1 interaction and C2 transfer"
    assert public_scene_text(asset, obj, {}) == "interaction and transfer"
    obj["label"] = "M4 independent control"
    assert public_scene_text(asset, obj, {}) == "M4 independent control"
