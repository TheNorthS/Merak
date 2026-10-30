"""Pure regressions for the source-scoped deterministic method compiler."""

from __future__ import annotations

import pytest

from server.services.figure_semantic_projection import project_figure_semantics
from server.services.figurespec_layout_policy import figurespec_layout_issues_payload
from server.services.scientific_scene_figure import (
    ScientificSceneFigureError,
    compile_scientific_scene_figure,
)


def _eeg_asset() -> dict:
    source = "experiments/EXPERIMENT_PLAN.md"
    idea = "ideas/SELECTED_IDEA.json"
    return {
        "id": "method_architecture", "scientific_role": "method",
        "scientific_question": "How do named objectives cooperate under matched controls?",
        "publication_labels": [
            {"id": "method.mechanism.1", "display_text": "Montage-conditioned tokenization"},
            {"id": "method.mechanism.2", "display_text": "Cross-scale latent consistency"},
            {"id": "method.mechanism.3", "display_text": "Matched external mechanism test"},
        ],
        "scene_contract": {
            "contribution_type": "objective_mechanism",
            "complexity_budget": {"maximum_primary_objects": 8},
        },
        "method_brief": {
            "publication": {"method_name": "Montage-conditioned representation"},
            "mechanism_nodes": [
                {"id": "M1", "name": "Montage-conditioned tokenization"},
                {"id": "M2", "name": "Cross-scale latent consistency"},
                {"id": "M3", "name": "Matched external mechanism test"},
            ],
        },
        "scientific_scene": {
            "schema": 1,
            "objects": [
                {"id": "eeg_units", "kind": "input", "label": "Audited variable-montage EEG units", "source_path": source},
                {"id": "m1_tokenizer", "kind": "operation", "label": "M1 montage-conditioned tokenizer", "source_path": idea},
                {"id": "m2_objective", "kind": "operation", "label": "M2 paired cross-scale latent consistency", "source_path": idea},
                {"id": "m3_audit", "kind": "operation", "label": "M3 matched split and budget audit", "source_path": source},
                {"id": "transfer_outcomes", "kind": "output", "label": "Held-out unit-level transfer outcomes", "source_path": source},
            ],
            "relations": [
                {"from": "eeg_units", "to": "m1_tokenizer", "kind": "data"},
                {"from": "m1_tokenizer", "to": "m2_objective", "kind": "data"},
                {"from": "m3_audit", "to": "m1_tokenizer", "kind": "constraint"},
                {"from": "m2_objective", "to": "transfer_outcomes", "kind": "data"},
                {"from": "m3_audit", "to": "transfer_outcomes", "kind": "constraint"},
            ],
        },
    }


def test_eeg_method_projection_is_legible_and_keeps_every_scoped_relation() -> None:
    asset = _eeg_asset()
    projected = project_figure_semantics(asset)
    compilation = compile_scientific_scene_figure(asset)
    spec = compilation.spec
    assert figurespec_layout_issues_payload(spec) == []
    assert {node["id"] for node in spec["nodes"]} == {
        item["id"] for item in projected["entities_states_transformations"]
    }
    assert {(edge["from"], edge["to"]) for edge in spec["edges"]} == {
        (edge["from"], edge["to"]) for edge in projected["relations"]
    }
    assert "transfer_outcomes" in compilation.profile["excluded_component_ids"]
    assert {item["element_id"] for item in compilation.element_mappings} == {
        node["id"] for node in spec["nodes"]
    }
    audit = next(node for node in spec["nodes"] if node["id"] == "m3_audit")
    assert audit["label"] == "Matched external mechanism test"
    assert not any(node.get("sublabel") for node in spec["nodes"])
    assert audit["visual_kind"] == "audit"


def test_other_domain_uses_authored_nodes_without_eeg_template() -> None:
    asset = {
        "scientific_role": "method",
        "scientific_question": "How does specimen preparation lead to the assay readout?",
        "scene_contract": {"contribution_type": "clinical_biological_mechanism"},
        "scientific_scene": {
            "schema": 1,
            "objects": [
                {"id": "specimen", "kind": "sample", "label": "Biopsy specimen", "source_path": "experiments/METHOD_CONTRACT.json"},
                {"id": "stain", "kind": "operation", "label": "Marker-specific staining", "source_path": "experiments/METHOD_CONTRACT.json"},
                {"id": "readout", "kind": "output", "label": "Cellular marker readout", "source_path": "experiments/METHOD_CONTRACT.json"},
            ],
            "relations": [
                {"from": "specimen", "to": "stain", "kind": "data"},
                {"from": "stain", "to": "readout", "kind": "causal"},
            ],
        },
    }
    compilation = compile_scientific_scene_figure(asset)
    assert figurespec_layout_issues_payload(compilation.spec) == []
    assert [node["id"] for node in compilation.spec["nodes"]] == [
        "specimen", "stain", "readout",
    ]
    assert all(mapping["source_path"] == "experiments/METHOD_CONTRACT.json"
               for mapping in compilation.element_mappings)


def test_invalid_scene_fails_at_source_owner_boundary() -> None:
    asset = _eeg_asset()
    asset["scientific_scene"]["objects"][1]["id"] = "eeg_units"
    with pytest.raises(ScientificSceneFigureError, match="unique id"):
        compile_scientific_scene_figure(asset)


def test_oversize_scene_requests_split_instead_of_dropping_nodes() -> None:
    asset = _eeg_asset()
    asset["scene_contract"]["complexity_budget"]["maximum_primary_objects"] = 2
    with pytest.raises(ScientificSceneFigureError, match="split the authored figure portfolio"):
        compile_scientific_scene_figure(asset)
