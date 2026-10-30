"""
SSH 终端 WebSocket — 真实 PTY 转发

架构：
  [前端 Xterm.js] ←WebSocket→ [FastAPI] ←asyncssh PTY→ [远程服务器]

每个 WebSocket 连接对应一个独立的 SSH PTY 会话。
"""

import asyncio
import contextlib
import json
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect
import asyncssh
import structlog

from ..services.ssh_manager import ssh_manager

logger = structlog.get_logger()


class SSHTerminalSession:
    """单个 SSH 终端会话"""

    def __init__(self, websocket: WebSocket, server_id: str):
        self.websocket = websocket
        self.server_id = server_id
        self.process: Optional[asyncssh.SSHClientProcess] = None
        self._read_task: Optional[asyncio.Task] = None
        self._alive = True

    async def start(self, cols: int = 120, rows: int = 30):
        """建立 SSH PTY 连接"""
        conn_info = ssh_manager._connections.get(self.server_id)
        if not conn_info or not conn_info.conn or not conn_info.is_alive:
            # 尝试自动连接
            await ssh_manager.connect(self.server_id)
            conn_info = ssh_manager._connections.get(self.server_id)

        if not conn_info or not conn_info.conn:
            raise ConnectionError(f"Cannot connect to server {self.server_id}")

        # 打开 PTY 会话
        self.process = await conn_info.conn.create_process(
            term_type='xterm-256color',
            term_size=(cols, rows),
            encoding=None,  # 二进制模式
        )

        # 如果配置了工作目录，先 cd 过去
        if conn_info.config.work_dir and conn_info.config.work_dir != '~':
            self.process.stdin.write(f'cd {conn_info.config.work_dir}\n'.encode())

        # 如果配置了 conda 环境，自动激活
        if conn_info.config.conda_env:
            activate_cmd = (
                f'eval "$(/opt/conda/bin/conda shell.bash hook)" 2>/dev/null; '
                f'conda activate {conn_info.config.conda_env} 2>/dev/null\n'
            )
            self.process.stdin.write(activate_cmd.encode())

        # 启动输出读取协程
        self._read_task = asyncio.create_task(self._read_loop())

        logger.info("SSH PTY session started",
                    server=self.server_id,
                    cols=cols, rows=rows)

    async def _read_loop(self):
        """持续读取远程 PTY 输出，转发到 WebSocket"""
        try:
            while self._alive and self.process:
                data = await self.process.stdout.read(4096)
                if not data:
                    # 连接关闭
                    await self.websocket.send_text(json.dumps({
                        "type": "closed",
                        "reason": "Remote session ended",
                    }))
                    break

                # 二进制数据以 base64 发送，或直接发送文本
                try:
                    text = data.decode('utf-8')
                    await self.websocket.send_text(json.dumps({
                        "type": "output",
                        "data": text,
                    }))
                except UnicodeDecodeError:
                    # 二进制数据 fallback
                    import base64
                    await self.websocket.send_text(json.dumps({
                        "type": "output",
                        "data": base64.b64encode(data).decode('ascii'),
                        "encoding": "base64",
                    }))

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("SSH read loop error", error=str(e))
            try:
                await self.websocket.send_text(json.dumps({
                    "type": "error",
                    "message": str(e),
                }))
            except Exception:
                pass

    async def write(self, data: str):
        """写入数据到远程 PTY"""
        if self.process and self.process.stdin:
            self.process.stdin.write(data.encode('utf-8'))

    async def resize(self, cols: int, rows: int):
        """调整远程 PTY 大小"""
        if self.process:
            self.process.change_terminal_size(cols, rows)

    async def close(self):
        """关闭会话"""
        self._alive = False
        if self._read_task:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass
        if self.process:
            with contextlib.suppress(Exception):
                self.process.stdin.write_eof()
            self.process.close()
            with contextlib.suppress(asyncio.TimeoutError, Exception):
                await asyncio.wait_for(self.process.wait_closed(), timeout=5)
        logger.info("SSH PTY session closed", server=self.server_id)


async def handle_ssh_terminal(websocket: WebSocket, server_id: str):
    """处理 SSH 终端 WebSocket 连接的完整生命周期"""
    await websocket.accept()

    session: Optional[SSHTerminalSession] = None

    try:
        # 等待客户端发送初始化消息（含终端尺寸）
        init_data = await asyncio.wait_for(websocket.receive_text(), timeout=10)
        init_msg = json.loads(init_data)
        if not isinstance(init_msg, dict):
            raise ValueError("SSH terminal init message must be a JSON object")

        cols = max(20, min(500, int(init_msg.get("cols", 120))))
        rows = max(5, min(200, int(init_msg.get("rows", 30))))

        # 建立 SSH PTY
        session = SSHTerminalSession(websocket, server_id)
        await session.start(cols=cols, rows=rows)

        await websocket.send_text(json.dumps({
            "type": "connected",
            "serverId": server_id,
        }))

        # 主消息循环
        while True:
            raw = await websocket.receive_text()
            msg = json.loads(raw)
            if not isinstance(msg, dict):
                await websocket.send_text(json.dumps({
                    "type": "protocol_error",
                    "message": "SSH terminal message must be a JSON object",
                }))
                continue

            if msg.get("type") == "input":
                await session.write(str(msg.get("data") or ""))
            elif msg.get("type") == "resize":
                cols = max(20, min(500, int(msg.get("cols", 120))))
                rows = max(5, min(200, int(msg.get("rows", 30))))
                await session.resize(cols, rows)
            elif msg.get("type") == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
            else:
                await websocket.send_text(json.dumps({
                    "type": "protocol_error",
                    "message": "Unsupported SSH terminal message type",
                }))

    except WebSocketDisconnect:
        logger.info("SSH terminal WebSocket disconnected", server=server_id)
    except asyncssh.Error as e:
        logger.error("SSH error", server=server_id, error=str(e))
        try:
            await websocket.send_text(json.dumps({
                "type": "error",
                "message": f"SSH Error: {e}",
            }))
        except Exception:
            pass
    except Exception as e:
        logger.error("SSH terminal error", server=server_id, error=str(e))
        try:
            await websocket.send_text(json.dumps({
                "type": "error",
                "message": str(e),
            }))
        except Exception:
            pass
    finally:
        if session:
            await session.close()
