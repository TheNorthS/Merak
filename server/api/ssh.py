"""SSH 连接管理 API"""

import hashlib
import shlex
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Any, List, Optional

from .auth import get_current_user, UserInfo
from ..services.ssh_manager import ssh_manager, SSHServerConfig
from ..services.sftp_service import sftp_service
from ..services.connection_verification import connection_verification_store

router = APIRouter()


class SSHServerCreate(BaseModel):
    """SSH 服务器配置请求"""
    name: str
    host: str
    port: int = 22
    username: str = "root"
    auth_method: str = "key"  # "key" | "password"
    private_key_path: Optional[str] = None
    password: Optional[str] = None
    conda_env: Optional[str] = None
    work_dir: str = "~"
    gpu_count: int = 0
    gpu_type: str = ""
    host_key_fingerprint: str = ""


class SSHServerResponse(BaseModel):
    """SSH 服务器响应"""
    id: str
    name: str
    host: str
    port: int
    username: str
    is_connected: bool
    gpu_count: int
    gpu_type: str


class SSHConnectionStatus(BaseModel):
    """连接状态"""
    server_id: str
    name: str
    host: str
    is_alive: bool
    connected_at: Optional[str] = None


class GPUStatusResponse(BaseModel):
    """GPU 状态响应"""
    available: bool
    gpus: List[dict]


# Process-scoped cache synchronized from the desktop settings store. Secrets
# intentionally remain outside the shared project database.
_server_configs: dict[str, SSHServerConfig] = {}


@router.get("/servers", response_model=List[SSHServerResponse])
async def list_servers(user: UserInfo = Depends(get_current_user)):
    """列出所有已配置的 SSH 服务器"""
    results = []
    status = ssh_manager.get_status()

    for server_id, config in _server_configs.items():
        conn_status = status.get(server_id, {})
        results.append(SSHServerResponse(
            id=server_id,
            name=config.name,
            host=config.host,
            port=config.port,
            username=config.username,
            is_connected=conn_status.get("is_alive", False),
            gpu_count=config.gpu_count,
            gpu_type=config.gpu_type,
        ))

    return results


@router.post("/servers", response_model=SSHServerResponse)
async def add_server(data: SSHServerCreate, user: UserInfo = Depends(get_current_user)):
    """添加 SSH 服务器配置"""
    import hashlib
    server_id = hashlib.md5(f"{data.host}:{data.port}:{data.username}".encode()).hexdigest()[:12]

    # 注册到 SSH 管理器
    config = SSHServerConfig(
        id=server_id,
        name=data.name,
        host=data.host,
        port=data.port,
        username=data.username,
        private_key_path=data.private_key_path,
        password=data.password,
        conda_env=data.conda_env,
        work_dir=data.work_dir,
        gpu_count=data.gpu_count,
        gpu_type=data.gpu_type,
        host_key_fingerprint=data.host_key_fingerprint,
    )
    ssh_manager.add_server(config)
    _server_configs[server_id] = config

    return SSHServerResponse(
        id=server_id,
        name=data.name,
        host=data.host,
        port=data.port,
        username=data.username,
        is_connected=False,
        gpu_count=data.gpu_count,
        gpu_type=data.gpu_type,
    )


class SSHServerBatch(BaseModel):
    servers: List[dict]


class SSHTestRequest(BaseModel):
    id: str = ""
    name: str = ""
    host: str
    port: int = 22
    user: str = "root"
    auth: str = "key"
    keyPath: str = ""
    password: str = ""
    condaEnv: str = ""
    workDir: str = "~"
    requireGpu: bool = True
    hostKeyFingerprint: str = ""

def ssh_request_payload(data: SSHTestRequest) -> dict[str, Any]:
    return {
        "host": data.host.strip(),
        "port": data.port,
        "username": data.user.strip(),
        "auth": data.auth,
        "private_key_path": data.keyPath if data.auth == "key" else "",
        "password": data.password if data.auth == "password" else "",
        "conda_env": data.condaEnv,
        "work_dir": data.workDir or "~",
        "require_gpu": data.requireGpu,
        "host_key_fingerprint": data.hostKeyFingerprint,
    }


def _temporary_test_config(data: SSHTestRequest, server_id: str) -> SSHServerConfig:
    return SSHServerConfig(
        id=server_id,
        name=data.name or "test",
        host=data.host,
        port=data.port,
        username=data.user,
        private_key_path=data.keyPath if data.auth == "key" else None,
        password=data.password if data.auth == "password" else None,
        conda_env=data.condaEnv or None,
        work_dir=data.workDir or "~",
    )


def _quoted_remote_work_dir(value: str) -> str:
    if value.startswith("~"):
        suffix = value[1:].lstrip("/")
        return f'"$HOME"/{shlex.quote(suffix)}' if suffix else '"$HOME"'
    return shlex.quote(value or "/tmp")


def ssh_config_payload(config: SSHServerConfig) -> dict[str, Any]:
    if config.private_key_path is not None:
        auth = "key"
    elif config.password is not None:
        auth = "password"
    else:
        auth = "key"
    return {
        "host": config.host.strip(),
        "port": config.port,
        "username": config.username.strip(),
        "auth": auth,
        "private_key_path": config.private_key_path or "",
        "password": config.password or "",
        "conda_env": config.conda_env or "",
        "work_dir": config.work_dir or "~",
        "require_gpu": True,
        "host_key_fingerprint": config.host_key_fingerprint,
    }


def ssh_server_verification_status(server_id: str) -> dict[str, Any]:
    config = _server_configs.get(server_id)
    if not config:
        return {
            "configured": False,
            "tested": False,
            "verified": False,
            "stale": False,
            "tested_at": None,
            "message": "未配置",
        }
    return {
        "configured": True,
        **connection_verification_store.status("ssh", server_id, ssh_config_payload(config)),
    }


def is_ssh_server_verified(server_id: str) -> bool:
    return bool(ssh_server_verification_status(server_id)["verified"])


@router.put("/servers")
async def batch_update_servers(data: SSHServerBatch):
    """Synchronize frontend SSH configurations and expose fingerprint-bound status."""
    import hashlib

    previous_ids = set(_server_configs)
    incoming_ids = {str(server.get("id") or "") for server in data.servers}
    for removed_id in previous_ids - incoming_ids:
        await ssh_manager.disconnect(removed_id)
        ssh_manager._configs.pop(removed_id, None)

    _server_configs.clear()
    for server in data.servers:
        server_id = server.get("id") or hashlib.md5(
            f"{server['host']}:{server.get('port', 22)}:{server['user']}".encode()
        ).hexdigest()[:12]
        config = SSHServerConfig(
            id=server_id,
            name=server.get("name", ""),
            host=server.get("host", ""),
            port=server.get("port", 22),
            username=server.get("user", "root"),
            private_key_path=server.get("keyPath") if server.get("auth") == "key" else None,
            password=server.get("password") if server.get("auth") == "password" else None,
            conda_env=server.get("condaEnv") or None,
            work_dir=server.get("workDir", "~"),
            host_key_fingerprint=server.get("hostKeyFingerprint", ""),
        )
        ssh_manager.add_server(config)
        _server_configs[server_id] = config

    return {
        "status": "updated",
        "count": len(data.servers),
        "verification": {
            server_id: ssh_server_verification_status(server_id)
            for server_id in _server_configs
        },
    }

@router.post("/test")
async def test_connection(data: SSHTestRequest):
    """Test an SSH configuration and persist its fingerprint-bound result."""
    verification_id = data.id or hashlib.md5(
        f"{data.host}:{data.port}:{data.user}".encode()
    ).hexdigest()[:12]
    test_server_id = f"test_{uuid.uuid4().hex[:12]}"
    payload = ssh_request_payload(data)
    ssh_manager.add_server(_temporary_test_config(data, test_server_id))

    try:
        await ssh_manager.connect(test_server_id, accept_unknown_host=not bool(data.hostKeyFingerprint))
        captured_fingerprint = ssh_manager.get_host_key_fingerprint(test_server_id)
        payload["host_key_fingerprint"] = captured_fingerprint
        remote_work_dir = _quoted_remote_work_dir(data.workDir)
        probe = (
            "set -e; "
            "command -v bash >/dev/null; "
            "(command -v python >/dev/null || command -v python3 >/dev/null); "
            f"mkdir -p {remote_work_dir}; "
            f"test -w {remote_work_dir}; "
            + ("command -v nvidia-smi >/dev/null; nvidia-smi -L; " if data.requireGpu else "")
            + "echo MERAK_SSH_OK"
        )
        stdout, stderr, code = await ssh_manager.execute(test_server_id, probe, timeout=15)
        success = code == 0 and "MERAK_SSH_OK" in stdout
        if success:
            from ..services.sftp_service import sftp_service

            home, _, _ = await ssh_manager.execute(test_server_id, "printf '%s' \"$HOME\"", timeout=8)
            resolved_root = data.workDir
            if resolved_root.startswith("~"):
                resolved_root = home.strip() + resolved_root[1:]
            probe_path = str(resolved_root.rstrip("/") + f"/.merak-connection-{uuid.uuid4().hex[:8]}.txt")
            await sftp_service.write_file(test_server_id, probe_path, "MERAK_SFTP_OK\n")
            round_trip = await sftp_service.read_file(test_server_id, probe_path, max_size=1024)
            await sftp_service.delete(test_server_id, probe_path)
            success = round_trip.strip() == "MERAK_SFTP_OK"
        capability = "SSH + Python + SFTP" + (" + NVIDIA GPU" if data.requireGpu else "")
        message = (
            f"{capability} verified on {data.user}@{data.host}:{data.port}"
            if success else (stderr.strip() or stdout.strip()[-500:] or "SSH capability probe failed")
        )
        verification = connection_verification_store.record(
            "ssh", verification_id, payload, success, message
        )
        return {
            "success": success,
            "message": message if success else "",
            "error": "" if success else message,
            "verification": verification,
            "host_key_fingerprint": captured_fingerprint,
        }
    except Exception as exc:
        message = str(exc)
        verification = connection_verification_store.record(
            "ssh", verification_id, payload, False, message
        )
        return {"success": False, "error": message, "verification": verification}
    finally:
        await ssh_manager.disconnect(test_server_id)
        ssh_manager._configs.pop(test_server_id, None)


@router.get("/servers/verification")
async def list_server_verifications():
    return {
        server_id: ssh_server_verification_status(server_id)
        for server_id in _server_configs
    }

@router.post("/servers/{server_id}/connect")
async def connect_server(server_id: str, user: UserInfo = Depends(get_current_user)):
    """连接到 SSH 服务器"""
    if server_id not in _server_configs:
        raise HTTPException(status_code=404, detail="Server not found")

    try:
        await ssh_manager.connect(server_id)
        return {"status": "connected", "server_id": server_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Connection failed: {e}")


@router.post("/servers/{server_id}/disconnect")
async def disconnect_server(server_id: str, user: UserInfo = Depends(get_current_user)):
    """断开 SSH 连接"""
    await ssh_manager.disconnect(server_id)
    return {"status": "disconnected", "server_id": server_id}


@router.delete("/servers/{server_id}")
async def remove_server(server_id: str, user: UserInfo = Depends(get_current_user)):
    """删除 SSH 服务器配置"""
    await ssh_manager.disconnect(server_id)
    _server_configs.pop(server_id, None)
    ssh_manager._configs.pop(server_id, None)
    return {"status": "removed", "server_id": server_id}


@router.get("/servers/{server_id}/status", response_model=SSHConnectionStatus)
async def server_status(server_id: str, user: UserInfo = Depends(get_current_user)):
    """获取服务器连接状态"""
    status = ssh_manager.get_status()
    conn = status.get(server_id)
    config = _server_configs.get(server_id)

    if not config:
        raise HTTPException(status_code=404, detail="Server not found")

    return SSHConnectionStatus(
        server_id=server_id,
        name=config.name,
        host=config.host,
        is_alive=conn.get("is_alive", False) if conn else False,
        connected_at=conn.get("connected_at") if conn else None,
    )


@router.get("/servers/{server_id}/gpu", response_model=GPUStatusResponse)
async def gpu_status(server_id: str, user: UserInfo = Depends(get_current_user)):
    """获取服务器 GPU 状态"""
    try:
        result = await ssh_manager.get_gpu_status(server_id)
        return GPUStatusResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/servers/{server_id}/exec")
async def execute_command(
    server_id: str,
    command: str,
    timeout: int = 30,
    user: UserInfo = Depends(get_current_user),
):
    """在远程服务器执行命令"""
    try:
        stdout, stderr, exit_code = await ssh_manager.execute(server_id, command, timeout=timeout)
        return {
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": exit_code,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== SFTP 远程文件操作 ====================


@router.get("/servers/{server_id}/files")
async def list_remote_files(
    server_id: str,
    path: str = "~",
    user: UserInfo = Depends(get_current_user),
):
    """列出远程目录内容"""
    try:
        entries = await sftp_service.list_dir(server_id, path)
        return {"path": path, "entries": entries}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/servers/{server_id}/files/read")
async def read_remote_file(
    server_id: str,
    path: str,
    user: UserInfo = Depends(get_current_user),
):
    """读取远程文件内容"""
    try:
        content = await sftp_service.read_file(server_id, path)
        return {"path": path, "content": content}
    except ValueError as e:
        raise HTTPException(status_code=413, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/servers/{server_id}/files/write")
async def write_remote_file(
    server_id: str,
    path: str,
    content: str,
    user: UserInfo = Depends(get_current_user),
):
    """写入远程文件"""
    try:
        result = await sftp_service.write_file(server_id, path, content)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/servers/{server_id}/files/mkdir")
async def create_remote_dir(
    server_id: str,
    path: str,
    user: UserInfo = Depends(get_current_user),
):
    """创建远程目录"""
    try:
        result = await sftp_service.mkdir(server_id, path)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/servers/{server_id}/files")
async def delete_remote_file(
    server_id: str,
    path: str,
    user: UserInfo = Depends(get_current_user),
):
    """删除远程文件或目录"""
    try:
        result = await sftp_service.delete(server_id, path)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/servers/{server_id}/files/rename")
async def rename_remote_file(
    server_id: str,
    old_path: str,
    new_path: str,
    user: UserInfo = Depends(get_current_user),
):
    """重命名远程文件"""
    try:
        result = await sftp_service.rename(server_id, old_path, new_path)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
