"""Explicit non-streaming requests use the same model, protocol checks and budget."""

from types import SimpleNamespace

import pytest

from server.agent import LLMResponse, ModelRole, ToolCall, ToolDefinition
from server.agent.engine import AgentEngine
from server.agent.model_deadlines import ModelRequestBudget, active_model_budget
from server.agent.tool_response_protocol import ToolResponseProtocolError


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_mode", [False, True])
async def test_configured_non_streaming_uses_one_budget_attempt(monkeypatch, tool_mode):
    class Provider:
        name = model = "fixture"
        streaming_enabled = False

        async def chat_stream(self, **kwargs):
            pytest.fail("Explicit non-streaming mode must not open an SSE connection")
            yield

        async def chat(self, **kwargs):
            return LLMResponse(content="Complete result", stop_reason="stop")

    provider = Provider()
    engine = AgentEngine(SimpleNamespace(_providers={"fixture": provider}, _strategy={ModelRole.EXECUTOR: "fixture"}))
    budget = ModelRequestBudget()
    budget.begin_attempt()
    token = active_model_budget.set(budget)
    try:
        response, streamed = await engine._chat_with_progress(
            provider, "fixture", [], [ToolDefinition("Read", "read", {})] if tool_mode else None, 32, None,
        )
    finally:
        active_model_budget.reset(token)
    assert response.content == "Complete result" and streamed is False
    assert budget.attempts == 1


@pytest.mark.asyncio
async def test_non_streaming_keeps_truncated_tool_response_rejection():
    provider = SimpleNamespace(name="fixture", model="fixture", streaming_enabled=False)

    async def chat(**kwargs):
        return LLMResponse(stop_reason="length", tool_calls=[ToolCall("incomplete", "Read", {})])

    provider.chat = chat
    engine = AgentEngine(SimpleNamespace(_providers={}, _strategy={}))
    with pytest.raises(ToolResponseProtocolError):
        await engine._chat_with_progress(provider, "fixture", [], [ToolDefinition("Read", "read", {})], 32, None)


def test_provider_mode_comes_from_validated_settings(monkeypatch):
    import server.agent as agent
    from server.services.settings_models import ModelConfig

    router = agent.ModelRouter()
    monkeypatch.setattr(agent, "model_router", router)
    config = ModelConfig(openai_api_key="fixture", openai_transport="non_stream")
    agent.init_models_from_config(config)
    assert router._providers["openai-api"].streaming_enabled is False
    assert ModelConfig().openai_transport == "stream"
    from server.api.settings import model_verification_payload
    assert model_verification_payload(config, "openai-api")["openai_transport"] == "non_stream"
    assert model_verification_payload(config, "openai-api") != model_verification_payload(
        config.model_copy(update={"openai_transport": "stream"}), "openai-api",
    )
