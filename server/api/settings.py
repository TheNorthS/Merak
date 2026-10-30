"""User settings API with database and JSON durability."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any, Optional
import asyncio
import json
from pathlib import Path

import structlog

from ..services.connection_verification import connection_verification_store
from ..services import settings_repository
from ..services.settings_models import (
    INTEGRATION_LABELS,
    MODEL_PROVIDER_ALIASES,
    MODEL_PROVIDER_FIELDS,
    ModelConfig,
    UserSettings,
)
from ..services.integration_probes import (
    test_integration_connection as _test_integration_connection,
)

from ..services.settings_visibility import public_model_config, public_settings
from ..services.integration_environment import apply_integration_environment
from ..services.settings_storage import settings_storage_path

logger = structlog.get_logger()
router = APIRouter()

# 配置文件路径（兼容 fallback）
CONFIG_FILE = settings_storage_path("user_settings.json")





def model_verification_payload(config: ModelConfig, provider_name: str) -> dict[str, str]:
    fields = MODEL_PROVIDER_FIELDS.get(provider_name, ())
    if provider_name == "openai-api":
        fields = (*fields, "openai_transport")
    return {field: str(getattr(config, field, "") or "") for field in fields}


def integration_verification_payload(config: ModelConfig, service: str) -> dict[str, str]:
    payloads = {
        "gemini": {
            "api_key": config.gemini_api_key,
            "base_url": config.gemini_base_url,
            "model": config.gemini_model,
        },
        "gpt_image": {
            "api_key": config.gpt_image_api_key or config.openai_api_key,
            "base_url": config.gpt_image_base_url,
        },
        "nano_banana": {"api_key": config.nano_banana_api_key},
        "exa": {"api_key": config.exa_api_key},
        "zotero": {"api_key": config.zotero_api_key, "user_id": config.zotero_user_id},
        "obsidian": {"vault_path": config.obsidian_vault_path},
        "vastai": {"api_key": config.vastai_api_key},
        "modal": {"token_id": config.modal_token_id, "token_secret": config.modal_token_secret},
        "patent": {
            "serpapi_api_key": config.serpapi_api_key,
            "epo_ops_key": config.epo_ops_key,
            "epo_ops_secret": config.epo_ops_secret,
        },
    }
    return {key: str(value or "") for key, value in payloads.get(service, {}).items()}


def integration_is_configured(config: ModelConfig, service: str) -> bool:
    if service == "patent":
        return bool(config.serpapi_api_key or (config.epo_ops_key and config.epo_ops_secret))
    required_values = {
        "gemini": (config.gemini_api_key,),
        "gpt_image": (config.gpt_image_api_key or config.openai_api_key,),
        "nano_banana": (config.nano_banana_api_key,),
        "exa": (config.exa_api_key,),
        "zotero": (config.zotero_api_key, config.zotero_user_id),
        "obsidian": (config.obsidian_vault_path,),
        "vastai": (config.vastai_api_key,),
        "modal": (config.modal_token_id, config.modal_token_secret),
    }.get(service, ())
    return bool(required_values) and all(bool(value) for value in required_values)


def integration_status(config: ModelConfig, service: str) -> dict[str, Any]:
    configured = integration_is_configured(config, service)
    status = connection_verification_store.status(
        "integration", service, integration_verification_payload(config, service)
    )
    return {
        "configured": configured,
        "label": INTEGRATION_LABELS.get(service, service),
        **status,
        "verified": configured and bool(status["verified"]),
    }


def is_integration_verified(service: str) -> bool:
    config = load_settings().models
    return bool(integration_status(config, service)["verified"])


def is_model_provider_verified(provider_name: str) -> bool:
    config = load_settings().models
    payload = model_verification_payload(config, provider_name)
    return bool(payload) and connection_verification_store.is_verified("model", provider_name, payload)




def load_settings() -> UserSettings:
    return settings_repository.load(CONFIG_FILE)


def save_settings(settings: UserSettings):
    settings_repository.save(CONFIG_FILE, settings)


def apply_model_config(config: ModelConfig):
    """将用户配置应用到 model_router（直接从 DB 配置注册，不经过环境变量）。

    非模型集成服务（搜索、画图、GPU 云、Zotero 等）仍需写 env var 供各自 SDK 读取。
    模型 provider 直接从 config 对象注册，避免系统环境变量污染注册列表。
    """
    import os

    apply_integration_environment(config)

    # ===== 模型 Provider — 直接从 config 注册，跳过 env var =====
    from ..agent import model_router, ModelRole, init_models_from_config
    previous_strategy = dict(model_router._strategy)
    model_router._providers.clear()
    model_router._strategy = previous_strategy or {
        ModelRole.EXECUTOR: "openai-api",
        ModelRole.REVIEWER: "openai-api",
        ModelRole.SEARCH: "gemini",
        ModelRole.FIGURE: "openai-api",
        ModelRole.GENERAL: "openai-api",
    }
    init_models_from_config(config)

    logger.info("Model config applied from user settings",
                providers=list(model_router._providers.keys()),
                executor=model_router._strategy.get(ModelRole.EXECUTOR))


# ==================== API 端点 ====================

@router.get("/", response_model=UserSettings)
async def get_settings():
    """获取用户设置"""
    settings = load_settings()
    return public_settings(settings)


@router.get("/models", response_model=ModelConfig)
async def get_model_config():
    """获取模型配置（key 部分脱敏）"""
    return public_model_config(load_settings().models)


@router.put("/models")
async def update_model_config(config: ModelConfig):
    """更新模型配置（用户在设置界面填入 key 和 url）"""
    settings = load_settings()

    # Keep masked secrets while carrying every typed model option through the save.
    previous = settings.models.model_dump()
    values = config.model_dump()
    for field, value in values.items():
        if isinstance(value, str) and "****" in value:
            values[field] = previous[field]
    settings.models = ModelConfig.model_validate(values)

    save_settings(settings)
    apply_model_config(settings.models)

    return {"status": "saved", "message": "Model configuration updated and applied"}



def _is_transient_connection_error(error: Exception) -> bool:
    message = str(error).lower()
    return any(marker in message for marker in (
        "429", "500", "502", "503", "504", "timeout", "timed out",
        "temporarily unavailable", "service unavailable", "connection reset",
        "connection closed", "incomplete chunk", "no available accounts",
    ))

@router.post("/models/test")
async def test_model_connection(provider: str):
    """Test a saved model configuration and bind success to its fingerprint."""
    from ..agent import Message, model_router

    provider_name = MODEL_PROVIDER_ALIASES.get(provider, provider)
    if provider_name not in MODEL_PROVIDER_FIELDS:
        return {"success": False, "error": f"Unknown provider: {provider}"}

    config = load_settings().models
    payload = model_verification_payload(config, provider_name)
    model_provider = model_router.get_provider_by_name(provider_name)
    if not model_provider:
        message = f"Provider {provider_name} not registered. Save a complete API configuration first."
        verification = connection_verification_store.record(
            "model", provider_name, payload, False, message
        )
        return {"success": False, "error": message, "verification": verification}

    from ..agent import _normalize_openai_base

    base_url = getattr(model_provider, "base_url", None)
    model_name = getattr(model_provider, "model", "?")
    try:
        if provider_name == "claude-api":
            actual_url = ((base_url.rstrip("/") if base_url else "https://api.anthropic.com") + "/v1/messages")
        else:
            normalized = _normalize_openai_base(
                base_url, getattr(model_provider, "DEFAULT_BASE_PATH", "/v1")
            ) if base_url else None
            actual_url = (normalized or "") + "/chat/completions" if normalized else "(default)"
    except Exception:
        actual_url = str(base_url)

    last_error: Exception | None = None
    attempts = 0
    for attempts in range(1, 4):
        try:
            response = await asyncio.wait_for(
                model_provider.chat([Message(role="user", content="Reply with OK only.")]),
                timeout=30,
            )
            message = f"Connected to {response.model or model_name}"
            verification = connection_verification_store.record(
                "model", provider_name, payload, True, message
            )
            if provider_name == "gemini":
                connection_verification_store.record(
                    "integration", "gemini", integration_verification_payload(config, "gemini"), True, message
                )
            return {
                "success": True,
                "response": response.content[:100],
                "model": response.model,
                "url": actual_url,
                "attempts": attempts,
                "verification": verification,
            }
        except Exception as exc:
            last_error = exc
            if attempts >= 3 or not _is_transient_connection_error(exc):
                break
            await asyncio.sleep(0.75 * (2 ** (attempts - 1)))

    message = f"{last_error}\n\n[诊断] URL: {actual_url} | Model: {model_name} | Attempts: {attempts}"
    verification = connection_verification_store.record(
        "model", provider_name, payload, False, message
    )
    return {
        "success": False,
        "error": message,
        "attempts": attempts,
        "verification": verification,
    }




@router.post("/integrations/{service}/test")
async def test_integration_connection(service: str):
    if service not in INTEGRATION_LABELS:
        raise HTTPException(status_code=404, detail=f"Unknown integration: {service}")

    config = load_settings().models
    payload = integration_verification_payload(config, service)
    if not integration_is_configured(config, service):
        message = "配置不完整，请填写并保存必需字段"
        verification = connection_verification_store.record(
            "integration", service, payload, False, message
        )
        return {"success": False, "error": message, "verification": verification}

    try:
        success, message = await _test_integration_connection(service, config)
    except Exception as exc:
        success, message = False, str(exc)

    verification = connection_verification_store.record(
        "integration", service, payload, success, message
    )
    return {
        "success": success,
        "message": message if success else "",
        "error": "" if success else message,
        "verification": verification,
    }


# ==================== 模型策略切换 ====================

class StrategyUpdate(BaseModel):
    """模型策略更新"""
    executor: Optional[str] = None    # openai-api | claude-api | deepseek | qwen | ...
    reviewer: Optional[str] = None    # openai-api | claude-api | glm | qwen | ...
    search: Optional[str] = None
    figure: Optional[str] = None


def _provider_verification_statuses(providers: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    config = load_settings().models
    statuses: dict[str, dict[str, Any]] = {}
    for provider in providers:
        name = provider["name"]
        payload = model_verification_payload(config, name)
        status = connection_verification_store.status("model", name, payload)
        statuses[name] = {
            "configured": bool(payload),
            "model": provider.get("model", ""),
            **status,
        }
    return statuses


def _independent_reviewer_status() -> dict[str, Any]:
    """Describe the API route used for context-isolated review.

    Connection verification remains bound to the selected provider's saved
    configuration fingerprint. Reviewer independence is supplied by a fresh,
    read-only session and does not require a different concrete model.
    """
    from ..agent import ModelRole, model_router

    empty_verification = {
        "tested": False,
        "verified": False,
        "stale": False,
        "tested_at": None,
        "message": "尚未配置可用的审查模型 API",
    }
    try:
        executor_provider, _executor, executor_model = (
            model_router.get_provider_route(ModelRole.EXECUTOR)
        )
        reviewer_provider, _reviewer, reviewer_model = (
            model_router.get_isolated_provider_route(
                ModelRole.REVIEWER,
            )
        )
    except RuntimeError:
        return {
            "configured": False,
            "provider": "",
            "model": "",
            "executor_provider": "",
            "executor_model": "",
            "isolated": False,
            "session_isolated": False,
            "same_model_allowed": True,
            "same_model": False,
            "ready": False,
            **empty_verification,
        }

    configured = bool(
        reviewer_provider
        and model_router.get_provider_by_name(reviewer_provider)
    )
    session_isolated = bool(configured and reviewer_model)
    same_model = bool(
        reviewer_model
        and executor_model
        and reviewer_model.casefold() == executor_model.casefold()
    )
    if configured:
        config = load_settings().models
        payload = model_verification_payload(config, reviewer_provider)
        verification = connection_verification_store.status(
            "model",
            reviewer_provider,
            payload,
        )
    else:
        verification = empty_verification

    connection_verified = bool(verification.get("verified"))
    return {
        "configured": configured,
        "provider": reviewer_provider,
        "model": reviewer_model,
        "executor_provider": executor_provider,
        "executor_model": executor_model,
        # ``isolated`` is retained for older clients and now denotes session,
        # rather than model-identity, isolation.
        "isolated": session_isolated,
        "session_isolated": session_isolated,
        "same_model_allowed": True,
        "same_model": same_model,
        "ready": session_isolated and connection_verified,
        **verification,
    }


@router.get("/models/strategy")
async def get_strategy():
    """Return configured providers and the tested subset that may be selected."""
    from ..agent import ModelRole, model_router

    providers = model_router.list_providers()
    provider_status = _provider_verification_statuses(providers)
    selectable = [
        provider["name"] for provider in providers
        if provider_status.get(provider["name"], {}).get("verified")
    ]
    selectable_set = set(selectable)
    defaults = {
        ModelRole.EXECUTOR: "openai-api",
        ModelRole.REVIEWER: "openai-api",
        ModelRole.SEARCH: "gemini",
        ModelRole.FIGURE: "openai-api",
        ModelRole.GENERAL: "openai-api",
    }
    for role, default_provider in defaults.items():
        current = model_router._strategy.get(role)
        if current in selectable_set:
            continue
        fallback = default_provider if default_provider in selectable_set else (selectable[0] if selectable else None)
        if fallback:
            model_router.set_strategy(role, fallback)

    return {
        "strategy": {
            role: provider if provider in selectable_set else ""
            for role, provider in model_router.get_strategy().items()
        },
        "available_providers": [provider["name"] for provider in providers],
        "selectable_providers": selectable,
        "provider_models": {provider["name"]: provider["model"] for provider in providers},
        "provider_contexts": {provider["name"]: provider["context"] for provider in providers},
        "provider_status": provider_status,
        "independent_reviewer": _independent_reviewer_status(),
    }


@router.post("/models/reviewer/test")
async def test_independent_reviewer_connection():
    """Test the independent Reviewer through its configured model API."""
    status = _independent_reviewer_status()
    provider_name = str(status.get("provider") or "")
    if not status.get("configured") or not provider_name:
        return {
            "success": False,
            "error": "尚未配置可用的审查模型 API",
            "status": status,
        }
    result = await test_model_connection(provider=provider_name)
    refreshed = _independent_reviewer_status()
    if result.get("success"):
        suffix = "（与 Executor 同模型，使用独立冷启动会话）" if refreshed.get("same_model") else "（独立冷启动会话）"
        message = f"审稿 API 已连接：{refreshed.get('model') or provider_name}{suffix}"
        return {
            **result,
            "message": message,
            "model": refreshed.get("model") or result.get("model", ""),
            "status": refreshed,
        }
    return {**result, "status": refreshed}


@router.put("/models/strategy")
async def update_strategy(update: StrategyUpdate):
    """Switch model roles only to providers with a successful current test."""
    from ..agent import ModelRole, model_router

    requested = {
        ModelRole.EXECUTOR: update.executor,
        ModelRole.REVIEWER: update.reviewer,
        ModelRole.SEARCH: update.search,
        ModelRole.FIGURE: update.figure,
    }
    for role, provider_name in requested.items():
        if not provider_name:
            continue
        if not model_router.get_provider_by_name(provider_name):
            raise HTTPException(status_code=409, detail=f"Provider '{provider_name}' is not configured")
        if not is_model_provider_verified(provider_name):
            raise HTTPException(status_code=409, detail=f"Provider '{provider_name}' must pass a connection test first")
        model_router.set_strategy(role, provider_name)

    return {"status": "updated", "strategy": model_router.get_strategy()}


@router.get("/models/providers")
async def list_providers():
    """List providers together with connection-verification state."""
    from ..agent import model_router

    providers = model_router.list_providers()
    return {
        "providers": providers,
        "strategy": model_router.get_strategy(),
        "provider_status": _provider_verification_statuses(providers),
    }


@router.get("/integration-status")
async def get_integration_status():
    """Return configured and verified state for every external integration."""
    config = load_settings().models
    return {
        service: integration_status(config, service)
        for service in INTEGRATION_LABELS
    }
