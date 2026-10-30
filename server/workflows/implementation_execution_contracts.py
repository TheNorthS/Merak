"""Typed state shared by bounded implementation planning and invocation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from ..services.experiment_implementation_build import (
    ExperimentImplementationBuildService,
)
from ..services.implementation_stages import ImplementationStage
from .models import WorkflowNode, WorkflowRun


class ImplementationHost(Protocol):
    async def _emit(
        self, run: WorkflowRun, event_type: str, data: dict[str, Any]
    ) -> None: ...
    def _agent_event_counts_as_progress(self, event: Any) -> bool: ...
    async def _await_agent_with_activity_watchdog(
        self,
        *,
        task: asyncio.Task[Any],
        run: WorkflowRun,
        node: WorkflowNode,
        is_revision: bool,
        last_activity: Callable[[], float],
    ) -> Any: ...
    def _is_transport_research_error(self, error: Exception) -> bool: ...
    def _exception_summary(self, error: Exception) -> str: ...


@dataclass(frozen=True)
class ImplementationContext:
    host: ImplementationHost
    run: WorkflowRun
    direction: str
    node: WorkflowNode
    stages: tuple[ImplementationStage, ...]
    service: ExperimentImplementationBuildService

    @property
    def root(self) -> Path:
        return Path(self.run.project_path).expanduser().resolve()


@dataclass
class ImplementationStageState:
    stage: ImplementationStage
    report: dict[str, Any]
    effective_targets: list[str]
    previous_record: dict[str, Any]
    summaries: list[str] = field(default_factory=list)
    iteration_exhaustion: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AttemptProtection:
    protected_before: dict[Path, dict[str, Any]]
    method_path: Path
    previous_method: dict[str, Any]
    stage_target_declaration: dict[str, list[str]] | None = None
