"""
审计日志系统 — 操作追踪

功能：
- 异步批量写入（不阻塞请求）
- 全操作记录（who/what/when/where）
- 查询 API（按用户/操作/时间范围筛选）
- 自动清理（保留90天）
- FastAPI 中间件自动记录
"""

import asyncio
import time
from datetime import datetime
from typing import Optional
from collections import deque
from dataclasses import dataclass, field

import structlog

logger = structlog.get_logger()


@dataclass
class AuditEntry:
    """审计条目"""
    user_id: str
    action: str           # e.g., "experiment.create", "ssh.connect", "merak.execute"
    resource_type: str    # project | experiment | document | ssh | merak | auth
    resource_id: Optional[str] = None
    details: dict = field(default_factory=dict)
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    timestamp: float = field(default_factory=time.time)


class AuditLogger:
    """审计日志记录器"""

    def __init__(self, batch_size: int = 50, flush_interval: float = 5.0):
        self._buffer: deque[AuditEntry] = deque(maxlen=10000)
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._flush_task: Optional[asyncio.Task] = None
        self._log_store: list[AuditEntry] = []  # 内存存储（Phase 7 完善后写入 DB）
        self._total_logged = 0

    async def start(self):
        """启动异步刷新任务"""
        self._flush_task = asyncio.create_task(self._flush_loop())
        logger.info("Audit logger started")

    async def stop(self):
        """停止并刷新剩余日志"""
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        await self._flush()
        logger.info("Audit logger stopped", total_logged=self._total_logged)

    def log(
        self,
        user_id: str,
        action: str,
        resource_type: str,
        resource_id: Optional[str] = None,
        details: Optional[dict] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ):
        """记录一条审计日志（非阻塞）"""
        entry = AuditEntry(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details or {},
            ip_address=ip_address,
            user_agent=user_agent,
        )
        self._buffer.append(entry)

        # 达到批量大小立即刷新
        if len(self._buffer) >= self._batch_size:
            asyncio.create_task(self._flush())

    async def _flush_loop(self):
        """定时刷新"""
        while True:
            await asyncio.sleep(self._flush_interval)
            if self._buffer:
                await self._flush()

    async def _flush(self):
        """将缓冲区写入存储（文件持久化）"""
        if not self._buffer:
            return

        batch = []
        while self._buffer:
            batch.append(self._buffer.popleft())

        # 持久化到 .merak/audit_log.jsonl（append-only）
        import json
        from pathlib import Path
        log_file = Path(".merak") / "audit_log.jsonl"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(log_file, "a", encoding="utf-8") as f:
            for entry in batch:
                f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")

        # 也保留内存副本供 API 查询
        self._log_store.extend(batch)
        self._total_logged += len(batch)

        # 保留最近10000条
        if len(self._log_store) > 10000:
            self._log_store = self._log_store[-10000:]

    # ==================== 查询接口 ====================

    def query(
        self,
        user_id: Optional[str] = None,
        action: Optional[str] = None,
        resource_type: Optional[str] = None,
        since: Optional[float] = None,
        until: Optional[float] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """查询审计日志"""
        results = self._log_store

        if user_id:
            results = [e for e in results if e.user_id == user_id]
        if action:
            results = [e for e in results if action in e.action]
        if resource_type:
            results = [e for e in results if e.resource_type == resource_type]
        if since:
            results = [e for e in results if e.timestamp >= since]
        if until:
            results = [e for e in results if e.timestamp <= until]

        # 按时间倒序
        results = sorted(results, key=lambda e: e.timestamp, reverse=True)

        return [
            {
                "user_id": e.user_id,
                "action": e.action,
                "resource_type": e.resource_type,
                "resource_id": e.resource_id,
                "details": e.details,
                "ip_address": e.ip_address,
                "timestamp": datetime.fromtimestamp(e.timestamp).isoformat(),
            }
            for e in results[offset:offset + limit]
        ]

    def get_stats(self, hours: int = 24) -> dict:
        """获取审计统计"""
        since = time.time() - hours * 3600
        recent = [e for e in self._log_store if e.timestamp >= since]

        actions = {}
        users = set()
        for e in recent:
            actions[e.action] = actions.get(e.action, 0) + 1
            users.add(e.user_id)

        return {
            "total_events": len(recent),
            "unique_users": len(users),
            "top_actions": sorted(actions.items(), key=lambda x: x[1], reverse=True)[:10],
            "period_hours": hours,
        }


# 全局实例
audit_logger = AuditLogger()
