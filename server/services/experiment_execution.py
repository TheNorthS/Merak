"""Backend execution adapters for the experiment scheduler."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import textwrap
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog

from ..utils.atomic_write import atomic_write_text
from .experiment_health import HealthPolicy
from .experiment_models import Experiment, ExperimentJob, GPUBackend, JobStatus, OOMError
from .remote_experiment_runtime import RuntimeSpec, experiment_runtime
from .ssh_manager import ssh_manager


logger = structlog.get_logger()


def _runtime_spec(experiment: Experiment, job: ExperimentJob, project_path: Path) -> RuntimeSpec:
    backend = {
        GPUBackend.LOCAL: "local", GPUBackend.SSH_REMOTE: "ssh_remote",
        GPUBackend.VAST_AI: "vast_ai", GPUBackend.MODAL: "modal",
    }[job.backend]
    return RuntimeSpec(
        run_id=job.id, project_path=str(project_path), command=job.command,
        preflight_command=job.preflight_command or experiment.preflight_command, backend=backend,
        server_id=job.server_id or "", env_vars=dict(experiment.env_vars),
        timeout_seconds=experiment.timeout_seconds, include_data=experiment.include_data,
        max_retries=job.max_retries, auto_stop_on_anomaly=experiment.auto_stop_on_anomaly,
        health_policy=HealthPolicy(), gpu_required=experiment.gpu_required,
        gpu_type=experiment.gpu_type, max_remote_cost_usd=experiment.max_remote_cost_usd,
        vast_max_hourly_usd=experiment.vast_max_hourly_usd,
        auto_destroy=experiment.auto_destroy,
        approved_adjustment_id=job.approved_adjustment_id or "",
    )


def _apply_outcome(job: ExperimentJob, outcome: object) -> None:
    job.exit_code = outcome.exit_code
    job.manifest_path = outcome.manifest_path
    job.log_path = outcome.log_path or job.log_path
    job.result_path = outcome.result_path
    job.diagnosis_path = outcome.diagnosis_path
    job.metrics = dict(outcome.metrics)
    job.backend_metadata = dict(outcome.metadata)
    try:
        manifest = json.loads(Path(outcome.manifest_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        manifest = {}
    job.backend_metadata.update({
        "runtime_run_id": job.id,
        "current_attempt": int(manifest.get("current_attempt") or 0),
        "snapshot_hash": str(manifest.get("snapshot_hash") or ""),
        "execution_cell": dict(job.cell),
    })
    job.finished_at = datetime.utcnow()


async def _vast_instance(client: Any, headers: dict[str, str], job: ExperimentJob) -> Any:
    base_url = "https://console.vast.ai/api/v0"
    response = await client.post(f"{base_url}/bundles/", json={
        "verified": {"eq": True}, "rentable": {"eq": True},
        "num_gpus": {"gte": 1}, "gpu_ram": {"gte": 16000},
        "order": [["dph_total", "asc"]], "limit": 5,
    }, headers=headers)
    if response.status_code != 200:
        raise RuntimeError(f"Vast.ai search failed: {response.text}")
    offers = response.json().get("offers", [])
    if not offers:
        raise RuntimeError("No Vast.ai instances available matching criteria")
    offer = offers[0]
    logger.info(
        "Vast.ai offer selected", id=offer["id"], gpu=offer.get("gpu_name"),
        price=offer.get("dph_total"),
    )
    payload = {
        "client_id": "me", "image": "pytorch/pytorch:2.4.0-cuda12.4-cudnn9-runtime",
        "disk": 20,
        "onstart": f"#!/bin/bash\n{job.command} 2>&1 | tee /workspace/output.log\n"
        "echo 'MERAK_JOB_DONE' >> /workspace/output.log",
    }
    response = await client.put(
        f"{base_url}/asks/{offer['id']}/", json=payload, headers=headers,
    )
    if response.status_code not in (200, 201):
        raise RuntimeError(f"Vast.ai instance creation failed: {response.text}")
    instance_id = response.json().get("new_contract")
    job.remote_pid = instance_id
    logger.info("Vast.ai instance created", instance_id=instance_id)
    return instance_id


async def _destroy_vast(client: Any, instance_id: Any, headers: dict[str, str]) -> None:
    await client.delete(
        f"https://console.vast.ai/api/v0/instances/{instance_id}/", headers=headers,
    )


async def _poll_vast(
    scheduler: Any, client: Any, headers: dict[str, str],
    instance_id: Any, job: ExperimentJob,
) -> None:
    base_url = "https://console.vast.ai/api/v0"
    for _elapsed in range(15, 3601, 15):
        await asyncio.sleep(15)
        response = await client.get(f"{base_url}/instances/{instance_id}/", headers=headers)
        if response.status_code != 200:
            continue
        status = response.json().get("actual_status", "")
        if status in ("exited", "error"):
            await _destroy_vast(client, instance_id, headers)
            raise RuntimeError(f"Vast.ai instance {status}")
        if status != "running":
            continue
        logs_response = await client.get(
            f"{base_url}/instances/{instance_id}/logs/", headers=headers,
            params={"tail": 20},
        )
        if logs_response.status_code != 200 or "MERAK_JOB_DONE" not in logs_response.text:
            continue
        logs = logs_response.text
        await _destroy_vast(client, instance_id, headers)
        if "CUDA out of memory" in logs or "OutOfMemoryError" in logs:
            raise OOMError(logs)
        job.status = JobStatus.COMPLETED
        job.finished_at = datetime.utcnow()
        await scheduler._notify_listeners("job_completed", {"job_id": job.id})
        return
    await _destroy_vast(client, instance_id, headers)
    raise RuntimeError("Vast.ai job timed out after 1 hour")


def _modal_script(job: ExperimentJob) -> str:
    return textwrap.dedent(f'''\
        import modal
        import subprocess

        app = modal.App("merak-experiment-{job.id}")
        image = modal.Image.from_registry(
            "pytorch/pytorch:2.4.0-cuda12.4-cudnn9-runtime",
            add_python="3.11",
        ).pip_install("wandb", "numpy", "pandas", "scipy")

        @app.function(gpu="A100", timeout=3600, image=image)
        def run_experiment():
            result = subprocess.run(
                {job.command!r}, shell=True, capture_output=True, text=True, cwd="/root",
            )
            return {{"exit_code": result.returncode, "stdout": result.stdout[-5000:], "stderr": result.stderr[-2000:]}}

        @app.local_entrypoint()
        def main():
            import json
            result = run_experiment.remote()
            print("MERAK_RESULT:" + json.dumps(result))
    ''')


def _modal_result(output: str) -> dict[str, Any] | None:
    lines = [line for line in output.splitlines() if line.startswith("MERAK_RESULT:")]
    return json.loads(lines[0].removeprefix("MERAK_RESULT:")) if lines else None


def _safe_unlink(path: str) -> None:
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass


class ExperimentExecutionMixin:
    async def _run_managed_job(self, job: ExperimentJob):
        """Route every backend through the same durable lifecycle contract."""
        experiment = self._experiments.get(job.experiment_id)
        if not experiment:
            raise RuntimeError(f"Experiment {job.experiment_id} is not registered")
        project_path = Path(experiment.project_path or experiment.work_dir).expanduser().resolve()
        if not project_path.is_dir():
            raise RuntimeError(
                "A local project_path is required for snapshot/sync; "
                f"got {experiment.project_path or experiment.work_dir!r}"
            )

        spec = _runtime_spec(experiment, job, project_path)

        async def forward(event: str, payload: dict):
            await self._notify_listeners(event, {
                "experiment_id": job.experiment_id,
                "job_id": job.id,
                **payload,
            })

        outcome = await experiment_runtime.run(spec, forward)
        _apply_outcome(job, outcome)

        if outcome.status == "completed":
            job.status = JobStatus.COMPLETED
            await self._notify_listeners("job_completed", {
                "job_id": job.id,
                "experiment_id": job.experiment_id,
                "manifest_path": outcome.manifest_path,
                "result_path": outcome.result_path,
            })
            return

        if any(item.get("kind") == "oom" for item in outcome.anomalies):
            raise OOMError(outcome.error or "OOM detected by experiment health monitor")
        if outcome.status == "cancelled":
            job.status = JobStatus.CANCELLED
            await self._notify_listeners("job_cancelled", {
                "job_id": job.id,
                "experiment_id": job.experiment_id,
                "diagnosis_path": outcome.diagnosis_path,
            })
            return
        critical_anomalies = [
            item for item in outcome.anomalies
            if item.get("severity") == "critical"
        ]
        if outcome.status == "anomaly_stopped" or critical_anomalies:
            job.status = JobStatus.AWAITING_APPROVAL
            job.error_message = (
                outcome.error
                or "The health monitor stopped this attempt; diagnosis and an approved adjustment are required"
            )
            await self._notify_listeners("job_attention_required", {
                "job_id": job.id,
                "experiment_id": job.experiment_id,
                "diagnosis_path": outcome.diagnosis_path,
                "proposal_id": "",
                "reason": job.error_message,
                "anomalies": critical_anomalies,
            })
            return
        raise RuntimeError(
            outcome.error
            or f"Experiment stopped with status {outcome.status}; diagnosis: {outcome.diagnosis_path}"
        )

    async def _run_ssh_job(self, job: ExperimentJob):
        """通过 SSH 执行实验"""
        if not job.server_id:
            raise ValueError("No server_id specified for SSH job")

        # 创建日志目录
        log_dir = str(Path(job.log_path).parent) if job.log_path else "~/logs"
        await ssh_manager.execute(job.server_id, f"mkdir -p {log_dir}")

        # 使用 screen 启动后台任务
        screen_name = f"merak_{job.id}"
        job.screen_name = screen_name

        # 构建完整命令（带日志重定向）
        full_command = (
            f"screen -dmS {screen_name} bash -c '"
            f"cd {self._experiments[job.experiment_id].work_dir} && "
            f"{job.command} 2>&1 | tee {job.log_path}; "
            f"echo \"EXIT_CODE=$?\" >> {job.log_path}'"
        )

        stdout, stderr, exit_code = await ssh_manager.execute(
            job.server_id, full_command, timeout=10
        )

        if exit_code != 0:
            raise RuntimeError(f"Failed to start job: {stderr}")

        logger.info("SSH job started", job=job.name, screen=screen_name)

        # 轮询等待完成
        await self._poll_job_completion(job)

    async def _run_vastai_job(self, job: ExperimentJob):
        """Execute a job through the explicitly configured Vast.ai API."""
        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError("pip install httpx") from exc
        api_key = os.environ.get("VASTAI_API_KEY", "")
        if not api_key:
            raise RuntimeError("VASTAI_API_KEY not set")
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        async with httpx.AsyncClient(timeout=60) as client:
            instance_id = await _vast_instance(client, headers, job)
            await _poll_vast(self, client, headers, instance_id, job)

    async def _run_modal_job(self, job: ExperimentJob):
        """Execute a job with Modal while preserving its result envelope."""
        token_id = os.environ.get("MODAL_TOKEN_ID", "")
        token_secret = os.environ.get("MODAL_TOKEN_SECRET", "")
        if not token_id or not token_secret:
            raise RuntimeError("MODAL_TOKEN_ID and MODAL_TOKEN_SECRET must be set")
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, prefix="merak_modal_",
        ) as handle:
            handle.write(_modal_script(job))
            script_path = handle.name
        try:
            environment = os.environ.copy()
            environment.update({
                "MODAL_TOKEN_ID": token_id,
                "MODAL_TOKEN_SECRET": token_secret,
            })
            process = await asyncio.create_subprocess_exec(
                "modal", "run", script_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=environment,
            )
            stdout, _stderr = await asyncio.wait_for(process.communicate(), timeout=3700)
            output = stdout.decode("utf-8", errors="replace")
            if "CUDA out of memory" in output or "OutOfMemoryError" in output:
                raise OOMError(output)
            result = _modal_result(output)
            if result is not None and result.get("exit_code") != 0:
                raise RuntimeError(f"Modal job failed: {str(result.get('stderr') or '')[:500]}")
            if result is None and process.returncode != 0:
                raise RuntimeError(f"modal run exited with {process.returncode}: {output[-500:]}")
            job.status = JobStatus.COMPLETED
            job.finished_at = datetime.utcnow()
            await self._notify_listeners("job_completed", {"job_id": job.id})
        finally:
            _safe_unlink(script_path)

    async def _run_local_job(self, job: ExperimentJob):
        """本地执行实验"""
        work_dir = self._experiments[job.experiment_id].work_dir
        log_dir = str(Path(job.log_path).parent) if job.log_path else "."
        Path(log_dir).mkdir(parents=True, exist_ok=True)

        process = await asyncio.create_subprocess_shell(
            job.command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=work_dir if Path(work_dir).exists() else None,
        )
        job.remote_pid = process.pid

        # 读取输出并写入日志
        output_lines = []
        if process.stdout:
            async for line in process.stdout:
                decoded = line.decode('utf-8', errors='replace')
                output_lines.append(decoded)
                # 检测 OOM
                if 'CUDA out of memory' in decoded or 'OutOfMemoryError' in decoded:
                    process.terminate()
                    raise OOMError(decoded)

        await process.wait()
        job.exit_code = process.returncode

        # 写入日志
        if job.log_path:
            atomic_write_text(
                Path(job.log_path),
                ''.join(output_lines),
            )

        if process.returncode == 0:
            job.status = JobStatus.COMPLETED
            job.finished_at = datetime.utcnow()
            await self._notify_listeners("job_completed", {"job_id": job.id})
        else:
            raise RuntimeError(f"Job exited with code {process.returncode}")

    async def _poll_job_completion(self, job: ExperimentJob):
        """轮询 SSH 作业是否完成"""
        if not job.server_id or not job.screen_name:
            return

        while job.status == JobStatus.RUNNING:
            await asyncio.sleep(10)

            # 检查 screen 会话是否还存在
            stdout, _, _ = await ssh_manager.execute(
                job.server_id,
                f"screen -ls | grep -c {job.screen_name} || true",
                timeout=10,
            )

            if stdout.strip() == "0":
                # Screen 会话结束，检查退出码
                if job.log_path:
                    log_tail, _, _ = await ssh_manager.execute(
                        job.server_id,
                        f"tail -5 {job.log_path}",
                        timeout=10,
                    )

                    # 检查 OOM
                    if 'CUDA out of memory' in log_tail or 'OutOfMemoryError' in log_tail:
                        raise OOMError(log_tail)

                    # 检查退出码
                    if 'EXIT_CODE=0' in log_tail:
                        job.status = JobStatus.COMPLETED
                        job.finished_at = datetime.utcnow()
                        # 尝试提取 metrics
                        await self._extract_metrics(job)
                        await self._notify_listeners("job_completed", {"job_id": job.id})
                    else:
                        raise RuntimeError(f"Job failed. Last output:\n{log_tail}")
                else:
                    job.status = JobStatus.COMPLETED
                    job.finished_at = datetime.utcnow()
                break

    async def _handle_oom(self, job: ExperimentJob):
        """Create an approval-gated adjustment instead of a blind retry."""
        if job.retry_count >= job.max_retries:
            job.status = JobStatus.FAILED
            job.error_message = "OOM after max retries"
            job.finished_at = datetime.utcnow()
            await self._notify_listeners("job_failed", {
                "job_id": job.id,
                "error": "OOM after max retries",
            })
            return

        if job.batch_size and job.batch_size > 1:
            new_batch_size = max(1, job.batch_size // 2)
            logger.warning("OOM detected; adjustment approval required",
                          job=job.name, old_bs=job.batch_size, new_bs=new_batch_size)
            proposal = await self.create_adjustment_proposal(
                job.experiment_id,
                job.id,
                summary=f"Reduce batch size from {job.batch_size} to {new_batch_size}",
                rationale=(
                    "The preserved runtime evidence contains an out-of-memory finding. "
                    "Reducing only the per-device batch size is the smallest deterministic adjustment; "
                    "gradient accumulation should be reviewed separately if effective batch size matters."
                ),
                batch_size=new_batch_size,
                source="health_monitor",
            )
            job.error_message = "OOM detected; adjustment approval is required before another attempt"
            await self._notify_listeners("job_attention_required", {
                "job_id": job.id,
                "experiment_id": job.experiment_id,
                "diagnosis_path": job.diagnosis_path,
                "proposal_id": proposal["proposal_id"],
                "reason": job.error_message,
            })
        else:
            job.status = JobStatus.FAILED
            job.error_message = "OOM but cannot reduce batch_size further"
            job.finished_at = datetime.utcnow()
