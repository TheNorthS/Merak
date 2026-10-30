"""Seed declarations follow one contract at every deterministic run boundary."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from server.services.experiment_implementation_build import (
    experiment_implementation_build_service,
)
from server.services.risk_stage_exp_design import _rule_2
from server.services.run_spec import execution_seeds, run_spec_seed_groups
from server.tests.test_experiment_implementation_build import (
    _seed_contracts,
    _write_complete_pipeline,
)
from server.workflows.managed_experiment_execution import _run_contract
from server.workflows.models import WorkflowRun


def _budget_run_spec() -> dict:
    """Reproduce the frozen seed structure authored in test 104."""
    return {
        "schema": 1,
        "implementation_family": "machine_learning",
        "execution_mode": "train_and_evaluate",
        "command": "python experiments/src/train.py --seed {seed}",
        "budgets": {"seeds": [13, 42, 73], "epochs": 20},
    }


def test_explicit_execution_budget_seeds_are_preserved() -> None:
    run_spec = _budget_run_spec()
    original = deepcopy(run_spec)

    assert run_spec_seed_groups(run_spec) == {"default": [13, 42, 73]}
    assert execution_seeds(run_spec) == [13, 42, 73]
    assert run_spec == original


def test_canonical_seed_declaration_keeps_priority_over_conflicting_budget() -> None:
    run_spec = {**_budget_run_spec(), "seeds": [101, 202, 303]}

    assert execution_seeds(run_spec) == [101, 202, 303]


def test_existing_explicit_container_priority_is_unchanged() -> None:
    run_spec = {**_budget_run_spec(), "optimization": {"seeds": [7, 11]}}

    assert execution_seeds(run_spec) == [7, 11]


@pytest.mark.parametrize("value", [None, True, False, 1.5, "1.5", "invalid", {}, []])
def test_invalid_budget_values_cannot_supply_execution_seeds(value: object) -> None:
    assert run_spec_seed_groups({"budgets": {"seeds": value}}) == {}


def test_budget_seed_values_use_the_same_integer_rules_as_canonical_seeds() -> None:
    values = [13, "42", 73, True, None, 1.5, "invalid"]

    assert execution_seeds({"budgets": {"seeds": values}}) == [13, 42, 73]
    assert execution_seeds({"seeds": values}) == [13, 42, 73]


@pytest.mark.parametrize("run_spec", [
    {"augmentation": {"seeds": [13, 42, 73]}},
    {"budgets": {"augmentation": {"seeds": [13, 42, 73]}}},
    {"budgets": {"seeds": {"augmentation": {"seeds": [13, 42, 73]}}}},
    {"runtime": {"sampler": {"seeds": [13, 42, 73]}}},
])
def test_unrelated_nested_rng_values_are_not_execution_seeds(run_spec: dict) -> None:
    assert run_spec_seed_groups(run_spec) == {}
    assert execution_seeds(run_spec) == []


def test_named_budget_groups_keep_audit_duplicates_and_scheduler_preference() -> None:
    run_spec = {"budgets": {"seeds": {
        "pilot": [5], "decisive": [13, "13", 42, 73],
    }}}

    assert run_spec_seed_groups(run_spec) == {
        "pilot": [5], "decisive": [13, 13, 42, 73],
    }
    assert execution_seeds(run_spec) == [13, 42, 73]


def test_budget_seeds_pass_integration_and_risk_without_contract_rewrite(
    tmp_path: Path,
) -> None:
    _seed_contracts(tmp_path)
    _write_complete_pipeline(tmp_path)
    path = tmp_path / "experiments/RUN_SPEC.json"
    run_spec = _budget_run_spec()
    path.write_text(json.dumps(run_spec), encoding="utf-8")
    original = path.read_bytes()

    integration = experiment_implementation_build_service.validate_stage(
        tmp_path, "integration", "classification research",
    )
    findings: list[dict] = []
    _rule_2([], "", findings, {"run_experiment": True}, tmp_path, run_spec)

    assert integration["passed"], integration
    assert not any(item["id"] == "DESIGN-REP-001" for item in findings)
    assert path.read_bytes() == original


def test_scheduler_reads_every_declared_budget_seed_without_starting_a_job(
    tmp_path: Path,
) -> None:
    path = tmp_path / "experiments/RUN_SPEC.json"
    path.parent.mkdir()
    path.write_text(json.dumps(_budget_run_spec()), encoding="utf-8")
    original = path.read_bytes()

    contract = _run_contract(
        None, WorkflowRun(project_path=str(tmp_path)), {"gpu_target": "remote"},
    )

    assert contract[4] == [13, 42, 73]
    assert path.read_bytes() == original
