"""Route-level project and path authorization after the shared identity boundary."""
from pathlib import Path

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db.engine import get_db
from ..services.access_identity import Principal, authenticate_connection
from ..services.project_repository import project_roots


async def current_principal(request: Request) -> Principal:
    principal = getattr(request.state, "principal", None) or await authenticate_connection(request)
    if principal is None:
        raise HTTPException(401, "Authentication required")
    return principal


def require_project_location(principal: Principal, path: str) -> Path:
    root = Path(path).expanduser().resolve()
    if principal.role == "viewer":
        raise HTTPException(403, "Viewers cannot create or modify project structure")
    if not principal.operator:
        owned = (Path(settings.workspace_root) / principal.id).resolve()
        if not root.is_relative_to(owned) or root == owned:
            raise HTTPException(403, "New projects must be inside your workspace directory")
    return root


async def authorize_files(request: Request, principal: Principal = Depends(current_principal),
                          session: AsyncSession = Depends(get_db)) -> None:
    if principal.operator:
        return
    if request.url.path.endswith(("/open-external", "/latex-compile")):
        raise HTTPException(403, "Operator access required")
    values = dict(request.query_params)
    if request.method not in {"GET", "HEAD"}:
        values.update(await request.json())
    roots = await project_roots(session, principal, write=request.method not in {"GET", "HEAD"})
    for field in ("path", "root", "old_path", "new_path", "project_dir"):
        if field in values:
            target = Path(str(values[field])).expanduser().resolve()
            if not any(target.is_relative_to(root) for root in roots):
                raise HTTPException(403, "Path is outside your authorized projects")
