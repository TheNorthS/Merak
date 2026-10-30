"""
数据库模型 — SQLAlchemy ORM

所有持久化实体：
- User: 用户账号
- Organization: 组织/团队
- Project: 研究项目
- SSHServer: SSH 服务器配置
- Experiment: 实验记录
- AuditLog: 审计日志
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    String, Integer, Boolean, DateTime, Text, JSON,
    ForeignKey, Index, Enum as SAEnum,
)
from sqlalchemy.orm import DeclarativeBase, relationship, Mapped, mapped_column
import enum


class Base(DeclarativeBase):
    """基类"""


# ==================== 枚举 ====================

class UserRole(str, enum.Enum):
    ADMIN = "admin"
    RESEARCHER = "researcher"
    VIEWER = "viewer"


class ProjectRole(str, enum.Enum):
    OWNER = "owner"
    EDITOR = "editor"
    VIEWER = "viewer"


class ExperimentStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ==================== 模型 ====================

class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(128), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(SAEnum(UserRole), default=UserRole.RESEARCHER)

    # 偏好
    theme: Mapped[str] = mapped_column(String(16), default="dark")
    avatar_color: Mapped[str] = mapped_column(String(7), default="#5c7cfa")

    # 时间
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # 关系
    projects = relationship("ProjectMember", back_populates="user")
    ssh_servers = relationship("SSHServer", back_populates="owner")


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    max_members: Mapped[int] = mapped_column(Integer, default=50)
    max_projects: Mapped[int] = mapped_column(Integer, default=100)

    # 关系
    members = relationship("OrgMember", back_populates="organization")


class OrgMember(Base):
    __tablename__ = "org_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    org_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id"))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    role: Mapped[UserRole] = mapped_column(SAEnum(UserRole), default=UserRole.RESEARCHER)
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    organization = relationship("Organization", back_populates="members")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    path: Mapped[str] = mapped_column(String(512))
    org_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("organizations.id"), nullable=True)

    # MERAK 配置
    merak_effort: Mapped[str] = mapped_column(String(16), default="balanced")
    merak_assurance: Mapped[str] = mapped_column(String(16), default="draft")
    gpu_backend: Mapped[str] = mapped_column(String(16), default="ssh_remote")
    ssh_server_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("ssh_servers.id"), nullable=True)

    # 时间
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系
    members = relationship("ProjectMember", back_populates="project")
    experiments = relationship("ExperimentRecord", back_populates="project")


class ProjectMember(Base):
    __tablename__ = "project_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id"))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    role: Mapped[ProjectRole] = mapped_column(SAEnum(ProjectRole), default=ProjectRole.EDITOR)
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    project = relationship("Project", back_populates="members")
    user = relationship("User", back_populates="projects")


class SSHServer(Base):
    __tablename__ = "ssh_servers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    host: Mapped[str] = mapped_column(String(255))
    port: Mapped[int] = mapped_column(Integer, default=22)
    username: Mapped[str] = mapped_column(String(64))
    auth_method: Mapped[str] = mapped_column(String(16), default="key")  # key | password
    private_key_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    password_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 环境
    conda_env: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    work_dir: Mapped[str] = mapped_column(String(512), default="~")

    # GPU
    gpu_count: Mapped[int] = mapped_column(Integer, default=0)
    gpu_type: Mapped[str] = mapped_column(String(64), default="")

    # 归属
    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    org_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("organizations.id"), nullable=True)
    is_shared: Mapped[bool] = mapped_column(Boolean, default=False)  # 组织内共享

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    owner = relationship("User", back_populates="ssh_servers")


class ExperimentRecord(Base):
    __tablename__ = "experiments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id"))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    status: Mapped[ExperimentStatus] = mapped_column(SAEnum(ExperimentStatus), default=ExperimentStatus.PENDING)

    # 配置
    command_template: Mapped[str] = mapped_column(Text)
    backend: Mapped[str] = mapped_column(String(16))
    server_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    seeds: Mapped[str] = mapped_column(JSON, default="[42]")  # JSON array
    batch_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    config: Mapped[str] = mapped_column(JSON, default="{}")

    # 结果
    metrics: Mapped[str] = mapped_column(JSON, default="{}")
    total_jobs: Mapped[int] = mapped_column(Integer, default=0)
    completed_jobs: Mapped[int] = mapped_column(Integer, default=0)

    # 时间
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    project = relationship("Project", back_populates="experiments")

    __table_args__ = (
        Index("idx_experiments_project", "project_id"),
        Index("idx_experiments_user", "user_id"),
        Index("idx_experiments_status", "status"),
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)  # e.g., "experiment.create", "ssh.connect"
    resource_type: Mapped[str] = mapped_column(String(32))  # project | experiment | document | ssh
    resource_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    details: Mapped[str] = mapped_column(JSON, default="{}")
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    __table_args__ = (
        Index("idx_audit_user_time", "user_id", "timestamp"),
        Index("idx_audit_action", "action", "timestamp"),
    )


class UserSetting(Base):
    """用户配置 — 键值对存储（替代 user_settings.json）"""
    __tablename__ = "user_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True, default="default")
    key: Mapped[str] = mapped_column(String(128))  # e.g. "models.anthropic_api_key"
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_settings_user_key", "user_id", "key", unique=True),
    )
