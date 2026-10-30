"""Resolve the single results owner from explicit execution and evidence modes.

Disabled training does not imply pending evidence: imported and secondary data
still require their semantic analysis owner and deterministic evidence gates.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


RESULTS_HYBRID_RUNTIME = "evidence_validation+research_gates"
PLANNED_RESULTS_RUNTIME = "planned_results_analysis"
BENCHMARK_RESULTS_RUNTIME = "deterministic_benchmark_analysis"
SUPPORTED_NON_EXPERIMENT_EVIDENCE_MODES = frozenset({
    "design_only", "synthetic_preview", "existing_results", "secondary_analysis",
})


@dataclass(frozen=True)
class ResultsExecutionPolicy:
    kind: str
    runtime_service: str
    policy_required: bool
    reason: str
    issues: tuple[str, ...] = ()


def resolve_results_execution_policy(options: Mapping[str, Any] | None = None) -> ResultsExecutionPolicy:
    """Declare actual services; unsupported no-run modes cannot acquire runtime success."""
    opts = options or {}
    if opts.get("run_experiment") is True:
        return ResultsExecutionPolicy(
            "hybrid", RESULTS_HYBRID_RUNTIME, True,
            "Executed evidence requires semantic results analysis and deterministic evidence validation.",
        )
    mode = str(opts.get("non_experiment_evidence_mode") or "design_only").strip().casefold() or "design_only"
    if mode not in SUPPORTED_NON_EXPERIMENT_EVIDENCE_MODES:
        issue = f"Unsupported non-experiment results evidence mode: {mode}"
        return ResultsExecutionPolicy("hybrid", RESULTS_HYBRID_RUNTIME, True, issue, (issue,))
    if mode == "synthetic_preview":
        return ResultsExecutionPolicy(
            "runtime_owned", BENCHMARK_RESULTS_RUNTIME, False,
            "Runtime analyzes the current hash-bound deterministic benchmark evidence, not pending results.",
        )
    if mode == "design_only":
        return ResultsExecutionPolicy(
            "runtime_owned", PLANNED_RESULTS_RUNTIME, False,
            "Runtime preserves explicit pending-evidence analysis without inventing measured outcomes.",
        )
    return ResultsExecutionPolicy(
        "hybrid", RESULTS_HYBRID_RUNTIME, True,
        "Existing or secondary evidence requires its semantic analysis owner and evidence validation; training stays disabled.",
    )
