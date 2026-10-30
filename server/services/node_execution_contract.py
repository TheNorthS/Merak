"""Truthful model/runtime ownership contracts for workflow nodes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class NodeExecutionContract:
    """Describe who really owns a workflow stage."""

    kind: str
    runtime_service: str = ""
    policy_required: bool = True
    model_execution_mode: str = "primary"
    reason: str = ""
    blocking_issues: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "execution_kind": self.kind,
            "runtime_service": self.runtime_service,
            "policy_required": self.policy_required,
            "model_execution_mode": self.model_execution_mode,
            "reason": self.reason,
            "execution_contract_issues": list(self.blocking_issues),
        }


def resolve_execution_contract(
    node_id: str,
    options: dict[str, Any] | None = None,
    *,
    project_path: str | Path | None = None,
) -> NodeExecutionContract:
    """Return the truthful model/runtime ownership for one macro stage."""

    run_experiment = bool(options and options.get("run_experiment") is True)
    if node_id == "figure":
        return _figure_contract(project_path)
    if node_id == "results":
        return _results_contract(options)
    if node_id in {"lit", "idea", "novelty"}:
        return NodeExecutionContract(
            kind="model_owned",
            reason="The stage owner synthesizes a semantic research artifact.",
        )
    if node_id == "exp-run":
        return NodeExecutionContract(
            kind="runtime_owned",
            runtime_service=(
                "experiment_scheduler"
                if run_experiment
                else "experiment_placeholder_service"
            ),
            policy_required=False,
            reason=(
                "A durable scheduler executes the accepted run contract."
                if run_experiment
                else "Experiment execution is disabled; runtime creates non-evidence schemas."
            ),
        )
    if node_id == "compile":
        return NodeExecutionContract(
            kind="runtime_owned",
            runtime_service="paper_compiler",
            policy_required=False,
            reason=(
                "Compilation is deterministic; a model skill is only eligible "
                "for source repair."
            ),
        )
    if node_id == "ppt":
        return NodeExecutionContract(
            kind="hybrid",
            runtime_service="scientific_slide_service+paper_compiler",
            policy_required=True,
            reason=(
                "The /paper-talk owner designs the deck while bounded runtime "
                "services guarantee canonical source and compilation."
            ),
        )
    hybrid = _hybrid_contract(node_id)
    if hybrid is not None:
        return hybrid
    return NodeExecutionContract(
        kind="model_owned",
        reason="No dedicated runtime owner is declared.",
    )


def _figure_contract(project_path: str | Path | None) -> NodeExecutionContract:
    from .figure_execution_policy import FIGURE_RUNTIME_SERVICE, resolve_figure_execution_policy

    policy = resolve_figure_execution_policy(project_path)
    return NodeExecutionContract(
        kind=policy.kind, runtime_service=FIGURE_RUNTIME_SERVICE,
        policy_required=policy.policy_required, model_execution_mode=policy.model_execution_mode,
        reason=policy.reason, blocking_issues=policy.issues,
    )


def _results_contract(options: dict[str, Any] | None) -> NodeExecutionContract:
    from .results_execution_policy import resolve_results_execution_policy

    policy = resolve_results_execution_policy(options)
    return NodeExecutionContract(
        kind=policy.kind, runtime_service=policy.runtime_service,
        policy_required=policy.policy_required, reason=policy.reason,
        blocking_issues=policy.issues,
    )


def _hybrid_contract(node_id: str) -> NodeExecutionContract | None:
    services = {
        "exp-design": "artifact_builders+research_gates",
        "narrative": "paper_plan_service+research_gates",
        "paper": "staged_paper_drafting+paper_gates",
        "review": "cross_model_review_coordinator",
        "audit": "five_layer_audit_coordinator",
    }
    if node_id not in services:
        return None
    if node_id == "audit":
        reason = "The multi-layer audit accepts any verified declared model component while preserving per-layer fallback provenance."
    elif node_id == "exp-design":
        reason = "Experiment design may be completed by the primary owner or isolated implementation delegates; every accepted component retains model and skill provenance."
    else:
        reason = "A model skill creates or reviews semantics while runtime services validate and persist it."
    return NodeExecutionContract(
        kind="hybrid",
        runtime_service=services[node_id],
        model_execution_mode="any_component" if node_id in {"exp-design", "audit"} else "primary",
        reason=reason,
    )
