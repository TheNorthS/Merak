"""Contract-only document assembly; no model, experiment, or workflow calls."""

import inspect

import pytest

from server.workflows.engine import WorkflowEngine
from server.workflows.experiment_depth_supplement import build_depth_supplement


@pytest.mark.parametrize(
    ("family", "research_family", "expected"),
    [
        ("machine_learning", "generic", "Dataset, Analysis Unit, and Split Protocol"),
        (
            "formal_verification",
            "generic",
            "Formal Domain, Assumptions, and Instance Protocol",
        ),
        ("external_protocol", "qualitative", "Sampling, Corpus, and Coding Protocol"),
        (
            "external_protocol",
            "clinical",
            "Population, Protocol, and Estimand Contract",
        ),
        (
            "computational_general",
            "generic",
            "Inputs, Parameters, Scenarios, and Analysis Units",
        ),
    ],
)
def test_each_domain_produces_a_complete_supplement(
    family: str,
    research_family: str,
    expected: str,
) -> None:
    document = build_depth_supplement(
        "selected idea",
        "research direction",
        {
            "claims": [{"id": "C8", "statement": "specific falsifiable claim"}],
            "mechanisms": [{"id": "M3", "name": "registered component"}],
            "falsification_conditions": ["registered failure condition"],
        },
        {
            "claim_evidence_plan": [
                {"idea_claim_id": "C8", "outcomes": ["specific endpoint"]}
            ]
        },
        {"seeds": [1, 2]},
        {"implementation_family": family, "research_family": research_family},
    )

    assert expected in document
    assert "| C8 | specific falsifiable claim | specific endpoint |" in document
    assert "| M3 | registered component |" in document
    assert "registered failure condition" in document
    assert "## Staged Execution and Resource Budget" in document
    assert document.endswith("\n")


def test_public_engine_entrypoint_delegates_to_complete_document_assembly() -> None:
    args = ("idea", "direction", {}, {}, {}, {})
    assert WorkflowEngine._build_exp_design_depth_supplement(
        *args
    ) == build_depth_supplement(*args)


def test_start_run_remains_an_instance_bound_method_without_executing_it() -> None:
    instance = WorkflowEngine()
    assert inspect.ismethod(instance._start_run)
    assert instance._start_run.__self__ is instance
    assert "self" not in inspect.signature(instance._start_run).parameters


def test_semantic_json_recursion_preserves_run_identity_but_drops_timing() -> None:
    source = {"run_id": "run-A", "nested": [{"updated_at": "today", "value": 7}]}
    assert WorkflowEngine._stable_revision_json(source) == {
        "run_id": "run-A",
        "nested": [{"value": 7}],
    }
