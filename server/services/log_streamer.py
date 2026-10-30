"""
实验日志实时流服务

功能：
- SSH tail -f 远程日志文件
- WebSocket 实时推送到前端
- 支持 ANSI 颜色代码
- 自动检测 metrics 行（JSON 格式）
- 支持多个并发流
"""

import asyncio
import json
import re
from typing import Optional, Callable
from datetime import datetime

import structlog

from .ssh_manager import ssh_manager

logger = structlog.get_logger()

# 匹配 JSON metrics 行的模式
METRICS_PATTERN = re.compile(r'\{[^{}]*"(loss|acc|accuracy|lr|epoch|step|f1|bleu)"[^{}]*\}')


class LogStream:
    """单个日志流"""

    def __init__(self, server_id: str, log_path: str, on_data: Callable):
        self.server_id = server_id
        self.log_path = log_path
        self.on_data = on_data
        self._task: Optional[asyncio.Task] = None
        self._alive = True
        self._lines_sent = 0

    async def start(self, tail_lines: int = 50):
        """开始流式传输日志"""
        self._task = asyncio.create_task(self._stream_loop(tail_lines))

    async def stop(self):
        """停止流"""
        self._alive = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _stream_loop(self, tail_lines: int):
        """主流循环：通过 SSH 执行 tail -f"""
        conn_info = ssh_manager._connections.get(self.server_id)
        if not conn_info or not conn_info.conn:
            await self.on_data({
                "type": "error",
                "message": f"Server {self.server_id} not connected",
            })
            return

        try:
            # 打开持续的 tail -f 进程
            process = await conn_info.conn.create_process(
                f"tail -n {tail_lines} -f {self.log_path}",
                encoding=None,
            )

            # 持续读取输出
            buffer = b""
            while self._alive:
                try:
                    chunk = await asyncio.wait_for(
                        process.stdout.read(4096),
                        timeout=30,  # 30秒无输出发送心跳
                    )
                except asyncio.TimeoutError:
                    await self.on_data({"type": "heartbeat"})
                    continue

                if not chunk:
                    break

                buffer += chunk
                # 按行处理
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    await self._process_line(line.decode("utf-8", errors="replace"))

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Log stream error", path=self.log_path, error=str(e))
            await self.on_data({
                "type": "error",
                "message": str(e),
            })
        finally:
            # 尝试关闭远程进程
            try:
                if process:
                    process.terminate()
            except Exception:
                pass

    async def _process_line(self, line: str):
        """处理单行日志"""
        self._lines_sent += 1
        timestamp = datetime.utcnow().isoformat() + "Z"

        # 检测日志级别
        level = "info"
        line_lower = line.lower()
        if "error" in line_lower or "exception" in line_lower or "traceback" in line_lower:
            level = "error"
        elif "warning" in line_lower or "warn" in line_lower:
            level = "warn"
        elif "debug" in line_lower:
            level = "debug"

        # 检测 metrics JSON
        metrics_match = METRICS_PATTERN.search(line)
        if metrics_match:
            try:
                metrics = json.loads(metrics_match.group(0))
                await self.on_data({
                    "type": "metric",
                    "timestamp": timestamp,
                    "metrics": metrics,
                    "raw": line,
                })
                return
            except json.JSONDecodeError:
                pass

        # 普通日志行
        await self.on_data({
            "type": "log",
            "timestamp": timestamp,
            "level": level,
            "message": line,
            "line_number": self._lines_sent,
        })


class LogStreamManager:
    """日志流管理器"""

    def __init__(self):
        self._streams: dict[str, LogStream] = {}

    async def start_stream(
        self,
        stream_id: str,
        server_id: str,
        log_path: str,
        on_data: Callable,
        tail_lines: int = 50,
    ) -> str:
        """启动一个日志流"""
        # 如果已存在，先停止
        if stream_id in self._streams:
            await self.stop_stream(stream_id)

        stream = LogStream(server_id, log_path, on_data)
        self._streams[stream_id] = stream
        await stream.start(tail_lines)

        logger.info("Log stream started", stream_id=stream_id, path=log_path)
        return stream_id

    async def stop_stream(self, stream_id: str):
        """停止日志流"""
        stream = self._streams.pop(stream_id, None)
        if stream:
            await stream.stop()
            logger.info("Log stream stopped", stream_id=stream_id)

    async def stop_all(self):
        """停止所有流"""
        for stream_id in list(self._streams.keys()):
            await self.stop_stream(stream_id)

    def get_active_streams(self) -> list[str]:
        """获取活跃流列表"""
        return list(self._streams.keys())


# 全局实例
log_stream_manager = LogStreamManager()
