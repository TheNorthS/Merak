"""Execute the declared deterministic result producer with truthful trace evidence.

First execution, artifact revalidation and bounded repair share this operation.
Only the actual producer can create a completed runtime record; a selected plan,
old analysis file or gate-only pass cannot manufacture execution evidence.
"""

from __future__ import annotations

from typing import Any

from ..services.node_execution_contract import NodeExecutionContract, resolve_execution_contract
from .models import WorkflowNode, WorkflowRun


def runtime_results_contract(run: WorkflowRun, options: dict[str, Any]) -> NodeExecutionContract:
    """Reject unsupported/model-owned evidence before any deterministic mutation."""
    contract = resolve_execution_contract("results", options, project_path=run.project_path)
    if contract.blocking_issues:
        raise ValueError("Result execution contract is blocked: " + "; ".join(contract.blocking_issues))
    return contract


async def execute_results_runtime(
    host: Any, node: WorkflowNode, run: WorkflowRun, direction: str, options: dict[str, Any],
    *, result: str = "",
) -> str:
    """Run only an authorized local result projection, never a simulator or experiment."""
    contract = runtime_results_contract(run, options)
    if node.id != "results" or contract.kind != "runtime_owned" or not contract.runtime_service:
        raise ValueError("Measured or imported result analysis must use its declared semantic author, not a planned-result producer")
    run_contract = runtime_results_contract(run, dict(run.options))
    if run_contract.kind != contract.kind or run_contract.runtime_service != contract.runtime_service:
        raise ValueError("Result options disagree with the current run's immutable evidence contract")
    operation, service = await host._runtime_execution_started(node, run, options, contract.runtime_service)
    try:
        output = host._ensure_planned_results_analysis(run, direction, result=result)
    except Exception as error:
        await host._runtime_execution_finished(node, run, operation, service,
                                               error=host._exception_summary(error))
        raise
    await host._runtime_execution_finished(node, run, operation, service, output=output)
    node.execution_kind, node.runtime_service, node.policy_required = contract.kind, contract.runtime_service, contract.policy_required
    return output
