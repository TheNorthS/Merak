"""Own an isolated shipped backend and record evidence without exposing secrets."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import time

import httpx

ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def write_json(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(".pending")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def package_identity(package: Path) -> dict:
    runtime = package / "resources/server-bundle/runtime/win32-x64"
    manifest = json.loads((runtime / "merak-bundle.json").read_bytes())
    version = json.loads((ROOT / "package.json").read_bytes())["version"]
    installer = ROOT / "release" / f"Merak-Setup-{version}-x64.exe"
    executable = runtime / "merak-backend.exe"
    actual = digest(executable)
    if actual != manifest["executable_sha256"]:
        raise RuntimeError("Backend executable does not match its bundle manifest")
    return {"version": version, "backend_source_sha256": manifest["source_sha256"],
            "backend_sha256": actual, "asar_sha256": digest(package / "resources/app.asar"),
            "installer_sha256": digest(installer), "installer": str(installer)}


def freeze_sources(destination: Path) -> dict:
    from scripts.export_source import source_files
    manifest = {path.relative_to(ROOT).as_posix(): digest(path) for path in source_files()}
    write_json(destination / "source-manifest.json", manifest)
    return manifest


class PackageRuntime:
    def __init__(self, package: Path, output: Path, settings_root: Path):
        self.package, self.output, self.settings_root = package, output, settings_root
        self.profile = output / "profile"
        self.token = secrets.token_hex(32)
        self.process = None
        self.logs = []
        self.redactions = [self.token]
        self.client = None
        self.base = ""
        self.desktop = None

    def clean(self, text: str) -> str:
        for secret in self.redactions:
            if secret:
                text = text.replace(secret, "[redacted]")
        return text

    async def request(self, method: str, route: str, **kwargs):
        response = await self.desktop.request(method, route, **kwargs)
        if response["status"] >= 400:
            raise RuntimeError(self.clean(f"{method} {route}: HTTP {response['status']}: {response['text'][:5000]}"))
        return json.loads(response["text"])

    def websocket(self, route: str):
        return self.desktop.websocket(route)

    async def _capture(self, stream, name: str):
        with (self.output / name).open("a", encoding="utf-8") as log:
            while line := await stream.readline():
                log.write(self.clean(line.decode("utf-8", errors="replace")))
                log.flush()

    async def start(self):
        from scripts.stability_desktop_transport import DesktopTransport
        self.profile.mkdir(parents=True, exist_ok=False)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 8011))  # Refuse to attach to a user's running backend.
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = {key: value for key, value in os.environ.items()
               if key.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "COMSPEC", "PATHEXT"}}
        env.update({key: str(self.profile) for key in ("TEMP", "TMP", "APPDATA", "LOCALAPPDATA", "USERPROFILE")})
        env.update({"PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1", "MERAK_IDE_DEBUG": "false"})
        self.process = await asyncio.create_subprocess_exec(
            str(self.package / "Merak.exe"), f"--remote-debugging-port={port}",
            f"--user-data-dir={self.profile}", cwd=self.profile, env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW, limit=4 * 1024 * 1024,
        )
        self.logs = [asyncio.create_task(self._capture(self.process.stdout, "desktop.stdout.log")),
                     asyncio.create_task(self._capture(self.process.stderr, "desktop.stderr.log"))]
        self.client = httpx.AsyncClient(timeout=2, trust_env=False)
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            if self.process.returncode is not None:
                raise RuntimeError("Packaged desktop exited during startup")
            try:
                pages = (await self.client.get(f"http://127.0.0.1:{port}/json/list")).json()
                target = next((page for page in pages if page.get("type") == "page"
                               and page.get("url", "").startswith("file://")), None)
                if target:
                    self.desktop = DesktopTransport(target["webSocketDebuggerUrl"])
                    status = await self.desktop.evaluate("window.merakIDE.backend.getStatus()", timeout=5)
                    if status.get("status") == "ready":
                        health = await self.request("GET", "/api/health")
                        if health.get("desktop_owner_pid") != self.process.pid:
                            raise RuntimeError("Desktop attached to a different process's backend")
                        self.base = f"http://127.0.0.1:{status['port']}"
                        await self.desktop.evaluate("window.merakIDE.window.minimize()")
                        write_json(self.output / "desktop-process.json", {
                            "pid": self.process.pid, "backend_pid": health["backend_pid"], "port": status["port"],
                        })
                        return
            except (httpx.HTTPError, RuntimeError, TimeoutError):
                pass
            await asyncio.sleep(0.5)
        raise RuntimeError("Packaged desktop did not become healthy within 180 seconds")

    async def configure_models(self):
        from scripts.live_snapshot_safety import load_current_model_config_readonly
        from server.services.settings_models import ModelConfig
        original = load_current_model_config_readonly(self.settings_root)
        selected = {key: value for key, value in original.model_dump().items() if key.startswith("openai_")}
        if not selected.get("openai_api_key"):
            raise RuntimeError("No configured OpenAI-compatible provider in the authorized user profile")
        self.redactions.extend([selected["openai_api_key"], selected.get("openai_base_url", "")])
        await self.request("PUT", "/api/settings/models", json=ModelConfig(**selected).model_dump())
        results = {}
        for label, route in (("executor", "/api/settings/models/test?provider=openai"),
                             ("reviewer", "/api/settings/models/reviewer/test")):
            result = await self.request("POST", route)
            results[label] = {key: result.get(key) for key in ("success", "model", "attempts")}
            if not result.get("success"):
                write_json(self.output / "model-connectivity.json", results)
                raise RuntimeError(self.clean(str(result.get("error") or "Model connection test failed")))
        await self.request("PUT", "/api/settings/models/strategy", json={
            "executor": "openai-api", "reviewer": "openai-api", "search": "openai-api", "figure": "openai-api",
        })
        results["transport"] = selected["openai_transport"]
        write_json(self.output / "model-connectivity.json", results)

    async def close(self):
        if self.process and self.process.returncode is None:
            try:
                if self.desktop:
                    await self.desktop.evaluate("setTimeout(() => window.merakIDE.window.close(), 50); true", timeout=10)
                await asyncio.wait_for(self.process.wait(), 45)
            except (RuntimeError, OSError, TimeoutError):
                if self.process.returncode is None:
                    self.process.terminate()
                    await self.process.wait()
        if self.logs:
            await asyncio.gather(*self.logs)
        if self.client:
            await self.client.aclose()
        # Only this runner's isolated credential stores; never user settings.
        for name in ("user_settings.json", "merak_ide.db", "merak_ide.db-wal", "merak_ide.db-shm", "merak_ide.db-journal"):
            for path in self.profile.rglob(name):
                if path.resolve().is_relative_to(self.profile.resolve()):
                    path.unlink(missing_ok=True)
