"""Results evidence mode declares the same service that performs actual runtime work."""

from __future__ import annotations

import copy
from types import SimpleNamespace
from typing import Any

import pytest

from server.services.node_execution_contract import resolve_execution_contract
from server.services.results_execution_policy import (
    BENCHMARK_RESULTS_RUNTIME, PLANNED_RESULTS_RUNTIME, RESULTS_HYBRID_RUNTIME,
    resolve_results_execution_policy,
)
from server.workflows import run_execution_node as execution


class RuntimeFixture:
    """In-memory owner boundary; no project, data, model or workflow execution."""

    def __init__(self, *, failure: Exception | None = None) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.failure = failure

    async def _runtime_execution_started(self, node, run, opts, service):
        self.calls.append(("started", service))
        return "runtime-operation", service

    def _ensure_planned_results_analysis(self, run, direction, result=""):
        self.calls.append(("analysis", direction))
        if self.failure:
            raise self.failure
        return "Bound result-analysis fixture"

    async def _runtime_execution_finished(self, node, run, operation, service, **kwargs):
        self.calls.append(("finished", service, kwargs))

    @staticmethod
    def _exception_summary(error):
        return str(error)


def _context(options: dict[str, Any], *, failure: Exception | None = None):
    return SimpleNamespace(node=SimpleNamespace(id="results"), opts=options,
                           run=SimpleNamespace(project_path="fixture-not-read", options=options),
                           research_direction="Declared research", host=RuntimeFixture(failure=failure), result="")


@pytest.mark.parametrize("options,kind,service,policy", [
    ({}, "runtime_owned", PLANNED_RESULTS_RUNTIME, False),
    ({"non_experiment_evidence_mode": "design_only"}, "runtime_owned", PLANNED_RESULTS_RUNTIME, False),
    ({"non_experiment_evidence_mode": "  DESIGN_ONLY  "}, "runtime_owned", PLANNED_RESULTS_RUNTIME, False),
    ({"non_experiment_evidence_mode": "   "}, "runtime_owned", PLANNED_RESULTS_RUNTIME, False),
    ({"non_experiment_evidence_mode": "synthetic_preview"}, "runtime_owned", BENCHMARK_RESULTS_RUNTIME, False),
    ({"non_experiment_evidence_mode": "  SYNTHETIC_PREVIEW  "}, "runtime_owned", BENCHMARK_RESULTS_RUNTIME, False),
    ({"non_experiment_evidence_mode": "existing_results"}, "hybrid", RESULTS_HYBRID_RUNTIME, True),
    ({"non_experiment_evidence_mode": "  SECONDARY_ANALYSIS "}, "hybrid", RESULTS_HYBRID_RUNTIME, True),
    ({"run_experiment": True}, "hybrid", RESULTS_HYBRID_RUNTIME, True),
    ({"run_experiment": True, "non_experiment_evidence_mode": "synthetic_preview"}, "hybrid", RESULTS_HYBRID_RUNTIME, True),
])
def test_node_contract_uses_single_results_policy_without_mutating_options(options, kind, service, policy) -> None:
    before = copy.deepcopy(options)
    resolved = resolve_results_execution_policy(options)
    contract = resolve_execution_contract("results", options)
    assert contract.kind == resolved.kind == kind
    assert contract.runtime_service == resolved.runtime_service == service
    assert contract.policy_required is resolved.policy_required is policy
    assert not contract.blocking_issues
    assert options == before


@pytest.mark.parametrize("mode", ["design_only", "synthetic_preview", "  SYNTHETIC_PREVIEW  "])
@pytest.mark.asyncio
async def test_runtime_start_and_finish_use_exact_declared_service(mode) -> None:
    ctx = _context({"run_experiment": False, "non_experiment_evidence_mode": mode})
    contract = resolve_execution_contract("results", ctx.opts)
    await execution.run_planned_results(ctx)
    assert ctx.host.calls[0] == ("started", contract.runtime_service)
    assert ctx.host.calls[-1] == ("finished", contract.runtime_service, {"output": ctx.result})
    assert ctx.result == "Bound result-analysis fixture"


@pytest.mark.asyncio
async def test_runtime_failure_is_recorded_with_exact_declared_service() -> None:
    ctx = _context({"non_experiment_evidence_mode": "synthetic_preview"}, failure=ValueError("source hash fixture"))
    with pytest.raises(ValueError, match="source hash fixture"):
        await execution.run_planned_results(ctx)
    assert ctx.host.calls[-1] == ("finished", BENCHMARK_RESULTS_RUNTIME, {"error": "source hash fixture"})


@pytest.mark.parametrize("mode", ["existing_results", "secondary_analysis", "unknown_mode"])
@pytest.mark.asyncio
async def test_planned_dispatch_rejects_imported_or_unsupported_mode_before_runtime_write(mode) -> None:
    ctx = _context({"run_experiment": False, "non_experiment_evidence_mode": mode})
    with pytest.raises(ValueError, match="semantic author|execution contract is blocked"):
        await execution.run_planned_results(ctx)
    assert ctx.host.calls == []


def test_unsupported_mode_retains_blocking_contract_not_success_alias() -> None:
    contract = resolve_execution_contract("results", {"non_experiment_evidence_mode": "unrecognized"})
    assert contract.kind == "hybrid" and contract.policy_required
    assert contract.blocking_issues == ("Unsupported non-experiment results evidence mode: unrecognized",)
    assert contract.as_dict()["execution_contract_issues"] == list(contract.blocking_issues)


@pytest.mark.parametrize("mode", ["existing_results", "secondary_analysis"])
@pytest.mark.asyncio
async def test_imported_evidence_primary_dispatch_keeps_semantic_owner_not_pending(mode, monkeypatch) -> None:
    ctx = _context({"run_experiment": False, "non_experiment_evidence_mode": mode})
    called = []

    async def semantic_primary(target):
        called.append(target)

    monkeypatch.setattr(execution, "run_generic_primary", semantic_primary)
    await execution.run_primary_model(ctx)
    assert called == [ctx]
    assert ctx.host.calls == []


@pytest.mark.asyncio
async def test_unknown_primary_dispatch_is_blocked_before_any_owner_call(monkeypatch) -> None:
    ctx = _context({"non_experiment_evidence_mode": "unknown"})

    async def forbidden(_ctx):
        pytest.fail("Unsupported evidence cannot execute a model or pending runtime")

    monkeypatch.setattr(execution, "run_generic_primary", forbidden)
    with pytest.raises(ValueError, match="execution contract is blocked"):
        await execution.run_primary_model(ctx)
    assert ctx.host.calls == []
