"""工作流管理 API"""

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Any, List, Literal, Optional
import json
import asyncio
import structlog

from ..workflows.engine import (
    AUTONOMOUS_REVISION_ROUNDS,
    LITERATURE_SOURCE_TOOLS,
    normalize_workflow_illustration_mode,
    workflow_engine,
)
from ..services.workflow_recovery import workflow_recovery_watchdog
from ..services.workflow_display_logs import read_workflow_display_logs
from .workflow_run_service import WorkflowRequestError, prepare_workflow_run

router = APIRouter()
from .evidence_version_routes import router as evidence_version_router
router.include_router(evidence_version_router)
logger = structlog.get_logger()

from ..contracts.workflow_nodes import WORKFLOW_NODES
WORKFLOW_NODE_IDS = {node["id"] for node in WORKFLOW_NODES}


class WorkflowRunRequest(BaseModel):
    node_ids: List[str]
    project_path: str
    research_direction: str = ""
    effort: str = "balanced"
    assurance: str = "draft"
    delivery_goal: Literal["submission_candidate", "reviewable_draft"] = "reviewable_draft"
    research_quality_mode: Literal["standard", "rigorous", "off"] = "rigorous"
    # GPU / SSH
    gpu_target: str = "local"  # "local" | "remote" | "vast" | "modal"
    ssh_server_id: str = ""
    # 实验控制
    # Scientific execution is opt-in. Omitting this field may build and verify
    # research artifacts, but must never start training or inference.
    run_experiment: bool = False
    non_experiment_evidence_mode: Literal[
        "design_only", "synthetic_preview", "existing_results", "secondary_analysis"
    ] = "design_only"
    illustration_mode: Literal["auto"] = "auto"
    gpu_info: str = ""
    max_retries: int = 3
    experiment_timeout_seconds: int = Field(default=6 * 3600, ge=30, le=7 * 24 * 3600)
    sync_project_data: bool = False
    auto_stop_on_anomaly: bool = True
    remote_gpu_type: str = "A100"
    max_remote_cost_usd: float = Field(default=10.0, gt=0, le=10000)
    vast_max_hourly_usd: float = Field(default=2.0, gt=0, le=100)
    auto_destroy_vast: bool = True
    # Research task definition
    research_mode: Literal["from_scratch", "paper_code_innovation"] = "from_scratch"
    innovation_focus: str = ""
    ref_paper: str = ""
    base_repo: str = ""
    input_files: List[str] = Field(default_factory=list, max_length=128)
    # Inputs from the focused-node schema. These are prompt/configuration
    # constraints only; they never authorize arbitrary command execution.
    node_inputs: dict[str, Any] = Field(default_factory=dict)
    research_family: Literal[
        "auto", "machine_learning", "computer_systems", "computational_biology",
        "clinical_biomedical", "experimental_natural_science",
        "social_behavioral", "engineering_systems", "theoretical_formal",
        "qualitative_humanities", "generic_quantitative",
    ] = "auto"
    study_archetype: Literal[
        "auto", "algorithm_benchmark", "observational_cohort",
        "diagnostic_prognostic", "intervention_trial", "omics_discovery",
        "controlled_experiment", "systems_testbed", "simulation_modeling",
        "formal_theory", "qualitative_mixed", "generic_empirical",
    ] = "auto"
    target_venue: str = "ICLR"
    venue_template_path: str = ""
    target_pages: int = Field(default=0, ge=0, le=50)
    target_page_tolerance: int = Field(default=1, ge=0, le=5)
    # Research strategy controls
    literature_year_from: int = 2021
    literature_year_to: int = 0  # 0 = current year
    literature_max_papers: int = Field(default=35, ge=5, le=80)
    literature_sources: List[str] = Field(default_factory=lambda: ["arxiv", "semantic_scholar"])
    literature_venues: str = ""
    include_keywords: str = ""
    exclude_keywords: str = ""
    seed_papers: str = ""
    evidence_policy: str = "recent_balanced"
    novelty_window_years: int = 3
    enable_patent_search: bool = False
    patent_date_from: int = Field(default=2000, ge=1800, le=2100)
    patent_date_to: int = Field(default=0, ge=0, le=2100)
    patent_max_results: int = Field(default=15, ge=1, le=50)
    enable_meta_optimization: bool = False
    # Pipeline options
    auto_proceed: bool = True
    human_checkpoint: bool = False
    human_checkpoint_nodes: List[
        Literal["exp-design", "exp-run", "paper"]
    ] = Field(default_factory=lambda: ["exp-design", "exp-run", "paper"])
    checkpoint_timeout_seconds: int = Field(default=300, ge=30, le=7200)
    # User-selectable but strictly bounded; the execution engine also clamps
    # client values to this bounded range.
    max_revision_rounds: int = Field(default=AUTONOMOUS_REVISION_ROUNDS, ge=1, le=12)
    max_research_loop_cycles: int = Field(default=3, ge=1, le=6)
    # The enclosing audit watchdog must outlive the model transport timeout.
    audit_layer_timeout_seconds: int = Field(default=420, ge=1, le=900)
    code_review: bool = True
    auto_write: bool = False
    compact: bool = False
    wandb: bool = False
    review_difficulty: Literal["medium", "hard", "nightmare"] = "hard"
    # Integration services (tool toggles)
    enable_gemini: bool = False
    enable_gpt_image: bool = False
    enable_zotero: bool = False
    enable_obsidian: bool = False
    enable_overleaf_sync: bool = False
    overleaf_project_id: str = ""
    # Durable resume
    resume_run_id: str = ""

    @field_validator("node_ids")
    @classmethod
    def validate_node_ids(cls, value: List[str]) -> List[str]:
        normalized = list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))
        if not normalized:
            raise ValueError("node_ids must contain at least one workflow node")
        unknown = [item for item in normalized if item not in WORKFLOW_NODE_IDS]
        if unknown:
            raise ValueError("unknown workflow node(s): " + ", ".join(unknown))
        return normalized

    @field_validator("target_pages")
    @classmethod
    def validate_target_pages(cls, value: int) -> int:
        if value not in {0} and value < 4:
            raise ValueError("target_pages must be 0 (disabled) or between 4 and 50")
        return value

    @field_validator("illustration_mode", mode="before")
    @classmethod
    def validate_current_illustration_mode(cls, value: object) -> object:
        return normalize_workflow_illustration_mode(value)

    @field_validator("literature_sources")
    @classmethod
    def validate_literature_sources(cls, value: List[str]) -> List[str]:
        normalized = list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))
        if not normalized:
            raise ValueError("literature_sources must contain at least one source")
        unknown = [item for item in normalized if item not in LITERATURE_SOURCE_TOOLS]
        if unknown:
            raise ValueError(
                "unknown literature source(s): " + ", ".join(unknown)
            )
        return normalized

    @field_validator("node_inputs")
    @classmethod
    def validate_node_inputs(cls, value: dict[str, Any]) -> dict[str, Any]:
        from ..services.workflow_user_constraints import node_input_constraints

        return node_input_constraints({"node_inputs": value})

    @model_validator(mode="after")
    def validate_date_ranges(self):
        current_year = __import__("datetime").datetime.now().year
        patent_to = self.patent_date_to or current_year
        literature_to = self.literature_year_to or current_year
        if self.patent_date_from > patent_to:
            raise ValueError("patent_date_from must not exceed patent_date_to")
        if self.literature_year_from > literature_to:
            raise ValueError("literature_year_from must not exceed literature_year_to")
        return self


@router.post("/run")
async def run_workflow(request: WorkflowRunRequest):
    """执行工作流（选中的节点）"""
    workflow_recovery_watchdog.observe_project(request.project_path)
    try:
        prepared = prepare_workflow_run(request)
        run_id = await workflow_engine.execute(
            node_ids=request.node_ids,
            project_path=request.project_path,
            research_direction=request.research_direction,
            effort=request.effort,
            assurance=request.assurance,
            pipeline_options=prepared.options,
        )
    except WorkflowRequestError as exc:
        raise HTTPException(status_code=422, detail=exc.detail) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"run_id": run_id, "status": "running"}


@router.post("/run-all")
async def run_all(project_path: str, research_direction: str = "", effort: str = "balanced", assurance: str = "draft"):
    """一键全流程；复用主入口的输入、集成和科研就绪校验。"""
    all_ids = ["lit", "idea", "novelty", "exp-design", "exp-run", "results", "narrative", "figure", "paper", "review", "audit", "compile", "ppt"]
    response = await run_workflow(WorkflowRunRequest(
        node_ids=all_ids,
        project_path=project_path,
        research_direction=research_direction,
        effort=effort,
        assurance=assurance,
    ))
    return {**response, "nodes": len(all_ids)}


@router.get("/runs")
async def list_runs():
    """列出所有工作流运行"""
    return workflow_engine.list_runs()


@router.get("/runs/{run_id}")
async def get_run(run_id: str):
    """获取运行状态"""
    result = workflow_engine.get_run(run_id)
    if not result:
        raise HTTPException(status_code=404, detail="Run not found")
    return result


class CancelRequest(BaseModel):
    kill_experiment: bool = False
    project_path: str = ""


class WorkflowResumeRequest(BaseModel):
    evidence_version_approval: Optional[dict[str, str]] = None
    project_path: str = ""
    node_ids: Optional[List[str]] = None
    research_direction: str = ""
    effort: str = ""
    assurance: str = ""
    delivery_goal: Optional[Literal["submission_candidate", "reviewable_draft"]] = None
    checkpoint_feedback: str = ""
    # Omit this field to preserve the persisted run budget. Supplying it is an
    # explicit bounded override for the remaining nodes.
    max_revision_rounds: Optional[int] = Field(default=None, ge=1, le=12)
    max_research_loop_cycles: Optional[int] = Field(default=None, ge=1, le=6)
    audit_layer_timeout_seconds: int = Field(default=420, ge=1, le=900)

    @field_validator("node_ids")
    @classmethod
    def validate_node_ids(cls, value: Optional[List[str]]) -> Optional[List[str]]:
        if value is None:
            return None
        normalized = list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))
        if not normalized:
            raise ValueError("node_ids must contain at least one workflow node when supplied")
        unknown = [item for item in normalized if item not in WORKFLOW_NODE_IDS]
        if unknown:
            raise ValueError("unknown workflow node(s): " + ", ".join(unknown))
        return normalized


class WorkflowCheckpointExtendRequest(BaseModel):
    seconds: int = Field(default=300, ge=30, le=1800)


class WorkflowRevisionCheckpointRequest(BaseModel):
    project_path: str
    node_id: str


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str, request: Optional[CancelRequest] = None):
    """取消运行，可选终止实验进程"""
    active_run = workflow_engine._runs.get(run_id)
    if not active_run:
        raise HTTPException(status_code=404, detail="Run not found")
    requested_project = str(request.project_path or "").strip() if request else ""
    if requested_project and (
        workflow_engine._project_key(active_run.project_path)
        != workflow_engine._project_key(requested_project)
    ):
        raise HTTPException(status_code=409, detail="Run does not belong to the requested project")
    experiment_id = str(active_run.options.get("experiment_id") or "") if active_run else ""
    await workflow_engine.cancel_run(run_id)

    if request and request.kill_experiment:
        from ..services.experiment_runner import experiment_scheduler

        if experiment_id:
            await experiment_scheduler.cancel_experiment(experiment_id)

    return {
        "status": "cancelled",
        "resume_state": workflow_engine.get_resumable_run_snapshot(active_run.project_path, run_id),
        "experiment_id": experiment_id or None,
        "experiment_cancelled": bool(request and request.kill_experiment and experiment_id),
    }


@router.post("/runs/{run_id}/checkpoint/extend")
async def extend_checkpoint(run_id: str, request: WorkflowCheckpointExtendRequest):
    """延长当前人工检查点；不会重启或复制工作流。"""
    try:
        return await workflow_engine.extend_checkpoint(run_id, request.seconds)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/runs/{run_id}/revision-checkpoint/acknowledge")
async def acknowledge_revision_checkpoint(
    run_id: str,
    request: WorkflowRevisionCheckpointRequest,
):
    """Hide a reviewed hard-limit prompt without waiving or rerunning its quality gate."""
    from ..workflows.run_state import RunState

    run_state = RunState(request.project_path, run_id)
    if not run_state.load():
        raise HTTPException(status_code=404, detail="Run state not found")
    try:
        run_state.acknowledge_revision_checkpoint(request.node_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "run_id": run_id,
        "node_id": request.node_id,
        "status": "acknowledged",
    }


def _completed_resume_response(run_id: str, state: dict) -> dict:
    phases = state.get("phases", {})
    return {
        "run_id": run_id,
        "status": "completed",
        "resumed_from_state": False,
        "already_completed": True,
        "nodes_status": {
            str(phase_id): str(phase.get("status") or "pending")
            for phase_id, phase in phases.items()
            if isinstance(phase, dict)
        },
        "completion": state.get("completion"),
    }


@router.post("/runs/{run_id}/resume")
async def resume_run(run_id: str, request: Optional[WorkflowResumeRequest] = None):
    """恢复 paused workflow，或从 `.merak/runs/<run_id>.json` 续跑持久化 run。"""
    in_memory = workflow_engine.get_run(run_id)
    if in_memory and in_memory.get("status") == "paused":
        resumed = await workflow_engine.resume_run(run_id, request.checkpoint_feedback if request else "")
        return {
            "run_id": run_id,
            "status": "resumed" if resumed else "running",
            "resumed_from_state": False,
        }

    # The backend may auto-resume while the user is clicking. Treat that race as a no-op;
    # never interpret it as a request to launch a second persisted workflow.
    if in_memory and in_memory.get("status") == "running":
        return {
            "run_id": run_id,
            "status": "running",
            "resumed_from_state": False,
            "already_resumed": True,
        }

    if request and request.project_path:
        workflow_recovery_watchdog.observe_project(request.project_path)
        # A platform recovery may finish between the UI loading its checkpoint
        # and the researcher clicking Resume. Treat that stale click as a state
        # reconciliation, not as a new run or a 409 conflict.
        persisted = workflow_engine.get_persisted_run_state(
            request.project_path,
            run_id,
        )
        if persisted and str(persisted.get("status") or "") == "completed":
            return _completed_resume_response(run_id, persisted)

        resume_options = {
            "audit_layer_timeout_seconds": request.audit_layer_timeout_seconds,
        }
        if request.delivery_goal is not None:
            resume_options["delivery_goal"] = request.delivery_goal
        if request.evidence_version_approval:
            resume_options["_evidence_version_approval"] = request.evidence_version_approval
        if request.max_revision_rounds is not None:
            resume_options["max_revision_rounds"] = request.max_revision_rounds
        if request.max_research_loop_cycles is not None:
            resume_options["max_research_loop_cycles"] = (
                request.max_research_loop_cycles
            )
        try:
            resumed_id = await workflow_engine.resume_persisted_run(
                run_id=run_id,
                project_path=request.project_path,
                node_ids=request.node_ids,
                research_direction=request.research_direction,
                effort=request.effort,
                assurance=request.assurance,
                pipeline_options=resume_options,
                checkpoint_feedback=request.checkpoint_feedback,
            )
        except ValueError as exc:
            # Close the same race if completion happened after the pre-check
            # but before resume_persisted_run inspected the durable state.
            persisted = workflow_engine.get_persisted_run_state(
                request.project_path,
                run_id,
            )
            if persisted and str(persisted.get("status") or "") == "completed":
                return _completed_resume_response(run_id, persisted)
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"run_id": resumed_id, "status": "running", "resumed_from_state": True}

    resumed = await workflow_engine.resume_run(run_id, request.checkpoint_feedback if request else "")
    if not resumed:
        raise HTTPException(status_code=409, detail="Workflow is not waiting at a human checkpoint")
    return {"run_id": run_id, "status": "resumed", "resumed_from_state": False}


@router.get("/run-states")
async def list_run_states(project_path: str = "."):
    """列出项目 `.merak/runs/` 下的持久化 workflow run。"""
    workflow_recovery_watchdog.observe_project(project_path)
    return {"runs": workflow_engine.list_persisted_runs(project_path)}


@router.get("/display-logs")
async def get_workflow_display_logs(
    project_path: str = ".",
    run_id: str = "",
    limit: int = Query(default=5000, ge=1, le=10000),
):
    """Rebuild visible history from the durable per-run event journal."""
    try:
        result = read_workflow_display_logs(project_path, run_id, limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "run_id": result.run_id,
        "entries": result.entries,
        "source": result.source,
        "truncated": result.truncated,
    }


@router.get("/run-states/{run_id}")
async def get_run_state(run_id: str, project_path: str = "."):
    """读取单个持久化 workflow run-state。"""
    workflow_recovery_watchdog.observe_project(project_path)
    state = workflow_engine.get_persisted_run_state(project_path, run_id)
    if not state:
        raise HTTPException(status_code=404, detail="Run state not found")
    return {
        **state,
        "runtime_active": (
            workflow_engine._active_run_for_project(project_path) == run_id
        ),
    }


@router.get("/session-state")
async def get_session_state(project_path: str = "."):
    """获取可恢复的 session 状态"""
    workflow_recovery_watchdog.observe_project(project_path)
    from ..workflows.session_state import SessionState
    ss = SessionState(project_path)
    try:
        state = ss.load()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if state:
        run_id = str(state.get("run_id") or "")
        persisted = workflow_engine.get_persisted_run_state(project_path, run_id) if run_id else None
        if persisted:
            snapshot = workflow_engine.get_resumable_run_snapshot(project_path, run_id)
            if snapshot:
                return snapshot
            ss.clear()
        else:
            return state
    snapshot = workflow_engine.get_resumable_run_snapshot(project_path)
    return snapshot or {"resumable": False}


@router.websocket("/ws/{run_id}")
async def workflow_ws(websocket: WebSocket, run_id: str):
    """工作流实时状态 WebSocket"""
    await websocket.accept()

    run = workflow_engine.get_run(run_id)
    if not run:
        await websocket.send_text(json.dumps({"type": "error", "data": "Run not found"}))
        await websocket.close()
        return

    # 发送当前状态
    await websocket.send_text(json.dumps({"type": "state", "data": run}))

    # 保持连接直到工作流完成
    try:
        while True:
            await asyncio.sleep(2)
            current = workflow_engine.get_run(run_id)
            if current:
                await websocket.send_text(json.dumps({"type": "state", "data": current}))
                if current["status"] in ("completed", "incomplete", "failed", "cancelled"):
                    break
    except WebSocketDisconnect:
        logger.debug("Per-run workflow WebSocket disconnected", run_id=run_id)
