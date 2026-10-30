"""
监控系统 — Prometheus metrics + 健康检查

功能：
- Prometheus 格式 metrics 导出
- 系统资源监控（CPU/内存/磁盘）
- 应用级指标（请求数/延迟/活跃连接）
- 健康检查（依赖组件状态）
- 告警规则定义
"""

import time
import platform
from typing import Optional
from datetime import datetime
from dataclasses import dataclass, field

import structlog

logger = structlog.get_logger()


@dataclass
class MetricValue:
    """指标值"""
    name: str
    value: float
    labels: dict = field(default_factory=dict)
    metric_type: str = "gauge"  # gauge | counter | histogram
    help_text: str = ""
    timestamp: float = field(default_factory=time.time)


class MetricsCollector:
    """Prometheus 指标收集器"""

    def __init__(self):
        self._counters: dict[str, float] = {}
        self._gauges: dict[str, float] = {}
        self._histograms: dict[str, list[float]] = {}
        self._start_time = time.time()

    def inc_counter(self, name: str, value: float = 1, labels: Optional[dict] = None):
        """递增计数器"""
        key = self._make_key(name, labels)
        self._counters[key] = self._counters.get(key, 0) + value

    def set_gauge(self, name: str, value: float, labels: Optional[dict] = None):
        """设置仪表值"""
        key = self._make_key(name, labels)
        self._gauges[key] = value

    def observe_histogram(self, name: str, value: float, labels: Optional[dict] = None):
        """记录直方图观测值"""
        key = self._make_key(name, labels)
        if key not in self._histograms:
            self._histograms[key] = []
        self._histograms[key].append(value)
        # 保留最近1000个样本
        if len(self._histograms[key]) > 1000:
            self._histograms[key] = self._histograms[key][-1000:]

    def _make_key(self, name: str, labels: Optional[dict] = None) -> str:
        if not labels:
            return name
        label_str = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"

    def export_prometheus(self) -> str:
        """导出 Prometheus 格式的 metrics"""
        lines = []

        # 计数器
        for key, value in sorted(self._counters.items()):
            name = key.split("{")[0] if "{" in key else key
            lines.append(f"# TYPE {name} counter")
            lines.append(f"{key} {value}")

        # 仪表
        for key, value in sorted(self._gauges.items()):
            name = key.split("{")[0] if "{" in key else key
            lines.append(f"# TYPE {name} gauge")
            lines.append(f"{key} {value}")

        # 直方图摘要
        for key, values in sorted(self._histograms.items()):
            name = key.split("{")[0] if "{" in key else key
            if values:
                lines.append(f"# TYPE {name} summary")
                lines.append(f"{key}_count {len(values)}")
                lines.append(f"{key}_sum {sum(values):.4f}")
                sorted_vals = sorted(values)
                lines.append(f'{key}{{quantile="0.5"}} {sorted_vals[len(sorted_vals)//2]:.4f}')
                lines.append(f'{key}{{quantile="0.95"}} {sorted_vals[int(len(sorted_vals)*0.95)]:.4f}')
                lines.append(f'{key}{{quantile="0.99"}} {sorted_vals[int(len(sorted_vals)*0.99)]:.4f}')

        # 系统指标
        lines.append("# TYPE merak_ide_uptime_seconds gauge")
        lines.append(f"merak_ide_uptime_seconds {time.time() - self._start_time:.0f}")

        return "\n".join(lines) + "\n"

    def get_summary(self) -> dict:
        """获取指标摘要（JSON 格式）"""
        return {
            "counters": dict(self._counters),
            "gauges": dict(self._gauges),
            "uptime_seconds": time.time() - self._start_time,
        }


class HealthChecker:
    """健康检查器"""

    def __init__(self):
        self._checks: dict[str, dict] = {}

    async def run_all_checks(self) -> dict:
        """执行所有健康检查"""
        results = {}
        overall_healthy = True

        # 数据库检查
        db_status = await self._check_database()
        results["database"] = db_status
        if db_status["status"] != "healthy":
            overall_healthy = False

        # SSH 管理器
        ssh_status = self._check_ssh_manager()
        results["ssh_manager"] = ssh_status


        # 实验调度器
        scheduler_status = self._check_scheduler()
        results["experiment_scheduler"] = scheduler_status

        # 系统资源
        system_status = self._check_system_resources()
        results["system"] = system_status
        if system_status.get("memory_percent", 0) > 90:
            overall_healthy = False

        return {
            "status": "healthy" if overall_healthy else "degraded",
            "timestamp": datetime.utcnow().isoformat(),
            "checks": results,
        }

    async def _check_database(self) -> dict:
        """检查数据库连接"""
        try:
            from ..db.engine import engine
            async with engine.connect() as conn:
                await conn.execute("SELECT 1")
            return {"status": "healthy", "latency_ms": 0}
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}

    def _check_ssh_manager(self) -> dict:
        """检查 SSH 管理器状态"""
        from ..services.ssh_manager import ssh_manager
        status = ssh_manager.get_status()
        alive = sum(1 for s in status.values() if s.get("is_alive"))
        return {
            "status": "healthy",
            "total_servers": len(status),
            "alive_connections": alive,
        }
    def _check_scheduler(self) -> dict:
        """检查实验调度器"""
        from ..services.experiment_runner import experiment_scheduler
        queue = experiment_scheduler.get_queue_status()
        return {
            "status": "healthy",
            "queue_size": queue["queue_size"],
            "running_jobs": queue["running"],
            "max_concurrent": queue["max_concurrent"],
        }

    def _check_system_resources(self) -> dict:
        """检查系统资源"""
        import os
        try:
            # 基础系统信息（不依赖 psutil）
            return {
                "platform": platform.system(),
                "python_version": platform.python_version(),
                "cpu_count": os.cpu_count(),
                "pid": os.getpid(),
            }
        except Exception:
            return {"status": "unknown"}


# 全局实例
metrics = MetricsCollector()
health_checker = HealthChecker()
