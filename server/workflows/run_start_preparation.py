"""Resolve immutable start options and selected nodes before creating a run."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from ..services.workflow_inputs import workflow_input_service
from .engine_context import (
    normalize_revision_rounds,
    normalize_workflow_illustration_mode,
)
from .models import WorkflowNode
from .run_state import RunState


IMMUTABLE_RUN_OPTIONS = (
    "run_experiment",
    "non_experiment_evidence_mode",
    "illustration_mode",
    "evidence_import_manifest",
    "research_mode",
    "reference_snapshot_id",
)


class RunStartHost(Protocol):
    def _ensure_agent_tools(self) -> None: ...
    def _get_default_nodes(self) -> list[WorkflowNode]: ...
    def _topological_sort(self, nodes: list[WorkflowNode]) -> list[WorkflowNode]: ...


@dataclass(frozen=True)
class RunStartPlan:
    options: dict[str, Any]
    assurance: str
    existing_state: dict[str, Any] | None
    input_baseline: dict[str, Any]
    nodes: list[WorkflowNode]
    requested_run_id: str
    resume_claim_token: str
    project_claim_token: str
    project_claim_run_id: str
    resume_feedback: str


def _normalized_options(
    options: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, str]]:
    resolved = dict(options or {})
    claims = {
        "project_claim_token": str(resolved.pop("_project_claim_token", "") or ""),
        "project_claim_run_id": str(
            resolved.pop("_project_claim_run_id", "") or ""
        ).strip(),
        "resume_claim_token": str(resolved.pop("_resume_claim_token", "") or ""),
        "resume_feedback": str(resolved.pop("resume_feedback", "") or "").strip(),
    }
    resolved["max_revision_rounds"] = normalize_revision_rounds(
        resolved.get("max_revision_rounds"),
    )
    resolved.pop("revision_rounds_per_cycle", None)
    resolved["illustration_mode"] = normalize_workflow_illustration_mode(
        resolved.get("illustration_mode"),
    )
    resolved["staged_experiment_implementation"] = True
    return resolved, claims


def _restore_immutable_options(
    options: dict[str, Any],
    existing: dict[str, Any] | None,
    assurance: str,
    node_ids: list[str],
) -> str:
    if isinstance(existing, dict):
        config = existing.get("config")
        config = config if isinstance(config, dict) else {}
        saved = config.get("options")
        saved = saved if isinstance(saved, dict) else {}
        for key in IMMUTABLE_RUN_OPTIONS:
            if key in saved:
                options[key] = saved[key]
        options["illustration_mode"] = normalize_workflow_illustration_mode(
            options.get("illustration_mode"),
        )
        return str(config.get("assurance") or assurance)
    options["run_experiment"] = bool(
        options.get("run_experiment") is True and "exp-run" in set(map(str, node_ids)),
    )
    return assurance


def _input_baseline(
    project_path: str,
    options: dict[str, Any],
    existing: dict[str, Any] | None,
    requested_run_id: str,
) -> dict[str, Any]:
    baseline = (
        dict(existing.get("input_baseline") or {}) if isinstance(existing, dict) else {}
    )
    if not baseline:
        baseline = workflow_input_service.capture(
            project_path,
            options.get("input_files") or [],
            run_id=requested_run_id or "pending",
        )
    issues = workflow_input_service.validate_snapshot(project_path, baseline)
    if issues:
        raise ValueError(
            "; ".join(issues)
            + ". Start a new workflow run to accept changed research inputs.",
        )
    options["input_files"] = [
        str(entry.get("path") or "")
        for entry in baseline.get("entries") or []
        if isinstance(entry, dict) and entry.get("path")
    ]
    return baseline


async def prepare_run_start(
    host: RunStartHost,
    node_ids: list[str],
    project_path: str,
    assurance: str,
    pipeline_options: dict[str, Any] | None,
) -> RunStartPlan:
    options, claims = _normalized_options(pipeline_options)
    requested_id = str(options.get("resume_run_id") or "").strip()
    if (
        requested_id
        and claims["project_claim_run_id"]
        and requested_id != claims["project_claim_run_id"]
    ):
        raise ValueError("Project workflow claim does not match resume_run_id")
    existing = RunState(project_path, requested_id).load() if requested_id else None
    assurance = _restore_immutable_options(options, existing, assurance, node_ids)
    from ..services.workflow_readiness import validate_submission_start

    issues = validate_submission_start(
        node_ids,
        assurance,
        options,
        resume=isinstance(existing, dict),
    )
    if issues and not existing:
        raise ValueError("; ".join(issues))
    host._ensure_agent_tools()
    baseline = _input_baseline(project_path, options, existing, requested_id)
    if options.get("run_experiment") is not True:
        options.update({"gpu_target": "none", "ssh_server_id": "", "gpu_info": ""})
    await _prepare_reference_context(project_path, options)
    from ..services.paper_budget import paper_budget_service

    paper_budget_service.prepare(
        project_path,
        options.get("target_pages", 0),
        options.get("target_page_tolerance", 1),
        str(options.get("target_venue") or ""),
    )
    selected = [node for node in host._get_default_nodes() if node.id in node_ids]
    return RunStartPlan(
        options,
        assurance,
        existing,
        baseline,
        host._topological_sort(selected),
        requested_id,
        claims["resume_claim_token"],
        claims["project_claim_token"],
        claims["project_claim_run_id"],
        claims["resume_feedback"],
    )


async def _prepare_reference_context(
    project_path: str, options: dict[str, Any]
) -> None:
    if str(options.get("research_mode") or "from_scratch") != "paper_code_innovation":
        return
    from ..services.research_intake import research_intake_service

    context = await asyncio.to_thread(
        research_intake_service.prepare,
        project_path,
        str(options.get("ref_paper") or ""),
        str(options.get("base_repo") or ""),
        str(options.get("innovation_focus") or ""),
    )
    options["reference_context_path"] = str(
        Path(project_path) / ".merak" / "reference_context" / "REFERENCE_CONTEXT.json",
    )
    options["reference_snapshot_id"] = context.get("snapshot_id", "")
