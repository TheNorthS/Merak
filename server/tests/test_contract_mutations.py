"""Mutation tests for load-bearing workflow contracts."""

from __future__ import annotations

import copy

import pytest

from server.contracts.entrypoints import parse_python_entrypoint
from server.contracts.implementation_evidence import ImplementationEvidencePatch
from server.contracts.writers import versioned_payload_issues
from server.services.figure_preflight import figure_preflight_findings


def _selected() -> dict:
    return {
        "schema": 2,
        "status": "accepted",
        "title": "Study",
        "problem_statement": "Problem",
        "hypothesis": "Hypothesis",
        "claims": [{"id": "C1", "statement": "Claim"}],
        "mechanisms": [{"id": "M1", "name": "Mechanism"}],
        "falsification_conditions": ["No effect"],
        "publication": {"title": "Study"},
    }


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        (lambda value: value.update(schema=1), "unsupported schema; current schema=2"),
        (lambda value: value.pop("hypothesis"), "hypothesis is required"),
        (lambda value: value.update(claims=[]), "claims must be a non-empty list"),
        (lambda value: value.pop("publication"), "publication object is required"),
    ],
)
def test_selected_idea_mutations_fail_at_owner_contract(mutation, expected: str) -> None:
    payload = copy.deepcopy(_selected())
    mutation(payload)

    assert expected in versioned_payload_issues("selected_idea", payload)


@pytest.mark.parametrize("entrypoint", [
    "experiments/src/train.py:main()",
    "experiments/src/train.py::main",
    "/absolute/train.py:main",
    "experiments/../train.py:main",
])
def test_entrypoint_mutations_fail_before_stage_execution(entrypoint: str) -> None:
    with pytest.raises(ValueError):
        parse_python_entrypoint(entrypoint)


def test_evidence_alias_without_typed_selector_is_not_promoted() -> None:
    with pytest.raises(ValueError, match="typed selector"):
        ImplementationEvidencePatch.parse({
            "id": "I1",
            "description": "Route",
            "evidence": [{
                "path": "experiments/src/train.py",
                "observable_outputs": ["metrics.json"],
            }],
        })


@pytest.mark.parametrize("reference", [
    {"path": "experiments/src/train.py", "symbols": "run_training"},
    {"path": "experiments/src/train.py", "symbols": [1]},
    {"path": "experiments/src/train.py", "symbols": [""]},
    {"path": "experiments/src/train.py", "symbols": 7},
    {"path": "experiments/src/train.py", "config_keys": ["execution.seeds"]},
    {"path": "C:/outside.py", "symbols": ["run"]},
    {"path": "C:outside.py", "symbols": ["run"]},
])
def test_malformed_evidence_is_rejected_before_canonical_write(tmp_path, reference):
    from server.contracts.writers import write_versioned_artifact

    target = tmp_path / "experiments/IMPLEMENTATION_EVIDENCE_PATCH.json"
    target.parent.mkdir()
    original = b'{"previous_reviewed_content":true}'
    target.write_bytes(original)
    payload = {"schema": 1, "checks": [{
        "check_id": "I1", "description": "Runtime evidence", "evidence": [reference],
    }]}
    with pytest.raises(ValueError):
        write_versioned_artifact(tmp_path, "implementation_evidence_patch", payload)
    assert target.read_bytes() == original


def test_figure_mapping_mutation_routes_to_upstream_owner() -> None:
    findings = figure_preflight_findings({
        "id": "method_architecture",
        "kind": "figure",
        "producer_kind": "model",
        "scientific_scene": {"objects": [{"id": "method"}]},
        "architecture_blueprint": {"components": []},
    })

    assert findings[0]["owner_node"] == "exp-design"
    assert findings[0]["validator"] == "figure-source-mapping-v1"


def test_figure_complexity_mutation_routes_to_layout_owner() -> None:
    findings = figure_preflight_findings({
        "id": "evaluation_design",
        "kind": "figure",
        "producer_kind": "model",
        "scientific_scene": {"objects": [{"id": str(index)} for index in range(12)]},
        "scene_contract": {"maximum_primary_nodes": 8},
        "layout_plan": {"split_required": False},
    })

    assert findings[0]["owner_node"] == "figure"
    assert findings[0]["validator"] == "figure-print-contract-v1"
