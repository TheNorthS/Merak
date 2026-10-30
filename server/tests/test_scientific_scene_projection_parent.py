"""Subtract evaluation leaves without deleting their still-operative method parent."""

from __future__ import annotations

import copy

import pytest

from server.services.figure_semantic_projection import project_figure_semantics
from server.services.figurespec_layout_policy import figurespec_layout_issues_payload
from server.services.scientific_scene_figure import ScientificSceneFigureError, compile_scientific_scene_figure


def _asset() -> dict:
    labels = ("Channel-subset shared structure", "Frequency-view shared structure",
              "Shared-private factorization", "Dataset-held-out transfer protocol")
    objects = [{"id": "planned_method", "kind": "operation", "label": "CSFS",
                "source_path": "ideas/SELECTED_IDEA.json", "source_reference": "publication/method_name"}]
    objects.extend({"id": f"declared_mechanism_{index}", "kind": "operation", "label": label,
                    "source_path": "ideas/SELECTED_IDEA.json", "source_reference": f"mechanisms/{index - 1}/publication_name"}
                   for index, label in enumerate(labels, 1))
    return {
        "id": "method_architecture", "scientific_role": "method", "narrative_level": "method_overview",
        "scientific_question": "How do the proposed objectives interact, conflict, or cooperate?",
        "intended_comparison": "Shared computation and named objective branches",
        "publication_labels": [{"display_text": label} for label in labels],
        "scene_contract": {"contribution_type": "objective_mechanism"},
        "scientific_scene": {"schema": 1, "objects": objects,
                             "relations": [{"from": "planned_method", "to": obj["id"], "kind": "containment"}
                                           for obj in objects[1:]]},
    }


def test_method_parent_keeps_remaining_authored_children_when_evaluation_leaf_is_subtracted():
    asset = _asset()
    original = copy.deepcopy(asset)
    projection = project_figure_semantics(asset)
    assert {item["id"] for item in projection["entities_states_transformations"]} == {
        "planned_method", "declared_mechanism_1", "declared_mechanism_2", "declared_mechanism_3",
    }
    assert "planned_method" in projection["presentation_roles"]["primary"]
    assert set(projection["excluded"]) == {"declared_mechanism_4"}
    assert projection["relations"] == original["scientific_scene"]["relations"][:3]
    compilation = compile_scientific_scene_figure(asset)
    assert figurespec_layout_issues_payload(compilation.spec) == []
    assert len(compilation.spec["nodes"]) == 4 and len(compilation.spec["edges"]) == 3
    assert {(edge["from"], edge["to"], edge["scientific_kind"]) for edge in compilation.spec["edges"]} == {
        (item["from"], item["to"], item["kind"]) for item in projection["relations"]
    }
    assert asset == original


@pytest.mark.parametrize("relation_kind", ["data", "causal", "logical", "shared"])
def test_retained_method_branch_does_not_become_an_incidental_interface(relation_kind):
    asset = _asset()
    for relation in asset["scientific_scene"]["relations"]:
        relation["kind"] = relation_kind
    projection = project_figure_semantics(asset)
    assert "planned_method" not in projection["excluded"]
    assert len(projection["relations"]) == 3


def test_all_evaluation_scene_still_fails_instead_of_inventing_method_relations():
    asset = _asset()
    asset["scientific_scene"]["objects"] = [
        {"id": "audit", "kind": "operation", "label": "Held-out evaluation audit", "source_path": "evaluation.py"},
        {"id": "endpoint", "kind": "output", "label": "Registered decision endpoint", "source_path": "evaluation.py"},
    ]
    asset["scientific_scene"]["relations"] = [{"from": "audit", "to": "endpoint", "kind": "data"}]
    with pytest.raises(ScientificSceneFigureError, match="at least two source objects and one authored relation"):
        compile_scientific_scene_figure(asset)
