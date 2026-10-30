"""
SFTP 远程文件操作服务

通过 asyncssh SFTP 实现远程文件系统操作：
- 目录浏览
- 文件读取/写入
- 文件上传/下载
- 文件重命名/删除
"""

import hashlib
import os
import uuid
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Optional

import asyncssh
import structlog

from ..utils.atomic_write import atomic_replace_file
from .ssh_manager import ssh_manager

logger = structlog.get_logger()


class SFTPService:
    """SFTP 远程文件操作"""

    @staticmethod
    def _remote_name(value: Any) -> str:
        """Normalize AsyncSSH filename unions before path/string operations."""

        if isinstance(value, bytes):
            return value.decode("utf-8", errors="surrogateescape")
        return str(value)

    async def _get_sftp(self, server_id: str) -> asyncssh.SFTPClient:
        """获取 SFTP 客户端（如果未连接会自动连接）"""
        conn_info = ssh_manager._connections.get(server_id)
        if not conn_info or not conn_info.conn or not conn_info.is_alive:
            await ssh_manager.connect(server_id)
            conn_info = ssh_manager._connections.get(server_id)

        if not conn_info or not conn_info.conn:
            raise ConnectionError(f"Cannot connect to server {server_id}")

        return await conn_info.conn.start_sftp_client()

    async def list_dir(self, server_id: str, path: str) -> list[dict]:
        """列出远程目录内容"""
        sftp = await self._get_sftp(server_id)

        try:
            entries = await sftp.readdir(path)
            results = []

            for entry in entries:
                name = self._remote_name(entry.filename)
                # 跳过 . 和 ..
                if name in ('.', '..'):
                    continue
                # 跳过隐藏文件（可选）
                if name.startswith('.') and name not in ('.env', '.gitignore'):
                    continue

                attrs = entry.attrs
                results.append({
                    "name": name,
                    "path": str(PurePosixPath(path) / name),
                    "is_directory": attrs.type == asyncssh.FILEXFER_TYPE_DIRECTORY if attrs.type else False,
                    "size": attrs.size or 0,
                    "modified": attrs.mtime or 0,
                    "permissions": oct(attrs.permissions & 0o777) if attrs.permissions else "0o000",
                })

            # 目录在前，按名称排序
            results.sort(key=lambda e: (not e["is_directory"], e["name"].lower()))
            return results

        finally:
            sftp.exit()

    async def read_file(self, server_id: str, path: str, max_size: int = 10 * 1024 * 1024) -> str:
        """读取远程文件内容"""
        sftp = await self._get_sftp(server_id)

        try:
            # 检查文件大小
            attrs = await sftp.stat(path)
            if attrs.size and attrs.size > max_size:
                raise ValueError(f"File too large: {attrs.size} bytes (max {max_size})")

            async with sftp.open(path, 'r') as f:
                content = await f.read()
                if isinstance(content, bytes):
                    return content.decode('utf-8')
                return content

        finally:
            sftp.exit()

    async def write_file(self, server_id: str, path: str, content: str) -> dict:
        """写入远程文件"""
        sftp = await self._get_sftp(server_id)

        try:
            async with sftp.open(path, 'w') as f:
                await f.write(content.encode('utf-8') if isinstance(content, str) else content)

            return {"status": "written", "path": path, "size": len(content)}

        finally:
            sftp.exit()

    async def upload_file(self, server_id: str, local_path: str | Path, remote_path: str) -> dict:
        """Upload one file and verify its content hash on both sides."""
        source = Path(local_path).resolve()
        if not source.is_file():
            raise FileNotFoundError(source)

        sftp = await self._get_sftp(server_id)
        try:
            await sftp.makedirs(str(PurePosixPath(remote_path).parent), exist_ok=True)
            await sftp.put(str(source), remote_path, preserve=True)
            local_hash = self._hash_local_file(source)
            remote_hash = await self._hash_remote_file(sftp, remote_path)
            if local_hash != remote_hash:
                raise IOError(f"Hash mismatch after upload: {source} -> {remote_path}")
            return {
                "status": "uploaded",
                "local_path": str(source),
                "remote_path": remote_path,
                "size": source.stat().st_size,
                "sha256": local_hash,
            }
        finally:
            sftp.exit()

    async def download_file(self, server_id: str, remote_path: str, local_path: str | Path) -> dict:
        """Download one file atomically and verify its content hash."""
        destination = Path(local_path).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(
            f".{destination.name}.{os.getpid()}.{uuid.uuid4().hex}.merak-part"
        )

        sftp = await self._get_sftp(server_id)
        try:
            remote_hash = await self._hash_remote_file(sftp, remote_path)
            await sftp.get(remote_path, str(temporary), preserve=True)
            local_hash = self._hash_local_file(temporary)
            if local_hash != remote_hash:
                temporary.unlink(missing_ok=True)
                raise IOError(f"Hash mismatch after download: {remote_path} -> {destination}")
            atomic_replace_file(temporary, destination)
            return {
                "status": "downloaded",
                "remote_path": remote_path,
                "local_path": str(destination),
                "size": destination.stat().st_size,
                "sha256": local_hash,
            }
        finally:
            temporary.unlink(missing_ok=True)
            sftp.exit()

    async def upload_directory(
        self,
        server_id: str,
        local_dir: str | Path,
        remote_dir: str,
        relative_paths: Optional[Iterable[str]] = None,
        verify: bool = True,
    ) -> dict:
        """Upload an explicit project snapshot without deleting remote files.

        ``relative_paths`` lets callers exclude credentials, local datasets,
        checkpoints, build output, and stale result artifacts.
        """
        root = Path(local_dir).resolve()
        if not root.is_dir():
            raise NotADirectoryError(root)

        if relative_paths is None:
            paths = [
                path.relative_to(root).as_posix()
                for path in root.rglob("*")
                if path.is_file() and not path.is_symlink()
            ]
        else:
            paths = sorted({str(path).replace("\\", "/").lstrip("/") for path in relative_paths})

        sftp = await self._get_sftp(server_id)
        uploaded: list[dict] = []
        try:
            await sftp.makedirs(remote_dir, exist_ok=True)
            for relative in paths:
                source = (root / Path(relative)).resolve()
                try:
                    source.relative_to(root)
                except ValueError as exc:
                    raise ValueError(f"Snapshot path escapes local root: {relative}") from exc
                if not source.is_file() or source.is_symlink():
                    continue

                remote_path = str(PurePosixPath(remote_dir) / PurePosixPath(relative))
                await sftp.makedirs(str(PurePosixPath(remote_path).parent), exist_ok=True)
                await sftp.put(str(source), remote_path, preserve=True)
                local_hash = self._hash_local_file(source)
                if verify:
                    remote_hash = await self._hash_remote_file(sftp, remote_path)
                    if local_hash != remote_hash:
                        raise IOError(f"Hash mismatch after upload: {relative}")
                uploaded.append({
                    "path": relative,
                    "size": source.stat().st_size,
                    "sha256": local_hash,
                })
            return {
                "status": "uploaded",
                "local_dir": str(root),
                "remote_dir": remote_dir,
                "files": uploaded,
                "file_count": len(uploaded),
                "bytes": sum(item["size"] for item in uploaded),
                "verified": verify,
            }
        finally:
            sftp.exit()

    async def download_directory(
        self,
        server_id: str,
        remote_dir: str,
        local_dir: str | Path,
        verify: bool = True,
    ) -> dict:
        """Recursively download results into an isolated local run directory."""
        destination = Path(local_dir).resolve()
        destination.mkdir(parents=True, exist_ok=True)
        sftp = await self._get_sftp(server_id)
        downloaded: list[dict] = []
        try:
            try:
                remote_files = await self._walk_remote_files(sftp, remote_dir)
            except (FileNotFoundError, asyncssh.SFTPNoSuchFile):
                return {
                    "status": "missing",
                    "remote_dir": remote_dir,
                    "local_dir": str(destination),
                    "files": [],
                    "file_count": 0,
                    "bytes": 0,
                    "verified": verify,
                }

            for remote_path in remote_files:
                relative = PurePosixPath(remote_path).relative_to(PurePosixPath(remote_dir)).as_posix()
                target = (destination / Path(relative)).resolve()
                try:
                    target.relative_to(destination)
                except ValueError as exc:
                    raise ValueError(f"Remote path escapes download root: {remote_path}") from exc
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_name(
                    f".{target.name}.{os.getpid()}.{uuid.uuid4().hex}.merak-part"
                )
                try:
                    remote_hash = await self._hash_remote_file(sftp, remote_path) if verify else ""
                    await sftp.get(remote_path, str(temporary), preserve=True)
                    local_hash = self._hash_local_file(temporary)
                    if verify and local_hash != remote_hash:
                        raise IOError(f"Hash mismatch after download: {remote_path}")
                    atomic_replace_file(temporary, target)
                    downloaded.append({
                        "path": relative,
                        "size": target.stat().st_size,
                        "sha256": local_hash,
                    })
                finally:
                    temporary.unlink(missing_ok=True)
            return {
                "status": "downloaded",
                "remote_dir": remote_dir,
                "local_dir": str(destination),
                "files": downloaded,
                "file_count": len(downloaded),
                "bytes": sum(item["size"] for item in downloaded),
                "verified": verify,
            }
        finally:
            sftp.exit()

    async def read_bytes(
        self,
        server_id: str,
        path: str,
        offset: int = 0,
        max_bytes: int = 1024 * 1024,
    ) -> tuple[bytes, int]:
        """Read a bounded byte range for incremental remote log tailing."""
        if offset < 0 or max_bytes <= 0:
            raise ValueError("offset must be >= 0 and max_bytes must be > 0")
        sftp = await self._get_sftp(server_id)
        try:
            try:
                attrs = await sftp.stat(path)
            except (FileNotFoundError, asyncssh.SFTPNoSuchFile):
                return b"", offset
            size = int(attrs.size or 0)
            if size < offset:
                offset = 0
            async with sftp.open(path, "rb") as handle:
                await handle.seek(offset)
                data = await handle.read(min(max_bytes, max(0, size - offset)))
            if isinstance(data, str):
                data = data.encode("utf-8")
            return data, offset + len(data)
        finally:
            sftp.exit()

    async def exists(self, server_id: str, path: str) -> bool:
        sftp = await self._get_sftp(server_id)
        try:
            try:
                await sftp.stat(path)
                return True
            except (FileNotFoundError, asyncssh.SFTPNoSuchFile):
                return False
        finally:
            sftp.exit()

    @staticmethod
    def _hash_local_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    async def _hash_remote_file(sftp: asyncssh.SFTPClient, path: str) -> str:
        digest = hashlib.sha256()
        async with sftp.open(path, "rb") as handle:
            while True:
                chunk = await handle.read(1024 * 1024)
                if not chunk:
                    break
                if isinstance(chunk, str):
                    chunk = chunk.encode("utf-8")
                digest.update(chunk)
        return digest.hexdigest()

    async def _walk_remote_files(self, sftp: asyncssh.SFTPClient, root: str) -> list[str]:
        files: list[str] = []
        entries = await sftp.readdir(root)
        for entry in entries:
            name = self._remote_name(entry.filename)
            if name in (".", ".."):
                continue
            path = str(PurePosixPath(root) / name)
            if entry.attrs.type == asyncssh.FILEXFER_TYPE_DIRECTORY:
                files.extend(await self._walk_remote_files(sftp, path))
            else:
                files.append(path)
        return files

    async def mkdir(self, server_id: str, path: str) -> dict:
        """创建远程目录"""
        sftp = await self._get_sftp(server_id)

        try:
            await sftp.makedirs(path, exist_ok=True)
            return {"status": "created", "path": path}
        finally:
            sftp.exit()

    async def delete(self, server_id: str, path: str) -> dict:
        """删除远程文件或目录"""
        sftp = await self._get_sftp(server_id)

        try:
            attrs = await sftp.stat(path)
            if attrs.type == asyncssh.FILEXFER_TYPE_DIRECTORY:
                # 递归删除目录
                await self._rmdir_recursive(sftp, path)
            else:
                await sftp.remove(path)

            return {"status": "deleted", "path": path}
        finally:
            sftp.exit()

    async def rename(self, server_id: str, old_path: str, new_path: str) -> dict:
        """重命名远程文件"""
        sftp = await self._get_sftp(server_id)

        try:
            await sftp.rename(old_path, new_path)
            return {"status": "renamed", "old": old_path, "new": new_path}
        finally:
            sftp.exit()

    async def stat(self, server_id: str, path: str) -> dict:
        """获取远程文件信息"""
        sftp = await self._get_sftp(server_id)

        try:
            attrs = await sftp.stat(path)
            return {
                "path": path,
                "size": attrs.size or 0,
                "is_directory": attrs.type == asyncssh.FILEXFER_TYPE_DIRECTORY if attrs.type else False,
                "modified": attrs.mtime or 0,
                "permissions": oct(attrs.permissions & 0o777) if attrs.permissions else "0o000",
                "owner": attrs.uid,
                "group": attrs.gid,
            }
        finally:
            sftp.exit()

    async def _rmdir_recursive(self, sftp: asyncssh.SFTPClient, path: str):
        """递归删除目录"""
        entries = await sftp.readdir(path)
        for entry in entries:
            name = self._remote_name(entry.filename)
            if name in ('.', '..'):
                continue
            full_path = str(PurePosixPath(path) / name)
            if entry.attrs.type == asyncssh.FILEXFER_TYPE_DIRECTORY:
                await self._rmdir_recursive(sftp, full_path)
            else:
                await sftp.remove(full_path)
        await sftp.rmdir(path)


# 全局实例
sftp_service = SFTPService()
