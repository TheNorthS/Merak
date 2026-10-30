"""Prepare canonical node artifacts before deterministic acceptance checks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .engine_context import logger
from .models import NodeStatus, WorkflowNode, WorkflowRun
from .run_state import RunState


async def _repair_generated_sources(
    host: Any,
    node: WorkflowNode,
    run: WorkflowRun,
    assurance: str,
    opts: dict[str, Any],
) -> None:
    if node.id in {"lit", "idea", "novelty"} or not opts.get(
        "deterministic_source_repair", True
    ):
        return
    from ..services.generated_source_repair import generated_source_repair_service

    repair = generated_source_repair_service.repair_python_sources(
        run.project_path,
        node_id="exp-design",
    )
    if not repair["repaired"]:
        return
    await host._emit(
        run,
        "source_integrity_repaired",
        {
            "node_id": node.id,
            "owner_node_id": "exp-design",
            "repairs": repair["repaired"],
            "report_path": repair["report_path"],
        },
    )
    if node.id == "exp-design":
        return
    owner = host._find_node(run, "exp-design") or WorkflowNode(
        id="exp-design",
        name="Experiment design",
        skill="/experiment-plan",
    )
    state = RunState(run.project_path, run.id)
    persisted = state.load() or {}
    if "exp-design" in persisted.get("phases", {}):
        state.set_status(
            "exp-design",
            "done",
            details={
                "deterministic_source_repair": {
                    "report_path": repair["report_path"],
                    "files": [item["path"] for item in repair["repaired"]],
                },
            },
        )
    gate = host._acceptance_gate(
        owner,
        run,
        assurance,
        "Deterministic source integrity repair completed.",
        require_fresh=False,
    )
    if gate.get("accepted"):
        if "exp-design" in persisted.get("phases", {}):
            state.accept(
                "exp-design",
                str(gate.get("verdict_id") or "artifact:exp-design-repaired"),
                str(gate.get("reviewer") or "deterministic:source-repair"),
                details={
                    "source_repair_revalidated": True,
                    "source_repair_report": repair["report_path"],
                },
            )
        owner.status = NodeStatus.COMPLETED
    await host._emit(
        run,
        "upstream_owner_revalidated",
        {
            "node_id": node.id,
            "owner_node_id": "exp-design",
            "accepted": bool(gate.get("accepted")),
            "summary": str(gate.get("summary") or gate.get("reason") or ""),
        },
    )


async def _preflight(
    host: Any,
    node: WorkflowNode,
    run: WorkflowRun,
    opts: dict[str, Any],
    result: str,
) -> bool:
    from ..services.node_risk_audit import node_risk_audit_service

    findings = node_risk_audit_service.preflight_node(run.project_path, node.id, opts)
    run.options.setdefault("_node_preflight_findings", {})[node.id] = findings
    upstream = [
        item
        for item in findings
        if item.get("severity") == "blocker"
        and str(item.get("upstream_node") or "").strip()
        and str(item.get("upstream_node") or "").strip() != node.id
    ]
    if not upstream:
        return False
    owners = list(
        dict.fromkeys(
            str(item.get("upstream_node") or "")
            for item in upstream
            if item.get("upstream_node")
        )
    )
    already_emitted = run.options.pop("_upstream_execution_deferred", "") == node.id
    if not already_emitted:
        await host._emit(
            run,
            "node_preparation_deferred",
            {
                "node_id": node.id,
                "owner_node_ids": owners,
                "issues": [
                    str(item.get("plain_message") or item.get("message") or "")
                    for item in upstream[:8]
                ],
            },
        )
    return True


async def _prepare_primary_artifacts(
    host: Any,
    node: WorkflowNode,
    run: WorkflowRun,
    result: str,
    direction: str,
    assurance: str,
    opts: dict[str, Any],
) -> str:
    if node.id == "figure":
        await host._ensure_figure_artifacts(run, result, direction)
    if node.id == "exp-design":
        await host._ensure_exp_design_artifacts(run, result, direction, assurance)
        if opts.get("staged_experiment_implementation") is True:
            report = await host._execute_staged_experiment_implementation(
                run=run,
                direction=direction,
                opts=opts,
            )
            run.options["_staged_implementation_report"] = (
                report if isinstance(report, dict) else {}
            )
            result = (
                result.rstrip()
                + "\n\nStaged implementation build: "
                + str(
                    report.get("status") or "unknown",
                )
            )
            # Do not render downstream previews while the implementation owner
            # is blocked: acceptance must expose its structured stage findings.
            if report.get("blocking"):
                return result
        from .design_review import ensure_design_review
        await ensure_design_review(host, run, direction, opts, assurance)
    if node.id == "narrative":
        await _prepare_narrative(host, node, run, direction, opts)
    if node.id == "exp-run" and opts.get("run_experiment") is not True:
        from .design_review import ensure_design_review
        await ensure_design_review(host, run, direction, opts, assurance)
        await host._ensure_planned_result_templates(run, direction, force=False)
    return result


async def _prepare_narrative(
    host: Any,
    node: WorkflowNode,
    run: WorkflowRun,
    direction: str,
    opts: dict[str, Any],
) -> None:
    from ..services.paper_plan import paper_plan_service
    from ..services.scientific_narrative import scientific_narrative_service

    path = Path(run.project_path) / "NARRATIVE_REPORT.md"
    authored = bool(
        node.started_at
        and path.is_file()
        and path.stat().st_mtime + 1.0 >= float(node.started_at)
    )
    if authored and host._artifact_changed_from_baseline(
        run.project_path,
        path,
        node.artifact_baseline,
    ):
        scientific_narrative_service.record_existing(
            run.project_path,
            generator="model-authored:narrative-node",
        )
    from ..contracts.preparation import PreparationContractError
    if not path.is_file() or not path.stat().st_size:
        raise PreparationContractError("Model-authored narrative is missing; resume its producer",
                                       owner="narrative", paths=("NARRATIVE_REPORT.md",))
    build_path = Path(run.project_path) / scientific_narrative_service.build_relative_path
    build = json.loads(build_path.read_text(encoding="utf-8-sig")) if build_path.is_file() else {}
    current_source = scientific_narrative_service._source_hash(Path(run.project_path),
        scientific_narrative_service._source_paths(Path(run.project_path)))
    if build.get("source_bundle_sha256") != current_source:
        raise PreparationContractError("Model-authored narrative sources changed; repair narrative before its paper plan",
                                       owner="narrative", paths=("NARRATIVE_REPORT.md",))
    plan_path = paper_plan_service.path(Path(run.project_path))
    if not paper_plan_service.is_valid(plan_path) or not paper_plan_service.is_current(run.project_path):
        raise PreparationContractError("Model-authored paper plan is missing or stale; resume its producer",
                                       owner="narrative", paths=("paper/PAPER_PLAN.md",))



async def _prepare_results_and_paper(
    host: Any,
    node: WorkflowNode,
    run: WorkflowRun,
    result: str,
    direction: str,
    opts: dict[str, Any],
) -> str:
    if node.id == "results":
        from .results_runtime_execution import execute_results_runtime, runtime_results_contract
        if runtime_results_contract(run, opts).kind == "runtime_owned":
            result = await execute_results_runtime(host, node, run, direction, opts, result=result)
    if node.id == "paper":
        result = await host._ensure_paper_artifacts(run, result, direction)
    if node.id == "ppt":
        await _prepare_slides(host, node, run, direction)
    return result


async def _prepare_slides(
    host: Any,
    node: WorkflowNode,
    run: WorkflowRun,
    direction: str,
) -> None:
    from ..services.scientific_slides import scientific_slide_service

    slide_main = Path(run.project_path) / "slides" / "main.tex"
    authored = host._artifact_changed_from_baseline(
        run.project_path,
        slide_main,
        node.artifact_baseline,
    )
    slides = scientific_slide_service.ensure(
        run.project_path,
        direction,
        bind_existing=authored,
    )
    event = (
        "slide_artifact_recovered"
        if slides["generated"]
        else ("slide_source_bound" if slides.get("bound") else "")
    )
    if event:
        await host._emit(run, event, {"node_id": node.id, **slides})


async def _compile_if_required(
    host: Any, node: WorkflowNode, run: WorkflowRun, opts: dict[str, Any]
) -> None:
    if node.id not in {"compile", "ppt"}:
        return
    from ..services.paper_compiler import paper_compiler

    service = (
        "paper_compiler"
        if node.id == "compile"
        else "scientific_slide_service+paper_compiler"
    )
    operation_id, runtime = await host._runtime_execution_started(
        node, run, opts, service
    )
    source_root = Path(run.project_path) / (
        "paper" if node.id == "compile" else "slides"
    )
    source = source_root / "main.tex"
    if not source.is_file() or source.stat().st_size <= 0:
        await host._runtime_execution_finished(
            node, run, operation_id, runtime, error=f"Missing or empty source: {source}"
        )
        return
    packages = (
        paper_compiler.repair_common_source_dependencies(source_root, "main.tex")
        if node.id == "ppt"
        else []
    )
    if packages:
        await host._emit(
            run,
            "latex_dependency_repaired",
            {"node_id": node.id, "packages": packages, "source_path": str(source)},
        )
    if node.id == "ppt":
        from ..services.scientific_slides import scientific_slide_service

        scientific_slide_service.refresh_plan_binding(run.project_path)
    if node.id == 'compile':
        from ..services.paper_print_repair import compile_print_verified_paper
        compiled = await compile_print_verified_paper(
            paper_compiler, run.project_path,
            on_repair=lambda data: host._emit(run, 'paper_print_layout_repaired', {'node_id': node.id, **data}),
        )
    else:
        compiled = await paper_compiler.compile(str(source_root), "main.tex", clean=True)
    await _finish_compile(host, node, run, operation_id, runtime, source_root, compiled)


async def _finish_compile(
    host: Any,
    node: WorkflowNode,
    run: WorkflowRun,
    operation_id: str,
    runtime: str,
    source_root: Path,
    compiled: Any,
) -> None:
    await host._emit(
        run,
        "deterministic_compile_completed",
        {
            "node_id": node.id,
            "success": compiled.success,
            "pdf_path": compiled.pdf_path or "",
            "pages": compiled.pages,
            "errors": [item.message for item in compiled.errors[:5]],
        },
    )
    if not compiled.success:
        errors = host._compile_failure_summary(compiled)
        await host._runtime_execution_finished(
            node, run, operation_id, runtime, error=errors
        )
        raise RuntimeError(f"Deterministic {node.id} compile failed: {errors}")
    host._refresh_compiled_artifact_record(
        source_root,
        "PAPER_BUILD.json" if node.id == "compile" else "SLIDE_BUILD.json",
        "main.pdf",
        pages=getattr(compiled, "pages", 0),
        compile_time_ms=getattr(compiled, "compile_time_ms", 0),
        warning_count=len(getattr(compiled, "warnings", []) or []),
    )
    await host._runtime_execution_finished(
        node,
        run,
        operation_id,
        runtime,
        output=json.dumps(
            {"pdf_path": compiled.pdf_path or "", "pages": compiled.pages}
        ),
    )


def _refresh_evidence_map(host: Any, node: WorkflowNode, run: WorkflowRun) -> None:
    if node.id not in {"paper", "review", "audit", "compile", "ppt"}:
        return
    try:
        from ..services.paper_artifacts import paper_artifact_builder

        paper_artifact_builder.refresh_evidence_map(run.project_path)
    except Exception as error:
        logger.warning(
            "Paper evidence map refresh failed", node=node.id, error=str(error)
        )


async def prepare_node_for_gate(
    host: Any,
    node: WorkflowNode,
    run: WorkflowRun,
    result: str,
    direction: str,
    assurance: str,
    opts: dict[str, Any],
) -> str:
    await _repair_generated_sources(host, node, run, assurance, opts)
    if await _preflight(host, node, run, opts, result):
        return result
    result = await _prepare_primary_artifacts(
        host,
        node,
        run,
        result,
        direction,
        assurance,
        opts,
    )
    result = await _prepare_results_and_paper(host, node, run, result, direction, opts)
    await _compile_if_required(host, node, run, opts)
    _refresh_evidence_map(host, node, run)
    return result
