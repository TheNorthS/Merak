"""Connect implementation ownership, frozen prompts and gates to the execution harness."""
from __future__ import annotations

import asyncio

from ..agent.execution_harness import ExecutionAttempt, fingerprint
from ..services.implementation_review_receipt import load_review, review_source_hash
from ..services.implementation_handoff import MAX_STAGE_HANDOFF_CHARS
from .implementation_reconciliation import reconcile_attempt


async def run_implementation_attempt(coordinator, context, state, invocation, protection) -> str:
    """A missing durable receipt or changed review contract prevents stage acceptance."""
    review_identity = fingerprint(load_review(context.root))
    invocation.prepared_arguments = invocation._arguments()
    invocation.prepared_input_fingerprint = invocation.resume_fingerprint()
    attempt = ExecutionAttempt(context.root, context.run.id, {
        "node_id": context.node.id, "stage_id": state.stage.id, "attempt": invocation.attempt,
        "targets": list(state.effective_targets), "findings": list(state.report.get("issues") or []),
        "input_sha256": invocation.prepared_input_fingerprint,
        "review_sha256": review_identity, "prompt_sha256": fingerprint(invocation.prepared_arguments),
        "max_model_iterations": 24, "max_stage_attempts": 2,
        "tools": ["Read", "Glob", "Grep", "Write", "Edit"], "scientific_execution_authorized": False,
    })
    try:
        output = await coordinator._invoke_attempt(state, invocation)
        if fingerprint(load_review(context.root)) != review_identity:
            raise RuntimeError("Independent review changed during the owner attempt; reconcile before acceptance")
        state.summaries.append(output[:MAX_STAGE_HANDOFF_CHARS])
        state.report = reconcile_attempt(context, state, protection)
        attempt.finish(state.report, output, review_source_hash(context.root), exhausted=bool(state.iteration_exhaustion))
    except (Exception, asyncio.CancelledError) as error:
        attempt.interrupt(error)
        raise
    await coordinator._emit("implementation_attempt_validated", {
        "stage_id": state.stage.id, "attempt_id": attempt.record["attempt_id"],
        "status": attempt.record["status"], "changed_targets": attempt.record["changed_targets"],
        "message": "实现尝试已记录；静态校验与独立审查结果分别保存。",
    })
    return output
