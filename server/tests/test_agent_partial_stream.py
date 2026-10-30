from __future__ import annotations

import asyncio
from types import SimpleNamespace
import pytest

from server.agent import (
    DEFAULT_MODEL_CONTEXT_TOKENS,
    ClaudeProvider,
    DeepSeekProvider,
    GeminiProvider,
    GLMProvider,
    LLMResponse,
    ModelRole,
    OpenAIProvider,
    QwenProvider,
)
from server.agent.engine import AgentEngine
from server.agent.provider_messages import parse_openai_response


def test_every_model_provider_defaults_to_one_million_context_tokens():
    providers = [
        OpenAIProvider("test", model="custom-openai-model"),
        ClaudeProvider("test", model="custom-claude-model"),
        DeepSeekProvider("test", model="custom-deepseek-model"),
        GLMProvider("test", model="custom-glm-model"),
        QwenProvider("test", model="custom-qwen-model"),
        GeminiProvider("test", model="custom-gemini-model"),
    ]

    assert DEFAULT_MODEL_CONTEXT_TOKENS == 1_000_000
    assert {provider.max_context for provider in providers} == {
        DEFAULT_MODEL_CONTEXT_TOKENS
    }


def test_openai_length_finish_reason_is_preserved() -> None:
    response = parse_openai_response({
        "choices": [{
            "finish_reason": "length",
            "message": {"content": "{\\\"verdict\\\":"},
        }],
        "usage": {"completion_tokens": 8192},
    }, "test-model")

    assert response.stop_reason == "length"

@pytest.mark.parametrize('prior_writes', [0, 1])
def test_partial_tool_stream_is_not_accepted_as_final_output(monkeypatch, prior_writes):
    provider = SimpleNamespace(name="fake", model="fake-model")
    router = SimpleNamespace(
        _providers={"fake": provider},
        _strategy={ModelRole.EXECUTOR: "fake"},
    )
    engine = AgentEngine(router)
    engine.register_tool(
        "Write",
        "write a file",
        {"type": "object", "properties": {}},
        lambda **_: "ok",
    )
    session = engine.create_session(role=ModelRole.EXECUTOR)
    session.tool_call_counts['Write'] = prior_writes
    session.max_iterations = 3
    responses = [
        (LLMResponse(content="I will write the artifact.", stop_reason="partial_timeout"), True),
        (LLMResponse(content="Completed after continuation.", stop_reason="end_turn"), False),
    ]

    async def fake_chat(**_kwargs):
        return responses.pop(0)

    monkeypatch.setattr(engine, "_chat_with_progress", fake_chat)
    events = []

    async def capture(event):
        events.append(event)

    with pytest.raises(TimeoutError, match="MODEL_STREAM_INTERRUPTED"):
        asyncio.run(engine.run(
            session.id, "Create the required artifact.", on_event=capture,
            tools=["Write"], partial_stream_timeout_seconds=1,
        ))
    assert session.iterations == 1
    assert session.status.value == "error"
    assert len(responses) == 1
    assert any(message.content == "I will write the artifact." for message in session.messages)


def test_cancelling_model_progress_joins_the_active_stream_child():
    started = asyncio.Event()
    closed = asyncio.Event()

    class BlockingProvider:
        name = "blocking"
        model = "blocking-model"

        async def chat_stream(self, **_kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
                if False:  # pragma: no cover - makes this an async generator
                    yield None
            finally:
                closed.set()

    engine = AgentEngine(SimpleNamespace(_providers={}, _strategy={}))
    provider = BlockingProvider()

    async def cancel_request() -> tuple[bool, bool]:
        request = asyncio.create_task(engine._chat_with_progress(
            provider=provider,
            provider_name=provider.name,
            messages=[],
            tools=None,
            max_tokens=32,
            on_event=None,
        ))
        await asyncio.wait_for(started.wait(), timeout=1)
        request.cancel()
        result = await asyncio.gather(request, return_exceptions=True)
        await asyncio.wait_for(closed.wait(), timeout=1)
        return request.cancelled(), isinstance(result[0], asyncio.CancelledError)

    cancelled, propagated = asyncio.run(cancel_request())

    assert cancelled is True
    assert propagated is True
