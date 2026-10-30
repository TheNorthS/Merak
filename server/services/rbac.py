"""
RBAC 权限系统 — 基于角色的访问控制

角色层级：
- Admin: 全局管理员（管理用户、组织、全部资源）
- Researcher: 研究员（管理自己的项目、实验、SSH）
- Viewer: 查看者（只读访问被分享的资源）

资源级权限：
- Project: owner / editor / viewer
- Document: owner / editor / viewer
- SSHServer: owner / shared（组织内）

权限检查中间件通过 FastAPI Depends 注入。
"""

from enum import Enum

from fastapi import Depends, HTTPException, status, Request
from ..db.engine import get_db
from .access_identity import authenticate_connection
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.models import UserRole, ProjectRole


class Permission(str, Enum):
    """系统级权限"""
    # 用户管理
    USERS_LIST = "users.list"
    USERS_CREATE = "users.create"
    USERS_DELETE = "users.delete"
    USERS_EDIT_ROLE = "users.edit_role"

    # 组织管理
    ORG_CREATE = "org.create"
    ORG_DELETE = "org.delete"
    ORG_MANAGE_MEMBERS = "org.manage_members"

    # 项目
    PROJECT_CREATE = "project.create"
    PROJECT_DELETE = "project.delete"
    PROJECT_EDIT = "project.edit"
    PROJECT_VIEW = "project.view"

    # SSH
    SSH_CREATE = "ssh.create"
    SSH_CONNECT = "ssh.connect"
    SSH_DELETE = "ssh.delete"

    # 实验
    EXPERIMENT_CREATE = "experiment.create"
    EXPERIMENT_CANCEL = "experiment.cancel"
    EXPERIMENT_VIEW = "experiment.view"

    # MERAK 技能
    MERAK_EXECUTE = "merak.execute"
    MERAK_EXECUTE_SUBMISSION = "merak.execute_submission"  # assurance=submission 需要更高权限

    # 系统
    SYSTEM_METRICS = "system.metrics"
    SYSTEM_AUDIT = "system.audit"
    SYSTEM_SETTINGS = "system.settings"


# 角色 → 权限映射
ROLE_PERMISSIONS: dict[UserRole, set[Permission]] = {
    UserRole.ADMIN: set(Permission),  # 管理员拥有全部权限

    UserRole.RESEARCHER: {
        Permission.PROJECT_CREATE,
        Permission.PROJECT_EDIT,
        Permission.PROJECT_VIEW,
        Permission.PROJECT_DELETE,
        Permission.SSH_CREATE,
        Permission.SSH_CONNECT,
        Permission.SSH_DELETE,
        Permission.EXPERIMENT_CREATE,
        Permission.EXPERIMENT_CANCEL,
        Permission.EXPERIMENT_VIEW,
        Permission.MERAK_EXECUTE,
        Permission.MERAK_EXECUTE_SUBMISSION,
    },

    UserRole.VIEWER: {
        Permission.PROJECT_VIEW,
        Permission.EXPERIMENT_VIEW,
    },
}


def has_permission(role: UserRole, permission: Permission) -> bool:
    """检查角色是否有指定权限"""
    allowed = ROLE_PERMISSIONS.get(role, set())
    return permission in allowed


def require_permission(permission: Permission):
    """
    FastAPI 依赖：要求当前用户有指定权限

    Usage:
        @router.get("/admin/users")
        async def list_users(
            user = Depends(get_current_user),
            _ = Depends(require_permission(Permission.USERS_LIST)),
        ):
            ...
    """
    async def _check(user=Depends(_get_current_user_with_role)):
        user_role = UserRole(user.get("role", "viewer"))
        if not has_permission(user_role, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: {permission.value}",
            )
        return user
    return _check


def require_project_role(min_role: ProjectRole):
    """
    FastAPI 依赖：要求当前用户对项目有指定最低角色

    Usage:
        @router.post("/projects/{project_id}/experiments")
        async def create_experiment(
            project_id: str,
            user = Depends(get_current_user),
            _ = Depends(require_project_role(ProjectRole.EDITOR)),
        ):
            ...
    """
    role_hierarchy = {ProjectRole.OWNER: 3, ProjectRole.EDITOR: 2, ProjectRole.VIEWER: 1}

    async def _check(project_id: str, user=Depends(_get_current_user_with_role), db=Depends(get_db)):
        # Admin 有全部项目权限
        if UserRole(user.get("role")) == UserRole.ADMIN:
            return user

        if not await ResourceChecker.can_access_project(user["id"], project_id, db, min_role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires at least {min_role.value} role on this project",
            )
        return user
    return _check


async def _get_current_user_with_role(request: Request):
    """Use the authenticated database/capability identity, never an assumed role."""
    principal = getattr(request.state, "principal", None) or await authenticate_connection(request)
    if principal is None:
        raise HTTPException(401, "Authentication required")
    return {"id": principal.id, "username": principal.username, "role": principal.role}


# ==================== 资源级权限检查 ====================

class ResourceChecker:
    """资源级权限检查器"""

    @staticmethod
    async def can_access_project(user_id: str, project_id: str, db: AsyncSession, min_role: ProjectRole = ProjectRole.VIEWER) -> bool:
        """检查用户是否可以访问项目"""
        from sqlalchemy import select
        from ..models.models import ProjectMember

        role_hierarchy = {ProjectRole.OWNER: 3, ProjectRole.EDITOR: 2, ProjectRole.VIEWER: 1}

        result = await db.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
            )
        )
        member = result.scalar_one_or_none()
        if not member:
            return False
        return role_hierarchy.get(member.role, 0) >= role_hierarchy.get(min_role, 0)

    @staticmethod
    async def can_access_ssh(user_id: str, server_id: str, db: AsyncSession) -> bool:
        """检查用户是否可以使用 SSH 服务器"""
        from sqlalchemy import select
        from ..models.models import SSHServer, OrgMember

        result = await db.execute(
            select(SSHServer).where(SSHServer.id == server_id)
        )
        server = result.scalar_one_or_none()
        if not server:
            return False

        # 是服务器所有者
        if server.owner_id == user_id:
            return True

        # 共享给组织且用户是组织成员
        if server.is_shared and server.org_id:
            member_result = await db.execute(
                select(OrgMember).where(
                    OrgMember.org_id == server.org_id,
                    OrgMember.user_id == user_id,
                )
            )
            return member_result.scalar_one_or_none() is not None

        return False


resource_checker = ResourceChecker()
