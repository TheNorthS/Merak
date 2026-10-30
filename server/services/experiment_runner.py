"""
实验调度器 — 多 GPU 实验编排引擎

功能：
- 多 seed 并行运行
- 异常诊断与人工审批后重试
- Wave gating（批次控制，前一批完成才启动下一批）
- 优先级队列
- 多后端路由（本地 / SSH / Vast.ai / Modal）
- 实验状态持久化
"""

import asyncio
import itertools
import json
from datetime import datetime
from typing import Optional, Callable, Any

import structlog

from .ssh_manager import ssh_manager
from .remote_experiment_runtime import experiment_runtime
from .experiment_models import (
    Experiment,
    ExperimentJob,
    GPUBackend,
    JobStatus,
    OOMError,
)
from .experiment_adjustments import ExperimentAdjustmentMixin
from .experiment_execution import ExperimentExecutionMixin
from .experiment_retries import ExperimentRetryMixin


logger = structlog.get_logger()


class ExperimentScheduler(
    ExperimentExecutionMixin,
    ExperimentAdjustmentMixin,
    ExperimentRetryMixin,
):
    """实验调度器"""

    def __init__(self):
        self._experiments: dict[str, Experiment] = {}
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._queue_sequence = itertools.count()
        self._running_jobs: dict[str, ExperimentJob] = {}
        self._max_concurrent: int = 4  # 最大并行作业数
        self._scheduler_task: Optional[asyncio.Task] = None
        self._job_tasks: dict[str, asyncio.Task] = {}
        self._listeners: list[Callable] = []
        self._stopping = False

    async def start(self):
        """启动调度器"""
        if self._scheduler_task and not self._scheduler_task.done():
            return
        self._stopping = False
        self._scheduler_task = asyncio.create_task(self._schedule_loop())
        logger.info("Experiment scheduler started", max_concurrent=self._max_concurrent)

    async def stop(self):
        """停止调度器"""
        self._stopping = True
        if self._scheduler_task:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass
            self._scheduler_task = None
        # Local children cannot be reattached safely. Remote jobs are left
        # running and their manifests remain in monitor state for reattachment.
        for job in list(self._running_jobs.values()):
            if job.backend == GPUBackend.LOCAL:
                await self._cancel_job(job)
        for task in list(self._job_tasks.values()):
            if not task.done():
                task.cancel()
        if self._job_tasks:
            await asyncio.gather(*self._job_tasks.values(), return_exceptions=True)
        self._job_tasks.clear()
        logger.info("Experiment scheduler stopped")

    def add_listener(self, callback: Callable):
        """添加状态变更监听器"""
        if callback not in self._listeners:
            self._listeners.append(callback)

    def remove_listener(self, callback: Callable):
        """Remove a temporary workflow/WebSocket listener."""
        if callback in self._listeners:
            self._listeners.remove(callback)

    async def _notify_listeners(self, event: str, data: Any):
        """通知所有监听器"""
        for listener in self._listeners:
            try:
                if asyncio.iscoroutinefunction(listener):
                    await listener(event, data)
                else:
                    listener(event, data)
            except Exception as e:
                logger.error("Listener error", error=str(e))

    async def submit_experiment(self, experiment: Experiment) -> str:
        """提交实验（生成 jobs 并排队）"""
        from .protocol_conformance import require_protocol_execution_readiness
        require_protocol_execution_readiness(experiment.project_path)
        if not experiment.seeds:
            raise ValueError("Experiment must define at least one seed")
        if experiment.wave_size < 0:
            raise ValueError("wave_size must be zero or a positive integer")
        if experiment.jobs or experiment.id in self._experiments:
            raise ValueError("Experiment already has scheduled jobs; resume that identity instead of resubmitting")
        # 为每个 seed 生成一个 job
        cells = experiment.execution_cells or [{"seed": seed} for seed in experiment.seeds]
        jobs = []
        for i, cell in enumerate(cells):
            seed = cell["seed"]
            # 计算 wave 编号
            wave = i // experiment.wave_size if experiment.wave_size > 0 else 0

            # 渲染命令模板
            try:
                command = experiment.command_template.format(
                    seed=seed,
                    batch_size=experiment.batch_size or "",
                    work_dir=experiment.work_dir,
                    **{key: value for key, value in cell.items() if key != "seed"},
                )
            except (KeyError, IndexError, ValueError) as exc:
                raise ValueError(
                    "command_template may only use {seed}, {batch_size}, "
                    "{work_dir}, and escaped braces {{...}}"
                ) from exc

            job = ExperimentJob(
                id=f"{experiment.id[:56]}-seed-{seed}-{i}",
                experiment_id=experiment.id,
                name=f"{experiment.name}_{cell.get('cell_id', 'seed' + str(seed))}",
                command=command,
                backend=experiment.backend,
                server_id=experiment.server_id,
                seed=seed,
                cell=dict(cell) if experiment.execution_cells else {},
                preflight_command=experiment.preflight_command.format(
                    **cell, batch_size=experiment.batch_size or "", work_dir=experiment.work_dir),
                wave=wave,
                batch_size=experiment.batch_size,
                original_batch_size=experiment.batch_size,
                max_retries=experiment.max_retries,
                log_path=f"{experiment.work_dir}/logs/{experiment.name}_{cell.get('cell_id', 'seed' + str(seed))}.log",
            )
            jobs.append(job)

        from .execution_cell_binding import persist_cell_receipts
        persist_cell_receipts(experiment, jobs)
        experiment.jobs = jobs
        self._experiments[experiment.id] = experiment

        # 将第一波的 jobs 加入队列
        first_wave_jobs = [j for j in experiment.jobs if j.wave == 0]
        for job in first_wave_jobs:
            job.status = JobStatus.QUEUED
            await self._queue.put((-job.priority, next(self._queue_sequence), job))

        await self._notify_listeners("experiment_submitted", {
            "experiment_id": experiment.id,
            "total_jobs": len(experiment.jobs),
            "first_wave": len(first_wave_jobs),
        })

        logger.info("Experiment submitted",
                    id=experiment.id, name=experiment.name,
                    seeds=len(experiment.seeds), waves=wave + 1 if experiment.wave_size > 0 else 1)

        return experiment.id

    async def cancel_experiment(self, experiment_id: str):
        """取消实验的所有作业"""
        experiment = self._experiments.get(experiment_id)
        if not experiment:
            return

        for job in experiment.jobs:
            if job.status in {
                JobStatus.RUNNING,
                JobStatus.QUEUED,
                JobStatus.PENDING,
                JobStatus.RETRYING,
                JobStatus.STOPPING,
                JobStatus.AWAITING_APPROVAL,
                JobStatus.READY_TO_RETRY,
            }:
                await self._cancel_job(job)

        await self._notify_listeners("experiment_cancelled", {"experiment_id": experiment_id})

    async def _schedule_loop(self):
        """主调度循环"""
        while True:
            try:
                # 检查是否有空槽
                if len(self._running_jobs) >= self._max_concurrent:
                    await asyncio.sleep(1)
                    continue

                # 从队列取出下一个作业
                try:
                    _, _, job = await asyncio.wait_for(self._queue.get(), timeout=2.0)
                except asyncio.TimeoutError:
                    continue

                # 检查是否已被取消
                if job.status == JobStatus.CANCELLED:
                    continue

                # Reserve the slot before yielding back to the scheduler.  If
                # reservation happens inside _run_job, a non-empty queue can
                # schedule every job before the first child task gets CPU time.
                self._running_jobs[job.id] = job
                task = asyncio.create_task(
                    self._run_job(job),
                    name=f"merak-experiment-{job.id}",
                )
                self._job_tasks[job.id] = task

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Scheduler loop error", error=str(e))
                await asyncio.sleep(5)

    async def _run_job(self, job: ExperimentJob):
        """执行单个作业"""
        job.status = JobStatus.RUNNING
        job.started_at = datetime.utcnow()
        self._running_jobs[job.id] = job

        await self._notify_listeners("job_started", {
            "job_id": job.id,
            "experiment_id": job.experiment_id,
            "name": job.name,
        })

        try:
            from .protocol_conformance import require_protocol_execution_readiness
            require_protocol_execution_readiness(self._experiments[job.experiment_id].project_path)
            await self._run_managed_job(job)

        except OOMError:
            await self._handle_oom(job)
        except asyncio.CancelledError:
            # A scheduler shutdown cancels the monitoring coroutine. Local
            # children cannot survive that shutdown and STOPPING always means
            # an explicit operator cancellation. Remote provider jobs may keep
            # running and are deliberately marked detached for durable
            # reattachment instead of being falsely reported as completed.
            if job.backend == GPUBackend.LOCAL or job.status == JobStatus.STOPPING:
                job.status = JobStatus.CANCELLED
                job.finished_at = datetime.utcnow()
                await self._notify_listeners("job_cancelled", {
                    "job_id": job.id,
                    "experiment_id": job.experiment_id,
                    "reason": "Experiment scheduler stopped",
                })
            else:
                job.backend_metadata["detached"] = True
                job.backend_metadata["detached_at"] = datetime.utcnow().isoformat()
            raise
        except Exception as e:
            job.status = JobStatus.FAILED
            job.error_message = str(e)
            job.finished_at = datetime.utcnow()
            logger.error("Job failed", job=job.name, error=str(e))
            await self._notify_listeners("job_failed", {
                "job_id": job.id,
                "error": str(e),
            })
        finally:
            self._running_jobs.pop(job.id, None)
            self._job_tasks.pop(job.id, None)
            # 检查是否需要启动下一波
            await self._check_wave_completion(job)

    async def _check_wave_completion(self, job: ExperimentJob):
        """检查当前 wave 是否完成，启动下一波"""
        if self._stopping:
            return
        experiment = self._experiments.get(job.experiment_id)
        if not experiment or experiment.wave_size <= 0:
            return

        current_wave = job.wave
        wave_jobs = [j for j in experiment.jobs if j.wave == current_wave]

        # 检查当前 wave 是否全部完成
        all_done = all(
            j.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED)
            for j in wave_jobs
        )

        if all_done:
            if experiment.auto_stop_on_anomaly and any(j.status == JobStatus.FAILED for j in wave_jobs):
                await self._notify_listeners('experiment_wave_blocked', {
                    'experiment_id': experiment.id, 'wave': current_wave,
                    'failed_jobs': [j.id for j in wave_jobs if j.status == JobStatus.FAILED],
                    'message': 'Failed wave must be diagnosed before additional cells run.'})
                return
            # 启动下一波
            next_wave = current_wave + 1
            next_wave_jobs = [j for j in experiment.jobs if j.wave == next_wave and j.status == JobStatus.PENDING]

            if next_wave_jobs:
                logger.info("Wave completed, starting next",
                           experiment=experiment.name, wave=next_wave, jobs=len(next_wave_jobs))

                for next_job in next_wave_jobs:
                    next_job.status = JobStatus.QUEUED
                    await self._queue.put((
                        -next_job.priority,
                        next(self._queue_sequence),
                        next_job,
                    ))

                await self._notify_listeners("wave_started", {
                    "experiment_id": experiment.id,
                    "wave": next_wave,
                    "jobs": len(next_wave_jobs),
                })

    async def _cancel_job(self, job: ExperimentJob):
        """Request a cooperative stop and let the runtime finalize evidence."""
        if job.status in {JobStatus.PENDING, JobStatus.QUEUED, JobStatus.AWAITING_APPROVAL, JobStatus.READY_TO_RETRY}:
            job.status = JobStatus.CANCELLED
            job.finished_at = datetime.utcnow()
            return
        if job.status not in {JobStatus.RUNNING, JobStatus.RETRYING, JobStatus.STOPPING}:
            return
        job.status = JobStatus.STOPPING
        await experiment_runtime.cancel(job.id, "Stopped by operator")
        await self._notify_listeners("job_stopping", {
            "experiment_id": job.experiment_id,
            "job_id": job.id,
            "runtime_run_id": job.id,
        })

    async def stop_job(self, experiment_id: str, job_id: str, reason: str = "Stopped by operator") -> dict[str, Any]:
        experiment = self._experiments.get(experiment_id)
        job = self.get_job(job_id)
        if not experiment or not job or job.experiment_id != experiment_id:
            raise KeyError("Experiment job not found")
        if job.status in {JobStatus.PENDING, JobStatus.QUEUED, JobStatus.AWAITING_APPROVAL, JobStatus.READY_TO_RETRY}:
            job.status = JobStatus.CANCELLED
            job.finished_at = datetime.utcnow()
            return {"status": "cancelled", "job_id": job.id}
        if job.status not in {JobStatus.RUNNING, JobStatus.RETRYING, JobStatus.STOPPING}:
            raise ValueError(f"Job is not active (status={job.status.value})")
        job.status = JobStatus.STOPPING
        requested = await experiment_runtime.cancel(job.id, reason.strip() or "Stopped by operator")
        await self._notify_listeners("job_stopping", {
            "experiment_id": experiment_id,
            "job_id": job.id,
            "runtime_run_id": job.id,
            "reason": reason.strip() or "Stopped by operator",
        })
        return {"status": "stopping", "job_id": job.id, "runtime_active": requested}

    async def _extract_metrics(self, job: ExperimentJob):
        """从日志中提取 metrics"""
        if not job.server_id or not job.log_path:
            return

        try:
            # 读取日志最后100行，寻找 JSON metrics
            stdout, _, _ = await ssh_manager.execute(
                job.server_id,
                f"tail -100 {job.log_path} | grep -o '{{.*}}' | tail -1",
                timeout=10,
            )
            if stdout.strip():
                try:
                    job.metrics = json.loads(stdout.strip())
                except json.JSONDecodeError:
                    pass
        except Exception:
            pass

    # ==================== 查询接口 ====================

    def get_experiment(self, experiment_id: str) -> Optional[Experiment]:
        return self._experiments.get(experiment_id)

    def list_experiments(self, project_id: Optional[str] = None) -> list[Experiment]:
        experiments = list(self._experiments.values())
        if project_id:
            experiments = [e for e in experiments if e.project_id == project_id]
        return sorted(experiments, key=lambda e: e.created_at, reverse=True)

    def get_job(self, job_id: str) -> Optional[ExperimentJob]:
        for exp in self._experiments.values():
            for job in exp.jobs:
                if job.id == job_id:
                    return job
        return None

    def get_queue_status(self) -> dict:
        return {
            "queue_size": self._queue.qsize(),
            "running": len(self._running_jobs),
            "max_concurrent": self._max_concurrent,
            "running_jobs": [
                {"id": j.id, "name": j.name, "started_at": j.started_at.isoformat() if j.started_at else None}
                for j in self._running_jobs.values()
            ],
        }


# 全局实例
experiment_scheduler = ExperimentScheduler()
