"""管理员 API — 监控、审计、系统管理"""

from fastapi import APIRouter, Depends, Response
from typing import Optional

from .auth import get_current_user, UserInfo
from ..services.monitoring import metrics, health_checker
from ..services.audit import audit_logger

router = APIRouter()


@router.get("/health")
async def detailed_health():
    """详细健康检查（含各组件状态）"""
    return await health_checker.run_all_checks()


@router.get("/metrics")
async def prometheus_metrics():
    """Prometheus 格式 metrics 导出"""
    content = metrics.export_prometheus()
    return Response(content=content, media_type="text/plain; charset=utf-8")


@router.get("/metrics/json")
async def metrics_json(user: UserInfo = Depends(get_current_user)):
    """JSON 格式 metrics"""
    return metrics.get_summary()


@router.get("/audit")
async def query_audit_logs(
    user_id: Optional[str] = None,
    action: Optional[str] = None,
    resource_type: Optional[str] = None,
    hours: int = 24,
    limit: int = 100,
    offset: int = 0,
    user: UserInfo = Depends(get_current_user),
):
    """查询审计日志"""
    import time
    since = time.time() - hours * 3600

    return {
        "logs": audit_logger.query(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            since=since,
            limit=limit,
            offset=offset,
        ),
        "limit": limit,
        "offset": offset,
    }


@router.get("/audit/stats")
async def audit_stats(hours: int = 24, user: UserInfo = Depends(get_current_user)):
    """审计日志统计"""
    return audit_logger.get_stats(hours)


@router.get("/system/info")
async def system_info(user: UserInfo = Depends(get_current_user)):
    """系统信息"""
    import platform
    import os
    from ..services.ssh_manager import ssh_manager
    from ..services.experiment_runner import experiment_scheduler
    from ..services.skill_registry import skill_registry

    return {
        "version": "0.1.0",
        "platform": platform.system(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
        "pid": os.getpid(),
        "components": {
            "ssh_servers": len(ssh_manager.get_status()),
            "registered_skills": skill_registry.total_skills,
            "experiment_queue": experiment_scheduler.get_queue_status(),
        },
    }
