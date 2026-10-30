"""One fail-closed HTTP/WS boundary, including routes without local dependencies."""
from __future__ import annotations

from starlette.requests import HTTPConnection
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .access_identity import allowed_origin, authenticate_connection

PUBLIC_PATHS = frozenset({"/api/health", "/api/auth/login", "/api/auth/register"})


class ApiAccessMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if scope["type"] not in {"http", "websocket"} or not path.startswith(("/api/", "/ws/")):
            await self.app(scope, receive, send)
            return
        connection = HTTPConnection(scope)
        origin = connection.headers.get("origin", "")
        if origin and not allowed_origin(origin):
            await self._reject(scope, receive, send, 403, "Origin is not allowed")
            return
        if scope.get("method") == "OPTIONS" or path in PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return
        principal = await authenticate_connection(connection)
        if principal is None:
            await self._reject(scope, receive, send, 401, "Authentication required")
            return
        # Global settings, shell, SSH, model execution and workflow registries
        # are operator resources. Project/file APIs have member-level policies.
        member_route = path.startswith(("/api/projects/", "/api/files/", "/api/auth/"))
        if not principal.operator and not member_route:
            await self._reject(scope, receive, send, 403, "Operator access required")
            return
        scope.setdefault("state", {})["principal"] = principal
        await self.app(scope, receive, send)

    @staticmethod
    async def _reject(scope: Scope, receive: Receive, send: Send, status: int, detail: str) -> None:
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 4401 if status == 401 else 4403})
        else:
            await JSONResponse({"detail": detail}, status_code=status)(scope, receive, send)
