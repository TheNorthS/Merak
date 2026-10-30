"""Long source labels remain readable without changing scientific objects or relations."""

from copy import deepcopy
import json

from server.services.scientific_scene_figure import compile_scientific_scene_figure
from server.services.figurespec_layout_policy import figurespec_layout_issues_payload
from server.services.figure_scientific_alignment import _projected_relation_issues
from server.services.scientific_scene_labels import projected_public_labels


def long_scene():
    labels = [
        ("eligible_eeg", "input", "licensed labeled same-acquisition EEG windows with subject/session and electrode identity; acquisition pending"),
        ("split_and_masks", "operation", "subject-isolated folds and paired fixed grouped channel-mask bank"),
        ("identity_intervention", "operation", "M1 correct versus disabled electrode identity under fixed masks"),
        ("topology_control", "operation", "M2 grouped versus independent masks and removal with difficulty diagnostics"),
        ("paired_endpoint", "output", "C1 subject-paired full-minus-missing score difference and full-channel noninferiority"),
        ("interaction_endpoint", "output", "C2 topology interaction, not evidence of identity necessity"),
    ]
    return {"id": "method_architecture", "scientific_role": "method", "narrative_level": "method_overview",
        "producer_kind": "deterministic", "production_strategy": "deterministic_architecture",
        "claim_ids": ["C1", "C2"], "method_brief": {"mechanism_nodes": [
            {"id": "M1", "name": "Electrode identity under fixed structured masks"},
            {"id": "M2", "name": "Missingness-topology control"},
        ]}, "scene_contract": {"complexity_budget": {"maximum_primary_objects": 8}},
        "scientific_scene": {"schema": 1,
            "objects": [{"id": key, "kind": kind, "label": text, "source_path": "experiments/METHOD_CONTRACT.json"}
                        for key, kind, text in labels],
            "relations": [{"from": a, "to": b, "kind": kind} for a, b, kind in [
                ("eligible_eeg", "split_and_masks", "data"),
                ("split_and_masks", "identity_intervention", "data"),
                ("split_and_masks", "topology_control", "data"),
                ("identity_intervention", "paired_endpoint", "data"),
                ("topology_control", "interaction_endpoint", "data"),
                ("topology_control", "paired_endpoint", "control"),
            ]]}}


def test_real_shape_long_labels_compile_without_altering_frozen_scene(tmp_path):
    asset = long_scene()
    original = deepcopy(asset)
    result = compile_scientific_scene_figure(asset)
    assert asset == original
    assert figurespec_layout_issues_payload(result.spec) == []
    assert len(result.spec["nodes"]) == len(result.spec["edges"]) == 6
    assert {node["id"] for node in result.spec["nodes"]} == {obj["id"] for obj in asset["scientific_scene"]["objects"]}
    assert {item["source_label"] for item in result.element_mappings} == {item["label"] for item in asset["scientific_scene"]["objects"]}
    first = result.spec["nodes"][0]
    assert first["label"] + " " + first["sublabel"] == original["scientific_scene"]["objects"][0]["label"].split(";")[0]
    assert projected_public_labels(asset)["identity_intervention"] == "Electrode identity under fixed structured masks"
    source = tmp_path / "method.json"
    source.write_text(json.dumps(result.spec), encoding="utf-8")
    assert _projected_relation_issues("method_architecture", asset, source) == []
    result.spec["nodes"][0]["sublabel"] = "different scientific meaning"
    source.write_text(json.dumps(result.spec), encoding="utf-8")
    assert any("labels differ" in issue for issue in _projected_relation_issues("method_architecture", asset, source))


def test_unbound_identifier_is_not_invented_as_a_public_mechanism():
    asset = long_scene()
    asset["method_brief"]["mechanism_nodes"] = []
    assert projected_public_labels(asset)["identity_intervention"].startswith("M1 ")
