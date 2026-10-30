"""Pure source-to-blueprint relation checks, without rendering or model calls."""

from __future__ import annotations

from typing import Any
import xml.etree.ElementTree as ET

import pytest

from server.services.model_svg_relation_preflight import method_relation_preflight_issues
from server.services.model_svg_relation_preflight import method_relation_contract


def _spec(
    objects: list[tuple[str, str, str]], relations: list[tuple[str, str, str]],
    *, question: str = "How does the input reach the method and final state?",
) -> dict[str, Any]:
    return {
        "scientific_role": "method",
        "scientific_question": question,
        "scene_contract": {"contribution_type": "system_architecture"},
        "scientific_scene": {
            "schema": 1,
            "objects": [
                {"id": identity, "kind": kind, "label": label,
                 "source_path": "method.md"}
                for identity, kind, label in objects
            ],
            "relations": [
                {"from": source, "to": target, "kind": kind}
                for source, target, kind in relations
            ],
        },
    }


def _blueprint(
    bindings: dict[str, str], flows: list[tuple[str, str, str]],
) -> dict[str, Any]:
    return {
        "primitives": [
            {"id": group, "scientific_object_id": scene_id}
            for scene_id, group in bindings.items()
        ],
        "flows": [
            {"from": source, "to": target, "kind": kind}
            for source, target, kind in flows
        ],
    }


def test_missing_input_to_method_relation_is_blocked() -> None:
    spec = _spec([
        ("observations", "input", "Observed material"),
        ("transformation", "operation", "Focal transformation"),
        ("final_state", "output", "Final state"),
    ], [
        ("observations", "transformation", "data"),
        ("transformation", "final_state", "causal"),
    ])
    blueprint = _blueprint({
        "observations": "input", "transformation": "method",
        "final_state": "output",
    }, [("method", "output", "causal")])

    issues = method_relation_preflight_issues(spec, blueprint)

    assert any("observations->transformation (data)" in item for item in issues)
    assert any("input->method" in item for item in issues)


def test_control_cannot_be_promoted_to_active_data_flow() -> None:
    spec = _spec([
        ("guard", "input", "Eligibility guard"),
        ("process", "operation", "Method process"),
        ("result", "output", "Final state"),
    ], [
        ("guard", "process", "constraint"),
        ("process", "result", "causal"),
    ], question="How does eligibility guard constrain the method process?")
    blueprint = _blueprint({
        "guard": "audit", "process": "method", "result": "output",
    }, [("audit", "method", "data"), ("method", "output", "causal")])

    issues = method_relation_preflight_issues(spec, blueprint)

    assert any("guard->process (constraint)" in item for item in issues)
    assert any("cannot be drawn as active data/causal" in item for item in issues)


def test_missing_terminal_output_relation_is_blocked() -> None:
    spec = _spec([
        ("material", "input", "Input material"),
        ("method", "operation", "Method process"),
        ("terminal", "output", "Final state"),
    ], [
        ("material", "method", "data"),
        ("method", "terminal", "causal"),
    ])
    blueprint = _blueprint({
        "material": "input", "method": "process", "terminal": "output",
    }, [("input", "process", "data")])

    issues = method_relation_preflight_issues(spec, blueprint)

    assert any("method->terminal (causal)" in item for item in issues)
    assert any("process->output" in item for item in issues)


@pytest.mark.parametrize(("objects", "relations", "flows"), [
    (
        [("specimen", "input", "Eligible specimen"),
         ("intervention", "operation", "Controlled intervention"),
         ("cell_state", "output", "Changed cell state")],
        [("specimen", "intervention", "data"),
         ("intervention", "cell_state", "causal")],
        [("specimen", "intervention", "data"),
         ("intervention", "cell_state", "causal")],
    ),
    (
        [("request", "input", "Incoming request"),
         ("scheduler", "operation", "Work scheduler"),
         ("response", "output", "Returned response")],
        [("request", "scheduler", "data"),
         ("scheduler", "response", "data")],
        [("request", "scheduler", "data"),
         ("scheduler", "response", "data")],
    ),
    (
        [("assumption", "input", "Declared assumption"),
         ("lemma", "operation", "Derived lemma"),
         ("theorem", "output", "Proved theorem")],
        [("assumption", "lemma", "logical"),
         ("lemma", "theorem", "logical")],
        [("assumption", "lemma", "logical"),
         ("lemma", "theorem", "logical")],
    ),
])
def test_source_bound_cross_domain_relations_pass(
    objects: list[tuple[str, str, str]], relations: list[tuple[str, str, str]],
    flows: list[tuple[str, str, str]],
) -> None:
    spec = _spec(objects, relations)
    blueprint = _blueprint(
        {identity: identity for identity, _, _ in objects}, flows,
    )

    assert method_relation_preflight_issues(spec, blueprint) == []


def test_same_source_file_does_not_infer_scientific_identity() -> None:
    spec = _spec([
        ("source", "input", "Input material"),
        ("method", "operation", "Method process"),
    ], [("source", "method", "data")])
    blueprint = {"primitives": [{"id": "a"}, {"id": "b"}], "flows": [
        {"from": "a", "to": "b", "kind": "data"},
    ]}

    issues = method_relation_preflight_issues(spec, blueprint)

    assert any("no source-scene primary binding" in item for item in issues)


def test_authored_scene_without_relations_reports_source_defect() -> None:
    spec = _spec([
        ("input", "input", "Input material"),
        ("method", "operation", "Method process"),
    ], [])

    issues = method_relation_preflight_issues(spec, _blueprint({}, []))

    assert any("repair METHOD_CONTRACT.scientific_scene" in item for item in issues)


def test_svg_connector_metadata_cannot_contradict_blueprint() -> None:
    spec = _spec([
        ("source", "input", "Input material"),
        ("method", "operation", "Method process"),
    ], [("source", "method", "data")])
    blueprint = _blueprint(
        {"source": "a", "method": "b"}, [("a", "b", "data")],
    )
    root = ET.fromstring(
        '<svg><path id="wrong" data-from="b" data-to="a"/></svg>'
    )

    issues = method_relation_preflight_issues(spec, blueprint, root)

    assert any("SVG connector 'wrong'" in item for item in issues)


def test_unbound_disconnected_primary_mechanism_cannot_be_silently_omitted() -> None:
    spec = _spec([
        ("first_input", "input", "First material"),
        ("first_process", "operation", "First transformation"),
        ("second_input", "input", "Second material"),
        ("second_process", "operation", "Second transformation"),
    ], [
        ("first_input", "first_process", "data"),
        ("second_input", "second_process", "data"),
    ])
    blueprint = _blueprint(
        {"first_input": "input", "first_process": "method"},
        [("input", "method", "data")],
    )

    issues = method_relation_preflight_issues(spec, blueprint)

    assert any("second_process" in item and "bindings" in item for item in issues)


def test_bound_objects_cannot_gain_unwritten_scientific_relation() -> None:
    spec = _spec([
        ("source", "input", "Observed material"),
        ("first", "operation", "First process"),
        ("second", "operation", "Second process"),
    ], [("source", "first", "data"), ("source", "second", "data")])
    blueprint = _blueprint({"source": "a", "first": "b", "second": "c"}, [
        ("a", "b", "data"), ("a", "c", "data"), ("b", "c", "causal"),
    ])

    issues = method_relation_preflight_issues(spec, blueprint)

    assert any("unsupported scientific_scene relation first->second" in item for item in issues)


def test_coarse_method_overview_does_not_invent_loss_or_audit_internals() -> None:
    spec = _spec([
        ("observations", "input", "Provenance-locked observations"),
        ("paired_objectives", "operation", "Paired masked self-supervision"),
        ("attribution", "operation", "Leakage-aware transfer audit"),
        ("external_outcome", "output", "Held-out transfer outcome"),
    ], [
        ("observations", "paired_objectives", "data"),
        ("observations", "attribution", "control"),
        ("paired_objectives", "external_outcome", "data"),
        ("attribution", "external_outcome", "control"),
    ], question="How does paired masked self-supervision transform observations?")
    blueprint = _blueprint(
        {"observations": "input", "paired_objectives": "method"},
        [("input", "method", "data")],
    )

    contract = method_relation_contract(spec)

    assert {item["id"] for item in contract["objects"]} == {
        "observations", "paired_objectives",
    }
    assert "attribution" in contract["excluded"]
    assert method_relation_preflight_issues(spec, blueprint) == []


def test_preparation_contract_uses_same_relation_kind_policy_as_gate() -> None:
    spec = _spec([
        ("eligibility", "input", "Eligibility guard"),
        ("process", "operation", "Controlled process"),
    ], [("eligibility", "process", "constraint")], question="How does eligibility constrain process?")

    contract = method_relation_contract(spec)

    assert contract["flow_kinds_by_source_relation"]["constraint"] == ["constraint", "control"]
    assert "source_path alone never identifies" in contract["binding_rule"]


def test_structural_containment_is_not_guessed_as_active_data_flow() -> None:
    spec = _spec([
        ("method", "operation", "Combined method"),
        ("component", "operation", "Declared component"),
    ], [("method", "component", "containment")])
    blueprint = _blueprint(
        {"method": "method", "component": "component"},
        [("method", "component", "data")],
    )

    issues = method_relation_preflight_issues(spec, blueprint)

    assert any("declares containment, not a directed blueprint flow" in item for item in issues)
