"""Merak Server 配置"""

from pydantic import Field, field_validator, ValidationInfo
import secrets
import os
from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    """应用配置（从环境变量 / .env 加载）"""

    # 服务器
    host: str = "127.0.0.1"
    port: int = 8011
    debug: bool = True

    # Desktop/file renderer plus loopback Vite. Deployments that expose the
    # API remotely must opt in to their exact web origin through the env file.
    cors_origins: List[str] = Field(default_factory=lambda: list(dict.fromkeys([
        "null", "http://127.0.0.1:5178", "http://localhost:5178",
        os.environ.get("VITE_DEV_SERVER_URL", "http://127.0.0.1:5178"),
    ])))
    cors_origin_regex: str = ""

    # 数据库
    database_url: str = "sqlite+aiosqlite:///./merak_ide.db"
    data_dir: str = "."
    workspace_root: str = "./data/projects"
    allow_registration: bool = False

    # JWT 认证
    jwt_secret_key: str = Field(default_factory=lambda: secrets.token_urlsafe(48))
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440  # 24 hours

    # SSH 密钥加密密钥（Fernet）
    ssh_encryption_key: str = ""

    # MERAK Skills（本项目内置）
    merak_skills_path: str = "./merak-skills"


    # 文件上传限制
    max_upload_size_mb: int = 100

    @field_validator("jwt_secret_key")
    @classmethod
    def private_signing_key(cls, value: str, info: ValidationInfo) -> str:
        if value in {"merak-ide-dev-secret-change-in-production", "change-this-to-a-random-secret-in-production"}:
            if info.data.get("debug", True):
                return secrets.token_urlsafe(48)
            raise ValueError("Replace the example JWT secret with a private signing key")
        if len(value) < 32:
            if info.data.get("debug", True):
                return secrets.token_urlsafe(48)
            raise ValueError("JWT secret must contain at least 32 characters")
        return value

    model_config = {
        "env_file": ".env",
        "env_prefix": "MERAK_IDE_",
        "case_sensitive": False,
        "extra": "ignore",
        "hide_input_in_errors": True,
    }


settings = Settings()
