"""
本地终端 WebSocket — Windows 兼容

Windows 上 asyncio subprocess 不支持真 PTY。
使用 cmd.exe /Q /K 保持会话存活并逐行交互。
"""

import asyncio
import json
import os
import sys
import contextlib
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect
import structlog

logger = structlog.get_logger()


class LocalTerminalSession:
    def __init__(self, websocket: WebSocket):
        self.websocket = websocket
        self.process: Optional[asyncio.subprocess.Process] = None
        self._read_task: Optional[asyncio.Task] = None
        self._alive = True

    async def start(self, cols: int = 120, rows: int = 30, cwd: Optional[str] = None):
        if sys.platform == 'win32':
            # Windows: cmd /Q (echo off) /K (keep alive)
            shell_cmd = 'cmd.exe'
            shell_args = ['/Q', '/K', 'prompt $P$G']
        else:
            shell_cmd = os.environ.get('SHELL', '/bin/bash')
            shell_args = ['--norc', '-i']

        env = os.environ.copy()
        env['TERM'] = 'xterm-256color'

        work_dir = cwd or os.path.expanduser('~')
        if not os.path.isdir(work_dir):
            work_dir = os.path.expanduser('~')

        self.process = await asyncio.create_subprocess_exec(
            shell_cmd, *shell_args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=work_dir,
            env=env,
        )

        self._read_task = asyncio.create_task(self._read_loop())
        logger.info("Local terminal started", shell=shell_cmd, pid=self.process.pid, cwd=work_dir)

    async def _read_loop(self):
        try:
            while self._alive and self.process and self.process.stdout:
                # 非阻塞读取
                data = await self.process.stdout.read(4096)
                if not data:
                    await self.websocket.send_text(json.dumps({
                        "type": "output",
                        "data": "\r\n[Process exited]\r\n",
                    }))
                    break

                text = data.decode('utf-8', errors='replace')
                # Windows cmd 输出 \r\n，xterm 需要 \r\n
                await self.websocket.send_text(json.dumps({
                    "type": "output",
                    "data": text,
                }))

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Terminal read error", error=str(e))

    async def write(self, data: str):
        if self.process and self.process.stdin:
            # 将按键数据写入 stdin
            encoded = data.encode('utf-8')
            self.process.stdin.write(encoded)
            await self.process.stdin.drain()

    async def close(self):
        self._alive = False
        if self._read_task:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass
        if self.process:
            try:
                self.process.terminate()
                await asyncio.wait_for(self.process.wait(), timeout=3)
            except (asyncio.TimeoutError, OSError, ProcessLookupError):
                try:
                    self.process.kill()
                except (OSError, ProcessLookupError):
                    logger.debug(
                        "Terminal process was already closed",
                        pid=self.process.pid,
                    )
                else:
                    with contextlib.suppress(
                        asyncio.TimeoutError,
                        OSError,
                        ProcessLookupError,
                    ):
                        await asyncio.wait_for(self.process.wait(), timeout=3)


async def handle_local_terminal(websocket: WebSocket, session_id: str):
    await websocket.accept()
    session: Optional[LocalTerminalSession] = None

    try:
        # 等待 init 消息
        init_raw = await asyncio.wait_for(websocket.receive_text(), timeout=10)
        init_msg = json.loads(init_raw)
        if not isinstance(init_msg, dict):
            raise ValueError("Terminal init message must be a JSON object")
        cols = max(20, min(500, int(init_msg.get("cols", 120))))
        rows = max(5, min(200, int(init_msg.get("rows", 30))))
        cwd = init_msg.get("cwd")

        session = LocalTerminalSession(websocket)
        await session.start(cols=cols, rows=rows, cwd=cwd)

        await websocket.send_text(json.dumps({"type": "connected", "sessionId": session_id}))

        # 消息循环
        while True:
            raw = await websocket.receive_text()
            msg = json.loads(raw)
            if not isinstance(msg, dict):
                await websocket.send_text(json.dumps({
                    "type": "protocol_error",
                    "message": "Terminal message must be a JSON object",
                }))
                continue
            if msg.get("type") == "input":
                await session.write(str(msg.get("data") or ""))
            elif msg.get("type") == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
            else:
                await websocket.send_text(json.dumps({
                    "type": "protocol_error",
                    "message": "Unsupported terminal message type",
                }))

    except WebSocketDisconnect:
        logger.info("Terminal disconnected", session=session_id)
    except asyncio.TimeoutError:
        try:
            await websocket.send_text(json.dumps({"type": "error", "message": "Init timeout"}))
        except (RuntimeError, WebSocketDisconnect):
            logger.debug("Terminal websocket closed before timeout error could be sent", session=session_id)
    except Exception as e:
        logger.error("Terminal error", session=session_id, error=str(e))
    finally:
        if session:
            await session.close()
