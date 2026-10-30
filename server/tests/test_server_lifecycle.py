from __future__ import annotations

import asyncio
import hashlib
import json

import pytest
from fastapi import HTTPException

import server.main as server_main


def test_health_exposes_only_the_desktop_owner_digest(monkeypatch) -> None:
    token = "desktop-owner-secret"
    monkeypatch.setenv("MERAK_DESKTOP_OWNER_TOKEN", token)
    monkeypatch.setenv("MERAK_DESKTOP_OWNER_PID", "321")

    payload = asyncio.run(server_main.health_check())

    assert payload["desktop_owner_token_sha256"] == hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()
    assert payload["desktop_owner_pid"] == 321
    assert payload["backend_pid"] > 0
    assert len(payload["installation_sha256"]) == 64
    assert token not in json.dumps(payload)


def test_health_treats_invalid_desktop_owner_pid_as_unowned(monkeypatch) -> None:
    monkeypatch.setenv("MERAK_DESKTOP_OWNER_PID", "not-a-pid")

    payload = asyncio.run(server_main.health_check())

    assert payload["desktop_owner_pid"] == 0


def test_desktop_shutdown_requires_owner_and_stops_active_runtime(
    monkeypatch,
) -> None:
    token = "owned-desktop"
    monkeypatch.setenv("MERAK_DESKTOP_OWNER_TOKEN", token)
    calls: list[str] = []

    async def stopped(label: str) -> None:
        calls.append(label)

    monkeypatch.setattr(
        server_main.workflow_recovery_watchdog,
        "stop",
        lambda: stopped("watchdog"),
    )
    monkeypatch.setattr(
        server_main.workflow_engine,
        "shutdown",
        lambda: stopped("workflow"),
    )
    monkeypatch.setattr(
        server_main.merak_bridge,
        "stop",
        lambda: stopped("bridge"),
    )
    monkeypatch.setattr(
        server_main.experiment_scheduler,
        "stop",
        lambda: stopped("experiments"),
    )

    with pytest.raises(HTTPException) as rejected:
        asyncio.run(server_main.prepare_desktop_shutdown("wrong-token"))
    assert rejected.value.status_code == 403
    assert calls == []

    result = asyncio.run(server_main.prepare_desktop_shutdown(token))

    assert result == {"status": "prepared"}
    assert calls == ["watchdog", "workflow", "bridge", "experiments"]
