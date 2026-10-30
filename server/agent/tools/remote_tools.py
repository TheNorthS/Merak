"""Focused remote tools for the MERAK agent surface."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Optional

import structlog



logger = structlog.get_logger()
FILE_READ_MAX_CHARS = 128_000


async def terminal_exec(command: str, cwd: Optional[str] = None, timeout: int = 60) -> str:
    """执行终端命令"""
    from ..tool_process import shell_process_options, read_process_tail, stop_process_tree

    if not command.strip() or timeout <= 0:
        raise ValueError("command must be nonempty and timeout must be positive")
    proc = await asyncio.create_subprocess_shell(
        command,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=cwd,
        **shell_process_options(),
    )
    try:
        stdout = await asyncio.wait_for(read_process_tail(proc), timeout=timeout)
        import locale
        encoding = locale.getpreferredencoding(False) or 'utf-8'
        output = stdout.decode(encoding, errors='replace')
        exit_info = f"\n[exit code: {proc.returncode}]"
        result = output[-5000:] + exit_info
        if proc.returncode != 0:
            raise RuntimeError(result)
        return result
    except asyncio.TimeoutError:
        await stop_process_tree(proc)
        raise TimeoutError(f"TOOL_TIMEOUT: command exceeded {timeout}s")
    except asyncio.CancelledError:
        await stop_process_tree(proc)
        raise


# ==================== SSH 远程执行 ====================

async def ssh_exec(server_id: str, command: str, timeout: int = 30) -> str:
    """在远程服务器执行命令"""
    from server.services.ssh_manager import ssh_manager
    stdout, stderr, exit_code = await ssh_manager.execute(server_id, command, timeout=timeout)
    result = stdout
    if stderr:
        result += f"\n[stderr]: {stderr}"
    result += f"\n[exit code: {exit_code}]"
    if exit_code != 0:
        raise RuntimeError(result[-5000:])
    return result[-5000:]


async def ssh_sync(server_id: str, local_dir: str, remote_dir: str = "~/experiments") -> str:
    """Synchronize a safe project snapshot and verify every uploaded hash."""
    from server.services.ssh_manager import ssh_manager
    from server.services.sftp_service import sftp_service
    from pathlib import PurePosixPath

    config = ssh_manager._configs.get(server_id)
    if not config:
        raise ValueError(f"Server {server_id} not found. Register it first.")
    root = Path(local_dir).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Local directory does not exist: {root}")
    if server_id not in ssh_manager._connections or not ssh_manager._connections[server_id].is_alive:
        await ssh_manager.connect(server_id)
    if remote_dir.startswith("~"):
        home, stderr, code = await ssh_manager.execute(server_id, "printf '%s' \"$HOME\"", timeout=10)
        if code != 0 or not home.strip():
            raise RuntimeError(f"Unable to resolve remote home: {stderr or home}")
        suffix = remote_dir[1:].lstrip("/")
        remote_dir = str(PurePosixPath(home.strip()) / suffix) if suffix else home.strip()

    excluded_dirs = {
        ".git", ".merak", "node_modules", "dist", "dist-electron", "build",
        "__pycache__", ".pytest_cache", ".venv", "venv", "checkpoints", "wandb",
        "data", "dataset", "datasets",
    }
    excluded_names = {".env", ".env.local", "user_settings.json", "merak_ide.db", "yjs_docs.db"}
    relative_paths = []
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root)
        if set(relative.parts) & excluded_dirs or path.name.lower() in excluded_names:
            continue
        if path.suffix.lower() in {".pem", ".key", ".p12", ".pfx", ".db", ".sqlite"}:
            continue
        relative_paths.append(relative.as_posix())
    try:
        result = await sftp_service.upload_directory(
            server_id, root, remote_dir, relative_paths=relative_paths, verify=True
        )
        return (
            f"Sync complete: {result['file_count']} files, {result['bytes']} bytes, "
            f"hash_verified={result['verified']}, remote={remote_dir}"
        )
    except Exception as e:
        raise RuntimeError(f"Sync error: {e}") from e


async def _scp_fallback(config, local_dir: str, remote_dir: str) -> str:
    """rsync 不可用时用 scp"""
    from server.services.ssh_manager import ssh_manager
    # 先在远程创建目录
    await ssh_manager.execute(config.id, f"mkdir -p {remote_dir}")
    # 用 SFTP 上传
    try:
        from server.services.sftp_service import sftp_service
        await sftp_service.upload_directory(config.id, local_dir, remote_dir)
        return f"Uploaded {local_dir} to {config.username}@{config.host}:{remote_dir} (via SFTP)"
    except Exception as e:
        raise RuntimeError(f"SFTP upload failed: {e}") from e


async def ssh_deploy_experiment(server_id: str, script_path: str, args: str = "", gpu_id: int = 0) -> str:
    """在远程服务器部署实验"""
    from server.services.ssh_manager import ssh_manager
    import shlex

    screen_name = f"merak_exp_{os.urandom(4).hex()}"
    log_path = f"{script_path}.log"
    status_path = f"{script_path}.status.json"
    command = (
        f"screen -dmS {shlex.quote(screen_name)} bash -lc "
        + shlex.quote(
            "set -o pipefail; "
            f"CUDA_VISIBLE_DEVICES={int(gpu_id)} python {shlex.quote(script_path)} {args} "
            f"2>&1 | tee -a {shlex.quote(log_path)}; "
            "rc=${PIPESTATUS[0]}; "
            f"printf '{{\"exit_code\":%d}}\\n' \"$rc\" > {shlex.quote(status_path)}; "
            "exit \"$rc\""
        )
    )
    stdout, stderr, exit_code = await ssh_manager.execute(server_id, command, timeout=10)

    if exit_code == 0:
        return (
            f"Experiment deployed: screen={screen_name}, gpu={gpu_id}, script={script_path}, "
            f"log={log_path}, status={status_path}"
        )
    else:
        raise RuntimeError(f"Deploy failed: {stderr}")


# ==================== 文献搜索 ====================

