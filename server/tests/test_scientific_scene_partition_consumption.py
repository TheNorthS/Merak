"""Pure planner-to-compiler regressions; no native render or model invocation."""

from __future__ import annotations

import copy
import json

import pytest

from server.services.figure_scientific_alignment import _projected_relation_issues
from server.services.figurespec_layout_policy import figurespec_layout_issues_payload
from server.services.scientific_scene import plan_scientific_layout
from server.services.scientific_scene_figure import compile_scientific_scene_figure
from server.services.scientific_scene_partitions import panel_budget_issues


def _asset() -> dict:
    identities = [
        ("segment", "input", "One source-training EEG segment"),
        ("subsets", "operation", "Overlapping channel subsets A and B"),
        ("views", "operation", "Low/high spectral views"),
        ("encoder", "operation", "Shared temporal encoder"),
        ("factors", "operation", "Shared and private factors"),
        ("agreement", "operation", "Shared-only paired agreement"),
        ("covariance", "operation", "Shared-private covariance penalty"),
        ("readout", "output", "Frozen-encoder affine readout"),
        ("guardrail", "operation", "Dataset-held-out guardrail"),
    ]
    scene = {
        "schema": 1,
        "objects": [{
            "id": identity, "kind": kind, "label": label,
            "source_path": "experiments/EXPERIMENT_PLAN.md",
            "source_reference": f"Registered protocol/{identity}",
            "source_sha256": "a" * 64,
        } for identity, kind, label in identities],
        "relations": [
            *[{"from": source, "to": target, "kind": "data"} for source, target in (
                ("segment", "subsets"), ("subsets", "views"), ("views", "encoder"),
                ("encoder", "factors"), ("factors", "agreement"),
                ("factors", "covariance"), ("factors", "readout"),
            )],
            {"from": "guardrail", "to": "segment", "kind": "constraint"},
            {"from": "guardrail", "to": "readout", "kind": "constraint"},
        ],
    }
    budget = {
        "maximum_primary_objects": 8, "maximum_primary_branches": 2,
        "maximum_visible_labels": 12, "minimum_placed_font_pt": 8.0,
    }
    return {
        "id": "method_architecture", "scientific_role": "method",
        "narrative_level": "method_overview",
        "scientific_question": "How do named objectives interact under dataset-held-out guardrails?",
        "publication_labels": [{"display_text": "Dataset-held-out transfer protocol"}],
        "scene_contract": {"contribution_type": "objective_mechanism", "complexity_budget": budget},
        "scientific_scene": scene,
        "layout_plan": plan_scientific_layout(scene, complexity_budget=budget),
    }


def test_object_and_branch_overflow_partition_together_preserves_guardrail() -> None:
    asset = _asset()
    before = copy.deepcopy(asset["scientific_scene"])
    layout = asset["layout_plan"]
    assert [len(panel) for panel in layout["panels"]] == [7, 2]
    by_id = {item["id"]: item for item in before["objects"]}
    panels = [[by_id[identity] for identity in panel] for panel in layout["panels"]]
    assert panel_budget_issues(panels, before["relations"], layout["complexity_budget"]) == []
    assert {"readout", "guardrail"} == set(layout["panels"][1])
    assert before == asset["scientific_scene"]
    assert {tuple((edge["from"], edge["to"], edge["kind"])) for edge in layout["cross_panel_relations"]} == {
        ("factors", "readout", "data"), ("guardrail", "segment", "constraint"),
    }


def test_declared_partition_compiles_all_nine_objects_and_exact_edges(tmp_path) -> None:
    asset = _asset()
    before = copy.deepcopy(asset)
    compiled = compile_scientific_scene_figure(asset)
    assert figurespec_layout_issues_payload(compiled.spec) == []
    assert {node["id"] for node in compiled.spec["nodes"]} == {
        item["id"] for item in asset["scientific_scene"]["objects"]
    }
    assert len(compiled.spec["nodes"]) == 9
    assert len(compiled.spec["edges"]) == 9
    assert [len(panel["object_ids"]) for panel in compiled.spec["scientific_panels"]] == [7, 2]
    assert [group["node_ids"] for group in compiled.spec["groups"]] == [
        panel["object_ids"] for panel in compiled.spec["scientific_panels"]
    ]
    nodes = {node["id"]: node for node in compiled.spec["nodes"]}
    assert max(node["height"] for node in nodes.values()) <= 110
    assert nodes["readout"]["y"] == nodes["factors"]["y"]
    left, right = compiled.spec["scientific_panels"]
    assert max(nodes[identity]["x"] + nodes[identity]["width"] / 2 for identity in left["object_ids"]) < min(
        nodes[identity]["x"] - nodes[identity]["width"] / 2 for identity in right["object_ids"]
    )
    assert all(node["font_size"] * 468 / compiled.spec["canvas"]["width"] >= 8 for node in compiled.spec["nodes"])
    assert {item["element_id"] for item in compiled.element_mappings} == {
        item["id"] for item in asset["scientific_scene"]["objects"]
    }
    assert all(item["source_sha256"] == "a" * 64 for item in compiled.element_mappings)
    assert all(item["source_reference"].startswith("Registered protocol/") for item in compiled.element_mappings)
    source = tmp_path / "method.json"
    source.write_text(json.dumps(compiled.spec), encoding="utf-8")
    assert _projected_relation_issues("method_architecture", asset, source) == []
    assert asset == before


def test_partition_does_not_accept_unbounded_single_object_labels() -> None:
    asset = _asset()
    asset["scientific_scene"]["objects"][0]["subitems"] = [
        {"id": f"condition_{index}", "label": f"Condition {index}"} for index in range(13)
    ]
    with pytest.raises(ValueError, match="authored bounded partition"):
        plan_scientific_layout(asset["scientific_scene"], complexity_budget=asset["scene_contract"]["complexity_budget"])
