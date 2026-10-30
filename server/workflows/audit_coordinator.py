"""Coordinate five scientific audit layers plus the proof-checker pass."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Optional

import structlog

from .review_models import AuditResult, Verdict

logger = structlog.get_logger()

_ALLOWED_MODES = {
    "executed", "existing_results", "secondary_analysis", "design_only",
    "synthetic_preview", "execution_pending", "planned",
}


@dataclass
class AuditContext:
    chain: Any
    paper_path: str
    experiment_dir: str
    project_path: str
    on_progress: Optional[Any]
    evidence_mode: str
    layer_timeout_seconds: int
    run_id: str


async def run_full_audit(context: AuditContext) -> list[AuditResult]:
    from .draft_delivery import AUDIT_DELIVERY, run_delivery_goal
    token = AUDIT_DELIVERY.set(run_delivery_goal(context.project_path, context.run_id))
    try:
        return await _run_full_audit(context)
    finally:
        AUDIT_DELIVERY.reset(token)


async def _run_full_audit(context: AuditContext) -> list[AuditResult]:
    context.evidence_mode = (
        context.evidence_mode if context.evidence_mode in _ALLOWED_MODES
        else "design_only"
    )
    context.layer_timeout_seconds = _normalized_timeout(
        context.layer_timeout_seconds
    )
    start = _start_contract(context.project_path)
    from .audit_layer_checkpoint import load_layer_checkpoints, save_layer_checkpoints

    reusable = context.chain._load_reusable_model_results(
        context.project_path, run_id=context.run_id,
        evidence_mode=context.evidence_mode,
    )
    reusable.update(load_layer_checkpoints(context, start))
    from .draft_delivery import AUDIT_DELIVERY, DRAFT
    if AUDIT_DELIVERY.get() == DRAFT:
        reusable = {layer: result for layer, result in reusable.items()
                    if layer == 6 or result.delivery_goal == DRAFT and result.draft_blockers is not None}
    results: list[AuditResult] = []
    layers = (
        (1, "Experiment Audit", context.chain._audit_experiment),
        (2, "Result-to-Claim", context.chain._audit_result_to_claim),
        (3, "Paper Claim Audit", context.chain._audit_paper_claims),
        (4, "Citation Audit", context.chain._audit_citations),
        (5, "Kill Argument", context.chain._audit_kill_argument),
    )
    for number, name, operation in layers:
        result = await _run_scientific_layer(
            context, number, name, operation, reusable.get(number)
        )
        results.append(result)
        save_layer_checkpoints(context, start, results)
    results.append(await _run_proof_layer(context, reusable.get(6)))
    save_layer_checkpoints(context, start, results)
    context.chain._save_results(
        results, context.project_path, context.evidence_mode,
        run_id=context.run_id,
        expected_source_bundle_sha256=start["source_hash"],
        expected_audit_runtime_signature=start["runtime_signature"],
        expected_reviewer_route_sha256=start["route_hash"],
        expected_policy_sha256=start["policies"],
    )
    return results


def _api() -> Any:
    from . import review_audit

    return review_audit


def _normalized_timeout(value: int) -> int:
    minimum = int(_api().REVIEW_MODEL_CALL_TIMEOUT_SECONDS) + 60
    return max(minimum, min(900, int(value or minimum)))


def _start_contract(project_path: str) -> dict[str, Any]:
    api = _api()
    from .draft_delivery import AUDIT_DELIVERY
    source_hash, _ = api.audit_source_bundle(project_path)
    route = api.audit_reviewer_route()
    return {
        "source_hash": source_hash,
        "delivery_goal": AUDIT_DELIVERY.get(),
        "runtime_signature": api.audit_runtime_signature(),
        "route_hash": api.audit_reviewer_route_sha256(route),
        "policies": {
            layer: api.audit_policy_sha256(skill)
            for layer, skill in api.AUDIT_LAYER_SKILLS.items()
        },
    }


async def _run_scientific_layer(
    context: AuditContext, number: int, name: str, operation: Any,
    reusable: AuditResult | None,
) -> AuditResult:
    if reusable is not None:
        reusable.layer_name = name
        if context.on_progress:
            await context.on_progress(
                f"Layer {number}/5: {name} — reusing verified same-run model "
                "result; inputs unchanged"
            )
        return reusable
    if context.on_progress:
        await context.on_progress(f"Layer {number}/5: {name}")
    result = await _invoke_layer(context, number, name, operation)
    _require_completed_call(result, number, name)
    from .draft_delivery import AUDIT_DELIVERY, DRAFT
    result.delivery_goal = AUDIT_DELIVERY.get()
    if result.delivery_goal == DRAFT and result.draft_blockers is None:
        raise ValueError(f"Audit layer {number} omitted independent draft integrity findings")
    result.layer = number
    result.layer_name = name
    logger.info("Audit layer complete", layer=number, name=name, verdict=result.verdict.value)
    return result


def _require_completed_call(result: AuditResult, number: int, name: str) -> None:
    if result.method in {"parse_error", "model_error", "deterministic_fallback"} or result.verdict == Verdict.ERROR:
        raise RuntimeError(f"Audit layer {number} ({name}) interrupted: {result.summary}. Resume this layer after repair.")


async def _invoke_layer(
    context: AuditContext, number: int, name: str, operation: Any
) -> AuditResult:
    activity = {"at": time.monotonic()}

    async def event(_event: Any) -> None:
        activity["at"] = time.monotonic()

    async def invoke() -> AuditResult:
        return await operation(
            context.paper_path, context.experiment_dir, context.project_path,
            context.evidence_mode, on_event=event,
        )

    from .review_audit import CrossModelReviewer

    return await CrossModelReviewer._run_fix_with_progress(
        invoke,
        timeout_seconds=max(900.0, context.layer_timeout_seconds * 5.0),
        idle_timeout_seconds=float(context.layer_timeout_seconds),
        on_progress=context.on_progress,
        progress_label=f"Layer {number}/5 {name}",
        last_activity=lambda: activity["at"],
    )


async def _run_proof_layer(
    context: AuditContext, reusable: AuditResult | None
) -> AuditResult:
    if reusable is not None:
        if context.on_progress:
            await context.on_progress(
                "Proof audit: Proof Checker — reusing verified same-run result; "
                "inputs unchanged"
            )
        return reusable
    if context.on_progress:
        await context.on_progress("Proof audit: /proof-checker")
    detector = context.chain._proof_detector_result(context.project_path)
    if detector is not None:
        return detector
    result = await _invoke_proof(context)
    _require_completed_call(result, 6, "Proof Checker")
    result.layer = 6
    result.layer_name = "Proof Checker"
    logger.info("Proof audit complete", verdict=result.verdict.value)
    return result


async def _invoke_proof(context: AuditContext) -> AuditResult:
    activity = {"at": time.monotonic()}

    async def event(_event: Any) -> None:
        activity["at"] = time.monotonic()

    async def invoke() -> AuditResult:
        return await context.chain._audit_proofs(
            context.paper_path, context.experiment_dir, context.project_path,
            context.evidence_mode, on_event=event,
        )

    from .review_audit import CrossModelReviewer

    return await CrossModelReviewer._run_fix_with_progress(
        invoke,
        timeout_seconds=max(900.0, context.layer_timeout_seconds * 5.0),
        idle_timeout_seconds=float(context.layer_timeout_seconds),
        on_progress=context.on_progress,
        progress_label="Proof audit /proof-checker",
        last_activity=lambda: activity["at"],
    )
