"""
多模型 Provider 统一接口

支持的后端：
- OpenAI-compatible API — Chat/Executor/Reviewer
- Claude API (Anthropic) — 可选 Executor/Reviewer
- OpenAI API (GPT/Codex) — Reviewer 核心
- DeepSeek API — 代码生成/经济模式
- GLM API (智谱) — 中文场景
- Gemini API (Google) — 搜索增强/长文本
- Qwen API (通义) — 代码/审稿
- Ollama (本地) — 离线隐私模式
"""

import os
from typing import Optional

from .model_types import (
    LLMResponse,
    Message as Message,
    ModelProvider,
    ModelRole,
    StreamChunk,
    ToolCall,
    ToolDefinition as ToolDefinition,
    DEFAULT_MAX_OUTPUT_TOKENS,
)
from .provider_messages import anthropic_payload, openai_payload, parse_openai_response
from .openai_stream import stream_openai

import structlog

logger = structlog.get_logger()


# The workflow may use user-supplied OpenAI-compatible model names. Keep one
# platform default for every provider instead of stale provider-specific guesses.
DEFAULT_MODEL_CONTEXT_TOKENS = 1_000_000



class ClaudeProvider(ModelProvider):
    """Anthropic Claude API provider."""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6", base_url: Optional[str] = None):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self._client = None

    @property
    def name(self) -> str:
        return f"claude/{self.model}"

    @property
    def supports_tool_use(self) -> bool:
        return True

    @property
    def max_context(self) -> int:
        return DEFAULT_MODEL_CONTEXT_TOKENS

    async def _get_client(self):
        if not self._client:
            try:
                from anthropic import AsyncAnthropic
                kwargs = {"api_key": self.api_key}
                if self.base_url:
                    kwargs["base_url"] = self.base_url.rstrip("/")
                self._client = AsyncAnthropic(**kwargs)
            except ImportError:
                raise RuntimeError("pip install anthropic")
        return self._client

    async def chat(self, messages, tools=None, temperature=0.7, max_tokens=DEFAULT_MAX_OUTPUT_TOKENS):
        client = await self._get_client()

        kwargs = anthropic_payload(
            messages,
            tools,
            model=self.model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        response = await client.messages.create(**kwargs)

        content = ""
        tool_calls = []
        for block in response.content:
            if block.type == "text":
                content += block.text
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.id,
                    name=block.name,
                    arguments=block.input,
                ))

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            stop_reason="tool_use" if tool_calls else "end_turn",
            model=self.model,
            usage={"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens},
        )

    async def chat_stream(self, messages, tools=None, temperature=0.7, max_tokens=DEFAULT_MAX_OUTPUT_TOKENS):
        client = await self._get_client()

        kwargs = anthropic_payload(
            messages, tools, model=self.model,
            temperature=temperature, max_tokens=max_tokens,
        )

        async with client.messages.stream(**kwargs) as stream:
            async for event in stream:
                if event.type == "content_block_delta" and hasattr(event.delta, "text"):
                    yield StreamChunk(type="text", content=event.delta.text)
            yield StreamChunk(type="done")

# ==================== OpenAI Provider ====================

def _normalize_openai_base(base_url: Optional[str], default_path: str = "/v1") -> str:
    """统一化 OpenAI 兼容 API 的 base_url。

    用户在 Settings 里可能填有路径（https://api.openai.com/v1）
    也可能只填域名（https://api.openai.com）。
    规则：URL 无路径（或路径为 /）→ 追加 default_path；已有路径 → 原样保留。
    default_path 由各 Provider 子类通过 DEFAULT_BASE_PATH 指定，
    反映该服务的默认 API 版本前缀。
    """
    from urllib.parse import urlparse
    if not base_url:
        return ""   # 交给调用方决定 fallback
    stripped = base_url.rstrip("/")
    parsed = urlparse(stripped)
    if not parsed.path or parsed.path == "/":
        return stripped + default_path
    return stripped


class OpenAIProvider(ModelProvider):
    """OpenAI GPT/Codex API"""

    # 子类可覆盖此值，指定该服务"无路径域名"时应追加的默认路径
    DEFAULT_BASE_PATH: str = "/v1"
    # 无 base_url 时的默认完整前缀
    DEFAULT_BASE_HOST: str = "https://api.openai.com"
    streaming_enabled: bool = True

    def __init__(self, api_key: str, model: str = "gpt-4o", base_url: Optional[str] = None):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self._client = None

    @property
    def name(self) -> str:
        return f"openai/{self.model}"

    @property
    def supports_tool_use(self) -> bool:
        return True

    @property
    def max_context(self) -> int:
        return DEFAULT_MODEL_CONTEXT_TOKENS

    async def _get_client(self):
        if not self._client:
            try:
                from openai import AsyncOpenAI
                self._client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)
            except ImportError:
                raise RuntimeError("pip install openai")
        return self._client

    async def chat(self, messages, tools=None, temperature=0.7, max_tokens=DEFAULT_MAX_OUTPUT_TOKENS):
        """调用 OpenAI 兼容 API（手动 HTTP，兼容非标准代理）"""
        import httpx

        payload = openai_payload(
            messages, tools, model=self.model,
            temperature=temperature, max_tokens=max_tokens,
        )

        base = _normalize_openai_base(self.base_url, self.DEFAULT_BASE_PATH)
        if not base:
            base = self.DEFAULT_BASE_HOST + self.DEFAULT_BASE_PATH
        url = base + "/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

        # connect=10s：URL 不通时快速失败；read=240s：非流式工具调用可能包含较大的 Write 参数
        timeout = httpx.Timeout(connect=10.0, read=240.0, write=20.0, pool=5.0)

        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            try:
                resp = await client.post(url, json=payload, headers=headers)
            except httpx.TransportError as error:
                from .remote_errors import RemoteTransportError
                raise RemoteTransportError("openai-compatible", type(error).__name__) from error
            if resp.status_code != 200:
                from .remote_errors import response_error
                raise response_error(resp, "openai-compatible")

            try:
                data = resp.json()
            except ValueError:
                if resp.text.lstrip().lower().startswith(('<!doctype', '<html')):
                    raise RuntimeError(
                        "API 端点返回了 HTML 而不是 JSON，请检查 Settings → 模型 中的 Base URL。"
                    ) from None
                raise RuntimeError("OpenAI-compatible API returned invalid JSON (status 200)") from None

        return parse_openai_response(data, self.model)

    async def chat_stream(
        self,
        messages,
        tools=None,
        temperature=0.7,
        max_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
    ):
        payload = openai_payload(
            messages, tools, model=self.model,
            temperature=temperature, max_tokens=max_tokens, stream=True,
        )
        payload["stream_options"] = {"include_usage": True}
        base = _normalize_openai_base(self.base_url, self.DEFAULT_BASE_PATH)
        base = base or self.DEFAULT_BASE_HOST + self.DEFAULT_BASE_PATH
        async for chunk in stream_openai(
            url=base + "/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            payload=payload,
        ):
            yield chunk




# ==================== DeepSeek / GLM / Qwen (OpenAI 兼容) ====================

class DeepSeekProvider(OpenAIProvider):
    """DeepSeek API — https://api.deepseek.com/v1/chat/completions"""
    DEFAULT_BASE_PATH = "/v1"
    DEFAULT_BASE_HOST = "https://api.deepseek.com"

    def __init__(self, api_key: str, model: str = "deepseek-chat", base_url: Optional[str] = None):
        super().__init__(api_key, model, base_url=base_url)

    @property
    def name(self):
        return f"deepseek/{self.model}"


class GLMProvider(OpenAIProvider):
    """智谱 GLM API — https://open.bigmodel.cn/api/paas/v4/chat/completions"""
    DEFAULT_BASE_PATH = "/api/paas/v4"
    DEFAULT_BASE_HOST = "https://open.bigmodel.cn"

    def __init__(self, api_key: str, model: str = "glm-4-plus", base_url: Optional[str] = None):
        super().__init__(api_key, model, base_url=base_url)

    @property
    def name(self):
        return f"glm/{self.model}"


class QwenProvider(OpenAIProvider):
    """通义千问 — https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"""
    DEFAULT_BASE_PATH = "/compatible-mode/v1"
    DEFAULT_BASE_HOST = "https://dashscope.aliyuncs.com"

    def __init__(self, api_key: str, model: str = "qwen-max", base_url: Optional[str] = None):
        super().__init__(api_key, model, base_url=base_url)

    @property
    def name(self):
        return f"qwen/{self.model}"


class GeminiProvider(OpenAIProvider):
    """Google Gemini OpenAI 兼容端点 — https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"""
    DEFAULT_BASE_PATH = "/v1beta/openai"
    DEFAULT_BASE_HOST = "https://generativelanguage.googleapis.com"

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash", base_url: Optional[str] = None):
        super().__init__(api_key, model, base_url=base_url)

    @property
    def name(self):
        return f"gemini/{self.model}"

    @property
    def max_context(self):
        return DEFAULT_MODEL_CONTEXT_TOKENS


# ==================== Model Router ====================

class ModelRouter:
    """模型路由器 — 根据任务类型选择最佳模型"""

    def __init__(self):
        self._providers: dict[str, ModelProvider] = {}
        self._strategy: dict[ModelRole, str] = {
            ModelRole.EXECUTOR: "openai-api",
            ModelRole.REVIEWER: "openai-api",
            ModelRole.SEARCH: "gemini",
            ModelRole.FIGURE: "openai-api",
            ModelRole.GENERAL: "openai-api",
        }

    def register(self, name: str, provider: ModelProvider):
        """注册模型 Provider"""
        self._providers[name] = provider
        logger.info("Model registered", name=name, provider=provider.name)

    def set_strategy(self, role: ModelRole, provider_name: str):
        """设置角色对应的 Provider"""
        self._strategy[role] = provider_name

    def get_provider(self, role: ModelRole) -> ModelProvider:
        """获取角色对应的 Provider"""
        name = self._strategy.get(role, "openai-api")
        provider = self._providers.get(name)
        if not provider:
            # Fallback 链：按优先级依次尝试
            for fallback in ["openai-api", "claude-api", "deepseek", "qwen", "glm", "gemini"]:
                if fallback in self._providers:
                    return self._providers[fallback]
            providers_str = list(self._providers.keys())
            raise RuntimeError(
                f"没有可用的模型 Provider（role={role.value}，策略={name}）。\n"
                f"当前已注册: {providers_str or '无'}\n"
                f"请在 Settings → 模型 中填写至少一个 API Key 并保存。"
            )
        return provider

    def get_provider_by_name(self, name: str) -> Optional[ModelProvider]:
        """按名称获取 Provider"""
        return self._providers.get(name)

    @staticmethod
    def provider_identity(provider: ModelProvider) -> str:
        """Return the concrete provider/model identity used for provenance.

        Provider registration keys describe a connection profile, not a model.
        Review independence must therefore compare the actual model identity.
        Custom providers sometimes expose ``name`` as only the provider family,
        so append their configured ``model`` when it is not already present.
        """
        declared = str(getattr(provider, "name", "") or "").strip()
        model = str(getattr(provider, "model", "") or "").strip()
        if not model:
            return declared or provider.__class__.__name__
        lowered = declared.casefold()
        model_lowered = model.casefold()
        if lowered == model_lowered or lowered.endswith("/" + model_lowered):
            return declared
        family = declared.split("/", 1)[0].strip()
        if not family:
            family = provider.__class__.__name__.removesuffix("Provider").casefold()
        return f"{family}/{model}"

    def get_provider_route(
        self,
        role: ModelRole,
    ) -> tuple[str, ModelProvider, str]:
        """Resolve a role to registration key, provider, and model identity."""
        provider = self.get_provider(role)
        strategy_name = str(self._strategy.get(role) or "").strip()
        if strategy_name and self._providers.get(strategy_name) is provider:
            provider_name = strategy_name
        else:
            provider_name = next(
                (
                    name
                    for name, candidate in self._providers.items()
                    if candidate is provider
                ),
                "",
            )
        return provider_name, provider, self.provider_identity(provider)

    def get_isolated_provider_route(
        self, role: ModelRole,
    ) -> tuple[str, ModelProvider, str]:
        """Resolve a role for a fresh session with frozen inputs and its own trace."""
        return self.get_provider_route(role)

    def list_providers(self) -> list[dict]:
        """列出所有已注册的 Provider"""
        return [
            {"name": name, "model": p.name, "tool_use": p.supports_tool_use, "context": p.max_context}
            for name, p in self._providers.items()
        ]

    def get_strategy(self) -> dict[str, str]:
        """获取当前策略"""
        return {role.value: name for role, name in self._strategy.items()}


# 全局实例
model_router = ModelRouter()


def init_models_from_config(config) -> None:
    """直接从用户配置对象初始化模型，不经过环境变量（防止系统 env 污染注册列表）。

    config 为 ModelConfig 实例，字段为空字符串则表示未配置，不会注册对应 provider。
    """
    def _or_none(v: str) -> Optional[str]:
        return v.strip() or None

    # ===== Claude API =====
    anthropic_key = _or_none(getattr(config, "anthropic_api_key", ""))
    if anthropic_key:
        anthropic_model = _or_none(getattr(config, "anthropic_model", "")) or "claude-sonnet-4-6"
        anthropic_base = _or_none(getattr(config, "anthropic_base_url", ""))
        model_router.register("claude-api", ClaudeProvider(anthropic_key, anthropic_model, base_url=anthropic_base))
        model_router.set_strategy(ModelRole.EXECUTOR, "claude-api")
        model_router.set_strategy(ModelRole.GENERAL, "claude-api")

    # ===== OpenAI API =====
    openai_key = _or_none(config.openai_api_key)
    if openai_key:
        openai_model = _or_none(config.openai_model) or "gpt-4o"
        openai_base = _or_none(config.openai_base_url)
        provider = OpenAIProvider(openai_key, openai_model, base_url=openai_base)
        provider.streaming_enabled = getattr(config, "openai_transport", "stream") != "non_stream"
        model_router.register("openai-api", provider)
        model_router.set_strategy(ModelRole.REVIEWER, "openai-api")
        model_router.set_strategy(ModelRole.EXECUTOR, "openai-api")
        model_router.set_strategy(ModelRole.GENERAL, "openai-api")
        model_router.set_strategy(ModelRole.FIGURE, "openai-api")

    # ===== 扩展模型 =====
    if _or_none(config.deepseek_api_key):
        model_router.register("deepseek", DeepSeekProvider(
            config.deepseek_api_key,
            model=_or_none(config.deepseek_model) or "deepseek-chat",
            base_url=_or_none(config.deepseek_base_url),
        ))

    if _or_none(config.glm_api_key):
        model_router.register("glm", GLMProvider(
            config.glm_api_key,
            model=_or_none(config.glm_model) or "glm-4-plus",
            base_url=_or_none(config.glm_base_url),
        ))

    if _or_none(config.qwen_api_key):
        model_router.register("qwen", QwenProvider(
            config.qwen_api_key,
            model=_or_none(config.qwen_model) or "qwen-max",
            base_url=_or_none(config.qwen_base_url),
        ))

    if _or_none(config.gemini_api_key):
        model_router.register("gemini", GeminiProvider(
            config.gemini_api_key,
            model=_or_none(config.gemini_model) or "gemini-2.0-flash",
            base_url=_or_none(config.gemini_base_url),
        ))

    logger.info("Models initialized from config",
                count=len(model_router._providers),
                providers=list(model_router._providers.keys()),
                executor=model_router._strategy.get(ModelRole.EXECUTOR),
                reviewer=model_router._strategy.get(ModelRole.REVIEWER))


def init_models_from_env():
    """从环境变量初始化模型 — 仅在无持久化配置时作为冷启动 fallback"""

    # ===== Claude API =====
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if anthropic_key:
        model_router.register("claude-api", ClaudeProvider(
            anthropic_key,
            model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
            base_url=os.environ.get("ANTHROPIC_BASE_URL") or None,
        ))
        model_router.set_strategy(ModelRole.EXECUTOR, "claude-api")
        model_router.set_strategy(ModelRole.GENERAL, "claude-api")

    # ===== OpenAI API =====
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    openai_base = os.environ.get("OPENAI_BASE_URL") or None
    if openai_key:
        openai_model = os.environ.get("OPENAI_MODEL") or "gpt-4o"
        model_router.register("openai-api", OpenAIProvider(openai_key, openai_model, base_url=openai_base))
        model_router.set_strategy(ModelRole.REVIEWER, "openai-api")
        model_router.set_strategy(ModelRole.EXECUTOR, "openai-api")
        model_router.set_strategy(ModelRole.GENERAL, "openai-api")
        model_router.set_strategy(ModelRole.FIGURE, "openai-api")

    # ===== 扩展模型 =====
    deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if deepseek_key:
        model_router.register("deepseek", DeepSeekProvider(
            deepseek_key,
            model=os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
            base_url=os.environ.get("DEEPSEEK_BASE_URL") or None,
        ))

    glm_key = os.environ.get("GLM_API_KEY", "")
    if glm_key:
        model_router.register("glm", GLMProvider(
            glm_key,
            model=os.environ.get("GLM_MODEL", "glm-4-plus"),
            base_url=os.environ.get("GLM_BASE_URL") or None,
        ))

    qwen_key = os.environ.get("QWEN_API_KEY", "")
    if qwen_key:
        model_router.register("qwen", QwenProvider(
            qwen_key,
            model=os.environ.get("QWEN_MODEL", "qwen-max"),
            base_url=os.environ.get("QWEN_BASE_URL") or None,
        ))

    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    if gemini_key:
        model_router.register("gemini", GeminiProvider(
            gemini_key,
            model=os.environ.get("GEMINI_MODEL", "gemini-2.0-flash"),
            base_url=os.environ.get("GEMINI_BASE_URL") or None,
        ))

    logger.info("Models initialized from env",
                count=len(model_router._providers),
                executor=model_router._strategy.get(ModelRole.EXECUTOR),
                reviewer=model_router._strategy.get(ModelRole.REVIEWER))
