"""Phases for a bounded revision state machine."""

from __future__ import annotations
import hashlib
import json
from pathlib import Path
from typing import Any
from .run_state import RunState
from .revision_loop_context import RevisionComplete, RevisionLoopContext
from ..contracts.preparation import PreparationContractError


def bounded_round(value: Any, maximum: int) -> int:
    try:
        return min(max(0, int(value or 0)), maximum)
    except (TypeError, ValueError):
        return 0


def persisted_ids(ctx: RevisionLoopContext) -> set[str]:
    candidates = (
        ctx.persisted_progress.get("finding_ids")
        or ctx.persisted_progress.get("current_finding_ids")
        or ctx.persisted_scope.get("finding_ids")
    )
    if isinstance(candidates, (list, tuple, set)):
        values = {str(item).strip() for item in candidates if str(item).strip()}
        if values:
            return values
    return {
        hashlib.sha256(
            ctx.host._stable_revision_finding_text(item).encode(
                "utf-8", errors="replace"
            )
        ).hexdigest()[:12]
        for item in ctx.persisted_gate.get("issues", [])
        if str(item).strip()
    }


async def initialize_revision(ctx: RevisionLoopContext) -> None:
    ctx.run_state = RunState(ctx.run.project_path, ctx.run.id)
    ctx.saved_revision = ctx.run_state.revision_state(ctx.node.id)
    from ..services.skill_orchestrator import resolve_execution_contract

    ctx.execution_contract = resolve_execution_contract(
        ctx.node.id, ctx.opts, project_path=ctx.run.project_path,
    )
    ctx.gate_runtime_service = (
        ctx.execution_contract.runtime_service
        if (ctx.execution_contract.kind == "hybrid" or ctx.node.id == "figure")
        and ctx.node.id in {"exp-design", "results", "figure", "narrative", "paper"}
        else ""
    )
    ctx.raw_owner_rounds = ctx.saved_revision.get("owner_rounds")
    ctx.owner_rounds = {
        str(owner_id): bounded_round(owner_round, ctx.max_revision_rounds)
        for owner_id, owner_round in (
            ctx.raw_owner_rounds.items()
            if isinstance(ctx.raw_owner_rounds, dict)
            else []
        )
        if str(owner_id).strip()
    }
    ctx.active_owner_id = str(
        ctx.saved_revision.get("active_owner_id")
        or ctx.saved_revision.get("artifact_owner_id")
        or ctx.node.id
    )
    if not ctx.owner_rounds and bounded_round(
        ctx.saved_revision.get("round"), ctx.max_revision_rounds
    ):
        ctx.owner_rounds[ctx.active_owner_id] = bounded_round(
            ctx.saved_revision.get("round"), ctx.max_revision_rounds
        )
    ctx.round_number = ctx.owner_rounds.get(ctx.active_owner_id, 0)
    ctx.cycle = max(1, int(ctx.saved_revision.get("cycle") or 1))
    if ctx.saved_revision.get("waiting"):
        ctx.cycle += 1
    ctx.result = ctx.initial_result or ""
    ctx.first_gate = True
    ctx.last_revision_attempt_round = 0
    ctx.last_revision_method = ""
    ctx.last_revision_owner_id = ctx.active_owner_id


async def initialize_progress(ctx: RevisionLoopContext) -> None:
    ctx.last_revision_scope_before = ""
    ctx.last_revision_scope_diagnostics: dict[str, Any] = {}
    ctx.last_revision_execution_succeeded = False
    ctx.last_revision_event_pending = False
    ctx.pending_feedback = ""
    ctx.transport_failures = 0
    ctx.last_execution_error: dict[str, Any] | None = None
    ctx.consumer_refresh_upstream_gate: dict[str, Any] | None = None
    ctx.consumer_refresh_required = bool(
        ctx.saved_revision.get("consumer_refresh_required")
    )
    ctx.owner_last_finding_ids: dict[str, set[str]] = {}
    ctx.owner_last_scope_signatures: dict[str, str] = {}
    ctx.owner_last_draft_review_signatures: dict[str, str] = {}
    ctx.owner_no_progress_counts: dict[str, int] = {}
    try:
        ctx.no_progress_limit = int(ctx.opts.get("revision_no_progress_limit") or 2)
    except (TypeError, ValueError):
        ctx.no_progress_limit = 2
    ctx.no_progress_limit = min(3, max(2, ctx.no_progress_limit))
    ctx.persisted_gate = (
        ctx.saved_revision.get("last_gate")
        if isinstance(ctx.saved_revision.get("last_gate"), dict)
        else {}
    )
    ctx.persisted_progress = (
        ctx.persisted_gate.get("revision_progress")
        if isinstance(ctx.persisted_gate.get("revision_progress"), dict)
        else {}
    )
    ctx.persisted_scope = (
        ctx.persisted_gate.get("repair_scope")
        if isinstance(ctx.persisted_gate.get("repair_scope"), dict)
        else {}
    )
    if not ctx.persisted_scope:
        history = ctx.saved_revision.get("history")
        if isinstance(history, list):
            history = history[int(ctx.saved_revision.get("progress_history_start") or 0):]
        if isinstance(history, list) and history:
            latest_history = history[-1]
            if isinstance(latest_history, dict):
                ctx.persisted_scope = (
                    latest_history.get("repair_scope")
                    if isinstance(latest_history.get("repair_scope"), dict)
                    else {}
                )
                if not ctx.persisted_progress and isinstance(
                    latest_history.get("revision_progress"), dict
                ):
                    ctx.persisted_progress = latest_history["revision_progress"]


async def restore_progress(ctx: RevisionLoopContext) -> None:
    if ctx.active_owner_id:
        restored_ids = persisted_ids(ctx)
        if restored_ids:
            ctx.owner_last_finding_ids[ctx.active_owner_id] = restored_ids
        restored_scope = str(
            ctx.persisted_progress.get("scope_signature") or ""
        ).strip()
        if not restored_scope and ctx.persisted_gate:
            try:
                restored_scope = ctx.host._revision_scope_signature(
                    ctx.run.project_path,
                    ctx.active_owner_id,
                    ctx.persisted_gate,
                    ctx.opts,
                )
            except Exception:
                restored_scope = ""
        if restored_scope:
            ctx.owner_last_scope_signatures[ctx.active_owner_id] = restored_scope
        restored_draft_review = str(
            ctx.persisted_progress.get("draft_review_signature") or ""
        ).strip()
        if restored_draft_review:
            ctx.owner_last_draft_review_signatures[
                ctx.active_owner_id
            ] = restored_draft_review
        try:
            restored_no_progress = int(
                ctx.persisted_progress.get("consecutive_no_progress") or 0
            )
        except (TypeError, ValueError):
            restored_no_progress = 0
        ctx.owner_no_progress_counts[ctx.active_owner_id] = min(
            ctx.no_progress_limit, max(0, restored_no_progress)
        )
    ctx.max_transport_failures = max(
        3, min(5, int(ctx.opts.get("max_retries", 3) or 3))
    )
    ctx.transport_attempt_since_gate = False
    if ctx.run.checkpoint_node_id == ctx.node.id and ctx.run.checkpoint_feedback:
        ctx.pending_feedback = ctx.run.checkpoint_feedback.strip()
        ctx.run.checkpoint_feedback = ""
        ctx.run.checkpoint_node_id = ""


async def prepare_gate_artifacts(ctx: RevisionLoopContext) -> None:
    """Preserve typed producer failures; unexpected execution faults still propagate."""
    from ..services.figure_producer_errors import DeterministicFigureProducerError
    from ..services.paper_acceptance_errors import PaperAcceptanceError
    from ..services.paper_preparation_errors import PaperPreparationError

    ctx.preparation_error = ""
    ctx.preparation_failure_details = {}
    try:
        if ctx.node.id in {'exp-design', 'exp-run', 'results', 'paper', 'review', 'audit'} and ctx.opts.get('run_experiment') is True:
            from ..services.independent_matrix_audit import audit_current_matrix
            audit_current_matrix(Path(ctx.run.project_path))
        if ctx.node.id == "exp-run" and ctx.opts.get("run_experiment") is True:
            from .managed_experiment_execution import _run_contract
            _run_contract(ctx.host, ctx.run, ctx.opts)
        if ctx.node.id in {"exp-design", "figure", "paper"}:
            from ..services.evaluation_protocol_validation import validate_project_evaluation
            validate_project_evaluation(Path(ctx.run.project_path))
        ctx.result = await ctx.host._prepare_node_for_gate(
            ctx.node,
            ctx.run,
            ctx.result,
            ctx.research_direction,
            ctx.assurance,
            ctx.opts,
        )
    except PreparationContractError as exc:
        ctx.preparation_error = str(exc)
        ctx.preparation_failure_details = exc.details()
    except (DeterministicFigureProducerError, PaperAcceptanceError, PaperPreparationError) as exc:
        ctx.preparation_error = str(exc)
        ctx.preparation_failure_details = exc.gate_details()


async def prepare_consumer_state(ctx: RevisionLoopContext) -> None:
    if ctx.run.status == "cancelled":
        raise RevisionComplete(({"accepted": False, "cancelled": True}, ctx.result))
    await prepare_gate_artifacts(ctx)
    if ctx.node.id in {"review", "audit"}:
        try:
            from ..services.node_risk_audit import node_risk_audit_service

            fresh_preflight = node_risk_audit_service.preflight_node(
                ctx.run.project_path, ctx.node.id, ctx.opts
            )
            previous_preflight = (
                ctx.run.options.get("_node_preflight_findings", {}).get(ctx.node.id, [])
                if isinstance(ctx.run.options.get("_node_preflight_findings"), dict)
                else []
            )
            ctx.preflight_for_current = []
            seen_preflight: set[tuple[str, str]] = set()
            for item in [
                *previous_preflight,
                *[
                    candidate
                    for candidate in fresh_preflight
                    if isinstance(candidate, dict)
                    and (
                        str(candidate.get("category") or "").casefold() == "freshness"
                        or "stale" in str(candidate.get("message") or "").casefold()
                        or "过期" in str(candidate.get("plain_message") or "")
                        or ("changed" in str(candidate.get("message") or "").casefold())
                        or ("变化" in str(candidate.get("plain_message") or ""))
                    )
                ],
            ]:
                if not isinstance(item, dict):
                    continue
                marker = (
                    str(item.get("id") or ""),
                    str(item.get("message") or item.get("plain_message") or ""),
                )
                if marker in seen_preflight:
                    continue
                seen_preflight.add(marker)
                ctx.preflight_for_current.append(item)
            ctx.run.options.setdefault("_node_preflight_findings", {})[ctx.node.id] = (
                ctx.preflight_for_current
            )
        except Exception:
            ctx.preflight_for_current = []
    else:
        ctx.preflight_for_current = (
            ctx.run.options.get("_node_preflight_findings", {}).get(ctx.node.id, [])
            if isinstance(ctx.run.options.get("_node_preflight_findings"), dict)
            else []
        )


async def load_consumer_refresh(ctx: RevisionLoopContext) -> None:
    if not ctx.consumer_refresh_required and ctx.node.id in {"review", "audit"}:
        ctx.stale_snapshot_findings = [
            item
            for item in ctx.preflight_for_current
            if isinstance(item, dict)
            and str(item.get("severity") or "").casefold() == "blocker"
            and (
                str(item.get("category") or "").casefold() == "freshness"
                or any(
                    (
                        marker
                        in str(
                            item.get("message") or item.get("plain_message") or ""
                        ).casefold()
                        for marker in (
                            "source bundle is stale",
                            "snapshot is stale",
                            "hash-bound to the current",
                            "evidence packet is incomplete or stale",
                        )
                    )
                )
            )
        ]
        try:
            if ctx.node.id == "review":
                from .review_audit import review_source_bundle

                managed_state_path = (
                    Path(ctx.run.project_path) / "review-stage" / "REVIEW_STATE.json"
                )
                managed_payload = json.loads(
                    managed_state_path.read_text(encoding="utf-8-sig")
                )
                managed_source_hash = str(
                    managed_payload.get("source_bundle_sha256") or ""
                )
                live_source_hash, _ = review_source_bundle(ctx.run.project_path)
            else:
                from .review_audit import audit_source_bundle

                managed_state_path = (
                    Path(ctx.run.project_path) / "audit-results" / "AUDIT_BUILD.json"
                )
                managed_payload = json.loads(
                    managed_state_path.read_text(encoding="utf-8-sig")
                )
                managed_source_hash = str(
                    managed_payload.get("source_bundle_sha256") or ""
                )
                live_source_hash, _ = audit_source_bundle(ctx.run.project_path)
            if (
                managed_source_hash
                and live_source_hash
                and (managed_source_hash != live_source_hash)
            ):
                ctx.stale_snapshot_findings.append(
                    {
                        "id": f"{ctx.node.id.upper()}-SOURCE-BINDING-STALE",
                        "severity": "blocker",
                        "category": "freshness",
                        "owner_node": ctx.node.id,
                        "message": f"Managed {ctx.node.id} source bundle is stale for the current research artifacts.",
                    }
                )
        except (OSError, UnicodeError, json.JSONDecodeError):
            pass


async def persist_consumer_refresh(ctx: RevisionLoopContext) -> None:
    if not ctx.consumer_refresh_required and ctx.node.id in {"review", "audit"}:
        if ctx.stale_snapshot_findings:
            refresh_reason = "; ".join(
                (
                    str(item.get("plain_message") or item.get("message") or "").strip()
                    for item in ctx.stale_snapshot_findings[:4]
                )
            )
            ctx.run_state.require_consumer_refresh(
                ctx.node.id, owner_id=ctx.node.id, reason=refresh_reason
            )
            ctx.consumer_refresh_required = True
            ctx.saved_revision["consumer_refresh_owner_id"] = ctx.node.id
            await ctx.host._emit(
                ctx.run,
                "consumer_snapshot_refresh_required",
                {
                    "node_id": ctx.node.id,
                    "upstream_owner_id": ctx.node.id,
                    "reason": refresh_reason[:1000],
                    "detected_from_freshness_gate": True,
                },
            )


async def collect_upstream_blockers(ctx: RevisionLoopContext) -> None:
    ctx.current_upstream_blockers = [
        item
        for item in ctx.preflight_for_current
        if isinstance(item, dict)
        and item.get("severity") == "blocker"
        and str(item.get("upstream_node") or "").strip()
        and (str(item.get("upstream_node") or "").strip() != ctx.node.id)
    ]
    ctx.consumer_refresh_upstream_gate = None


async def hold_refresh_for_upstream(ctx: RevisionLoopContext) -> None:
    if (
        (ctx.node.id == "paper" or (ctx.consumer_refresh_required and ctx.node.id in {"review", "audit"}))
        and ctx.current_upstream_blockers
    ):
        upstream_messages = list(
            dict.fromkeys(
                (
                    str(item.get("plain_message") or item.get("message") or "").strip()
                    for item in ctx.current_upstream_blockers
                    if str(
                        item.get("plain_message") or item.get("message") or ""
                    ).strip()
                )
            )
        )
        ctx.consumer_refresh_upstream_gate = {
            "accepted": False,
            "reason": "managed consumer refresh is waiting for upstream dependencies",
            "summary": "; ".join(upstream_messages)[:2000],
            "details": {
                "issues": upstream_messages,
                "node_risk_audit": {
                    "passed": False,
                    "findings": ctx.current_upstream_blockers,
                },
            },
        }


async def prepare_scientific_stage(ctx: RevisionLoopContext) -> None:
    staged = ctx.run.options.get("_staged_implementation_report")
    if (ctx.node.id == "exp-design" and isinstance(staged, dict)
            and staged.get("blocking")):
        return
    if (
        ctx.consumer_refresh_required
        and ctx.node.id in {"review", "audit"}
        and (not ctx.preparation_error)
        and (not ctx.current_upstream_blockers)
    ):
        refresh_owner_id = str(
            ctx.saved_revision.get("consumer_refresh_owner_id") or ""
        )
        await ctx.host._emit(
            ctx.run,
            "consumer_snapshot_refresh_started",
            {
                "node_id": ctx.node.id,
                "upstream_owner_id": refresh_owner_id,
                "message": "Upstream repairs are fresh; regenerating the managed consumer verdict before routing any prior finding.",
            },
        )
        try:
            if ctx.node.id == "review":
                ctx.result = await ctx.host._execute_review_node(
                    ctx.node, ctx.run, ctx.assurance, ctx.opts
                )
            else:
                ctx.result = await ctx.host._execute_audit_node(
                    ctx.node, ctx.run, ctx.assurance
                )
        except Exception:
            raise  # Execution failures must reach the durable interruption boundary.
        else:
            ctx.run_state.clear_consumer_refresh(ctx.node.id)
            ctx.consumer_refresh_required = False
            ctx.owner_last_finding_ids.clear()
            ctx.owner_last_scope_signatures.clear()
            ctx.owner_no_progress_counts.clear()
            ctx.active_owner_id = ctx.node.id
            ctx.round_number = ctx.owner_rounds.get(ctx.node.id, 0)
            ctx.cycle += 1
            ctx.last_revision_attempt_round = 0
            ctx.last_revision_owner_id = ctx.node.id
            ctx.last_revision_scope_before = ""
            ctx.last_revision_scope_diagnostics = {}
            ctx.last_revision_execution_succeeded = False
            ctx.last_revision_event_pending = False
            ctx.last_execution_error = None
            await ctx.host._emit(
                ctx.run,
                "consumer_snapshot_refreshed",
                {
                    "node_id": ctx.node.id,
                    "upstream_owner_id": refresh_owner_id,
                    "cycle": ctx.cycle,
                },
            )
    if not ctx.preparation_error and ctx.node.id in {"exp-design", "results"}:
        specialist_result = await ctx.host._execute_profile_specialists(
            node=ctx.node, run=ctx.run, direction=ctx.research_direction, opts=ctx.opts
        )
        if not specialist_result.get("accepted"):
            ctx.preparation_error = str(
                specialist_result.get("error")
                or "required specialist subnode did not complete"
            )
