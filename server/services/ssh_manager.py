"""
SSH 连接管理器 — asyncssh 连接池

功能：
- 多服务器连接管理
- 连接池 + 心跳保活
- 密钥/密码加密存储
- PTY 会话转发
- SFTP 文件操作
"""

import asyncio
import hmac
from dataclasses import dataclass
from typing import Optional
from datetime import datetime

import asyncssh
import structlog

logger = structlog.get_logger()


@dataclass
class SSHServerConfig:
    """SSH 服务器配置"""
    id: str
    name: str
    host: str
    port: int = 22
    username: str = "root"
    # 认证方式（二选一）
    private_key_path: Optional[str] = None
    password: Optional[str] = None  # 加密存储
    # 环境配置
    conda_env: Optional[str] = None
    work_dir: str = "~"
    # GPU 信息
    gpu_count: int = 0
    gpu_type: str = ""
    host_key_fingerprint: str = ""


@dataclass
class SSHConnection:
    """活跃的 SSH 连接"""
    config: SSHServerConfig
    conn: Optional[asyncssh.SSHClientConnection] = None
    connected_at: Optional[datetime] = None
    last_heartbeat: Optional[datetime] = None
    is_alive: bool = False
    host_key_fingerprint: str = ""


class SSHManager:
    """SSH 连接池管理器"""

    def __init__(self):
        self._connections: dict[str, SSHConnection] = {}
        self._configs: dict[str, SSHServerConfig] = {}
        self._heartbeat_task: Optional[asyncio.Task] = None

    async def start(self):
        """启动心跳检测"""
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        logger.info("SSH Manager started")

    async def stop(self):
        """关闭所有连接"""
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        for conn_id in list(self._connections.keys()):
            await self.disconnect(conn_id)
        logger.info("SSH Manager stopped")

    def add_server(self, config: SSHServerConfig):
        """注册服务器配置"""
        self._configs[config.id] = config
        logger.info("SSH server registered", server=config.name, host=config.host)

    async def connect(self, server_id: str, accept_unknown_host: bool = False) -> str:
        """建立 SSH 连接"""
        config = self._configs.get(server_id)
        if not config:
            raise ValueError(f"Server {server_id} not configured")

        try:
            connect_kwargs: dict = {
                "host": config.host,
                "port": config.port,
                "username": config.username,
            }

            # A first explicit connection test may use TOFU to capture a key.
            # Normal execution either checks the pinned fingerprint below or
            # delegates to the user's OpenSSH known_hosts file.
            if accept_unknown_host or config.host_key_fingerprint:
                connect_kwargs["known_hosts"] = None

            if config.private_key_path:
                connect_kwargs["client_keys"] = [config.private_key_path]
            elif config.password:
                connect_kwargs["password"] = config.password

            conn = await asyncssh.connect(**connect_kwargs)
            server_key = conn.get_server_host_key()
            if server_key is None:
                conn.close()
                await conn.wait_closed()
                raise ConnectionError("SSH server did not provide a host key")
            fingerprint = server_key.get_fingerprint("sha256")
            if config.host_key_fingerprint and not hmac.compare_digest(
                fingerprint, config.host_key_fingerprint
            ):
                conn.close()
                await conn.wait_closed()
                raise ConnectionError(
                    "SSH host key mismatch. The server identity changed; run connection verification again only after checking the new fingerprint."
                )

            ssh_conn = SSHConnection(
                config=config,
                conn=conn,
                connected_at=datetime.utcnow(),
                last_heartbeat=datetime.utcnow(),
                is_alive=True,
                host_key_fingerprint=fingerprint,
            )
            self._connections[server_id] = ssh_conn

            logger.info("SSH connected", server=config.name, host=config.host)
            return server_id

        except Exception as e:
            logger.error("SSH connection failed", server=config.name, error=str(e))
            raise

    async def disconnect(self, server_id: str):
        """断开 SSH 连接"""
        conn = self._connections.pop(server_id, None)
        if conn and conn.conn:
            conn.conn.close()
            await conn.conn.wait_closed()
            logger.info("SSH disconnected", server=conn.config.name)

    async def execute(self, server_id: str, command: str, timeout: int = 30) -> tuple[str, str, int]:
        """执行远程命令"""
        conn = self._connections.get(server_id)
        if not conn or not conn.conn or not conn.is_alive:
            raise ConnectionError(f"Server {server_id} not connected")

        # 如果配置了 conda 环境，自动激活
        if conn.config.conda_env:
            command = f'eval "$(/opt/conda/bin/conda shell.bash hook)" && conda activate {conn.config.conda_env} && {command}'

        result = await asyncio.wait_for(
            conn.conn.run(command),
            timeout=timeout,
        )

        stdout = result.stdout or ""
        stderr = result.stderr or ""
        return (
            stdout.decode("utf-8", errors="replace")
            if isinstance(stdout, bytes) else stdout,
            stderr.decode("utf-8", errors="replace")
            if isinstance(stderr, bytes) else stderr,
            result.exit_status or 0,
        )

    async def open_pty(self, server_id: str, term_type: str = "xterm-256color", cols: int = 80, rows: int = 24):
        """打开 PTY 会话（用于交互式终端）"""
        conn = self._connections.get(server_id)
        if not conn or not conn.conn or not conn.is_alive:
            raise ConnectionError(f"Server {server_id} not connected")

        process = await conn.conn.create_process(
            term_type=term_type,
            term_size=(cols, rows),
        )
        return process

    async def get_gpu_status(self, server_id: str) -> dict:
        """获取 GPU 状态（nvidia-smi）"""
        stdout, _, exit_code = await self.execute(
            server_id,
            "nvidia-smi --query-gpu=index,name,memory.used,memory.total,utilization.gpu,temperature.gpu "
            "--format=csv,noheader,nounits",
        )

        if exit_code != 0:
            return {"available": False, "gpus": []}

        gpus = []
        for line in stdout.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 6:
                gpus.append({
                    "index": int(parts[0]),
                    "name": parts[1],
                    "memory_used_mb": int(parts[2]),
                    "memory_total_mb": int(parts[3]),
                    "utilization_percent": int(parts[4]),
                    "temperature_c": int(parts[5]),
                })

        return {"available": True, "gpus": gpus}

    def get_status(self) -> dict:
        """获取所有连接状态"""
        return {
            server_id: {
                "name": conn.config.name,
                "host": conn.config.host,
                "is_alive": conn.is_alive,
                "connected_at": conn.connected_at.isoformat() if conn.connected_at else None,
                "host_key_fingerprint": conn.host_key_fingerprint,
            }
            for server_id, conn in self._connections.items()
        }

    def get_host_key_fingerprint(self, server_id: str) -> str:
        connection = self._connections.get(server_id)
        return connection.host_key_fingerprint if connection else ""

    async def _heartbeat_loop(self):
        """定期检查连接存活"""
        while True:
            await asyncio.sleep(30)
            for server_id, conn in list(self._connections.items()):
                if not conn.conn:
                    continue
                try:
                    await asyncio.wait_for(
                        conn.conn.run("echo ok", check=True),
                        timeout=10,
                    )
                    conn.last_heartbeat = datetime.utcnow()
                    conn.is_alive = True
                except Exception:
                    conn.is_alive = False
                    logger.warning("SSH heartbeat failed", server=conn.config.name)


# 全局实例
ssh_manager = SSHManager()
