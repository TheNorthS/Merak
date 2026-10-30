"""Typed acceptance-gate context and deterministic prerequisite checks."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .models import WorkflowNode, WorkflowRun
from .run_state import RunState


class AcceptanceGateHost(Protocol):
    def _gate_requirements_for_node(
        self, run: WorkflowRun, node_id: str
    ) -> list[Path]: ...
    def _artifact_check(
        self, paths: list[Path], **options: Any
    ) -> tuple[bool, list[str]]: ...
    def _managed_experiment_acceptance_gate(
        self, run: WorkflowRun, options: dict[str, Any]
    ) -> dict[str, Any]: ...
    def _experiment_code_integrity_gate(self, project_path: str) -> dict[str, Any]: ...
    def _exp_design_method_alignment_gate(
        self, run: WorkflowRun, direction: str
    ) -> dict[str, Any]: ...
    def _figure_acceptance_gate(self, project_path: str) -> dict[str, Any]: ...
    def _paper_acceptance_gate(
        self, project_path: str, **options: Any
    ) -> dict[str, Any]: ...
    def _review_acceptance_gate(
        self, project_path: str, **options: Any
    ) -> dict[str, Any]: ...
    def _audit_acceptance_gate(
        self, project_path: str, assurance: str, result: str, **options: Any
    ) -> dict[str, Any]: ...
    def _verdict_id(self, node_id: str, artifacts: list[Path]) -> str: ...
    def _extract_selected_idea(
        self, root: Path, result: str, direction: str
    ) -> str: ...


@dataclass
class AcceptanceContext:
    host: AcceptanceGateHost
    node: WorkflowNode
    run: WorkflowRun
    assurance: str
    result: str
    require_fresh: bool
    run_state: dict[str, Any] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)
    requirements: list[Path] = field(default_factory=list)
    content_baseline: dict[str, dict[str, Any]] | None = None
    freshness_since: float | None = None
    managed_output_gate: dict[str, Any] = field(default_factory=dict)
    specialist_gate: dict[str, Any] = field(
        default_factory=lambda: {
            "accepted": True,
            "applicable": False,
            "issues": [],
        }
    )

    @property
    def innovation_mode(self) -> bool:
        return (
            str(self.options.get("research_mode") or "from_scratch")
            == "paper_code_innovation"
        )


def build_context(
    host: AcceptanceGateHost,
    node: WorkflowNode,
    run: WorkflowRun,
    assurance: str,
    result: str,
    require_fresh: bool,
) -> AcceptanceContext:
    run_state = RunState(run.project_path, run.id).load() or {}
    options = dict(run.options or run_state.get("config", {}).get("options", {}))
    options.setdefault("assurance", assurance)
    return AcceptanceContext(
        host, node, run, assurance, result, require_fresh, run_state, options
    )


def prerequisite_failure(context: AcceptanceContext) -> dict[str, Any] | None:
    staged = context.run.options.pop("_staged_implementation_report", None)
    if (
        context.node.id == "exp-design"
        and isinstance(staged, dict)
        and staged.get("blocking")
    ):
        issues = [
            str(item).strip()
            for item in staged.get("issues") or []
            if str(item).strip()
        ]
        issues = issues or ["staged experiment implementation pipeline is blocked"]
        findings = [dict(item) for item in staged.get("findings") or [] if isinstance(item, dict)]
        scope = staged.get("repair_scope")
        scope = dict(scope) if isinstance(scope, dict) else {}
        return {
            "accepted": False,
            "reason": "staged experiment implementation is blocked",
            "summary": "; ".join(issues[:8]),
            "details": {
                "issues": issues,
                "staged_implementation": staged,
                "findings": findings,
                "repair_scope": scope,
            },
        }
    return None


def artifact_failure(context: AcceptanceContext) -> dict[str, Any] | None:
    from ..services.workflow_inputs import workflow_input_service

    input_issues = workflow_input_service.validate_snapshot(
        context.run.project_path,
        context.run.input_baseline,
    )
    if input_issues:
        return {
            "accepted": False,
            "reason": "explicit workflow input changed",
            "summary": "; ".join(input_issues[:8]),
            "details": {
                "issues": input_issues,
                "input_baseline_snapshot_id": str(
                    context.run.input_baseline.get("snapshot_id") or ""
                ),
            },
        }
    context.requirements = context.host._gate_requirements_for_node(
        context.run, context.node.id
    )
    fresh = (
        context.require_fresh
        and context.node.id not in {"compile", "ppt"}
        and not (
            context.node.id == "exp-run"
            and context.options.get("run_experiment") is not True
        )
    )
    context.content_baseline = (
        context.node.artifact_baseline
        if fresh and context.node.artifact_baseline
        else None
    )
    context.freshness_since = (
        context.node.started_at if fresh and context.content_baseline is None else None
    )
    ok, missing = context.host._artifact_check(
        context.requirements,
        since=context.freshness_since,
        baseline=context.content_baseline,
        project_path=context.run.project_path,
        input_baseline=context.run.input_baseline,
    )
    if ok:
        return None
    mode = (
        "content-baseline"
        if context.content_baseline is not None
        else ("mtime" if context.freshness_since is not None else "validation-only")
    )
    return {
        "accepted": False,
        "reason": "required artifact missing, empty, or stale",
        "summary": f"Missing/stale artifacts: {', '.join(missing)}",
        "details": {
            "missing": missing,
            "required": [str(path) for path in context.requirements],
            "fresh_since": context.freshness_since,
            "freshness_mode": mode,
        },
    }


def specialist_failure(context: AcceptanceContext) -> dict[str, Any] | None:
    if context.node.id == "exp-run" and context.options.get("run_experiment") is True:
        context.managed_output_gate = context.host._managed_experiment_acceptance_gate(
            context.run,
            context.options,
        )
        if not context.managed_output_gate.get("accepted"):
            return context.managed_output_gate
    if context.node.id not in {"exp-design", "results"}:
        return None
    from ..services.research_specialists import research_specialist_service

    context.specialist_gate = research_specialist_service.gate_node(
        context.run.project_path,
        context.run.id,
        context.node.id,
    )
    if context.specialist_gate.get("accepted"):
        return None
    issues = list(context.specialist_gate.get("issues") or [])
    return {
        "accepted": False,
        "reason": "required research-profile specialist subnode failed",
        "summary": "; ".join(str(item) for item in issues[:8]),
        "details": {"issues": issues, "profile_specialists": context.specialist_gate},
    }
