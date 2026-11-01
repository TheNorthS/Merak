"""Run one authorized implementation attempt with bounded progress tracking."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from .implementation_execution_contracts import (
    ImplementationContext,
    ImplementationStageState,
)


class StageModelInvocation:
    def __init__(
        self,
        context: ImplementationContext,
        state: ImplementationStageState,
        attempt: int,
    ):
        self.context = context
        self.state = state
        self.attempt = attempt
        self.last_activity = time.monotonic()
        self.last_event = 0.0
        from ..services.implementation_review_receipt import stage_obligation_signature
        self.obligation_signature = stage_obligation_signature(context.root, state.effective_targets)
        self.prepared_arguments: str | None = None
        self.prepared_input_fingerprint: str | None = None

    def resume_fingerprint(self) -> str:
        """Changed review obligations must not resume a session for an older repair."""
        from ..agent.execution_harness import fingerprint
        return fingerprint([self.context.service.input_hash(self.context.root, self.state.stage.id,
                            self.context.direction), self.obligation_signature])

    def mark(self, status: str, *, output: str = "", error: str = "") -> None:
        from ..services.skill_orchestrator import skill_orchestrator

        run = self.context.run
        from .run_state import RunState
        def checkpoint(state: dict) -> None:
            repair = state.get("active_owner_revision")
            if repair and repair.get("owner_node") == "exp-design":
                repair["substage"] = self.state.stage.id
        RunState(run.project_path, run.id).update_state(checkpoint)
        skill_orchestrator.mark_execution(
            run.project_path,
            run.id,
            "exp-design",
            "domain-experiment-plan",
            status,
            role="delegate",
            output=output,
            error=error,
            policy_loaded=True,
            execution_kind="model_owned",
        )

    async def progress(self, event: Any) -> None:
        now = time.monotonic()
        if self.context.host._agent_event_counts_as_progress(event):
            self.last_activity = now
        payload = event.data if isinstance(getattr(event, "data", None), dict) else {}
        status = str(payload.get("status") or getattr(event, "type", "working"))
        if now - self.last_event < 15.0 and status not in {
            "retrying_provider", "retrying_tool_response", "stream_fallback_non_streaming", "iteration_budget",
        }:
            return
        self.last_event = now
        request = {key: payload[key] for key in (
            "elapsed", "attempt", "max_attempts", "next_attempt", "retry_in_seconds",
            "total_elapsed_seconds", "remaining_seconds", "total_budget_seconds", "attempt_remaining_seconds", "error_code",
            "iterations_used", "iterations_remaining", "max_iterations",
        ) if key in payload}
        await self.context.host._emit(
            self.context.run,
            "implementation_stage_progress",
            {
                "node_id": "exp-design",
                "stage_id": self.state.stage.id,
                "attempt": self.attempt,
                "status": status,
                "model_request": request,
                "provider": str(payload.get("provider") or ""),
                "model": str(payload.get("model") or ""),
            },
        )

    def _arguments(self) -> str:
        """Carry current user intent into the isolated stage without widening ownership."""
        from ..contracts.implementation_readiness import readiness_instruction
        from ..services.research_edit_context import research_edit_context
        from ..services.scheduler_authoring_contract import scheduler_authoring_instruction
        from ..services.implementation_handoff import implementation_handoff_context

        context, state = self.context, self.state
        prompt = context.service.stage_prompt(
            context.run.project_path, state.stage.id, context.direction,
            list(state.report.get("issues") or []), owned_targets=state.effective_targets,
        )
        prompt += "\n\n" + readiness_instruction()
        prompt += scheduler_authoring_instruction()
        prompt += implementation_handoff_context(context.service, context.root, state.stage.id, context.direction)
        prompt += research_edit_context(context.run.project_path, "exp-design")
        from .operator_feedback import operator_feedback_context
        prompt += operator_feedback_context(context.run, context.node.id)
        return prompt

    async def _invoke(self) -> Any:
        from ..agent.tools import invoke_skill

        context, state = self.context, self.state
        from .owner_revision_transaction import update_owner_boundary
        from .run_state import RunState
        update_owner_boundary(RunState(context.run.project_path, context.run.id), context.node, "acceptance")
        task = asyncio.create_task(
            invoke_skill(
                "domain-experiment-plan",
                self.prepared_arguments if self.prepared_arguments is not None else self._arguments(),
                project_path=context.run.project_path,
                parent_context="skill-chain:workflow>exp-design-staged-"
                + state.stage.id,
                workflow_node_id="exp-design",
                on_event=self.progress,
                allowed_tools_override=["Read", "Glob", "Grep", "Write", "Edit"],
                allowed_write_paths=list(state.effective_targets),
                invocation_contract=(
                    "One isolated implementation stage. For this bounded invocation, the exact "
                    "stage-owned targets in the arguments are the only permitted outputs; the "
                    "full design skill's broader output list is read-only unless explicitly "
                    "included in those targets. Do not edit METHOD_CONTRACT lifecycle state. "
                    "All other stage source and frozen design inputs are read-only. Do not run training, "
                    "fabricate results, invoke nested skills, or replace the frozen scientific idea."
                ),
                max_iterations=24,
                resume_input_fingerprint=self.prepared_input_fingerprint or self.resume_fingerprint(),
            )
        )
        return await context.host._await_agent_with_activity_watchdog(
            task=task,
            run=context.run,
            node=context.node,
            is_revision=bool(state.report.get("issues")),
            last_activity=lambda: self.last_activity,
        )

    async def run(self) -> str:
        self.mark("running")
        try:
            output = await self._invoke()
        except asyncio.CancelledError:
            self.mark("interrupted", error="Implementation stage was cancelled.")
            raise
        except Exception as error:
            status = (
                "interrupted"
                if self.context.host._is_transport_research_error(error)
                else "failed"
            )
            self.mark(status, error=self.context.host._exception_summary(error))
            raise
        return str(output or "")
