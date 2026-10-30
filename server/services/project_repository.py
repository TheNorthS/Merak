"""Durable project identities and membership; all resource paths remain explicit."""
from __future__ import annotations

from pathlib import Path
import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.models import Project, ProjectMember, ProjectRole, User, UserRole
from .access_identity import Principal


async def project_roots(session: AsyncSession, principal: Principal, *, write: bool) -> list[Path]:
    statement = select(Project.path).join(ProjectMember).where(ProjectMember.user_id == principal.id)
    if write:
        statement = statement.where(ProjectMember.role.in_([ProjectRole.OWNER, ProjectRole.EDITOR]))
    return [Path(path).expanduser().resolve() for path in (await session.execute(statement)).scalars()]


async def visible_projects(session: AsyncSession, principal: Principal) -> list[Project]:
    statement = select(Project).join(ProjectMember).where(ProjectMember.user_id == principal.id)
    return list((await session.execute(statement)).scalars().unique())


async def create_project(session: AsyncSession, principal: Principal, name: str, path: str, description: str) -> Project:
    if principal.desktop and await session.get(User, principal.id) is None:
        session.add(User(id=principal.id, username=principal.username, email=principal.email,
                         display_name=principal.display_name, password_hash="!desktop-capability-only",
                         role=UserRole.ADMIN))
        await session.flush()
    root = Path(path).expanduser().resolve()
    existing = (await session.execute(select(Project).where(Project.path == str(root)))).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(409, "This project path is already registered")
    project = Project(id=str(uuid.uuid4()), name=name, path=str(root), description=description)
    session.add(project)
    await session.flush()
    session.add(ProjectMember(project_id=project.id, user_id=principal.id, role=ProjectRole.OWNER))
    await session.flush()
    return project


async def project_payload(session: AsyncSession, project: Project) -> dict:
    members = (await session.execute(select(User.username, ProjectMember.role).join(
        ProjectMember, ProjectMember.user_id == User.id).where(ProjectMember.project_id == project.id))).all()
    return {"id": project.id, "name": project.name, "path": project.path, "description": project.description,
            "created_at": project.created_at, "updated_at": project.updated_at,
            "owner": next((name for name, role in members if role == ProjectRole.OWNER), ""),
            "collaborators": [name for name, role in members if role != ProjectRole.OWNER]}
