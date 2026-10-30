"""Gate, progress, and stop phases for the bounded revision state machine."""

from __future__ import annotations
import hashlib
import json
import time
import uuid
from typing import Any
from ..services.skill_orchestrator import skill_orchestrator
from .engine_context import logger
from .revision_loop_context import RevisionComplete, RevisionLoopContext


async def persist_gate_inputs(ctx: RevisionLoopContext) -> None:
    ctx.node.output = ctx.result
    ctx.node.finished_at = time.time()
    ctx.run_state.set_status(
        ctx.node.id,
        "done",
        artifact=ctx.host._primary_artifact_for_node(ctx.run.project_path, ctx.node.id),
        details={"summary": ctx.result[:500]},
    )
    if ctx.first_gate:
        await ctx.host._emit(
            ctx.run,
            "node_completed",
            {
                "node_id": ctx.node.id,
                "duration": max(
                    0.0,
                    ctx.node.finished_at
                    - (ctx.node.started_at or ctx.node.finished_at),
                ),
                "verification_pending": True,
            },
        )
        ctx.first_gate = False
    ctx.unchanged_revision_event: dict[str, Any] | None = None


async def measure_revision_change(ctx: RevisionLoopContext) -> None:
    if ctx.last_revision_event_pending:
        scope_signature_after = ctx.host._revision_scope_signature(
            ctx.run.project_path,
            ctx.last_revision_owner_id,
            ctx.last_revision_scope_diagnostics,
            ctx.opts,
        )
        target_artifact_changed = bool(
            ctx.last_revision_scope_before
            and scope_signature_after != ctx.last_revision_scope_before
        )
        revision_event = {
            "node_id": ctx.node.id,
            "revision_owner_id": ctx.last_revision_owner_id,
            "round": ctx.last_revision_attempt_round,
            "cycle": ctx.cycle,
            "method": ctx.last_revision_method or "agent",
            "preparation_error": ctx.preparation_error,
            "execution_succeeded": ctx.last_revision_execution_succeeded,
            "target_artifact_changed": target_artifact_changed,
            "target_signature_before": ctx.last_revision_scope_before,
            "target_signature_after": scope_signature_after,
        }
        if ctx.last_revision_execution_succeeded and target_artifact_changed:
            await ctx.host._emit(ctx.run, "node_revision_completed", revision_event)
        elif not target_artifact_changed:
            ctx.unchanged_revision_event = revision_event
        ctx.last_revision_event_pending = False


async def build_current_gate(ctx: RevisionLoopContext) -> None:
    from .figure_execution_verification import refresh_figure_execution_contract

    refresh_figure_execution_contract(ctx)
    if ctx.preparation_error:
        ctx.gate = {
            "accepted": False,
            "reason": "artifact preparation or verification failed",
            "summary": ctx.preparation_error[:2000],
            "details": ctx.preparation_failure_details or {"issues": [ctx.preparation_error[:2000]]},
        }
    else:
        ctx.gate = ctx.host._acceptance_gate(
            ctx.node,
            ctx.run,
            ctx.assurance,
            ctx.result,
            require_fresh=ctx.require_fresh,
        )
        if ctx.consumer_refresh_upstream_gate is not None:
            ctx.gate = ctx.consumer_refresh_upstream_gate
    if ctx.unchanged_revision_event is not None:
        if ctx.gate.get("accepted"):
            await ctx.host._emit(
                ctx.run,
                "node_revision_revalidated",
                {
                    **ctx.unchanged_revision_event,
                    "summary": "The targeted artifact was unchanged, but the fresh acceptance gate now passes.",
                },
            )
        else:
            await ctx.host._emit(
                ctx.run,
                "node_revision_no_progress",
                {
                    **ctx.unchanged_revision_event,
                    "summary": "The revision attempt finished without changing any target artifact or semantic asset implicated by the current structured findings.",
                },
            )


async def record_runtime_gate(ctx: RevisionLoopContext) -> None:
    if ctx.gate_runtime_service:
        gate_operation_id = uuid.uuid4().hex[:12]
        gate_output = json.dumps(
            {
                "accepted": bool(ctx.gate.get("accepted")),
                "reason": str(ctx.gate.get("reason") or ""),
                "summary": str(ctx.gate.get("summary") or "")[:2000],
                "revision_round": ctx.round_number,
                "revision_cycle": ctx.cycle,
            },
            ensure_ascii=False,
        )
        runtime_status = "failed" if ctx.node.id == "figure" and ctx.preparation_error else "completed"
        skill_orchestrator.mark_runtime_execution(
            ctx.run.project_path,
            ctx.run.id,
            ctx.node.id,
            ctx.gate_runtime_service,
            runtime_status,
            operation_id=gate_operation_id,
            output=gate_output,
            error=str(ctx.preparation_error or "") if runtime_status == "failed" else "",
        )
        await ctx.host._emit(
            ctx.run,
            f"runtime_execution_{runtime_status}",
            {
                "node_id": ctx.node.id,
                "runtime_service": ctx.gate_runtime_service,
                "operation_id": gate_operation_id,
                "accepted": bool(ctx.gate.get("accepted")),
                "scope": "artifact-preparation-and-acceptance-gate",
            },
        )


async def verify_runtime_execution(ctx: RevisionLoopContext) -> None:
    from .figure_execution_verification import revalidate_figure_after_runtime

    ctx.execution_gate_applied = bool(
        isinstance(ctx.gate.get("details"), dict)
        and ctx.gate["details"].get("execution_gate_applied")
    )
    revalidate_figure_after_runtime(ctx)
    if ctx.gate.get("accepted") and ctx.execution_gate_applied:
        execution_gate = skill_orchestrator.execution_gate(
            ctx.run.project_path, ctx.run.id, ctx.node.id
        )
        if not execution_gate.get("accepted"):
            ctx.gate = {
                "accepted": False,
                "reason": "declared node execution was not verified",
                "summary": "; ".join(execution_gate.get("issues", [])[:8]),
                "details": {
                    "issues": execution_gate.get("issues", []),
                    "execution_evidence": execution_gate,
                    "execution_gate_applied": True,
                },
            }
        else:
            ctx.gate.setdefault("details", {})["execution_evidence"] = execution_gate
    if (
        ctx.gate.get("accepted")
        and ctx.execution_gate_applied
        and (ctx.node.id == "figure")
    ):
        prior_node_ids: list[str] = []
        for workflow_node in ctx.run.nodes:
            prior_node_ids.append(workflow_node.id)
            if workflow_node.id == ctx.node.id:
                break
        workflow_execution = skill_orchestrator.workflow_execution_gate(
            ctx.run.project_path, ctx.run.id, prior_node_ids
        )
        if not workflow_execution.get("accepted"):
            ctx.gate = {
                "accepted": False,
                "reason": "upstream workflow execution was not verified",
                "summary": "; ".join(workflow_execution.get("issues", [])[:8]),
                "details": {
                    "issues": workflow_execution.get("issues", []),
                    "workflow_execution_evidence": workflow_execution,
                    "execution_gate_applied": True,
                },
            }
        else:
            ctx.gate.setdefault("details", {})["workflow_execution_evidence"] = (
                workflow_execution
            )


async def normalize_gate_outcome(ctx: RevisionLoopContext) -> None:
    ctx.diagnostics = ctx.host._gate_revision_diagnostics(ctx.gate)
    if ctx.node.id == "figure" and (not ctx.gate.get("accepted")):
        ctx.repair_scope = ctx.diagnostics.get("repair_scope")
        ctx.repair_scope = (
            ctx.repair_scope if isinstance(ctx.repair_scope, dict) else {}
        )
        scoped_assets = [
            str(value).strip()
            for value in ctx.repair_scope.get("asset_ids") or []
            if str(value).strip()
        ]
        if scoped_assets == ["evaluation_design"]:
            from ..services.figure_artifacts import figure_artifact_registry

            best_result = figure_artifact_registry.preserve_best_candidate(
                ctx.run.project_path,
                "evaluation_design",
                ctx.diagnostics.get("issues") or [],
            )
            await ctx.host._emit(
                ctx.run,
                "figure_best_candidate_updated",
                {
                    "node_id": ctx.node.id,
                    "asset_id": "evaluation_design",
                    "round": ctx.round_number,
                    **best_result,
                },
            )


async def complete_accepted_gate(ctx: RevisionLoopContext) -> None:
    if ctx.gate.get("accepted"):
        ctx.host._bind_gate_artifact_snapshot(ctx.node, ctx.run, ctx.gate)
        if ctx.node.id == "review":
            paper_node = ctx.host._find_node(ctx.run, "paper")
            if paper_node is not None:
                paper_gate: dict[str, Any] = {}
                ctx.host._bind_gate_artifact_snapshot(paper_node, ctx.run, paper_gate)
                ctx.run_state.refresh_accepted_details(
                    "paper",
                    dict(paper_gate.get("details") or {}),
                    reason="paper artifacts were revalidated after accepted cross-model review edits",
                )
        ctx.gate["revision_round"] = ctx.round_number
        ctx.gate["revision_cycle"] = ctx.cycle
        if ctx.round_number > 0:
            ctx.run_state.record_revision_gate(
                ctx.node.id,
                round_number=ctx.round_number,
                cycle=ctx.cycle,
                gate=ctx.diagnostics,
                owner_id=ctx.active_owner_id,
                owner_rounds=ctx.owner_rounds,
            )
        await ctx.host._emit(
            ctx.run,
            "node_revision_gate",
            {
                "node_id": ctx.node.id,
                "round": ctx.round_number,
                "cycle": ctx.cycle,
                **ctx.diagnostics,
            },
        )
        raise RevisionComplete((ctx.gate, ctx.result))


async def apply_execution_error(ctx: RevisionLoopContext) -> None:
    if ctx.last_execution_error:
        original_issues = list(ctx.diagnostics.get("issues") or [])
        ctx.diagnostics = {
            **ctx.diagnostics,
            "reason": "revision execution failed",
            "summary": f"{ctx.last_execution_error['summary']} Quality gate remains unresolved: {ctx.diagnostics.get('summary') or ctx.diagnostics.get('reason') or 'unknown gap'}"[
                :2000
            ],
            "issues": list(
                dict.fromkeys(
                    [
                        *list(ctx.last_execution_error.get("issues") or []),
                        *original_issues,
                    ]
                )
            ),
            "error_type": ctx.last_execution_error.get("error_type", ""),
            "error_category": ctx.last_execution_error.get(
                "error_category", "node_execution"
            ),
        }


async def select_revision_owner(ctx: RevisionLoopContext) -> None:
    ctx.revision_owner = ctx.host._revision_owner_for_gate(
        ctx.node, ctx.run, ctx.gate, ctx.owner_rounds
    )
    ctx.diagnostics = ctx.host._revision_diagnostics_for_owner(
        ctx.diagnostics, ctx.revision_owner.id, ctx.node.id
    )
    if ctx.revision_owner.id != ctx.active_owner_id:
        ctx.active_owner_id = ctx.revision_owner.id
        ctx.round_number = ctx.owner_rounds.get(ctx.active_owner_id, 0)
        ctx.cycle += 1
        ctx.last_revision_attempt_round = 0
        ctx.last_revision_owner_id = ctx.active_owner_id
        ctx.last_revision_scope_before = ""
        ctx.last_revision_scope_diagnostics = {}
        ctx.last_revision_execution_succeeded = False
        ctx.last_revision_event_pending = False


def _current_progress_findings(ctx: RevisionLoopContext) -> set[str]:
    finding_ids = {
        str(item).strip()
        for item in ctx.scope.get("finding_ids") or []
        if str(item).strip()
    }
    if finding_ids:
        return finding_ids
    return {
        hashlib.sha256(
            ctx.host._stable_revision_finding_text(item).encode(
                "utf-8", errors="replace"
            )
        ).hexdigest()[:12]
        for item in ctx.diagnostics.get("issues", [])
        if str(item).strip()
    }


def _draft_review_progress(ctx: RevisionLoopContext) -> tuple[str, bool]:
    if ctx.revision_owner.id != "figure":
        return "", False
    from ..services.figure_revision_progress import (
        figure_draft_progress_signature,
    )

    asset_ids = [
        str(item).strip() for item in ctx.scope.get("asset_ids") or []
        if str(item).strip()
    ]
    signature = figure_draft_progress_signature(
        ctx.run.project_path, asset_ids,
    )
    previous = ctx.owner_last_draft_review_signatures.get(
        ctx.revision_owner.id, "",
    )
    return signature, bool(previous and signature != previous)


def _apply_measured_progress(
    ctx: RevisionLoopContext, progress: dict[str, Any],
) -> None:
    ctx.resolved_finding_ids = progress["resolved_finding_ids"]
    ctx.new_finding_ids = progress["new_finding_ids"]
    ctx.target_changed = progress["target_changed"]
    ctx.no_progress_count = progress["consecutive_no_progress"]
    ctx.stall_classification = progress["stall_classification"]
    ctx.diagnostics = {
        **ctx.diagnostics,
        "revision_progress": {
            **progress,
            "no_progress_limit": ctx.no_progress_limit,
        },
    }


def _remember_progress(ctx: RevisionLoopContext) -> None:
    owner_id = ctx.revision_owner.id
    ctx.owner_last_finding_ids[owner_id] = ctx.current_finding_ids | set(
        ctx.diagnostics.get("revision_progress", {}).get("not_evaluated_finding_ids", [])
    )
    ctx.owner_last_scope_signatures[owner_id] = ctx.scope_signature
    if ctx.draft_review_signature:
        ctx.owner_last_draft_review_signatures[
            owner_id
        ] = ctx.draft_review_signature
    ctx.owner_no_progress_counts[owner_id] = ctx.no_progress_count
    ctx.transport_attempt_since_gate = False


async def record_progress(ctx: RevisionLoopContext) -> None:
    from .revision_progress_diagnostics import measure_revision_progress
    from .paper_revision_progress import new_author_scope
    from .implementation_review_progress import new_implementation_review_scope

    ctx.scope = ctx.diagnostics.get("repair_scope")
    ctx.scope = ctx.scope if isinstance(ctx.scope, dict) else {}
    ctx.current_finding_ids = _current_progress_findings(ctx)
    ctx.last_finding_ids = ctx.owner_last_finding_ids.get(ctx.revision_owner.id, set())
    ctx.last_scope_signature = ctx.owner_last_scope_signatures.get(
        ctx.revision_owner.id, ""
    )
    ctx.no_progress_count = ctx.owner_no_progress_counts.get(ctx.revision_owner.id, 0)
    ctx.scope_signature = ctx.host._revision_scope_signature(
        ctx.run.project_path, ctx.revision_owner.id, ctx.diagnostics, ctx.opts
    )
    (
        ctx.draft_review_signature,
        ctx.draft_review_changed,
    ) = _draft_review_progress(ctx)
    progress = measure_revision_progress(
        current=ctx.current_finding_ids, previous=ctx.last_finding_ids,
        scope_signature=ctx.scope_signature,
        previous_scope_signature=ctx.last_scope_signature,
        previous_count=ctx.no_progress_count,
        revision_started=ctx.owner_rounds.get(ctx.revision_owner.id, 0) > 0,
        transport_attempted=ctx.transport_attempt_since_gate,
        draft_review_changed=ctx.draft_review_changed,
        draft_review_signature=ctx.draft_review_signature,
        evaluation_complete=not bool(ctx.preparation_error),
        new_author_scope=new_author_scope(ctx) or new_implementation_review_scope(ctx),
    )
    _apply_measured_progress(ctx, progress)
    _remember_progress(ctx)
    ctx.run_state.record_revision_gate(
        ctx.node.id,
        round_number=ctx.round_number,
        cycle=ctx.cycle,
        gate=ctx.diagnostics,
        owner_id=ctx.active_owner_id,
        owner_rounds=ctx.owner_rounds,
    )
    await ctx.host._emit(
        ctx.run,
        "node_revision_gate",
        {
            "node_id": ctx.node.id,
            "round": ctx.round_number,
            "cycle": ctx.cycle,
            **ctx.diagnostics,
        },
    )
    logger.info(
        "Workflow node entering research revision",
        node=ctx.node.id,
        round=ctx.round_number,
        cycle=ctx.cycle,
        reason=ctx.diagnostics["reason"],
    )


async def classify_stop_policy(ctx: RevisionLoopContext) -> None:
    ctx.stop_for_no_progress = ctx.no_progress_count >= ctx.no_progress_limit and (
        not ctx.pending_feedback
    )
    if (ctx.node.id == "figure"
            and ctx.diagnostics.get("error_category") == "figure_retry_deferred"
            and not ctx.pending_feedback):
        ctx.stop_for_no_progress = True
    ctx.repair_scope = ctx.diagnostics.get("repair_scope")
    ctx.repair_scope = ctx.repair_scope if isinstance(ctx.repair_scope, dict) else {}
    ctx.has_repair_targets = bool(
        ctx.repair_scope.get("target_files") or ctx.repair_scope.get("asset_ids")
    )
    ctx.unscoped_platform_gate = (
        not ctx.has_repair_targets
        and ctx.revision_owner.id == ctx.node.id
        and (not ctx.pending_feedback)
        and any(
            (
                marker
                in " ".join((str(item) for item in ctx.diagnostics.get("issues", [])))
                for marker in (
                    "cannot be submission-eligible",
                    "lacks executed provenance",
                    "no runtime-verified skill invocation provenance",
                    "skill mismatch",
                )
            )
        )
    )
    if ctx.unscoped_platform_gate:
        ctx.stop_for_no_progress = True
        ctx.diagnostics = {
            **ctx.diagnostics,
            "reason": "unscoped platform or upstream contract failure",
            "summary": "The gate produced no legal target file or asset ID. Model revision was skipped; repair the platform/upstream contract first.",
            "issues": [
                *list(ctx.diagnostics.get("issues") or []),
                "No legal revision target was supplied; model invocation skipped.",
            ],
        }
    ctx.gate_details = (
        ctx.gate.get("details") if isinstance(ctx.gate.get("details"), dict) else {}
    )


async def classify_managed_stop(ctx: RevisionLoopContext) -> None:
    ctx.review_state_stale = any(
        (
            str(item.get("id") or "") in {"REVIEW-STALE-001", "REVIEW-HASH-001"}
            for item in ctx.diagnostics.get("findings", [])
            if isinstance(item, dict)
        )
    ) or any(
        (
            marker
            in " ".join(
                (str(item) for item in ctx.diagnostics.get("issues", []))
            ).casefold()
            for marker in (
                "structured review state is stale",
                "review_state.json predates",
                "source hash",
                "source bundle hash",
                "来源哈希",
            )
        )
    )
    ctx.review_state_incomplete = any(
        (
            str(item.get("id") or "") == "REVIEW-STATE-002"
            for item in ctx.diagnostics.get("findings", [])
            if isinstance(item, dict)
        )
    ) or any(
        (
            marker
            in " ".join(
                (str(item) for item in ctx.diagnostics.get("issues", []))
            ).casefold()
            for marker in (
                "no structured review rounds",
                "no structured rounds",
                "persist at least one structured review round",
                "review state has no structured review rounds",
            )
        )
    )
    ctx.reconciliation = ctx.gate_details.get("paper_reconciliation")
    ctx.review_reconciliation_failed = bool(
        isinstance(ctx.reconciliation, dict) and (not ctx.reconciliation.get("passed"))
    ) or any(
        (
            marker in str(ctx.diagnostics.get("reason") or "").casefold()
            for marker in (
                "reviewed paper failed deterministic reconciliation",
                "section unfocused",
            )
        )
    )
    ctx.stop_for_managed_stage = (
        ctx.node.id == "review"
        and bool(ctx.gate_details.get("managed_review"))
        and (ctx.revision_owner.id == ctx.node.id)
        and (not ctx.review_state_stale)
        and (not ctx.review_state_incomplete)
        and (not ctx.review_reconciliation_failed)
        and (ctx.transport_failures == 0)
        and (not ctx.pending_feedback)
    )
    ctx.stop_for_deterministic_stage = (
        ctx.node.id in {"compile", "ppt"}
        and ctx.revision_owner.id == ctx.node.id
        and (ctx.owner_rounds.get(ctx.revision_owner.id, 0) >= 1)
        and (not ctx.pending_feedback)
    )
    if ctx.node.id == "paper" and ctx.diagnostics.get("error_category") in {"paper_preparation", "paper_publication_layout"}:
        ctx.stop_for_deterministic_stage = True


async def record_no_progress_stop(ctx: RevisionLoopContext) -> None:
    if ctx.node.id == "paper" and ctx.diagnostics.get("error_category") in {"paper_preparation", "paper_publication_layout"}:
        ctx.diagnostics["reason"] = "deterministic paper preparation failed"
        return
    if (ctx.stop_for_no_progress and ctx.node.id == "figure"
            and ctx.diagnostics.get("error_category") == "figure_retry_deferred"):
        ctx.diagnostics = {
            **ctx.diagnostics,
            "reason": "figure producer automatic retry deferred",
            "summary": (
                "The unchanged figure asset has exhausted its automatic producer "
                "attempt. Its review findings remain blocking; a changed source, "
                "implementation, or asset-scoped researcher feedback can "
                "authorize another attempt."
            ),
        }
    elif ctx.stop_for_no_progress:
        from .revision_progress_diagnostics import revision_stall_message

        unchanged_summary, unchanged_issue = revision_stall_message(
            ctx.stall_classification, ctx.no_progress_count,
        )
        ctx.diagnostics = {
            **ctx.diagnostics,
            "reason": "targeted revision produced no semantic progress",
            "summary": unchanged_summary + " Unrelated node artifacts were not regenerated.",
            "issues": [*list(ctx.diagnostics.get("issues") or []), unchanged_issue],
            "stall_classification": ctx.stall_classification,
        }
    elif ctx.stop_for_managed_stage:
        ctx.diagnostics = {
            **ctx.diagnostics,
            "reason": "cross-model review loop exhausted its bounded rounds",
            "summary": "The managed review service completed its configured independent rounds without reaching the acceptance condition. The outer workflow will not start a duplicate review loop.",
            "issues": [
                *list(ctx.diagnostics.get("issues") or []),
                "Managed review findings remain unresolved after the configured independent rounds.",
            ],
        }
    elif ctx.stop_for_deterministic_stage:
        ctx.diagnostics = {
            **ctx.diagnostics,
            "reason": "deterministic stage repair remained unresolved after one bounded attempt",
            "summary": f"{ctx.node.id} completed one deterministic repair/rebuild attempt, but the acceptance gate remains unresolved. The workflow will wait for an artifact or runtime change instead of repeating the same deterministic operation.",
            "issues": [
                *list(ctx.diagnostics.get("issues") or []),
                "The deterministic stage is limited to one automatic repair attempt per unchanged artifact/runtime state.",
            ],
        }


async def prepare_revision_stop(ctx: RevisionLoopContext) -> None:
    if (
        ctx.round_number >= ctx.max_revision_rounds
        and (not ctx.pending_feedback)
        or ctx.stop_for_no_progress
        or ctx.stop_for_deterministic_stage
        or ctx.stop_for_managed_stage
    ):
        intervention_kind = ctx.host._revision_intervention_kind(
            ctx.node, ctx.diagnostics
        )
        ctx.requires_human_decision = bool(
            intervention_kind == "researcher_decision"
            and (
                ctx.opts.get("human_checkpoint", False)
                or not ctx.opts.get("auto_proceed", True)
            )
        )
        decision_brief = ctx.host._build_revision_decision_brief(
            ctx.node, ctx.diagnostics, ctx.round_number, ctx.max_revision_rounds
        )
        ctx.waiting_diagnostics = {
            **ctx.diagnostics,
            "decision_brief": decision_brief,
            "intervention_kind": intervention_kind,
            "requires_human_decision": ctx.requires_human_decision,
            "hard_limit": not (
                ctx.stop_for_no_progress
                or ctx.stop_for_deterministic_stage
                or ctx.stop_for_managed_stage
            ),
            "stopped_for_no_progress": ctx.stop_for_no_progress,
            "stopped_for_deterministic_stage": ctx.stop_for_deterministic_stage,
            "stopped_for_managed_stage": ctx.stop_for_managed_stage,
        }


async def emit_revision_stop(ctx: RevisionLoopContext) -> None:
    if (
        ctx.round_number >= ctx.max_revision_rounds
        and (not ctx.pending_feedback)
        or ctx.stop_for_no_progress
        or ctx.stop_for_deterministic_stage
        or ctx.stop_for_managed_stage
    ):
        ctx.run_state.set_revision_waiting(
            ctx.node.id,
            round_number=ctx.round_number,
            cycle=ctx.cycle,
            gate=ctx.waiting_diagnostics,
            artifact_signature=ctx.host._revision_artifact_signature(
                ctx.run.project_path, ctx.revision_owner.id, ctx.opts
            ),
            artifact_owner_id=ctx.revision_owner.id,
            runtime_signature=ctx.host._revision_runtime_signature(
                ctx.run.project_path, ctx.revision_owner.id, ctx.opts
            ),
            owner_rounds=ctx.owner_rounds,
        )
        if not ctx.requires_human_decision:
            await ctx.host._emit(
                ctx.run,
                "node_platform_repair_required",
                {
                    "node_id": ctx.node.id,
                    "name": ctx.node.name,
                    "owner_node_id": ctx.revision_owner.id,
                    "round": ctx.round_number,
                    "cycle": ctx.cycle,
                    "reason": str(ctx.diagnostics.get("reason") or ""),
                    "summary": str(ctx.diagnostics.get("summary") or ""),
                    "issues": list(ctx.diagnostics.get("issues") or [])[:8],
                    "component_statuses": ctx.diagnostics.get("component_statuses", {}),
                },
            )
        await ctx.host._emit(
            ctx.run,
            "node_revision_waiting",
            {
                "node_id": ctx.node.id,
                "name": ctx.node.name,
                "round": ctx.round_number,
                "cycle": ctx.cycle,
                "max_revision_rounds": ctx.max_revision_rounds,
                "hard_limit": not (
                    ctx.stop_for_no_progress
                    or ctx.stop_for_deterministic_stage
                    or ctx.stop_for_managed_stage
                ),
                "stopped_for_no_progress": ctx.stop_for_no_progress,
                "stopped_for_deterministic_stage": ctx.stop_for_deterministic_stage,
                "stopped_for_managed_stage": ctx.stop_for_managed_stage,
                **ctx.waiting_diagnostics,
            },
        )
        raise RevisionComplete(
            (
                {
                    **ctx.gate,
                    "waiting": True,
                    "revision_round": ctx.round_number,
                    "max_revision_rounds": ctx.max_revision_rounds,
                },
                ctx.result,
            )
        )


async def classify_guided_revision(ctx: RevisionLoopContext) -> None:
    ctx.guided_revision = bool(
        ctx.pending_feedback and ctx.round_number >= ctx.max_revision_rounds
    )


async def advance_revision_round(ctx: RevisionLoopContext) -> None:
    if not ctx.guided_revision:
        ctx.round_number += 1
        ctx.owner_rounds[ctx.active_owner_id] = ctx.round_number


async def start_revision(ctx: RevisionLoopContext) -> None:
    from .owner_revision_transaction import begin_owner_revision
    begin_owner_revision(ctx)
    if ctx.revision_owner.id != ctx.node.id:
        await ctx.host._emit(ctx.run, "owner_acceptance_revoked", {
            "node_id": ctx.revision_owner.id, "consumer_node": ctx.node.id,
            "message": "上游修订已开始，旧验收已撤销；新产物需要重新验收。",
        })
    ctx.host._start_node_attempt(ctx.node)
    ctx.node.artifact_baseline = ctx.host._snapshot_node_artifacts(ctx.node, ctx.run)
    if ctx.revision_owner.id != ctx.node.id:
        ctx.revision_owner.artifact_baseline = ctx.host._snapshot_node_artifacts(
            ctx.revision_owner, ctx.run
        )
    ctx.run_state.set_status(
        ctx.node.id,
        "running",
        details={
            "artifact_baseline": ctx.node.artifact_baseline,
            "revision_owner_id": ctx.revision_owner.id,
        },
    )
    await ctx.host._emit(
        ctx.run,
        "node_revision_started",
        {
            "node_id": ctx.node.id,
            "name": ctx.node.name,
            "revision_owner_id": ctx.revision_owner.id,
            "revision_owner_name": ctx.revision_owner.name,
            "round": ctx.round_number,
            "cycle": ctx.cycle,
            "attempt": ctx.round_number,
            "max_revision_rounds": ctx.max_revision_rounds,
            "has_feedback": bool(ctx.pending_feedback),
            "guided_beyond_automatic_limit": ctx.guided_revision,
            **ctx.diagnostics,
        },
    )
    ctx.last_revision_owner_id = ctx.revision_owner.id
    ctx.last_revision_scope_before = ctx.scope_signature
    ctx.last_revision_scope_diagnostics = {
        "repair_scope": {
            "target_files": list(ctx.scope.get("target_files") or []),
            "asset_ids": list(ctx.scope.get("asset_ids") or []),
        }
    }
    ctx.last_revision_execution_succeeded = False
    ctx.last_revision_event_pending = False


async def finalize_revision(ctx: RevisionLoopContext) -> None:
    ctx.last_revision_attempt_round = ctx.round_number
    ctx.last_revision_event_pending = True
    ctx.require_fresh = False
