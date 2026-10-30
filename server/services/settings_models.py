"""Typed user settings and provider/integration field contracts."""

from pydantic import BaseModel, Field
from typing import Literal


class ModelConfig(BaseModel):
    openai_api_key: str = ""
    openai_base_url: str = ""
    openai_model: str = "gpt-4o"
    openai_transport: Literal["stream", "non_stream"] = "stream"
    anthropic_api_key: str = ""
    anthropic_base_url: str = ""
    anthropic_model: str = ""
    deepseek_api_key: str = ""
    deepseek_base_url: str = ""
    deepseek_model: str = "deepseek-chat"
    glm_api_key: str = ""
    glm_base_url: str = ""
    glm_model: str = "glm-4-plus"
    qwen_api_key: str = ""
    qwen_base_url: str = ""
    qwen_model: str = "qwen-max"
    gemini_api_key: str = ""
    gemini_base_url: str = ""
    gemini_model: str = "gemini-2.0-flash"
    gpt_image_api_key: str = ""
    gpt_image_base_url: str = ""
    nano_banana_api_key: str = ""
    exa_api_key: str = ""
    serpapi_api_key: str = ""
    epo_ops_key: str = ""
    epo_ops_secret: str = ""
    vastai_api_key: str = ""
    modal_token_id: str = ""
    modal_token_secret: str = ""
    zotero_api_key: str = ""
    zotero_user_id: str = ""
    obsidian_vault_path: str = ""


class UserSettings(BaseModel):
    models: ModelConfig = Field(default_factory=ModelConfig)
    theme: str = "dark"
    editor_font_size: int = 14
    editor_font_family: str = "JetBrains Mono"
    default_effort: str = "balanced"
    default_assurance: str = "draft"


MODEL_PROVIDER_ALIASES = {
    "openai": "openai-api", "anthropic": "claude-api",
    "deepseek": "deepseek", "glm": "glm", "qwen": "qwen", "gemini": "gemini",
}
MODEL_PROVIDER_FIELDS = {
    "openai-api": ("openai_api_key", "openai_base_url", "openai_model"),
    "claude-api": ("anthropic_api_key", "anthropic_base_url", "anthropic_model"),
    "deepseek": ("deepseek_api_key", "deepseek_base_url", "deepseek_model"),
    "glm": ("glm_api_key", "glm_base_url", "glm_model"),
    "qwen": ("qwen_api_key", "qwen_base_url", "qwen_model"),
    "gemini": ("gemini_api_key", "gemini_base_url", "gemini_model"),
}
INTEGRATION_LABELS = {
    "gemini": "Gemini 搜索增强", "gpt_image": "GPT Image 图片生成",
    "nano_banana": "Nano Banana 图片生成", "exa": "Exa 搜索",
    "zotero": "Zotero 文献库", "obsidian": "Obsidian 笔记库",
    "vastai": "Vast.ai GPU", "modal": "Modal Serverless",
    "patent": "专利先前技术检索",
}
