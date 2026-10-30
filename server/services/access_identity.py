"""Authenticate desktop capabilities and database-backed browser identities."""
from __future__ import annotations

import hmac
import os
import re
from dataclasses import dataclass

from jose import JWTError, jwt
from sqlalchemy import select
from starlette.requests import HTTPConnection

from ..config import settings
from ..db.engine import AsyncSessionLocal
from ..models.models import User

SESSION_COOKIE = "merak_session"


@dataclass(frozen=True)
class Principal:
    id: str
    username: str
    email: str
    display_name: str
    operator: bool = False
    desktop: bool = False
    role: str = "researcher"


def allowed_origin(origin: str) -> bool:
    return origin in settings.cors_origins or bool(
        settings.cors_origin_regex and re.fullmatch(settings.cors_origin_regex, origin)
    )


async def authenticate_connection(connection: HTTPConnection) -> Principal | None:
    """Never treat debug mode or a loopback address alone as authentication."""
    desktop_secret = os.environ.get("MERAK_DESKTOP_OWNER_TOKEN", "")
    supplied = connection.headers.get("x-merak-owner-token", "")
    if desktop_secret and supplied and hmac.compare_digest(desktop_secret, supplied):
        if connection.client and connection.client.host in {"127.0.0.1", "::1"}:
            return Principal("desktop", "desktop", "desktop@merak.local", "Desktop", True, True, "admin")
    authorization = connection.headers.get("authorization", "")
    token = authorization[7:] if authorization.lower().startswith("bearer ") else connection.cookies.get(SESSION_COOKIE, "")
    if not token:
        return None
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        username = payload.get("sub")
        if not isinstance(username, str) or not username:
            return None
    except JWTError:
        return None
    async with AsyncSessionLocal() as session:
        user = (await session.execute(select(User).where(User.username == username))).scalar_one_or_none()
        if user is None or not user.is_active:
            return None
        return Principal(user.id, user.username, user.email, user.display_name,
                         user.role.value == "admin", role=user.role.value)
