"""
Merak Server — 主入口

生产级科研工作流 IDE 后端
- REST API: 项目管理、实验管理、文件操作
- WebSocket: 终端 PTY、SSH 转发、实验日志流
- SSH: asyncssh 连接池管理
"""

# Environment loading must happen before importing ``server.config`` and API
# modules that construct settings-backed singletons.
# ruff: noqa: E402

import sys
from pathlib import Path as _Path

from dotenv import load_dotenv


def _configure_utf8_standard_streams() -> None:
    """Keep Windows console code pages from crashing workflow logging."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="backslashreplace")
            except (OSError, ValueError):
                pass


_configure_utf8_standard_streams()

# 加载 .env 文件中所有环境变量（EXA_API_KEY, S2_API_KEY 等非 pydantic 管理的变量）
_env_file = _Path(__file__).parent.parent / ".env"
if _env_file.exists():
    load_dotenv(str(_env_file), override=False)

# 注意：不再设置 WindowsSelectorEventLoopPolicy

from contextlib import asynccontextmanager
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import structlog

from .config import settings
from .api import auth, projects, experiments, files, merak_skills
from .api import ssh as ssh_api
from .api import paper as paper_api
from .api import admin as admin_api
from .api import chat as chat_api
from .api import workflow as workflow_api
from .api import settings as settings_api
from .api import overleaf as overleaf_api
from .api import notification as notify_api
from .api import meta_optimize as meta_api
from .ws.router import ws_router
from .services.ssh_manager import ssh_manager
from .services.experiment_runner import experiment_scheduler
from .services.log_streamer import log_stream_manager
from .services.skill_registry import skill_registry
from .services.merak_bridge import merak_bridge
from .services.audit import audit_logger
from .services.workflow_recovery import workflow_recovery_watchdog
from .services.overleaf_sync import overleaf_sync
from .services.workflow_event_journal import workflow_event_journal
from .workflows.engine import workflow_engine

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # Uvicorn CLI arguments own the actual bind address. These settings may
    # differ when the app is launched with ``--host``/``--port``, so avoid
    # printing them as if they described the listening socket; Uvicorn logs
    # the authoritative address immediately after startup.
    logger.info("Merak Server starting", version="0.1.1")
    try:
        await ssh_manager.start()
        # 启动实验调度器
        await experiment_scheduler.start()
        # 初始化 MERAK 技能注册表
        from pathlib import Path
        skills_path = settings.merak_skills_path
        # 如果是相对路径，基于项目根目录解析
        if skills_path and not Path(skills_path).is_absolute():
            skills_path = str((Path(__file__).parent.parent / skills_path).resolve())
        if not skills_path or not Path(skills_path).exists():
            # Only fall back to the skills bundled with this MERAK installation.
            candidates = [Path(__file__).parent.parent / "merak-skills"]
            for candidate in candidates:
                if candidate.exists() and any(candidate.iterdir()):
                    skills_path = str(candidate.resolve())
                    break
        if skills_path and Path(skills_path).exists():
            # Publish the resolved absolute root for skill-local helper resolvers.
            # Child processes inherit this value regardless of their project cwd.
            import os
            skills_path = str(Path(skills_path).resolve())
            os.environ["MERAK_SKILLS_PATH"] = skills_path
            count = skill_registry.scan_directory(skills_path)
            logger.info("Skills loaded", path=skills_path, count=count)
        else:
            logger.warning("No MERAK skills directory found. Set MERAK_IDE_MERAK_SKILLS_PATH in .env")
        # 启动 MERAK 执行引擎
        await merak_bridge.start()
        # 加载用户保存的模型配置（无条件加载，覆盖所有 provider）
        from .api.settings import load_settings, apply_model_config
        user_cfg = load_settings()
        apply_model_config(user_cfg.models)
        logger.info("Model config applied from user settings")
        from .agent.tools import register_all_tools
        register_all_tools()
        logger.info("Agent tools registered for chat and workflow")
        # 启动审计日志
        await audit_logger.start()
        # 初始化数据库
        from .db.engine import init_db
        await init_db()
        await overleaf_sync.restore_auto_sync()
        # Resume due platform/network checkpoints only after every runtime service
        # is initialized. The watchdog schedules the normal engine; gates still own
        # scientific acceptance.
        await workflow_recovery_watchdog.start()
        yield
    finally:
        # Startup may fail after only some services were initialized. Every
        # stop implementation is idempotent, and one cleanup failure must not
        # prevent the remaining background tasks/processes from being closed.
        logger.info("Merak Server shutting down")
        shutdown_steps = (
            ("workflow recovery watchdog", workflow_recovery_watchdog.stop),
            ("active workflows", workflow_engine.shutdown),
            ("workflow event journal", workflow_event_journal.close),
            ("Overleaf sync", overleaf_sync.shutdown),
            ("audit logger", audit_logger.stop),
            ("log streams", log_stream_manager.stop_all),
            ("MERAK bridge", merak_bridge.stop),
            ("experiment scheduler", experiment_scheduler.stop),
            ("SSH manager", ssh_manager.stop),
        )
        for service_name, stop_service in shutdown_steps:
            try:
                await stop_service()
            except Exception as exc:
                logger.error(
                    "Service shutdown failed",
                    service=service_name,
                    error=str(exc),
                )


app = FastAPI(
    title="Merak Server",
    description="Production-grade Research Workflow IDE Backend",
    version="0.1.1",
    lifespan=lifespan,
)

from .services.api_access import ApiAccessMiddleware
app.add_middleware(ApiAccessMiddleware)

# CORS: local Electron/file origin plus configured loopback/deployment origins.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=settings.cors_origin_regex or None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# REST API 路由
app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(projects.router, prefix="/api/projects", tags=["Projects"])
app.include_router(experiments.router, prefix="/api/experiments", tags=["Experiments"])
app.include_router(files.router, prefix="/api/files", tags=["Files"])
app.include_router(merak_skills.router, prefix="/api/merak", tags=["MERAK Skills"])
app.include_router(ssh_api.router, prefix="/api/ssh", tags=["SSH"])
app.include_router(paper_api.router, prefix="/api/paper", tags=["Paper"])
app.include_router(admin_api.router, prefix="/api/admin", tags=["Admin"])
app.include_router(chat_api.router, prefix="/api/chat", tags=["Chat & Agent"])
app.include_router(workflow_api.router, prefix="/api/workflow", tags=["Workflow"])
app.include_router(settings_api.router, prefix="/api/settings", tags=["User Settings"])

app.include_router(overleaf_api.router, tags=["Overleaf Sync"])
app.include_router(notify_api.router, tags=["Notifications"])
app.include_router(meta_api.router, tags=["Meta-Optimize"])

# WebSocket 路由
app.include_router(ws_router)


@app.get("/api/health")
async def health_check():
    """健康检查"""
    import hashlib
    import os

    owner_token = os.environ.get("MERAK_DESKTOP_OWNER_TOKEN", "")
    owner_pid_text = os.environ.get("MERAK_DESKTOP_OWNER_PID", "")
    try:
        owner_pid = int(owner_pid_text) if owner_pid_text else 0
    except ValueError:
        owner_pid = 0
    installation_key = str(_Path(__file__).parent.parent.resolve()).replace(
        "\\", "/"
    ).casefold()
    installation_digest = os.environ.get("MERAK_INSTALLATION_SHA256", "")
    if len(installation_digest) != 64 or any(
        character not in "0123456789abcdef" for character in installation_digest
    ):
        installation_digest = hashlib.sha256(
            installation_key.encode("utf-8")
        ).hexdigest()

    return {
        "status": "healthy",
        "version": "0.1.1",
        "service": "merak-ide-server",
        # Loopback desktop ownership marker. It prevents a new renderer from
        # silently attaching to a stale backend process with old in-memory runs.
        "desktop_owner_token_sha256": (
            hashlib.sha256(owner_token.encode("utf-8")).hexdigest()
            if owner_token
            else ""
        ),
        # PIDs and the installation digest let a new desktop distinguish a
        # live second instance from an orphaned backend. No ownership secret
        # or user path is exposed.
        "desktop_owner_pid": owner_pid,
        "backend_pid": os.getpid(),
        "installation_sha256": installation_digest,
    }


@app.post("/api/desktop/prepare-shutdown")
async def prepare_desktop_shutdown(
    x_merak_owner_token: str = Header(default=""),
):
    """Persist active runtime state before Windows terminates the process tree."""
    import hmac
    import os

    expected = os.environ.get("MERAK_DESKTOP_OWNER_TOKEN", "")
    if (
        not expected
        or not x_merak_owner_token
        or not hmac.compare_digest(x_merak_owner_token, expected)
    ):
        raise HTTPException(status_code=403, detail="Desktop ownership token mismatch")
    await workflow_recovery_watchdog.stop()
    await workflow_engine.shutdown()
    await merak_bridge.stop()
    await experiment_scheduler.stop()
    return {"status": "prepared"}
