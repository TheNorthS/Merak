"""Resume durable runs after deterministic input and acceptance revalidation."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any, Protocol

from ..services.workflow_inputs import workflow_input_service
from .engine_context import (
    normalize_revision_rounds,
    normalize_workflow_illustration_mode,
)
from .models import WorkflowNode, WorkflowRun
from .run_state import RunState


IMMUTABLE_RESUME_OPTIONS = {
    "run_experiment",
    "non_experiment_evidence_mode",
    "illustration_mode",
    "evidence_import_manifest",
    "input_files",
    "research_mode",
    "reference_snapshot_id",
}


class ResumeHost(Protocol):
    def _get_default_nodes(self) -> list[WorkflowNode]: ...
    def _resumable_phase_ids(
        self, state: dict[str, Any], node_ids: list[str] | None = None
    ) -> list[str]: ...
    def _phase_is_durably_terminal(self, phase: dict[str, Any]) -> bool: ...
    async def _refresh_simulation_renderer_before_revalidation(
        self,
        run: WorkflowRun,
        direction: str,
    ) -> None: ...
    def _validated_accepted_phase_ids(
        self, run: WorkflowRun, state: RunState
    ) -> list[str]: ...
    async def execute(self, **options: Any) -> str: ...


def _requested_options(
    state: dict[str, Any],
    overrides: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    config = state.get("config")
    config = config if isinstance(config, dict) else {}
    saved = dict(config.get("options") or {})
    saved.pop("_evidence_version_approval", None)
    requested_overrides = dict(overrides or {})
    for key in IMMUTABLE_RESUME_OPTIONS:
        requested_overrides.pop(key, None)
    requested = {**saved, **requested_overrides}
    requested["illustration_mode"] = normalize_workflow_illustration_mode(
        requested.get("illustration_mode"),
    )
    requested["max_revision_rounds"] = normalize_revision_rounds(
        requested.get("max_revision_rounds"),
    )
    return requested, config


def _input_baseline(
    durable: RunState,
    state: dict[str, Any],
    project_path: str,
    saved_options: dict[str, Any],
    run_id: str,
) -> dict[str, Any]:
    baseline = dict(state.get("input_baseline") or {})
    if baseline:
        return baseline
    baseline = workflow_input_service.capture(
        project_path,
        saved_options.get("input_files") or [],
        run_id=run_id,
    )
    state = (
        durable.update_state(
            lambda latest: (
                latest
                if latest.get("input_baseline")
                else {
                    **latest,
                    "input_baseline": dict(baseline),
                }
            ),
        )
        or state
    )
    return dict(state.get("input_baseline") or baseline)


def _dependency_closure(
    host: ResumeHost,
    state: dict[str, Any],
    selected: list[str],
) -> list[str]:
    phases = state.get("phases")
    phases = phases if isinstance(phases, dict) else {}
    definitions = {node.id: node for node in host._get_default_nodes()}
    required, queue = set(selected), list(selected)
    while queue:
        current = queue.pop()
        definition = definitions.get(current)
        if definition is None:
            continue
        for dependency in definition.depends_on:
            if (
                dependency in phases
                and dependency not in required
                and not host._phase_is_durably_terminal(phases.get(dependency, {}))
            ):
                required.add(dependency)
                queue.append(dependency)
    return [
        phase_id
        for phase_id in phases
        if phase_id in required
        and not host._phase_is_durably_terminal(phases.get(phase_id, {}))
    ]


async def _revalidated_resume_state(
    host: ResumeHost,
    run_id: str,
    project_path: str,
    node_ids: list[str] | None,
    research_direction: str,
    overrides: dict[str, Any] | None,
) -> tuple[RunState, dict[str, Any], dict[str, Any], list[str]]:
    durable = RunState(project_path, run_id)
    state = durable.load()
    if not state:
        raise ValueError(f"Run state not found: {run_id}")
    requested, config = _requested_options(state, overrides)
    saved_options = dict((state.get("config") or {}).get("options") or {})
    baseline = _input_baseline(durable, state, project_path, saved_options, run_id)
    issues = workflow_input_service.validate_snapshot(project_path, baseline)
    if issues:
        raise ValueError(
            "; ".join(issues)
            + ". Start a new workflow run to accept changed research inputs.",
        )
    from .report_revision_recovery import active_report_consumer
    report_consumer = active_report_consumer(state)
    if report_consumer:
        return durable, state, requested, [report_consumer]
    validation = WorkflowRun(
        id=run_id,
        project_path=project_path,
        options=requested,
        input_baseline=baseline,
    )
    await host._refresh_simulation_renderer_before_revalidation(
        validation,
        research_direction or str(config.get("direction") or ""),
    )
    from .result_resume_refresh import refresh_accepted_benchmark_analysis
    await refresh_accepted_benchmark_analysis(host, validation, state,
        research_direction or str(config.get("direction") or ""))
    from .owner_revision_scope import revalidate_unaffected_owner_phases
    await asyncio.to_thread(revalidate_unaffected_owner_phases, host, validation, durable)
    from .revoked_acceptance_recovery import revalidate_unchanged_revoked_outputs
    await asyncio.to_thread(revalidate_unchanged_revoked_outputs, host, validation, durable)
    await asyncio.to_thread(host._validated_accepted_phase_ids, validation, durable)
    state = durable.load() or state
    selected = host._resumable_phase_ids(state, node_ids)
    if node_ids is not None and selected:
        selected = _dependency_closure(host, state, selected)
    if not selected:
        raise ValueError(f"Run has no resumable phases: {run_id}")
    return durable, state, requested, selected


def _unchanged_checkpoint_action(
    host: Any,
    durable: RunState,
    phase_id: str,
    phase: dict[str, Any],
    options: dict[str, Any],
    *,
    watchdog: bool,
) -> None:
    revision = (phase.get("details") or {}).get("revision") or {}
    saved_artifact = str(revision.get("artifact_signature") or "")
    saved_runtime = str(revision.get("runtime_signature") or "")
    owner = str(revision.get("artifact_owner_id") or phase_id)
    artifact = host._revision_artifact_signature(durable.project_path, owner, options)
    runtime = host._revision_runtime_signature(durable.project_path, owner, options)
    if saved_artifact and saved_artifact != artifact:
        durable.reset_revision_for_runtime_change(
            phase_id,
            runtime_signature=runtime,
            reason="research artifact or validator signature changed",
        )
        return
    if not saved_artifact or saved_artifact != artifact:
        return
    runtime_changed = bool(saved_runtime and saved_runtime != runtime)
    if runtime_changed:
        durable.reset_revision_for_runtime_change(
            phase_id,
            runtime_signature=runtime,
            reason="workflow runtime capability contract changed",
        )
        return
    if host._is_transport_revision_checkpoint(revision):
        return
    last_gate = revision.get("last_gate")
    if (phase_id == "figure" and isinstance(last_gate, dict)
            and last_gate.get("error_category") == "figure_retry_deferred"):
        raise ValueError(
            "figure 的未接受图稿和生产者均未变化，恢复令牌不能重开已耗尽的画图预算。"
            "请先修改该图的来源/规格、更新生产者，或提交针对具体图稿的反馈。"
        )
    if host._is_platform_repair_revision_checkpoint(revision):
        _reopen_platform_checkpoint(
            host, durable, phase_id, revision, runtime, options, watchdog
        )
        return
    raise ValueError(
        f"{phase_id} 的科研产物自上次质量检查后没有变化。"
        "请先修改产物或在检查点提交具体反馈，避免重复执行同一轮。",
    )


def _reopen_platform_checkpoint(
    host: Any,
    durable: RunState,
    phase_id: str,
    revision: dict[str, Any],
    runtime: str,
    options: dict[str, Any],
    watchdog: bool,
) -> None:
    if not watchdog:
        durable.reopen_platform_repair_checkpoint(
            phase_id,
            runtime_signature=runtime,
            reason="explicit resume requested for platform-owned checkpoint",
        )
        return
    if not host._platform_checkpoint_is_auto_recoverable(revision):
        raise ValueError(
            f"{phase_id} platform checkpoint is terminal and its artifact/runtime signature is unchanged",
        )
    try:
        limit = min(6, max(1, int(options.get("max_research_loop_cycles") or 3)))
    except (TypeError, ValueError):
        limit = 3
    count = max(0, int(revision.get("platform_auto_recovery_count") or 0))
    if count >= limit:
        raise ValueError(
            f"{phase_id} platform auto-recovery budget is exhausted and signatures are unchanged",
        )
    gate = revision.get("last_gate")
    gate = gate if isinstance(gate, dict) else {}
    durable.start_platform_recovery_cycle(
        phase_id,
        runtime_signature=runtime,
        reason=str(
            gate.get("summary")
            or gate.get("reason")
            or "watchdog platform checkpoint recovery"
        ),
    )


def _validate_figure_feedback_scope(
    selected: list[str], state: dict[str, Any], feedback: str,
    project_path: str, run_id: str,
) -> None:
    if "figure" not in selected:
        return
    phase = (state.get("phases") or {}).get("figure") or {}
    if phase.get("status") != "awaiting_revision":
        return
    revision = (phase.get("details") or {}).get("revision") or {}
    gate = revision.get("last_gate") or {}
    if gate.get("error_category") != "figure_retry_deferred":
        return
    scope = gate.get("repair_scope") or {}
    identities = scope.get("asset_ids") if isinstance(scope, dict) else []
    if not identities:
        from ..services.figure_delegate_budget import failed_figure_asset_ids

        identities = failed_figure_asset_ids(Path(project_path), run_id)
    from .figure_feedback_scope import scoped_figure_feedback

    if not scoped_figure_feedback(list(identities or []), feedback):
        raise ValueError(
            "画图反馈必须明确指向一张失败图；请包含对应 asset ID。"
            "含糊反馈不能重开已耗尽的画图预算。"
        )


async def resume_persisted_run_claimed(
    host: ResumeHost,
    *,
    run_id: str,
    project_path: str,
    node_ids: list[str] | None,
    research_direction: str,
    effort: str | None,
    assurance: str | None,
    pipeline_options: dict[str, Any] | None,
    on_event: Any,
    checkpoint_feedback: str,
    resume_source: str,
) -> str:
    if resume_source == 'explicit':
        from .report_revision_transport import reopen_transport_reports
        reopen_transport_reports(RunState(project_path, run_id))
        from .report_revision_recovery import reopen_missing_source_review
        reopen_missing_source_review(RunState(project_path, run_id))
    durable, state, options, selected = await _revalidated_resume_state(
        host,
        run_id,
        project_path,
        node_ids,
        research_direction,
        pipeline_options,
    )
    if checkpoint_feedback.strip():
        _validate_figure_feedback_scope(
            selected, state, checkpoint_feedback, project_path, run_id,
        )
    phases = state.get("phases") or {}
    for phase_id in selected:
        phase = phases.get(phase_id, {})
        if phase.get("status") != "accepted":
            revision = (phase.get("details") or {}).get("revision") or {}
            previous = str(revision.get("artifact_signature") or "")
            owner = str(revision.get("artifact_owner_id") or phase_id)
            current = host._revision_artifact_signature(project_path, owner, options)
            if previous and previous != current:
                durable.reset_revision_for_runtime_change(phase_id,
                    runtime_signature=host._revision_runtime_signature(project_path, owner, options),
                    reason="research artifact or validator signature changed before manual recovery")
            elif (phase.get("status") == "awaiting_revision" and not checkpoint_feedback.strip()
                    and not (phase.get("details") or {}).get("interruption")):
                _unchanged_checkpoint_action(
                    host,
                    durable,
                    phase_id,
                    phase,
                    options,
                    watchdog=str(resume_source or "").strip().casefold() == "watchdog",
                )
    config = state.get("config") or {}
    options["resume_run_id"] = run_id
    options.pop("_manual_resume_id", None)
    options.pop("_manual_resume_node", None)
    if resume_source == "explicit":
        from .interruption_checkpoint import acknowledge_manual_resume
        if state.get("interruption"):
            options["_manual_resume_id"] = uuid.uuid4().hex
            options["_manual_resume_node"] = str(state["interruption"].get("node_id") or "")
        acknowledge_manual_resume(durable)
    if checkpoint_feedback.strip():
        options["resume_feedback"] = checkpoint_feedback.strip()
    return await host.execute(
        node_ids=selected,
        project_path=project_path,
        research_direction=research_direction or config.get("direction", ""),
        effort=effort or config.get("effort", "balanced"),
        assurance=str(config.get("assurance") or assurance or "draft"),
        pipeline_options=options,
        on_event=on_event,
    )
