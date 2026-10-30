"""Network probes for explicitly requested external integrations."""

from __future__ import annotations

import asyncio
import base64
import os
import shutil
from pathlib import Path

from .settings_models import ModelConfig


def _obsidian(config: ModelConfig) -> tuple[bool, str]:
    vault = Path(config.obsidian_vault_path).expanduser()
    if not vault.exists():
        return False, "Vault 路径不存在"
    if not vault.is_dir():
        return False, "Vault 路径不是目录"
    return True, f"Vault 可访问: {vault}"


async def _gemini(config: ModelConfig) -> tuple[bool, str]:
    from ..agent import Message, model_router

    provider = model_router.get_provider_by_name("gemini")
    if not provider:
        return False, "Gemini provider 未注册，请先保存模型配置"
    response = await provider.chat([Message(role="user", content="Reply with OK only.")])
    return True, f"Connected to {response.model}"


async def _modal(config: ModelConfig) -> tuple[bool, str]:
    executable = shutil.which("modal")
    if not executable:
        return False, "Modal CLI 未安装，当前环境无法执行 Modal 实验"
    env = os.environ.copy()
    env.update({
        "MODAL_TOKEN_ID": config.modal_token_id,
        "MODAL_TOKEN_SECRET": config.modal_token_secret,
    })
    for arguments in (("app", "list", "--json"), ("volume", "list", "--json")):
        process = await asyncio.create_subprocess_exec(
            executable, *arguments, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, env=env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=20)
        except asyncio.TimeoutError:
            process.kill()
            await process.communicate()
            return False, f"Modal {' '.join(arguments[:2])} 连接测试超时"
        output = (stdout or stderr).decode("utf-8", errors="replace").strip()
        if process.returncode != 0:
            return False, output[:500] or f"Modal {' '.join(arguments[:2])} failed"
    return True, "Modal auth, app control, and persistent volume access verified"


async def _patent(client: object, config: ModelConfig) -> tuple[bool, str, object]:
    if config.serpapi_api_key:
        response = await client.get(
            "https://serpapi.com/account.json",
            params={"api_key": config.serpapi_api_key},
        )
        if response.is_success:
            return True, "SerpAPI Google Patents access verified", response
    else:
        auth = base64.b64encode(
            f"{config.epo_ops_key}:{config.epo_ops_secret}".encode("utf-8")
        ).decode("ascii")
        response = await client.post(
            "https://ops.epo.org/3.2/auth/accesstoken",
            headers={"Authorization": f"Basic {auth}"},
            data={"grant_type": "client_credentials"},
        )
        if response.is_success:
            return True, "EPO OPS patent-search access verified", response
    return False, "", response


async def _http_probe(service: str, config: ModelConfig) -> tuple[bool, str]:
    import httpx

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        if service == "gpt_image":
            from ..agent import _normalize_openai_base
            base = _normalize_openai_base(config.gpt_image_base_url or "https://api.openai.com/v1", "/v1")
            response = await client.get(f"{base}/models", headers={"Authorization": f"Bearer {config.gpt_image_api_key or config.openai_api_key}"})
        elif service == "nano_banana":
            response = await client.get("https://generativelanguage.googleapis.com/v1beta/models", params={"key": config.nano_banana_api_key})
        elif service == "exa":
            response = await client.post("https://api.exa.ai/search", headers={"x-api-key": config.exa_api_key, "Content-Type": "application/json"}, json={"query": "MERAK connection test", "numResults": 1})
        elif service == "zotero":
            response = await client.get(f"https://api.zotero.org/users/{config.zotero_user_id}/items", headers={"Zotero-API-Key": config.zotero_api_key}, params={"limit": 1})
        elif service == "vastai":
            headers = {"Accept": "application/json", "Authorization": f"Bearer {config.vastai_api_key}"}
            response = await client.get("https://console.vast.ai/api/v0/users/current/", headers=headers)
            if response.is_success:
                response = await client.post("https://console.vast.ai/api/v0/bundles/", headers=headers, json={"verified": {"eq": True}, "rentable": {"eq": True}, "num_gpus": {"gte": 1}, "limit": 1})
                if response.is_success:
                    return True, f"Vast.ai auth and offer search verified ({len(response.json().get('offers', []))} sampled offer(s))"
        elif service == "patent":
            success, message, response = await _patent(client, config)
            if success:
                return success, message
        else:
            return False, f"Unsupported integration: {service}"
    if response.is_success:
        return True, f"连接成功（HTTP {response.status_code}）"
    detail = response.text.strip().replace("\n", " ")[:300]
    return False, f"HTTP {response.status_code}: {detail or 'connection rejected'}"


async def test_integration_connection(
    service: str,
    config: ModelConfig,
) -> tuple[bool, str]:
    if service == "obsidian":
        return _obsidian(config)
    if service == "gemini":
        return await _gemini(config)
    if service == "modal":
        return await _modal(config)
    return await _http_probe(service, config)
