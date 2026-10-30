"""Dispatch current node execution after input and upstream preflight checks.

The shared execution context belongs to one run/node attempt. Managed scientific
execution requires explicit authorization; authoring and validation are separate."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..agent.engine import agent_engine
from ..services.workflow_inputs import artifact_state, artifact_state_equal
from .engine_context import LITERATURE_SEARCH_NODES, logger
from .models import NodeStatus
from .run_execution_context import (
    CompleteRun,
    RunExecutionContext,
    SkipRunNode,
    save_resume_session,
)


async def _reuse_prior_dependency(
    ctx: RunExecutionContext,
    dependency_id: str,
    gate: dict[str, Any],
) -> bool:
    if gate.get("accepted"):
        return False
    from .dependency_reuse import (
        execution_trace_only_failure,
        reusable_dependency_evidence,
    )

    if not execution_trace_only_failure(gate):
        return False
    evidence = reusable_dependency_evidence(
        ctx.host,
        ctx.run.project_path,
        ctx.run.id,
        dependency_id,
        str(ctx.run.input_baseline.get("snapshot_id") or ""),
    )
    if evidence is None:
        return False
    await ctx.host._emit(ctx.run, "node_dependency_reused", {
        "node_id": ctx.node.id,
        "dependency_id": dependency_id,
        "source_run_id": evidence["run_id"],
        "reviewer": evidence["reviewer"],
        "summary": "Reused hash-current accepted upstream execution evidence.",
    })
    return True


async def prepare_node(ctx: RunExecutionContext) -> None:
    if ctx.node.status == NodeStatus.COMPLETED:
        await ctx.host._emit(
            ctx.run,
            "node_accepted_cached",
            {"node_id": ctx.node.id, "name": ctx.node.name},
        )
        raise SkipRunNode()
    ctx.persisted_phases = (ctx.run_state.load() or {}).get("phases", {})
    ctx.dependencies = [
        ctx.host._find_node(ctx.run, dep_id) for dep_id in ctx.node.depends_on
    ]
    ctx.dependency_failures: list[str] = []
    for dep_id, dependency in zip(ctx.node.depends_on, ctx.dependencies):
        if dependency is not None:
            if dependency.status != NodeStatus.COMPLETED:
                ctx.dependency_failures.append(
                    f"{dep_id} is {dependency.status.value} in the current run"
                )
            continue
        if ctx.host._phase_is_durably_terminal(ctx.persisted_phases.get(dep_id, {})):
            continue
        definition = next(
            (
                candidate
                for candidate in ctx.host._get_default_nodes()
                if candidate.id == dep_id
            ),
            None,
        )
        if definition is None:
            ctx.dependency_failures.append(f"unknown dependency {dep_id}")
            continue
        dependency_gate = ctx.host._acceptance_gate(
            definition, ctx.run, ctx.assurance, "", require_fresh=False
        )
        if await _reuse_prior_dependency(ctx, dep_id, dependency_gate):
            continue
        if dependency_gate.get("accepted"):
            await ctx.host._emit(
                ctx.run,
                "node_dependency_reused",
                {
                    "node_id": ctx.node.id,
                    "dependency_id": dep_id,
                    "reviewer": dependency_gate.get("reviewer", "deterministic gate"),
                    "summary": dependency_gate.get("summary", ""),
                },
            )
            continue
        ctx.dependency_failures.append(
            f"{dep_id}: "
            + str(
                dependency_gate.get("summary")
                or dependency_gate.get("reason")
                or "existing artifact did not pass validation"
            )
        )
    ctx.deps_ok = not ctx.dependency_failures
    if not ctx.deps_ok:
        dependency_reason = "dependency not accepted: " + "; ".join(
            ctx.dependency_failures[:6]
        )
        ctx.node.status = NodeStatus.SKIPPED
        ctx.run_state.set_status(ctx.node.id, "skipped", error=dependency_reason)
        await ctx.host._emit(
            ctx.run,
            "node_skipped",
            {"node_id": ctx.node.id, "reason": dependency_reason},
        )
        raise SkipRunNode()


async def load_resume_state(ctx: RunExecutionContext) -> None:
    ctx.phase_record = (
        (ctx.run_state.load() or {}).get("phases", {}).get(ctx.node.id, {})
    )
    from .interruption_checkpoint import resume_execution_stage
    ctx.resume_stage = resume_execution_stage(ctx.phase_record)
    if ctx.resume_stage:
        ctx.revalidate_done = ctx.resume_stage in {"specialists", "acceptance"}
        ctx.resuming_revision = True
        ctx.checkpoint_consumed = ctx.run_state.human_checkpoint_consumed(ctx.node.id)
        return
    # Failed phases need revalidation, but a same-run completed Write must first
    # close its interrupted primary invocation using the persisted tool evidence.
    timeout_recovery = ctx.host._record_persisted_timeout_artifact_recovery(
        ctx.node, ctx.run, ctx.phase_record
    )
    if timeout_recovery:
        ctx.phase_record = (
            (ctx.run_state.load() or {})
            .get("phases", {})
            .get(ctx.node.id, ctx.phase_record)
        )
        await ctx.host._emit(
            ctx.run,
            "skill_invocation_completed",
            {
                "node_id": ctx.node.id,
                "skill": timeout_recovery.get("skill", ""),
                "role": "primary",
                "session_id": timeout_recovery.get("session_id", ""),
                "completion_mode": "artifact_persisted_before_timeout",
            },
        )
        await ctx.host._emit(
            ctx.run,
            "node_timeout_artifact_recovered",
            {
                "node_id": ctx.node.id,
                "artifact": timeout_recovery.get("artifact", ""),
                "session_id": timeout_recovery.get("session_id", ""),
                "message": "模型在超时前已写入规范产物；本次恢复只重新验收产物，不会重复发起同一个模型请求。",
            },
        )
    ctx.revalidate_done = ctx.host._phase_requires_revalidation(ctx.phase_record)
    ctx.resuming_revision = bool(
        ctx.phase_record.get("status") == "awaiting_revision" or ctx.revalidate_done
    )
    ctx.checkpoint_consumed = ctx.run_state.human_checkpoint_consumed(ctx.node.id)


async def consume_checkpoint(ctx: RunExecutionContext) -> None:
    if (
        ctx.human_checkpoint
        and ctx.node.id in ctx.human_checkpoint_nodes
        and (ctx.node.id != ctx.run.nodes[0].id)
        and (not ctx.resuming_revision)
        and (not ctx.checkpoint_consumed)
    ):
        feedback = await ctx.host._wait_for_human_checkpoint(
            ctx.run, ctx.node, ctx.checkpoint_timeout
        )
        if ctx.run.status == "cancelled":
            raise CompleteRun()
        ctx.run_state.consume_human_checkpoint(
            ctx.node.id,
            resolution=ctx.run.checkpoint_resolution,
            feedback_supplied=bool(feedback),
        )
        await ctx.host._emit(
            ctx.run,
            "checkpoint_consumed",
            {
                "node_id": ctx.node.id,
                "checkpoint_id": f"{ctx.run.id}:{ctx.node.id}:human",
                "resolution": ctx.run.checkpoint_resolution,
                "feedback_supplied": bool(feedback),
            },
        )
        if feedback:
            ctx.run.checkpoint_feedback = feedback
            ctx.run.checkpoint_node_id = ctx.node.id
    ctx.host._start_node_attempt(ctx.node)


async def prepare_revalidation(ctx: RunExecutionContext) -> None:
    if ctx.revalidate_done:
        ctx.run_state.set_status(ctx.node.id, "running")
        ctx.result = (
            ctx.phase_record.get("details", {}).get("execution_checkpoint", {}).get("result", "")
            or ctx.phase_record.get("details", {}).get("summary", "")
            or f"Revalidating previously completed phase: {ctx.node.id}"
        )
        if ctx.phase_record.get("artifact"):
            ctx.result += f"\nArtifact: {ctx.phase_record['artifact']}"
        await ctx.host._emit(
            ctx.run,
            "node_revalidating",
            {"node_id": ctx.node.id, "name": ctx.node.name},
        )
        if ctx.node.id in LITERATURE_SEARCH_NODES:
            ctx.host._ensure_agent_tools()
            enabled_source_tools = ctx.host._filter_literature_source_tools(
                ctx.node.id, ctx.opts, list(agent_engine._tools)
            )
            source_context = await ctx.host._ensure_stage_search_evidence(
                ctx.run,
                ctx.node,
                ctx.research_direction,
                ctx.opts,
                enabled_source_tools,
            )
            await ctx.host._emit(
                ctx.run,
                "node_revalidation_inputs_refreshed",
                {
                    "node_id": ctx.node.id,
                    "kind": "literature_sources",
                    "retrieval_attempted": bool(source_context),
                },
            )
        from .results_runtime_execution import execute_results_runtime, runtime_results_contract
        if ctx.node.id == "results" and runtime_results_contract(ctx.run, ctx.opts).kind == "runtime_owned":
            analysis_path = (
                Path(ctx.run.project_path) / "experiments" / "results" / "analysis.md"
            )
            before = artifact_state(analysis_path)
            ctx.result = await execute_results_runtime(
                ctx.host, ctx.node, ctx.run, ctx.research_direction, ctx.opts, result=ctx.result
            )
            after = artifact_state(analysis_path)
            await ctx.host._emit(
                ctx.run,
                "node_revalidation_inputs_refreshed",
                {
                    "node_id": ctx.node.id,
                    "kind": runtime_results_contract(ctx.run, ctx.opts).runtime_service,
                    "artifact_changed": not artifact_state_equal(before, after),
                },
            )
    else:
        ctx.node.artifact_baseline = ctx.host._snapshot_node_artifacts(
            ctx.node, ctx.run
        )
        ctx.run_state.set_status(
            ctx.node.id,
            "running",
            details={
                "artifact_baseline": ctx.node.artifact_baseline,
                "input_baseline_snapshot_id": str(
                    ctx.run.input_baseline.get("snapshot_id") or ""
                ),
            },
        )
        await ctx.host._emit(
            ctx.run, "node_started", {"node_id": ctx.node.id, "name": ctx.node.name}
        )
        save_resume_session(ctx, ctx.node.id)


async def initialize_preflight(ctx: RunExecutionContext) -> None:
    ctx.upstream_preflight: list[dict[str, Any]] = []
    if ctx.node.id == "exp-run":
        ctx.opts.pop("_training_check", None)
        ctx.run.options.pop("_training_check", None)


async def load_node_preflight(ctx: RunExecutionContext) -> None:
    if not ctx.revalidate_done:
        from ..services.node_risk_audit import node_risk_audit_service

        preflight_findings = node_risk_audit_service.preflight_node(
            ctx.run.project_path, ctx.node.id, ctx.opts
        )
        ctx.run.options.setdefault("_node_preflight_findings", {})[ctx.node.id] = (
            preflight_findings
        )
        ctx.upstream_preflight = [
            item
            for item in preflight_findings
            if item.get("severity") == "blocker"
            and str(item.get("upstream_node") or "").strip()
            and (str(item.get("upstream_node") or "").strip() != ctx.node.id)
        ]
        if ctx.upstream_preflight:
            owners = list(
                dict.fromkeys(
                    (
                        str(item.get("upstream_node") or "")
                        for item in ctx.upstream_preflight
                        if item.get("upstream_node")
                    )
                )
            )
            ctx.result = f"Execution of {ctx.node.id} was deferred because protected upstream artifacts owned by {', '.join(owners) or 'an earlier stage'} are invalid."
            ctx.run.options["_upstream_execution_deferred"] = ctx.node.id
            await ctx.host._emit(
                ctx.run,
                "node_preparation_deferred",
                {
                    "node_id": ctx.node.id,
                    "owner_node_ids": owners,
                    "issues": [
                        str(item.get("plain_message") or item.get("message") or "")
                        for item in ctx.upstream_preflight[:8]
                    ],
                },
            )


async def prepare_node_inputs(ctx: RunExecutionContext) -> None:
    from .results_runtime_execution import runtime_results_contract
    from ..services.literature_capabilities import validate_literature_configuration

    if ctx.node.id in {"lit", "novelty"} and not ctx.revalidate_done:
        validate_literature_configuration(ctx.opts)
    if not ctx.revalidate_done:
        if not ctx.upstream_preflight and ctx.node.id == "lit":
            await ctx.host._ensure_knowledge_source_context(
                ctx.run, ctx.research_direction, ctx.opts
            )
        if (
            not ctx.upstream_preflight
            and ctx.node.id == "compile"
            and ctx.opts.get("enable_overleaf_sync")
        ):
            await ctx.host._prepare_overleaf_compile(ctx.run, ctx.opts)
        if (
            not ctx.upstream_preflight
            and ctx.node.id == "novelty"
            and ctx.opts.get("enable_patent_search")
        ):
            await ctx.host._ensure_patent_prior_art(
                ctx.run, ctx.research_direction, ctx.opts
            )
        if (
            not ctx.upstream_preflight
            and ctx.opts.get("run_experiment") is not True
            and runtime_results_contract(ctx.run, ctx.opts).kind == "runtime_owned"
            and (
                ctx.node.id
                in {
                    "figure",
                    "narrative",
                    "paper",
                    "review",
                    "audit",
                    "compile",
                    "ppt",
                }
            )
        ):
            await ctx.host._ensure_planned_result_templates(
                ctx.run, ctx.research_direction, force=False
            )


async def invoke_code_review(ctx: RunExecutionContext) -> None:
    from pathlib import Path
    from ..services.implementation_review_receipt import load_review, review_source_hash
    receipt = load_review(Path(ctx.run.project_path).resolve())
    if receipt and receipt.get("source_sha256") == review_source_hash(Path(ctx.run.project_path).resolve()):
        ctx.assessment = dict(receipt["assessment"])
        ctx.review_result = str(ctx.assessment.get("summary") or "Reused current design review")
        return
    await ctx.host._emit(ctx.run, "code_review_started", {"node_id": ctx.node.id})

    async def run_code_review_once() -> str:
        return await ctx.host._run_code_review(
            ctx.run, ctx.research_direction, ctx.effort, ctx.assurance
        )

    ctx.review_result = await ctx.host._execute_with_model_transport_retry(
        run=ctx.run,
        node_id=ctx.node.id,
        operation_name="exp-run/code-review",
        stage_id="code-review",
        operation=run_code_review_once,
        opts=ctx.opts,
    )
    ctx.assessment = ctx.host._parse_training_check_result(
        ctx.review_result, assurance=ctx.assurance
    )


async def merge_code_integrity(ctx: RunExecutionContext) -> None:
    from ..services.experiment_implementation import experiment_implementation_service

    ctx.implementation_integrity = experiment_implementation_service.audit(
        ctx.run.project_path
    )
    ctx.assessment["deterministic_implementation_integrity"] = (
        ctx.implementation_integrity
    )
    if ctx.implementation_integrity.get("blocking"):
        deterministic_findings = [
            item
            for item in ctx.implementation_integrity.get("findings", [])
            if isinstance(item, dict)
        ]
        combined_findings = []
        seen_finding_ids: set[str] = set()
        for item in [
            *deterministic_findings,
            *list(ctx.assessment.get("findings") or []),
        ]:
            finding_id = str(item.get("id") or "")
            if finding_id and finding_id in seen_finding_ids:
                continue
            if finding_id:
                seen_finding_ids.add(finding_id)
            combined_findings.append(item)
        ctx.assessment["findings"] = combined_findings
        ctx.assessment["verdict"] = "FAIL"
        ctx.assessment["blocking"] = True
        ctx.assessment["summary"] = (
            "Deterministic implementation-integrity audit failed: "
            + "; ".join(
                (str(item.get("message") or "") for item in deterministic_findings[:4])
            )
        )[:2000]


async def persist_code_review(ctx: RunExecutionContext) -> None:
    ctx.report_path = ctx.host._persist_training_check(
        ctx.run, ctx.assessment, ctx.review_result
    )
    ctx.assessment["report_path"] = ctx.report_path
    ctx.workflow_blocking = ctx.host._training_check_blocks_current_mode(
        ctx.assessment, ctx.opts
    )
    ctx.assessment["workflow_blocking"] = ctx.workflow_blocking
    ctx.assessment["advisory_only"] = bool(
        ctx.assessment.get("blocking") and (not ctx.workflow_blocking)
    )
    ctx.opts["_training_check"] = ctx.assessment
    ctx.run.options["_training_check"] = ctx.assessment
    ctx.host._append_manifest(
        ctx.run.project_path,
        ctx.run.id,
        ctx.node.id,
        "code-review",
        str(ctx.assessment.get("verdict") or "ERROR"),
        str(ctx.assessment.get("summary") or "")[:500],
    )
    await ctx.host._emit(
        ctx.run,
        "code_review_completed",
        {
            "node_id": ctx.node.id,
            "result": str(ctx.assessment.get("summary") or "")[:500],
            "verdict": ctx.assessment.get("verdict"),
            "blocking": ctx.workflow_blocking,
            "advisory_only": ctx.assessment["advisory_only"],
            "findings": ctx.assessment.get("findings", [])[:8],
            "report_path": ctx.report_path,
        },
    )
    if ctx.workflow_blocking:
        from ..services.training_review_policy import current_review_findings
        ctx.upstream_preflight = current_review_findings(ctx.assessment, ctx.opts)
        ctx.result = "Experiment execution was deferred by the read-only training check. The findings are routed to exp-design for bounded automatic repair before a fresh review."
    elif ctx.assessment.get("blocking"):
        await ctx.host._emit(
            ctx.run,
            "code_review_advisory",
            {
                "node_id": ctx.node.id,
                "reason": "experiment execution is disabled",
                "findings": ctx.assessment.get("findings", [])[:8],
                "message": "The implementation review is retained as an advisory for a future physical run; deterministic simulation generation continues in the selected no-run mode.",
            },
        )


async def run_code_review(ctx: RunExecutionContext) -> None:
    # Revalidation is not permission to discard a failed implementation review.
    # A resumed exp-run receives a fresh read-only review before any new acceptance.
    if ctx.upstream_preflight or not ctx.code_review_enabled or ctx.node.id != "exp-run":
        return
    try:
        await invoke_code_review(ctx)
        await merge_code_integrity(ctx)
        await persist_code_review(ctx)
    except Exception as error:
        logger.error("Code review failed", error=str(error))
        await ctx.host._emit(ctx.run, "code_review_failed", {
            "node_id": ctx.node.id, "error": ctx.host._exception_summary(error),
        })
        raise


async def run_managed_experiment(ctx: RunExecutionContext) -> None:
    operation_id, runtime_service = await ctx.host._runtime_execution_started(
        ctx.node, ctx.run, ctx.opts, "experiment_scheduler"
    )
    try:
        ctx.result = await ctx.host._execute_managed_experiment(ctx.run, ctx.opts)
    except Exception as exc:
        await ctx.host._runtime_execution_finished(
            ctx.node,
            ctx.run,
            operation_id,
            runtime_service,
            error=ctx.host._exception_summary(exc),
        )
        raise
    await ctx.host._runtime_execution_finished(
        ctx.node, ctx.run, operation_id, runtime_service, output=ctx.result
    )


async def run_planned_experiment(ctx: RunExecutionContext) -> None:
    from .design_review import ensure_design_review
    await ensure_design_review(ctx.host, ctx.run, ctx.research_direction, ctx.opts, ctx.assurance)
    operation_id, runtime_service = await ctx.host._runtime_execution_started(
        ctx.node, ctx.run, ctx.opts, "experiment_placeholder_service"
    )
    try:
        await ctx.host._ensure_planned_result_templates(
            ctx.run, ctx.research_direction, force=False
        )
        ctx.result = (
            "Physical/GPU experiment execution was disabled; the complete deterministic benchmark package and its quantitative figure/table assets were generated with isolated provenance."
            if str(ctx.opts.get("non_experiment_evidence_mode") or "").casefold()
            == "synthetic_preview"
            else "Experiment execution was disabled by the researcher. Code/config integrity and explicit planned-result schemas were preserved; no scientific run or GPU job was started."
        )
    except Exception as exc:
        await ctx.host._runtime_execution_finished(
            ctx.node,
            ctx.run,
            operation_id,
            runtime_service,
            error=ctx.host._exception_summary(exc),
        )
        raise
    await ctx.host._runtime_execution_finished(
        ctx.node, ctx.run, operation_id, runtime_service, output=ctx.result
    )


async def run_planned_results(ctx: RunExecutionContext) -> None:
    from .results_runtime_execution import execute_results_runtime
    ctx.result = await execute_results_runtime(
        ctx.host, ctx.node, ctx.run, ctx.research_direction, ctx.opts,
    )


async def describe_compile(ctx: RunExecutionContext) -> None:
    ctx.result = "The compile node uses the deterministic LaTeX compiler first. A model revision is requested only when the compiler reports an actionable source error."


async def run_ppt(ctx: RunExecutionContext) -> None:
    from .primary_model_execution import run_model_primary
    await run_model_primary(ctx, presentation=True)


async def run_paper(ctx: RunExecutionContext) -> None:
    ctx.result = await ctx.host._execute_staged_paper(
        node=ctx.node,
        run=ctx.run,
        research_direction=ctx.research_direction,
        opts=ctx.opts,
    )


async def run_audit(ctx: RunExecutionContext) -> None:
    ctx.result = await ctx.host._execute_audit_node(ctx.node, ctx.run, ctx.assurance)


async def run_review(ctx: RunExecutionContext) -> None:
    ctx.result = await ctx.host._execute_review_node(
        ctx.node,
        ctx.run,
        ctx.assurance,
        ctx.opts,
    )


async def run_generic_primary(ctx: RunExecutionContext) -> None:
    from .primary_model_execution import run_model_primary
    await run_model_primary(ctx)


async def run_primary_model(ctx: RunExecutionContext) -> None:
    if ctx.node.id == "exp-run" and ctx.opts.get("run_experiment") is not True:
        await run_planned_experiment(ctx)
    elif ctx.node.id == "results":
        from ..services.node_execution_contract import resolve_execution_contract

        contract = resolve_execution_contract("results", ctx.opts, project_path=ctx.run.project_path)
        if contract.blocking_issues:
            raise ValueError("Results execution contract is blocked: " + "; ".join(contract.blocking_issues))
        if contract.kind == "runtime_owned":
            await run_planned_results(ctx)
        else:
            await run_generic_primary(ctx)
    elif ctx.node.id == "compile":
        await describe_compile(ctx)
    elif ctx.node.id == "ppt":
        await run_ppt(ctx)
    elif ctx.node.id == "paper":
        await run_paper(ctx)
    elif ctx.node.id == "audit":
        await run_audit(ctx)
    elif ctx.node.id == "review":
        await run_review(ctx)
    else:
        await run_generic_primary(ctx)


async def run_primary_execution(ctx: RunExecutionContext) -> None:
    from .paper_resume_stage import resume_incomplete_paper_stages
    if await resume_incomplete_paper_stages(ctx):
        return
    if ctx.revalidate_done or ctx.upstream_preflight:
        return
    if ctx.node.id == "exp-run" and ctx.opts.get("run_experiment") is True:
        await run_managed_experiment(ctx)
    else:
        await run_primary_model(ctx)
