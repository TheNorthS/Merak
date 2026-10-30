"""Experiment scheduler data contracts and lifecycle states."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class JobStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRYING = "retrying"
    STOPPING = "stopping"
    AWAITING_APPROVAL = "awaiting_approval"
    READY_TO_RETRY = "ready_to_retry"


class GPUBackend(str, Enum):
    LOCAL = "local"
    SSH_REMOTE = "ssh_remote"
    VAST_AI = "vast_ai"
    MODAL = "modal"


@dataclass
class ExperimentJob:
    """单个实验作业"""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    experiment_id: str = ""
    name: str = ""
    command: str = ""
    backend: GPUBackend = GPUBackend.SSH_REMOTE
    server_id: Optional[str] = None
    seed: int = 42
    cell: dict = field(default_factory=dict)
    preflight_command: str = ""
    priority: int = 0  # 越高越先执行
    wave: int = 0      # 波次编号

    # 状态
    status: JobStatus = JobStatus.PENDING
    retry_count: int = 0
    max_retries: int = 3

    # 时间
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    # 执行信息
    remote_pid: Optional[int] = None
    screen_name: Optional[str] = None
    log_path: Optional[str] = None
    exit_code: Optional[int] = None
    error_message: Optional[str] = None
    manifest_path: Optional[str] = None
    result_path: Optional[str] = None
    diagnosis_path: Optional[str] = None
    backend_metadata: dict = field(default_factory=dict)
    pending_adjustment_id: Optional[str] = None
    approved_adjustment_id: Optional[str] = None

    # Approval-gated retry state
    batch_size: Optional[int] = None
    original_batch_size: Optional[int] = None

    # 结果
    metrics: dict = field(default_factory=dict)


@dataclass
class Experiment:
    """实验（包含多个 job，如多 seed）"""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str = ""
    project_id: str = ""
    command_template: str = ""  # 支持 {seed}, {batch_size} 等模板变量
    preflight_command: str = ""
    backend: GPUBackend = GPUBackend.SSH_REMOTE
    server_id: Optional[str] = None
    project_path: str = ""

    # 配置
    seeds: list[int] = field(default_factory=lambda: [42])
    execution_cells: list[dict] = field(default_factory=list)
    batch_size: Optional[int] = None
    env_vars: dict = field(default_factory=dict)
    work_dir: str = "~/experiments"
    wave_size: int = 0  # 0 = 全部同时跑，>0 = 每批 N 个
    timeout_seconds: int = 6 * 3600
    include_data: bool = False
    auto_stop_on_anomaly: bool = True
    gpu_required: bool = True
    gpu_type: str = "A100"
    max_remote_cost_usd: float = 10.0
    vast_max_hourly_usd: float = 2.0
    auto_destroy: bool = True
    max_retries: int = 3

    # 关联的 jobs
    jobs: list[ExperimentJob] = field(default_factory=list)

    # 时间
    created_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def status(self) -> str:
        """聚合状态"""
        statuses = [j.status for j in self.jobs]
        if not statuses:
            return "pending"
        if all(s == JobStatus.COMPLETED for s in statuses):
            return "completed"
        if any(s in {JobStatus.RUNNING, JobStatus.RETRYING, JobStatus.STOPPING} for s in statuses):
            return "running"
        if any(s in {JobStatus.AWAITING_APPROVAL, JobStatus.READY_TO_RETRY} for s in statuses):
            return "attention_required"
        if all(s == JobStatus.CANCELLED for s in statuses):
            return "cancelled"
        if any(s in {JobStatus.FAILED, JobStatus.CANCELLED} for s in statuses):
            return "partial_failure"
        return "pending"

    @property
    def progress(self) -> float:
        """完成百分比"""
        if not self.jobs:
            return 0
        done = sum(1 for j in self.jobs if j.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED))
        return done / len(self.jobs) * 100



class OOMError(Exception):
    """GPU out-of-memory signal handled by the scheduler."""


