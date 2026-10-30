"""Coordinate resumable implementation stages; never run scientific experiments."""

from __future__ import annotations

from typing import Any
from pathlib import Path

from ..services.experiment_implementation_build import (
    experiment_implementation_build_service,
)
from ..services.implementation_stages import ImplementationStage
from .implementation_execution_contracts import (
    ImplementationContext,
    ImplementationHost,
    ImplementationStageState,
)
from .implementation_model_invocation import StageModelInvocation
from .implementation_stage_progress import progress_snapshot, stage_stop_reason, StageProgressSnapshot
from .implementation_reconciliation import (
    capture_protected_inputs,
    expand_integration_targets,
    prepare_stage,
    reconcile_attempt,
)
from .models import WorkflowNode, WorkflowRun
from ..agent.iteration_budget import AgentIterationLimit


class StagedImplementationCoordinator:
    def __init__(self, host: ImplementationHost, run: WorkflowRun, direction: str):
        self.host = host
        self.run = run
        self.direction = direction
        self.service = experiment_implementation_build_service

    async def _emit(self, event: str, data: dict[str, Any]) -> None:
        await self.host._emit(self.run, event, {"node_id": "exp-design", **data})

    async def _emit_revalidated(self, stage: ImplementationStage) -> None:
        await self._emit(
            "implementation_stage_revalidated",
            {
                "stage_id": stage.id,
                "title": stage.title,
                "targets": list(stage.targets),
                "message": "既有模型实现已通过当前确定性校验；无需对空问题列表重复调用模型。",
            },
        )

    async def _accept_previously_attempted(
        self,
        context: ImplementationContext,
        state: ImplementationStageState,
    ) -> bool:
        previous = state.previous_record
        if (
            not state.report.get("passed")
            or previous.get("status") not in {"needs_revision", "failed"}
            or int(previous.get("attempts") or 0) <= 0
            or previous.get("input_sha256") != context.service.input_hash(context.root, state.stage.id, context.direction)
        ):
            return False
        summaries = [
            str(item)
            for item in previous.get("session_summaries") or []
            if str(item).strip()
        ]
        summaries.append(
            "Accepted after deterministic revalidation of the previously attempted stage; "
            "no unresolved issues remained."
        )
        self.service.record_stage(
            self.run.project_path,
            state.stage.id,
            state.report,
            self.direction,
            attempts=int(previous.get("attempts") or 1),
            session_summaries=summaries,
        )
        await self._emit_revalidated(state.stage)
        return True

    async def _expand_targets(
        self, state: ImplementationStageState, attempt: int
    ) -> None:
        new_targets = expand_integration_targets(state)
        if new_targets:
            await self._emit(
                "implementation_stage_targets_expanded",
                {
                    "stage_id": state.stage.id,
                    "attempt": attempt,
                    "new_targets": new_targets,
                    "targets": list(state.effective_targets),
                    "message": "确定性复核发现新的跨阶段调用链修复目标；已授权下一次当前阶段尝试直接修复。",
                },
            )

    def _record_result(
        self,
        state: ImplementationStageState,
        attempt: int,
        invocation: StageModelInvocation,
        output: str,
    ) -> None:
        from ..services.implementation_review_receipt import stage_obligation_signature
        handled = stage_obligation_signature(invocation.context.root, state.effective_targets)
        self.service.record_stage(
            self.run.project_path,
            state.stage.id,
            state.report,
            self.direction,
            attempts=attempt,
            session_summaries=state.summaries,
            handled_obligations_sha256=handled if state.report.get("passed") else "",
        )
        if state.iteration_exhaustion:
            return  # Preserve the failed invocation trace; stage acceptance belongs to the fresh gate.
        invocation.mark(
            "completed" if state.report.get("passed") else "failed",
            output=output,
            error=""
            if state.report.get("passed")
            else "; ".join(state.report.get("issues", [])[:8]),
        )

    async def _invoke_attempt(self, state: ImplementationStageState, invocation: StageModelInvocation) -> str:
        state.iteration_exhaustion = {}
        try:
            return await invocation.run()
        except AgentIterationLimit as error:
            state.iteration_exhaustion = {
                "session_id": error.session_id, "iterations": error.iterations, "limit": error.limit,
            }
            await self._emit("implementation_stage_budget_exhausted", {
                "stage_id": state.stage.id, **state.iteration_exhaustion,
                "message": "模型本轮步骤预算已用完；正在验收已保存文件，再按具体验收问题处理。",
            })
            return (
                f"Model session {error.session_id} reached its {error.limit}-turn budget after tool completion. "
                "No model completion is claimed. Saved artifacts are submitted to the normal ownership and integration gate."
            )

    async def _attempts(
        self, context: ImplementationContext, state: ImplementationStageState
    ) -> None:
        stage = state.stage
        for attempt in range(1, 3):
            protection = capture_protected_inputs(context, state)
            before = progress_snapshot(context.root, state.effective_targets, state.report)
            await self._emit(
                "implementation_stage_started",
                {
                    "stage_id": stage.id,
                    "title": stage.title,
                    "attempt": attempt,
                    "max_attempts": 2,
                    "targets": list(state.effective_targets),
                    "issues": list(state.report.get("issues") or [])[:8],
                },
            )
            invocation = StageModelInvocation(context, state, attempt)
            output = await self._invoke_attempt(state, invocation)
            from ..services.implementation_handoff import MAX_STAGE_HANDOFF_CHARS
            state.summaries.append(output[:MAX_STAGE_HANDOFF_CHARS])
            state.report = reconcile_attempt(context, state, protection)
            await self._expand_targets(state, attempt)
            self._record_result(state, attempt, invocation, output)
            if state.report.get("passed"):
                await self._emit(
                    "implementation_stage_accepted",
                    {
                        "stage_id": stage.id,
                        "title": stage.title,
                        "attempt": attempt,
                        "targets": list(stage.targets),
                        "output_sha256": state.report.get("output_sha256"),
                    },
                )
                break
            await self._emit(
                "implementation_stage_needs_revision",
                {
                    "stage_id": stage.id,
                    "title": stage.title,
                    "attempt": attempt,
                    "issues": list(state.report.get("issues") or [])[:8],
                },
            )
            if state.report.get("ownership_violations"):
                break
            if state.report.get("owner_reconciliation_required"):
                break  # A dependency handoff is a runtime operation, not another integration prompt.
            if await self._stop_unproductive_attempt(context, state, before, attempt):
                break

    async def _stop_unproductive_attempt(
        self, context: ImplementationContext, state: ImplementationStageState,
        before: StageProgressSnapshot, attempt: int,
    ) -> bool:
        after = progress_snapshot(context.root, state.effective_targets, state.report)
        reason = stage_stop_reason(before, after, state.report)
        if not reason:
            return False
        await self._emit("implementation_stage_no_progress", {
            "stage_id": state.stage.id, "attempt": attempt, "reason": reason,
            "issues": sorted(after.findings), "targets": list(state.effective_targets),
            "before_sha256": before.artifact_sha256, "after_sha256": after.artifact_sha256,
            "message": "当前尝试未消除任何门禁问题；停止同阶段重复调用。检查覆盖写入、无效内容修改或生产者与门禁契约冲突。",
        })
        return True

    async def _run_stages(self, context: ImplementationContext) -> None:
        for handoff in range(2):
            owners = await self._stage_pass(context)
            if not owners or handoff:
                return
            await self._emit("implementation_owner_reconciliation_started", {
                "stage_ids": owners,
                "message": "集成修改了上游依赖；程序直接复核对应所有者，然后重新验收已保存的集成产物。",
            })

    async def _stage_pass(self, context: ImplementationContext) -> list[str]:
        from ..services.implementation_review_receipt import pending_stage_obligations
        for stage in context.stages:
            pending = pending_stage_obligations(self.service, context.root, stage.id, self.direction, list(stage.targets))
            if stage.id == "integration" and not pending:
                recovered = self.service.revalidate_existing_build(context.root, context.direction)
                if recovered.get("complete"):
                    await self._emit_revalidated(stage)
                    return []
            if not pending and self.service.can_reuse(self.run.project_path, stage.id, self.direction):
                await self._emit(
                    "implementation_stage_reused",
                    {
                        "stage_id": stage.id,
                        "title": stage.title,
                        "targets": list(stage.targets),
                    },
                )
                continue
            state = prepare_stage(context, stage)
            if state.report.get("owner_reconciliation_required"):
                return list(state.report["owner_reconciliation_required"])
            if await self._accept_previously_attempted(context, state):
                continue
            await self._attempts(context, state)
            if not state.report.get("passed"):
                return list(state.report.get("owner_reconciliation_required") or [])
        return []

    async def _revalidated_pipeline(
        self, stages: tuple[ImplementationStage, ...]
    ) -> None:
        for stage in stages:
            await self._emit_revalidated(stage)
        await self._emit(
            "implementation_pipeline_revalidated",
            {
                "stage_ids": [stage.id for stage in stages],
                "message": (
                    "全部既有分阶段实现均通过当前确定性门禁，且已验收阶段的源码哈希未变化；"
                    "已原子刷新构建记录，不重复调用模型。"
                ),
            },
        )

    async def execute(self) -> dict[str, Any]:
        blueprint = self.service.ensure_blueprint(self.run.project_path, self.direction)
        stages = self.service.stages(self.run.project_path, self.direction)
        if not self.service.applicable(self.run.project_path, self.direction):
            await self._emit(
                "implementation_pipeline_not_applicable",
                {
                    "implementation_family": blueprint.get("implementation_family"),
                    "message": "当前研究不是计算型代码实现；保留领域协议/形式化验证流程，不生成伪训练代码。",
                },
            )
            return self.service.audit(self.run.project_path, self.direction)
        revalidated = self.service.revalidate_existing_build(
            self.run.project_path, self.direction
        )
        from ..services.implementation_review_receipt import pending_stage_obligations
        has_obligations = any(pending_stage_obligations(self.service, Path(self.run.project_path), stage.id, self.direction, list(stage.targets)) for stage in stages)
        if revalidated.get("complete") and not has_obligations:
            await self._revalidated_pipeline(stages)
            return self.service.audit(self.run.project_path, self.direction)
        node = next(
            (item for item in self.run.nodes if item.id == "exp-design"),
            WorkflowNode(
                id="exp-design",
                name="实验设计",
                skill="/experiment-plan",
            ),
        )
        context = ImplementationContext(
            self.host, self.run, self.direction, node, stages, self.service
        )
        await self._run_stages(context)
        report = self.service.audit(self.run.project_path, self.direction)
        await self._emit(
            "implementation_pipeline_completed",
            {
                "status": report.get("status"),
                "blocking": bool(report.get("blocking")),
                "issues": list(report.get("issues") or [])[:12],
                "blueprint_path": report.get("blueprint_path", ""),
                "build_path": report.get("build_path", ""),
            },
        )
        return report


async def execute_staged_implementation(
    host: ImplementationHost,
    run: WorkflowRun,
    direction: str,
) -> dict[str, Any]:
    return await StagedImplementationCoordinator(host, run, direction).execute()
