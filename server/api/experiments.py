"""实验管理 API — 使用真实调度器"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from typing import List, Optional
from pathlib import Path

from .auth import get_current_user, UserInfo
from ..services.experiment_runner import (
    experiment_scheduler,
    Experiment as ExperimentModel,
    GPUBackend,
)

router = APIRouter()


class ExperimentCreate(BaseModel):
    """创建实验请求"""
    name: str = Field(min_length=1, max_length=200)
    project_id: str = Field(min_length=1, max_length=200)
    project_path: str = Field(min_length=1)
    command_template: str = Field(min_length=1, max_length=32000)
    preflight_command: str = ""
    backend: str = "ssh_remote"
    server_id: Optional[str] = None
    seeds: List[int] = Field(default_factory=lambda: [42], min_length=1, max_length=128)
    batch_size: Optional[int] = Field(default=None, ge=1)
    env_vars: dict = Field(default_factory=dict)
    work_dir: str = "~/experiments"
    wave_size: int = Field(default=0, ge=0, le=128)  # 0=全部同时跑
    timeout_seconds: int = Field(default=6 * 3600, ge=30, le=7 * 24 * 3600)
    include_data: bool = False
    auto_stop_on_anomaly: bool = True
    gpu_required: bool = True
    gpu_type: str = "A100"
    max_remote_cost_usd: float = Field(default=10.0, gt=0, le=10000)
    vast_max_hourly_usd: float = Field(default=2.0, gt=0, le=100)
    auto_destroy: bool = True
    max_retries: int = Field(default=3, ge=0, le=10)

    @field_validator("env_vars")
    @classmethod
    def validate_env_vars(cls, value: dict) -> dict:
        import re

        invalid = [
            str(key) for key in value
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(key))
        ]
        if invalid:
            raise ValueError("invalid environment variable name(s): " + ", ".join(invalid))
        return {str(key): str(item) for key, item in value.items()}


class ExperimentResponse(BaseModel):
    """实验响应"""
    id: str
    name: str
    project_id: str
    status: str
    progress: float
    total_jobs: int
    backend: str
    created_at: str
    seeds: List[int]


class JobResponse(BaseModel):
    """作业响应"""
    id: str
    name: str
    status: str
    seed: int
    wave: int
    retry_count: int
    started_at: Optional[str]
    finished_at: Optional[str]
    exit_code: Optional[int]
    error_message: Optional[str]
    metrics: dict
    log_path: Optional[str]
    manifest_path: Optional[str]
    result_path: Optional[str]
    diagnosis_path: Optional[str]
    backend_metadata: dict
    pending_adjustment_id: Optional[str]
    approved_adjustment_id: Optional[str]


class QueueStatus(BaseModel):
    """队列状态"""
    queue_size: int
    running: int
    max_concurrent: int
    running_jobs: List[dict]


class JobStopRequest(BaseModel):
    reason: str = Field(default="Stopped by operator", max_length=500)


class AdjustmentCreate(BaseModel):
    summary: str = Field(min_length=3, max_length=500)
    rationale: str = Field(min_length=3, max_length=4000)
    batch_size: Optional[int] = Field(default=None, ge=1)
    command: str = Field(default="", max_length=12000)


class AdjustmentResolve(BaseModel):
    approved: bool
    note: str = Field(default="", max_length=2000)


class JobRetryRequest(BaseModel):
    proposal_id: str = Field(min_length=1, max_length=64)


@router.get("/", response_model=List[ExperimentResponse])
async def list_experiments(
    project_id: Optional[str] = None,
    user: UserInfo = Depends(get_current_user),
):
    """列出所有实验"""
    experiments = experiment_scheduler.list_experiments(project_id)
    return [
        ExperimentResponse(
            id=exp.id,
            name=exp.name,
            project_id=exp.project_id,
            status=exp.status,
            progress=exp.progress,
            total_jobs=len(exp.jobs),
            backend=exp.backend.value,
            created_at=exp.created_at.isoformat(),
            seeds=exp.seeds,
        )
        for exp in experiments
    ]


@router.post("/", response_model=ExperimentResponse)
async def create_experiment(data: ExperimentCreate, user: UserInfo = Depends(get_current_user)):
    """创建并提交实验"""
    try:
        backend = GPUBackend(data.backend)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid backend: {data.backend}")

    if not Path(data.project_path).expanduser().is_dir():
        raise HTTPException(status_code=422, detail="project_path must be an existing local project directory")
    if backend == GPUBackend.SSH_REMOTE:
        from .ssh import is_ssh_server_verified

        if not data.server_id or not is_ssh_server_verified(data.server_id):
            raise HTTPException(status_code=422, detail="SSH server must pass connection verification before use")
    elif backend in {GPUBackend.VAST_AI, GPUBackend.MODAL}:
        from .settings import is_integration_verified

        integration = "vastai" if backend == GPUBackend.VAST_AI else "modal"
        if not is_integration_verified(integration):
            raise HTTPException(status_code=422, detail=f"{integration} must pass connection verification before use")

    experiment = ExperimentModel(
        name=data.name,
        project_id=data.project_id,
        command_template=data.command_template,
        preflight_command=data.preflight_command,
        backend=backend,
        server_id=data.server_id,
        project_path=data.project_path,
        seeds=data.seeds,
        batch_size=data.batch_size,
        env_vars=data.env_vars,
        work_dir=data.work_dir,
        wave_size=data.wave_size,
        timeout_seconds=data.timeout_seconds,
        include_data=data.include_data,
        auto_stop_on_anomaly=data.auto_stop_on_anomaly,
        gpu_required=data.gpu_required,
        gpu_type=data.gpu_type,
        max_remote_cost_usd=data.max_remote_cost_usd,
        vast_max_hourly_usd=data.vast_max_hourly_usd,
        auto_destroy=data.auto_destroy,
        max_retries=data.max_retries,
    )

    try:
        experiment_id = await experiment_scheduler.submit_experiment(experiment)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return ExperimentResponse(
        id=experiment_id,
        name=experiment.name,
        project_id=experiment.project_id,
        status=experiment.status,
        progress=experiment.progress,
        total_jobs=len(experiment.jobs),
        backend=experiment.backend.value,
        created_at=experiment.created_at.isoformat(),
        seeds=experiment.seeds,
    )


@router.get("/queue/status", response_model=QueueStatus)
async def queue_status(user: UserInfo = Depends(get_current_user)):
    """Get queue state; declared before the dynamic experiment route."""
    return experiment_scheduler.get_queue_status()


@router.get("/runtime/{run_id}")
async def runtime_manifest(
    run_id: str,
    project_path: str,
    user: UserInfo = Depends(get_current_user),
):
    """Read a durable runtime manifest after reconnect or IDE restart."""
    from ..services.remote_experiment_runtime import RunManifestStore

    store = RunManifestStore(project_path, run_id)
    payload = store.load()
    if not payload:
        raise HTTPException(status_code=404, detail="Runtime manifest not found")
    return {"manifest_path": str(store.path), "events_path": str(store.events_path), **payload}


@router.get("/runtime/{run_id}/log")
async def runtime_log(
    run_id: str,
    project_path: str,
    offset: int = 0,
    max_bytes: int = 1024 * 1024,
    user: UserInfo = Depends(get_current_user),
):
    """Read an incremental local mirror of the active experiment log."""
    from ..services.remote_experiment_runtime import RunManifestStore

    store = RunManifestStore(project_path, run_id)
    manifest = store.load()
    if not manifest:
        raise HTTPException(status_code=404, detail="Runtime manifest not found")
    log_path = Path(str(manifest.get("log_path") or ""))
    if not log_path.is_file():
        attempt = int(manifest.get("current_attempt") or 0)
        candidates = [
            store.root / f"attempt-{attempt:02d}" / "train.log",
            store.root / f"attempt-{attempt:02d}" / "modal.log",
        ]
        log_path = next((path for path in candidates if path.is_file()), Path())
    if not log_path or not log_path.is_file():
        return {"offset": offset, "next_offset": offset, "text": "", "status": manifest.get("status")}
    size = log_path.stat().st_size
    safe_offset = 0 if offset < 0 or offset > size else offset
    read_size = max(1, min(max_bytes, 4 * 1024 * 1024, size - safe_offset))
    with log_path.open("rb") as handle:
        handle.seek(safe_offset)
        data = handle.read(read_size)
    return {
        "offset": safe_offset,
        "next_offset": safe_offset + len(data),
        "text": data.decode("utf-8", errors="replace"),
        "status": manifest.get("status"),
    }


@router.post("/{experiment_id}/jobs/{job_id}/stop")
async def stop_job(
    experiment_id: str,
    job_id: str,
    request: JobStopRequest,
    user: UserInfo = Depends(get_current_user),
):
    """Safely stop a live attempt and let the runtime collect evidence."""
    try:
        return await experiment_scheduler.stop_job(experiment_id, job_id, request.reason)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{experiment_id}/jobs/{job_id}/adjustments")
async def list_adjustments(
    experiment_id: str,
    job_id: str,
    user: UserInfo = Depends(get_current_user),
):
    try:
        return {"proposals": experiment_scheduler.list_adjustment_proposals(experiment_id, job_id)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{experiment_id}/jobs/{job_id}/adjustments")
async def create_adjustment(
    experiment_id: str,
    job_id: str,
    request: AdjustmentCreate,
    user: UserInfo = Depends(get_current_user),
):
    try:
        return await experiment_scheduler.create_adjustment_proposal(
            experiment_id,
            job_id,
            summary=request.summary,
            rationale=request.rationale,
            batch_size=request.batch_size,
            command=request.command,
            source="operator",
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{experiment_id}/jobs/{job_id}/adjustments/{proposal_id}/resolve")
async def resolve_adjustment(
    experiment_id: str,
    job_id: str,
    proposal_id: str,
    request: AdjustmentResolve,
    user: UserInfo = Depends(get_current_user),
):
    try:
        return await experiment_scheduler.resolve_adjustment_proposal(
            experiment_id,
            job_id,
            proposal_id,
            approved=request.approved,
            note=request.note,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{experiment_id}/jobs/{job_id}/retry")
async def retry_job(
    experiment_id: str,
    job_id: str,
    request: JobRetryRequest,
    user: UserInfo = Depends(get_current_user),
):
    """Queue a new attempt; an approved, unused proposal is mandatory."""
    try:
        return await experiment_scheduler.retry_job(experiment_id, job_id, request.proposal_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{experiment_id}")
async def get_experiment(experiment_id: str, user: UserInfo = Depends(get_current_user)):
    """获取实验详情"""
    experiment = experiment_scheduler.get_experiment(experiment_id)
    if not experiment:
        raise HTTPException(status_code=404, detail="Experiment not found")

    return {
        "id": experiment.id,
        "name": experiment.name,
        "project_id": experiment.project_id,
        "status": experiment.status,
        "progress": experiment.progress,
        "backend": experiment.backend.value,
        "server_id": experiment.server_id,
        "command_template": experiment.command_template,
        "seeds": experiment.seeds,
        "batch_size": experiment.batch_size,
        "wave_size": experiment.wave_size,
        "work_dir": experiment.work_dir,
        "created_at": experiment.created_at.isoformat(),
        "jobs": [
            JobResponse(
                id=j.id,
                name=j.name,
                status=j.status.value,
                seed=j.seed,
                wave=j.wave,
                retry_count=j.retry_count,
                started_at=j.started_at.isoformat() if j.started_at else None,
                finished_at=j.finished_at.isoformat() if j.finished_at else None,
                exit_code=j.exit_code,
                error_message=j.error_message,
                metrics=j.metrics,
                log_path=j.log_path,
                manifest_path=j.manifest_path,
                result_path=j.result_path,
                diagnosis_path=j.diagnosis_path,
                backend_metadata=j.backend_metadata,
                pending_adjustment_id=j.pending_adjustment_id,
                approved_adjustment_id=j.approved_adjustment_id,
            ).model_dump()
            for j in experiment.jobs
        ],
    }


@router.post("/{experiment_id}/cancel")
async def cancel_experiment(experiment_id: str, user: UserInfo = Depends(get_current_user)):
    """取消实验"""
    experiment = experiment_scheduler.get_experiment(experiment_id)
    if not experiment:
        raise HTTPException(status_code=404, detail="Experiment not found")

    await experiment_scheduler.cancel_experiment(experiment_id)
    return {"status": "cancelled", "id": experiment_id}


@router.get("/{experiment_id}/jobs/{job_id}")
async def get_job(experiment_id: str, job_id: str, user: UserInfo = Depends(get_current_user)):
    """获取单个作业详情"""
    job = experiment_scheduler.get_job(job_id)
    if not job or job.experiment_id != experiment_id:
        raise HTTPException(status_code=404, detail="Job not found")

    return JobResponse(
        id=job.id,
        name=job.name,
        status=job.status.value,
        seed=job.seed,
        wave=job.wave,
        retry_count=job.retry_count,
        started_at=job.started_at.isoformat() if job.started_at else None,
        finished_at=job.finished_at.isoformat() if job.finished_at else None,
        exit_code=job.exit_code,
        error_message=job.error_message,
        metrics=job.metrics,
        log_path=job.log_path,
        manifest_path=job.manifest_path,
        result_path=job.result_path,
        diagnosis_path=job.diagnosis_path,
        backend_metadata=job.backend_metadata,
        pending_adjustment_id=job.pending_adjustment_id,
        approved_adjustment_id=job.approved_adjustment_id,
    )
