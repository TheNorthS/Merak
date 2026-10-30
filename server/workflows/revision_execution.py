"""Route one structured gate finding to its producer-owned repair operation."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from ..services.workflow_inputs import artifact_state, artifact_state_equal
from .models import WorkflowNode, WorkflowRun


IMPLEMENTATION_CATEGORIES = {
    "implementation",
    "staged_implementation",
    "implementation_review",
}
INTEGRATION_CATEGORIES = {"reproducibility", "configuration", "execution"}
INTEGRATION_TARGETS = {
    "experiments/METHOD_CONTRACT.json",
    "experiments/RUN_SPEC.json",
    "experiments/configs/main.yaml",
    "experiments/src/test_pipeline.py",
}


def _implementation_only(node: WorkflowNode, findings: list[dict[str, Any]]) -> bool:
    if node.id != "exp-design" or not findings:
        return False

    def accepted(item: dict[str, Any]) -> bool:
        category = str(item.get("category") or "").casefold()
        if category in IMPLEMENTATION_CATEGORIES:
            return True
        targets = item.get("target_files") or item.get("evidence") or []
        return (
            category in INTEGRATION_CATEGORIES
            and isinstance(targets, (list, tuple, set))
            and bool(targets)
            and {str(value).replace("\\", "/") for value in targets}
            <= INTEGRATION_TARGETS
        )

    return any(
        str(item.get("category") or "").casefold() in IMPLEMENTATION_CATEGORIES
        for item in findings
    ) and all(accepted(item) for item in findings)


async def _prepare_specialists(
    host: Any,
    node: WorkflowNode,
    run: WorkflowRun,
    diagnostics: dict[str, Any],
    direction: str,
    opts: dict[str, Any],
    implementation_only: bool,
) -> None:
    issues = " ".join(str(item) for item in diagnostics.get("issues", [])).casefold()
    specialist_failure = node.id in {"exp-design", "results"} and (
        "specialist" in str(diagnostics.get("reason") or "").casefold()
        or "specialist" in issues
    )
    if specialist_failure:
        result = await host._execute_profile_specialists(
            node=node,
            run=run,
            direction=direction,
            opts=opts,
        )
        if not result.get("accepted"):
            raise RuntimeError(str(result.get("error") or "specialist subnode failed"))
    elif node.id in {"exp-design", "results"} and not implementation_only:
        await host._execute_profile_specialists(
            node=node,
            run=run,
            direction=direction,
            opts=opts,
        )


def _results_runtime_owned(opts: dict[str, Any]) -> bool:
    """Use the same declared owner before specialist, model or runtime repair."""
    from ..services.results_execution_policy import resolve_results_execution_policy

    policy = resolve_results_execution_policy(opts)
    if policy.issues:
        raise ValueError("Results execution contract is blocked: " + "; ".join(policy.issues))
    return policy.kind == "runtime_owned"


async def _results_repair(
    host: Any,
    node: WorkflowNode,
    run: WorkflowRun,
    direction: str,
    round_number: int,
    opts: dict[str, Any],
) -> str:
    path = Path(run.project_path) / "experiments" / "results" / "analysis.md"
    before = artifact_state(path)
    from .results_runtime_execution import execute_results_runtime
    result = await execute_results_runtime(host, node, run, direction, opts)
    after = artifact_state(path)
    await host._emit(
        run,
        "planned_results_platform_repair",
        {
            "node_id": node.id,
            "round": round_number,
            "changed": not artifact_state_equal(before, after),
            "artifact": str(path),
            "message": (
                "确定性仿真基准分析已从当前机器结果包重新生成；不会让模型改写或杜撰数值。"
                if str(opts.get("non_experiment_evidence_mode") or "").casefold()
                == "synthetic_preview"
                else "未运行实验的结果分析已由前瞻语义生成器修复；不会调用模型生成实证结论。"
            ),
        },
    )
    return result


async def _figure_repair(
    host: Any,
    node: WorkflowNode,
    run: WorkflowRun,
    diagnostics: dict[str, Any],
    instruction: str,
    direction: str,
    effort: str,
    assurance: str,
    round_number: int,
    opts: dict[str, Any],
    user_feedback: str,
) -> str:
    scope = diagnostics.get("repair_scope")
    scope = scope if isinstance(scope, dict) else {}
    assets = sorted({str(item) for item in scope.get("asset_ids") or [] if str(item)})
    from .figure_repair_routing import rebuild_deterministic_assets

    model_assets, deterministic_assets = await rebuild_deterministic_assets(
        host, run, node.id, direction, round_number, assets,
    )
    if deterministic_assets and not model_assets:
        return "Rebuilt deterministic assets from their current typed specifications."
    assets = model_assets
    from .figure_feedback_scope import scoped_figure_feedback
    scoped_feedback = scoped_figure_feedback(assets, user_feedback)
    target_contract = (
        "Only repair semantic asset IDs: " + ", ".join(assets)
        if assets
        else "Repair only semantic assets named by the gate."
    )
    issue_text = " ".join(
        str(item) for item in diagnostics.get("issues", [])
    ).casefold()
    action_contract = (
        "This is a manuscript-plan linkage repair, not a rendering failure. Do not call\n"
        "  generate_figure and do not create, copy, rename, or move any figure asset. "
        "Read existing manifests, then edit only the canonical\n"
        "  paper/PAPER_PLAN.md."
        if "required figure is not referenced in paper/paper_plan.md" in issue_text
        else "Use the existing FIGURE_SPECS id as artifact_name and repair the same "
        "semantic asset in place. Never add a suffix, UUID, retry number, or duplicate."
    )
    if deterministic_assets:
        action_contract += (
            " Deterministic assets were already rebuilt by their owner and are not "
            "legal model edit targets: " + ", ".join(sorted(deterministic_assets)) + "."
        )
    return await host._execute_node(
        node,
        run,
        direction,
        effort,
        assurance,
        wandb=bool(opts.get("wandb", False)),
        compact=bool(opts.get("compact", False)),
        gpu_target=str(opts.get("gpu_target") or "local"),
        ssh_server_id=str(opts.get("ssh_server_id") or ""),
        opts={**opts, "_figure_revision_scoped_feedback": scoped_feedback},
        revision_context=(
            instruction
            + "\n\nFigure repair contract: "
            + target_contract
            + "\n"
            + action_contract
        ),
    )


async def _document_rebuild(
    host: Any,
    node: WorkflowNode,
    run: WorkflowRun,
    diagnostics: dict[str, Any],
    instruction: str,
    direction: str,
    effort: str,
    assurance: str,
    opts: dict[str, Any],
) -> str:
    from ..services.paper_compiler import paper_compiler

    root = Path(run.project_path) / ("paper" if node.id == "compile" else "slides")
    ids = {
        str(value).upper()
        for value in (diagnostics.get("repair_scope") or {}).get("finding_ids", [])
    }
    blob = json.dumps(diagnostics, ensure_ascii=False).casefold()
    model_changed = False
    if node.id == "ppt" and _ppt_semantic(ids, blob):
        await host._execute_node(
            node,
            run,
            direction,
            effort,
            assurance,
            wandb=False,
            compact=bool(opts.get("compact", False)),
            gpu_target="none",
            ssh_server_id="",
            opts=opts,
            revision_context=instruction,
        )
        model_changed = True
    if node.id == "compile" and _compile_source_error(ids, blob):
        model_changed = await _latex_source_repair(host, node, run, root, instruction)
    operation_id, runtime = await host._runtime_execution_started(
        node,
        run,
        opts,
        "paper_compiler"
        if node.id == "compile"
        else "scientific_slide_service+paper_compiler",
    )
    if node.id == "ppt":
        from ..services.scientific_slides import scientific_slide_service

        if not model_changed and any(
            (value.startswith(("PPT-PLAN-", "PPT-SOURCE-")) for value in ids)
        ):
            scientific_slide_service.ensure(run.project_path, direction, force=True)
        paper_compiler.repair_common_source_dependencies(root, "main.tex")
        scientific_slide_service.refresh_plan_binding(run.project_path)
    compiled = await paper_compiler.compile(str(root), "main.tex", clean=True)
    return await _finish_document_rebuild(
        host, node, run, root, compiled, operation_id, runtime, model_changed
    )


async def _finish_document_rebuild(
    host: Any,
    node: WorkflowNode,
    run: WorkflowRun,
    root: Path,
    compiled: Any,
    operation_id: str,
    runtime: str,
    model_changed: bool,
) -> str:
    if not compiled.success:
        errors = host._compile_failure_summary(compiled)
        await host._runtime_execution_finished(
            node, run, operation_id, runtime, error=errors
        )
        raise RuntimeError(f"Deterministic {node.id} compile failed: {errors}")
    host._refresh_compiled_artifact_record(
        root,
        "PAPER_BUILD.json" if node.id == "compile" else "SLIDE_BUILD.json",
        "main.pdf",
        pages=getattr(compiled, "pages", 0),
        compile_time_ms=getattr(compiled, "compile_time_ms", 0),
        warning_count=len(getattr(compiled, "warnings", []) or []),
    )
    summary = (
        f"Deterministic {node.id} rebuild succeeded with {compiled.pages} page(s); "
        + (
            "a bounded source repair was applied."
            if model_changed
            else "no model-authored source change was applied."
        )
    )
    await host._runtime_execution_finished(
        node, run, operation_id, runtime, output=summary
    )
    return summary


def _compile_source_error(ids: set[str], text: str) -> bool:
    return (
        any(value.startswith("COMPILE-TEX-") for value in ids)
        or bool(re.search(r"[^\s]+\.tex:\d+", text))
        or any(
            marker in text
            for marker in (
                "undefined control sequence",
                "runaway argument",
                "missing \\begin",
                "missing }",
                "missing $ inserted",
                "extra }",
                "unicode character",
            )
        )
    )


def _ppt_semantic(ids: set[str], text: str) -> bool:
    deterministic = ("PPT-PDF-", "PPT-STALE-", "PPT-BUILD-", "PPT-PLAN-", "PPT-SOURCE-")
    return bool(
        ids and any(not value.startswith(deterministic) for value in ids)
    ) or any(
        marker in text
        for marker in (
            "not a complete beamer",
            "text-dense",
            "tiny or scriptsize",
            "unknown citation",
            "unsupported claim",
            "slide content",
            "layout",
        )
    )


async def _latex_source_repair(
    host: Any,
    node: WorkflowNode,
    run: WorkflowRun,
    root: Path,
    instruction: str,
) -> bool:
    from ..agent.tools import invoke_skill
    from ..services.skill_orchestrator import skill_orchestrator

    started = time.time()
    skill_orchestrator.mark_execution(
        run.project_path,
        run.id,
        node.id,
        "paper-compile",
        "running",
        role="repair",
        policy_loaded=True,
        execution_kind="model_owned",
    )
    try:
        output = await invoke_skill(
            "paper-compile",
            f"Repair only actionable LaTeX source errors in {root}.\n{instruction}",
            project_path=run.project_path,
            parent_context="skill-chain:workflow>compile-repair",
            allowed_tools_override=["Read", "Write", "Edit", "Glob", "Grep"],
            invocation_contract="Repair pass only; runtime owns compilation.",
            max_iterations=10,
        )
    except Exception as error:
        _record_compile_repair(host, node, run, started, "failed", error=str(error))
        raise
    _record_compile_repair(host, node, run, started, "completed", output=str(output))
    return True


def _record_compile_repair(
    host: Any,
    node: WorkflowNode,
    run: WorkflowRun,
    started: float,
    status: str,
    *,
    output: str = "",
    error: str = "",
) -> None:
    from ..services.skill_orchestrator import skill_orchestrator

    traces = host._skill_invocation_traces(run.project_path, "paper-compile", started)
    trace = traces[-1] if traces else {}
    skill_orchestrator.mark_execution(
        run.project_path,
        run.id,
        node.id,
        "paper-compile",
        status,
        role="repair",
        session_id=str(trace.get("session_id") or ""),
        output=output,
        error=error,
        policy_loaded=True,
        execution_kind="model_owned",
    )


async def _runtime_repair(
    host: Any,
    node: WorkflowNode,
    run: WorkflowRun,
    diagnostics: dict[str, Any],
    round_number: int,
    cycle: int,
    direction: str,
    assurance: str,
    opts: dict[str, Any],
    feedback: str,
    implementation_only: bool,
) -> str | None:
    if node.id == "exp-run":
        if opts.get("run_experiment") is True:
            repaired = await host._repair_failed_experiment_source(
                run=run,
                diagnostics=diagnostics,
                round_number=round_number,
                cycle=cycle,
            )
            from .managed_experiment_repair_execution import execute_repaired_experiment
            result = await execute_repaired_experiment(host, node, run, opts)
            return repaired.rstrip() + "\n\n" + result if repaired.strip() else result
        from .design_review import ensure_design_review
        await ensure_design_review(host, run, direction, opts, assurance)
        await host._ensure_planned_result_templates(
            run,
            direction,
            force=False,
        )
        return "Experiment execution remains disabled; planned schemas were rebuilt."
    if node.id == "audit":
        return await host._execute_audit_node(node, run, assurance)
    if implementation_only:
        await host._emit(
            run,
            "implementation_repair_routed",
            {
                "node_id": node.id,
                "round": round_number,
                "cycle": cycle,
                "target_files": list(
                    (diagnostics.get("repair_scope") or {}).get("target_files") or [],
                ),
                "message": "实现类 finding 已直接路由到分阶段代码所有者。",
            },
        )
        return (
            "Implementation-only repair routed to the staged owner; "
            "deterministic preparation will revalidate implicated stages."
        )
    if node.id == "review":
        review_opts = {**opts}
        if feedback.strip():
            review_opts["review_researcher_feedback"] = feedback.strip()
        return await host._execute_review_node(node, run, assurance, review_opts)
    return None


def _messages_for_targets(
    findings: list[dict[str, Any]],
    targets: list[str],
    fallback: list[str],
) -> list[str]:
    selected = set(targets)
    messages = list(
        dict.fromkeys(
            str(item.get("message") or item.get("plain_message") or "").strip()
            for item in findings
            if selected.intersection(
                str(value).replace("\\", "/")
                for value in item.get("target_files", [])
                if str(value).strip()
            )
            and str(item.get("message") or item.get("plain_message") or "").strip()
        )
    )
    return messages or fallback


async def _paper_repair(
    host: Any,
    node: WorkflowNode,
    run: WorkflowRun,
    diagnostics: dict[str, Any],
    direction: str,
    feedback: str,
    opts: dict[str, Any],
) -> str:
    from ..services.paper_drafting import paper_drafting_service

    issues = [str(item) for item in diagnostics.get("issues", []) if str(item)]
    scope = diagnostics.get("repair_scope")
    scope = scope if isinstance(scope, dict) else {}
    targets = [
        str(item).replace("\\", "/")
        for item in scope.get("target_files") or []
        if str(item).replace("\\", "/").casefold().startswith("paper/")
    ]
    from .paper_repair_runtime import PAPER_RUNTIME_TARGETS, paper_refresh_required, refresh_paper_runtime_inputs, remaining_paper_findings
    stale_refresh = paper_refresh_required(diagnostics)
    runtime_targets = [path for path in targets if path.casefold() in PAPER_RUNTIME_TARGETS]
    targets = [path for path in targets if path.casefold() not in PAPER_RUNTIME_TARGETS]
    if stale_refresh or runtime_targets:
        refreshed = await refresh_paper_runtime_inputs(host, node, run, direction, opts)
        if not refreshed.get("passed"):
            raise RuntimeError("Paper runtime refresh requires current upstream evidence: " + "; ".join(refreshed.get("issues") or []))
        diagnostics = remaining_paper_findings(diagnostics)
        issues = list(diagnostics.get("issues") or [])
        fresh_gate = host._paper_acceptance_gate(
            run.project_path, require_staged=True, require_page_budget=False, paper_options=opts,
        )
        if fresh_gate.get("accepted"):
            return "Runtime-owned paper projections and scientific bindings were refreshed and freshly revalidated."
        diagnostics = host._gate_revision_diagnostics(fresh_gate)
        scope = diagnostics.get("repair_scope") or {}
        issues = list(diagnostics.get("issues") or [])
        targets = [str(item).replace("\\", "/") for item in scope.get("target_files") or []
                   if str(item).replace("\\", "/").casefold().startswith("paper/")
                   and str(item).replace("\\", "/").casefold() not in PAPER_RUNTIME_TARGETS]
    if stale_refresh:
        issues = [item for item in issues if not any(
            marker in str(item).casefold() for marker in (
                "scientific inputs changed after paper freeze", "authoritative paper-input hashes changed",
                "staged paper state is stale", "staged paper state is bound to a different scientific freeze",
            )
        )]
    staged, tables, unsupported = ([], [], [])
    for path in targets:
        if paper_drafting_service.stage_for_project_relative_target(path):
            staged.append(path)
        elif (
            path.casefold().startswith("paper/tables/") and Path(path).suffix == ".tex"
        ):
            tables.append(path)
        else:
            unsupported.append(path)
    if unsupported:
        raise RuntimeError(
            "Paper repair scope contains unsupported targets: " + ", ".join(unsupported)
        )
    return await _execute_paper_repairs(
        host,
        node,
        run,
        diagnostics,
        direction,
        feedback,
        opts,
        issues,
        scope,
        targets,
        staged,
        tables,
    )


async def _execute_paper_repairs(
    host: Any,
    node: WorkflowNode,
    run: WorkflowRun,
    diagnostics: dict[str, Any],
    direction: str,
    feedback: str,
    opts: dict[str, Any],
    issues: list[str],
    scope: dict[str, Any],
    targets: list[str],
    staged: list[str],
    tables: list[str],
) -> str:
    findings = [
        item for item in diagnostics.get("findings", []) if isinstance(item, dict)
    ]
    results = []
    if tables:
        table_gate = {
            **diagnostics,
            "issues": _messages_for_targets(findings, tables, issues),
            "repair_scope": {**scope, "target_files": tables},
        }
        results.append(
            await host._execute_bounded_paper_table_repair(
                node=node,
                run=run,
                diagnostics=table_gate,
                target_files=tables,
                user_feedback=feedback,
            )
        )
    if staged or not targets:
        revision_issues = [
            *(f"Target artifact: {path}" for path in staged),
            *_messages_for_targets(findings, staged, issues),
        ]
        if (
            "reviewed paper failed deterministic reconciliation"
            in str(diagnostics.get("reason") or "").casefold()
        ):
            revision_issues.insert(
                0,
                "Downstream review regression repair: restore the accepted section contract without broadening unrelated content.",
            )
        if feedback.strip():
            revision_issues.insert(0, "Researcher feedback: " + feedback.strip())
        results.append(
            await host._execute_staged_paper(
                node=node,
                run=run,
                research_direction=direction,
                opts=opts,
                revision_issues=revision_issues,
            )
        )
    return "\n\n".join((str(item).strip() for item in results if str(item).strip()))


async def revise_node_from_gate(
    host: Any,
    node: WorkflowNode,
    run: WorkflowRun,
    diagnostics: dict[str, Any],
    round_number: int,
    cycle: int,
    user_feedback: str,
    research_direction: str,
    effort: str,
    assurance: str,
    opts: dict[str, Any],
) -> str:
    if node.id == "results":
        _results_runtime_owned(opts)
    instruction = host._build_gate_revision_instruction(
        node, diagnostics, round_number, cycle, user_feedback
    )
    from .paper_plan_repair import repair_plan_only
    plan = await repair_plan_only(host, node, run, diagnostics, instruction, research_direction, effort, assurance, opts)
    if plan is not None:
        return plan
    findings = [
        item for item in diagnostics.get("findings", []) if isinstance(item, dict)
    ]
    implementation_only = _implementation_only(node, findings)
    await _prepare_specialists(
        host, node, run, diagnostics, research_direction, opts, implementation_only
    )
    return await _route_revision(
        host,
        node,
        run,
        diagnostics,
        round_number,
        cycle,
        user_feedback,
        research_direction,
        effort,
        assurance,
        opts,
        instruction,
        implementation_only,
    )


async def _route_revision(
    host: Any,
    node: WorkflowNode,
    run: WorkflowRun,
    diagnostics: dict[str, Any],
    round_number: int,
    cycle: int,
    user_feedback: str,
    research_direction: str,
    effort: str,
    assurance: str,
    opts: dict[str, Any],
    instruction: str,
    implementation_only: bool,
) -> str:
    if node.id == "results" and _results_runtime_owned(opts):
        return await _results_repair(
            host, node, run, research_direction, round_number, opts
        )
    if node.id == "figure":
        return await _figure_repair(
            host,
            node,
            run,
            diagnostics,
            instruction,
            research_direction,
            effort,
            assurance,
            round_number,
            opts,
            user_feedback,
        )
    if node.id in {"compile", "ppt"}:
        return await _document_rebuild(
            host,
            node,
            run,
            diagnostics,
            instruction,
            research_direction,
            effort,
            assurance,
            opts,
        )
    runtime = await _runtime_repair(
        host,
        node,
        run,
        diagnostics,
        round_number,
        cycle,
        research_direction,
        assurance,
        opts,
        user_feedback,
        implementation_only,
    )
    if runtime is not None:
        return runtime
    if node.id == "paper":
        return await _paper_repair(
            host, node, run, diagnostics, research_direction, user_feedback, opts
        )
    return await host._execute_node(
        node,
        run,
        research_direction,
        effort,
        assurance,
        wandb=bool(opts.get("wandb", False)),
        compact=bool(opts.get("compact", False)),
        gpu_target=str(opts.get("gpu_target") or "local"),
        ssh_server_id=str(opts.get("ssh_server_id") or ""),
        opts=opts,
        revision_context=instruction,
    )
