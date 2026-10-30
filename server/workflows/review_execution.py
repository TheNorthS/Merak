"""Execute the bounded review coordinator and persist hash-bound review state."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable

from ..services.paper_drafting import paper_drafting_service
from ..services.project_scaffold import get_convention_paths
from ..services.skill_orchestrator import skill_orchestrator
from ..utils.atomic_write import atomic_write_json
from .engine_context import (
    MANAGED_REVIEW_ROUNDS_MAX,
    REVIEW_MODEL_CALL_TIMEOUT_SECONDS,
    normalize_revision_rounds,
)
from .models import WorkflowNode, WorkflowRun
from .review_audit import cross_model_reviewer, review_source_bundle


async def _transport_retry(
    host: Any,
    run: WorkflowRun,
    node: WorkflowNode,
    opts: dict[str, Any],
    operation_name: str,
    operation: Callable[[], Awaitable[Any]],
) -> Any:
    retry_options = dict(opts)
    try:
        attempts = int(retry_options.get("model_transport_max_attempts") or 8)
    except (TypeError, ValueError):
        attempts = 8
    try:
        window = float(
            retry_options.get("model_transport_retry_window_seconds") or 900,
        )
    except (TypeError, ValueError):
        window = 900.0
    retry_options["model_transport_max_attempts"] = min(2, max(1, attempts))
    retry_options["model_transport_retry_window_seconds"] = min(
        3600.0,
        max(REVIEW_MODEL_CALL_TIMEOUT_SECONDS + 300.0, window),
    )
    return await host._execute_with_model_transport_retry(
        run=run,
        node_id=node.id,
        operation_name=f"review/{operation_name}",
        stage_id=operation_name,
        operation=operation,
        opts=retry_options,
    )


def _review_payload(state: Any, reconciliation: dict[str, Any]) -> dict[str, Any]:
    return {
        "managed_by": "cross_model_review_loop",
        "run_id": state.run_id,
        "final_score": state.final_score,
        "final_verdict": state.final_verdict,
        "rounds": len(state.rounds),
        "is_complete": state.is_complete,
        "threshold_met": bool(getattr(state, "threshold_met", False)),
        "bounded_complete": bool(getattr(state, "bounded_complete", False)),
        "reviewer_provider": getattr(state, "reviewer_provider", ""),
        "executor_provider": getattr(state, "executor_provider", ""),
        "reviewer_model": state.reviewer_model,
        "executor_model": state.executor_model,
        "evidence_mode": getattr(state, "evidence_mode", "executed"),
        "publication_ready": bool(getattr(state, "publication_ready", False)),
        "owner_skill": getattr(state, "owner_skill", "auto-review-loop"),
        "policy_loaded": bool(getattr(state, "policy_loaded", False)),
        "reviewer_session_ids": list(getattr(state, "reviewer_session_ids", [])),
        "executor_session_ids": list(getattr(state, "executor_session_ids", [])),
        "pdf_snapshots": list(getattr(state, "pdf_snapshots", [])),
        "paper_reconciliation": reconciliation,
    }


async def _bind_reconciled_state(
    host: Any,
    run: WorkflowRun,
    state: Any,
    paper_path: str,
) -> dict[str, Any]:
    # Actual edits were reconciled inside the bounded repair round, before its
    # output snapshot. A final consumer must never rewrite reviewed paper pixels.
    reconciliation = paper_drafting_service.gate_report(run.project_path, run.options)
    path = Path(run.project_path) / "review-stage" / "REVIEW_STATE.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    _source_hash, sources = review_source_bundle(run.project_path)
    root = Path(run.project_path).expanduser().resolve()
    payload.update(
        {
            "paper_reconciliation": reconciliation,
            "source_bundle_sha256": state.source_bundle_sha256,
            "sources": [
                item.relative_to(root).as_posix()
                if item.is_relative_to(root)
                else item.as_posix()
                for item in sources
            ],
        }
    )
    rounds = [
        dict(item) for item in payload.get("rounds") or [] if isinstance(item, dict)
    ]
    evidence = host._review_visual_evidence_gate(run.project_path, payload, rounds)
    payload["visual_evidence"] = evidence
    if evidence.get("required") is True and evidence.get("verified") is not True:
        payload.update({"threshold_met": False, "publication_ready": False})
        state.threshold_met = False
        state.publication_ready = False
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, payload)
    return reconciliation


async def execute_review_node(
    host: Any,
    node: WorkflowNode,
    run: WorkflowRun,
    assurance: str,
    opts: dict[str, Any],
) -> str:
    plan = skill_orchestrator.select(
        node.id, node.skill, run.project_path, {**opts, "assurance": assurance}
    )
    if not skill_orchestrator.full_policy(plan.primary):
        raise RuntimeError(f"Missing full skill policy: /{plan.primary}")
    trace = skill_orchestrator.record(run.project_path, run.id, plan)
    await host._emit(
        run,
        "skill_plan_selected",
        {
            "node_id": node.id,
            "primary": plan.primary,
            "specialists": plan.specialists,
            "validators": plan.validators,
            "registry_total": plan.registry_total,
            "trace_path": str(trace),
            "execution_kind": plan.execution_kind,
            "runtime_service": plan.runtime_service,
            "policy_required": plan.policy_required,
        },
    )
    operation_id = uuid.uuid4().hex[:12]
    skill_orchestrator.mark_execution(
        run.project_path,
        run.id,
        node.id,
        plan.primary,
        "running",
        role="primary",
        policy_loaded=True,
        execution_kind="hybrid",
    )
    service = plan.runtime_service or "cross_model_review_coordinator"
    skill_orchestrator.mark_runtime_execution(
        run.project_path, run.id, node.id, service, "running", operation_id=operation_id
    )
    await host._emit(
        run,
        "skill_invocation_started",
        {
            "node_id": node.id,
            "skill": plan.primary,
            "role": "primary",
            "execution_kind": "hybrid",
        },
    )
    return await _execute_registered_review(
        host, node, run, opts, plan, service, operation_id
    )


async def _execute_registered_review(
    host: Any,
    node: WorkflowNode,
    run: WorkflowRun,
    opts: dict[str, Any],
    plan: Any,
    service: str,
    operation_id: str,
) -> str:
    try:
        summary, state = await _run_review(host, node, run, opts, plan)
    except Exception as error:
        message = host._exception_summary(error)
        skill_orchestrator.mark_execution(
            run.project_path,
            run.id,
            node.id,
            plan.primary,
            "failed",
            role="primary",
            error=message,
            policy_loaded=True,
            execution_kind="hybrid",
        )
        skill_orchestrator.mark_runtime_execution(
            run.project_path,
            run.id,
            node.id,
            service,
            "failed",
            operation_id=operation_id,
            error=message,
        )
        await host._emit(
            run,
            "skill_invocation_failed",
            {
                "node_id": node.id,
                "skill": plan.primary,
                "role": "primary",
                "error": message,
            },
        )
        raise
    _finish_review_execution(run, node, plan, service, operation_id, summary, state)
    event = (
        "skill_invocation_recovered"
        if str(state.reviewer_model).startswith("deterministic:")
        else "skill_invocation_completed"
    )
    await host._emit(
        run,
        event,
        {
            "node_id": node.id,
            "skill": plan.primary,
            "role": "primary",
            "session_id": state.reviewer_session_ids[0]
            if getattr(state, "reviewer_session_ids", [])
            else "",
        },
    )
    return summary


async def _run_review(
    host: Any,
    node: WorkflowNode,
    run: WorkflowRun,
    opts: dict[str, Any],
    plan: Any,
) -> tuple[str, Any]:
    if (opts.get('run_experiment') is not True
            and opts.get('non_experiment_evidence_mode') == 'synthetic_preview'):
        from ..services.simulation_replay_capsule import ensure_simulation_replay_capsule
        # Restored accepted results may predate the capsule; extend their
        # provenance through its producer without rewriting any result row.
        ensure_simulation_replay_capsule(Path(run.project_path), str(opts.get('research_direction') or ''))
    paths = get_convention_paths(run.project_path)
    paper_path = paths.get("paper_main") or str(
        Path(run.project_path) / "paper" / "main.tex",
    )

    async def progress(message: str) -> None:
        await host._emit(
            run,
            "review_progress",
            {
                "node_id": node.id,
                "message": message,
            },
        )

    async def transport(name: str, operation: Callable[[], Awaitable[Any]]) -> Any:
        return await _transport_retry(host, run, node, opts, name, operation)

    state = await cross_model_reviewer.run_review_loop(
        paper_path=paper_path,
        project_path=run.project_path,
        max_rounds=min(
            MANAGED_REVIEW_ROUNDS_MAX,
            normalize_revision_rounds(opts.get("max_revision_rounds")),
        ),
        difficulty=str(opts.get("review_difficulty") or "hard"),
        on_progress=progress,
        run_id=run.id,
        researcher_feedback=str(opts.get("review_researcher_feedback") or ""),
        evidence_mode=(
            "executed"
            if opts.get("run_experiment") is True
            else str(opts.get("non_experiment_evidence_mode") or "design_only")
        ),
        transport_retry=transport,
    )
    reconciliation = await _bind_reconciled_state(host, run, state, paper_path)
    return json.dumps(
        _review_payload(state, reconciliation),
        ensure_ascii=False,
        indent=2,
    ), state


def _finish_review_execution(
    run: WorkflowRun,
    node: WorkflowNode,
    plan: Any,
    service: str,
    operation_id: str,
    summary: str,
    state: Any,
) -> None:
    session = (
        state.reviewer_session_ids[0]
        if getattr(state, "reviewer_session_ids", [])
        else ""
    )
    status = (
        "recovered"
        if str(state.reviewer_model).startswith("deterministic:")
        else "completed"
    )
    skill_orchestrator.mark_execution(
        run.project_path,
        run.id,
        node.id,
        plan.primary,
        status,
        role="primary",
        session_id=session,
        output=summary,
        policy_loaded=bool(getattr(state, "policy_loaded", False)),
        execution_kind="hybrid",
        model_name=state.reviewer_model,
    )
    skill_orchestrator.mark_runtime_execution(
        run.project_path,
        run.id,
        node.id,
        service,
        "completed",
        operation_id=operation_id,
        output=summary,
    )
