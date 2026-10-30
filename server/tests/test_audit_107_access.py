"""Exercise real HTTP/WS boundaries without listeners, shells or user credentials."""
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from jose import jwt

from server.api import auth, files, projects, settings as settings_api
from server.config import settings
from server.db.engine import get_db
from server.models.models import Base, User, UserRole
from server.services import access_identity
from server.services.access_identity import Principal
from server.services.api_access import ApiAccessMiddleware
from server.services.project_repository import create_project
from server.services.settings_models import ModelConfig, UserSettings
from server.services.settings_visibility import SECRET_FIELDS
from server.ws.local_terminal import LocalTerminalSession
from server.ws.router import ws_router


def application():
    app = FastAPI()
    app.add_middleware(ApiAccessMiddleware)
    for router, prefix in [(files.router, "/api/files"), (auth.router, "/api/auth"),
                           (projects.router, "/api/projects"), (settings_api.router, "/api/settings")]:
        app.include_router(router, prefix=prefix)
    app.include_router(ws_router)
    return app


@pytest.mark.parametrize("path", ["/api/files/read", "/api/files/write", "/api/settings/",
                                 "/api/workflow/run", "/api/ssh/servers", "/api/experiments/"])
def test_every_sensitive_route_rejects_missing_auth_even_in_debug(monkeypatch, path):
    monkeypatch.setattr(settings, "debug", True)
    response = TestClient(application()).post(path, json={})
    assert response.status_code == 401


def test_foreign_origin_websocket_cannot_start_terminal(monkeypatch):
    start = AsyncMock()
    monkeypatch.setattr(LocalTerminalSession, "start", start)
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect):
        with TestClient(application()).websocket_connect("/ws/terminal/audit", headers={"origin": "https://untrusted.invalid"}):
            pytest.fail("unauthorized WebSocket accepted")
    start.assert_not_called()


@pytest.mark.asyncio
async def test_web_login_sets_private_cookie_and_registration_is_closed(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(settings, "debug", False)
    monkeypatch.setattr(settings, "allow_registration", False)
    monkeypatch.setattr(auth.authentication_service, "authenticate", AsyncMock(return_value=SimpleNamespace(username="fixture")))
    app = application()
    async def db():
        yield None
    app.dependency_overrides[get_db] = db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="https://test") as client:
        response = await client.post("/api/auth/login", json={"username": "fixture", "password": "fixture-password"})
        assert response.status_code == 200
        cookie = response.headers["set-cookie"]
        assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=strict" in cookie
        denied = await client.post("/api/auth/register", json={"username": "new", "email": "new@example.org", "password": "fixture-password"})
        assert denied.status_code == 403


@pytest.mark.asyncio
async def test_desktop_capability_and_masked_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("MERAK_DESKTOP_OWNER_TOKEN", "fixture-desktop-secret")
    synthetic = ModelConfig(**{name: "short-secret" for name in SECRET_FIELDS})
    monkeypatch.setattr(settings_api, "load_settings", lambda: UserSettings(models=synthetic))
    app = application()
    transport = httpx.ASGITransport(app, client=("127.0.0.1", 12345))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = {"x-merak-owner-token": "fixture-desktop-secret", "origin": "null"}
        for endpoint in ["/api/settings/", "/api/settings/models"]:
            response = await client.get(endpoint, headers=headers)
            assert response.status_code == 200
            assert "short-secret" not in response.text
            assert "********" in response.text
        denied = await client.get("/api/settings/", headers={**headers, "origin": "https://untrusted.invalid"})
        assert denied.status_code == 403


@pytest.mark.asyncio
async def test_member_files_and_project_durability(monkeypatch, tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async def db():
        async with sessions() as session:
            yield session
            await session.commit()
    monkeypatch.setattr(access_identity, "AsyncSessionLocal", sessions)
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "workspaces"))
    monkeypatch.setattr(settings, "jwt_secret_key", "fixture-secret" * 4)
    async with sessions() as session:
        session.add(User(id="alice", username="alice", email="alice@example.org", password_hash="!",
                         role=UserRole.RESEARCHER))
        await session.commit()
    principal = Principal("alice", "alice", "alice@example.org", "Alice")
    root = tmp_path / "workspaces/alice/project"
    root.mkdir(parents=True)
    (root / "file.txt").write_text("mine", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("other", encoding="utf-8")
    app = application()
    app.dependency_overrides[get_db] = db
    token = jwt.encode({"sub": "alice"}, settings.jwt_secret_key, algorithm="HS256")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test",
                                headers={"Authorization": f"Bearer {token}"}) as client:
        created = await client.post("/api/projects/", json={"name": "project", "path": str(root)})
        assert created.status_code == 200, created.text
        project_id = created.json()["id"]
        assert (await client.get("/api/files/read", params={"path": str(root / 'file.txt')})).status_code == 200
        assert (await client.get("/api/files/read", params={"path": str(outside)})).status_code == 403
        assert (await client.post("/api/files/write", json={"path": str(outside), "content": "bad"})).status_code == 403
        assert (await client.post("/api/projects/", json={"name": "foreign", "path": str(tmp_path)})).status_code == 403
        assert (await client.get("/api/settings/")).status_code == 403
    # A fresh app/session has no process-local project registry to repopulate.
    reopened = application()
    reopened.dependency_overrides[get_db] = db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(reopened), base_url="http://test",
                                headers={"Authorization": f"Bearer {token}"}) as client:
        result = await client.get(f"/api/projects/{project_id}")
        assert result.status_code == 200 and result.json()["path"] == str(root.resolve())
    await engine.dispose()
