"""Keep implementation repairs within their declared ownership boundaries."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..services.method_contract import method_contract_service
from ..services.implementation_stages import ImplementationStage
from ..services.impl_stage_targets import target_declaration
from ..services.workflow_inputs import artifact_state, artifact_state_equal
from .implementation_execution_contracts import (
    AttemptProtection,
    ImplementationContext,
    ImplementationStageState,
)
from ..contracts.implementation_evidence import parse_evidence_patch_document
from ..services.method_contract_persistence import apply_implementation_evidence_patches
from .implementation_declared_handoff import bind_declared_owner_handoff


def _method_payload(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _stale_stage_report(
    context: ImplementationContext,
    state: ImplementationStageState,
) -> dict[str, Any]:
    report, previous, stage = state.report, state.previous_record, state.stage
    if (not report.get("passed") or previous.get("status") not in {"accepted", "needs_revision"}
            or not previous.get("input_sha256") or not previous.get("output_sha256")):
        return report
    stale = []
    if str(previous.get("input_sha256") or "") != context.service.input_hash(
        context.run.project_path,
        stage.id,
        context.direction,
    ):
        stale.append("upstream/input contract changed")
    if str(previous.get("output_sha256") or "") != context.service.output_hash(
        context.run.project_path,
        stage.id,
    ):
        stale.append("stage-owned output changed")
    if stale:
        return {
            **report,
            "passed": False,
            "issues": [
                "accepted stage fingerprint is stale: "
                + "; ".join(stale)
                + ". Reconcile this stage with the current frozen contracts.",
            ],
        }
    return report


def prepare_stage(
    context: ImplementationContext, stage: ImplementationStage
) -> ImplementationStageState:
    report = context.service.validate_stage(
        context.run.project_path, stage.id, context.direction
    )
    targets = list(stage.targets)
    if stage.id == "integration":
        targets.extend(
            str(item).replace("\\", "/")
            for item in report.get("repair_targets") or []
            if str(item).strip()
        )
        targets = list(dict.fromkeys(targets))
    build = context.service.load_build(context.run.project_path)
    records = build.get("stages") if isinstance(build, dict) else {}
    records = records if isinstance(records, dict) else {}
    previous = records.get(stage.id)
    state = ImplementationStageState(
        stage, report, targets, previous if isinstance(previous, dict) else {}
    )
    state.report = _stale_stage_report(context, state)
    from ..services.implementation_review_receipt import pending_stage_obligations
    obligations = pending_stage_obligations(context.service, context.root, stage.id, context.direction, targets)
    if obligations:
        state.report = {**state.report, "passed": False, "issues": list(dict.fromkeys([
            *obligations, *list(state.report.get("issues") or []),
        ]))}
    state.report = bind_declared_owner_handoff(context, state, state.report)
    return state


def capture_protected_inputs(
    context: ImplementationContext,
    state: ImplementationStageState,
) -> AttemptProtection:
    root = context.root
    protected = [
        root / "ideas" / "SELECTED_IDEA.json",
        root / "experiments" / "IMPLEMENTATION_BLUEPRINT.json",
        root / "experiments" / "EXPERIMENT_PLAN.md",
    ]
    for stage in context.stages:
        if stage.id == state.stage.id:
            continue
        protected.extend(
            root / relative
            for relative in stage.targets
            if relative not in set(state.effective_targets)
        )
    if state.stage.id != "integration":
        protected.extend(
            [
                root / "experiments" / "RUN_SPEC.json",
                root / "experiments" / "configs" / "main.yaml",
            ]
        )
    method_path = root / "experiments" / "METHOD_CONTRACT.json"
    protected.append(method_path)
    return AttemptProtection(
        {path: artifact_state(path) for path in protected},
        method_path,
        _method_payload(method_path),
        target_declaration(root),
    )


def _merge_issues(report: dict[str, Any], issues: list[str]) -> dict[str, Any]:
    return {
        **report,
        "passed": False,
        "issues": list(dict.fromkeys([*list(report.get("issues") or []), *issues])),
    }


def _refresh_integration_dependencies(
    context: ImplementationContext,
    state: ImplementationStageState,
    report: dict[str, Any],
) -> dict[str, Any]:
    """Input changes require their owning stage; integration cannot rebind old code."""
    records = context.service.load_build(context.root).get("stages") or {}
    authorized_targets = set(state.effective_targets) - set(state.stage.targets)
    issues: list[str] = []
    owner_reconciliation: list[str] = []
    for stage in context.stages:
        if stage.id == "integration":
            break
        record = records.get(stage.id) or {}
        if record.get("status") != "accepted":
            issues.append(f"{stage.id}: integration requires a prior accepted owner stage")
            break
        output_changed = record.get("output_sha256") != context.service.output_hash(
            context.root, stage.id,
        )
        input_changed = record.get("input_sha256") != context.service.input_hash(
            context.root, stage.id, context.direction,
        )
        if not input_changed and not output_changed:
            continue
        if input_changed and not output_changed:
            issues.append(f"{stage.id}: integration changed scientific inputs; owning stage must reconcile before reuse")
            owner_reconciliation.append(stage.id)
            break
        if output_changed and not authorized_targets.intersection(stage.targets):
            issues.append(f"{stage.id}: owned artifacts changed without a finding-routed repair")
            break
        candidate = context.service.validate_stage(
            context.run.project_path, stage.id, context.direction
        )
        context.service.record_stage(
            context.run.project_path,
            stage.id,
            candidate,
            context.direction,
            attempts=int(record.get("attempts") or 0),
            session_summaries=[
                *list(record.get("session_summaries") or [])[-1:],
                "Deterministically revalidated after integration updated declared dependencies."
            ],
        )
        if not candidate.get("passed"):
            issues.extend(
                f"{stage.id}: {item}" for item in candidate.get("issues") or []
            )
            break
    if issues:
        return {**_merge_issues(report, issues), "owner_reconciliation_required": owner_reconciliation}
    return report


def reconcile_attempt(
    context: ImplementationContext,
    state: ImplementationStageState,
    protection: AttemptProtection,
) -> dict[str, Any]:
    try:
        declaration = target_declaration(context.root)
    except (ValueError, RuntimeError) as error:
        return _merge_issues(state.report, [f"stage modified runtime-owned target declaration: {error}"])
    if declaration != protection.stage_target_declaration:
        return _merge_issues(state.report, ["stage modified runtime-owned implementation_stage_targets declaration"])
    violations = [
        path.relative_to(context.root).as_posix()
        for path, before in protection.protected_before.items()
        if not artifact_state_equal(before, artifact_state(path))
    ]
    if violations:
        return {
            **_merge_issues(state.report, [
                "stage modified protected upstream/frozen artifacts: "
                + ", ".join(violations)
            ]),
            "ownership_violations": violations,
        }
    if state.stage.id == "integration":
        patch_path = context.root / "experiments/IMPLEMENTATION_EVIDENCE_PATCH.json"
        try:
            patches = parse_evidence_patch_document(_method_payload(patch_path))
            apply_implementation_evidence_patches(
                protection.method_path, patches,
            )
        except (OSError, UnicodeError, ValueError) as error:
            return _merge_issues(
                state.report,
                [f"integration evidence patch is invalid: {error}"],
            )
    report = context.service.validate_stage(
        context.run.project_path, state.stage.id, context.direction
    )
    if state.stage.id == "integration":
        report = _refresh_integration_dependencies(context, state, report)
        from ..services.implementation_stage_validation import (
            integration_candidate_report,
        )
        candidate = integration_candidate_report(report)
        if candidate.get("passed"):
            method_contract_service.finalize_integration_contract(
                context.run.project_path,
                candidate,
            )
            report = context.service.validate_stage(
                context.run.project_path, state.stage.id, context.direction,
            )
    return bind_declared_owner_handoff(context, state, report)


def expand_integration_targets(state: ImplementationStageState) -> list[str]:
    if state.stage.id != "integration" or state.report.get("passed"):
        return []
    targets = [
        str(item).replace("\\", "/")
        for item in state.report.get("repair_targets") or []
        if str(item).strip()
        and str(item).replace("\\", "/") not in state.effective_targets
    ]
    if targets:
        state.effective_targets = list(
            dict.fromkeys([*state.effective_targets, *targets])
        )
    return targets
