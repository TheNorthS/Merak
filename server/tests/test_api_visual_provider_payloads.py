from __future__ import annotations

import base64
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from server.agent import ClaudeProvider, Message, OpenAIProvider


class _OpenAIResponse:
    status_code = 200
    text = ""

    @staticmethod
    def json() -> dict[str, Any]:
        return {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 7, "completion_tokens": 1},
        }


class _OpenAIClient:
    def __init__(self) -> None:
        self.request: dict[str, Any] = {}

    async def __aenter__(self) -> "_OpenAIClient":
        return self

    async def __aexit__(self, *_args: Any) -> None:
        return None

    async def post(
        self,
        url: str,
        *,
        json: dict[str, Any],
        headers: dict[str, str],
    ) -> _OpenAIResponse:
        self.request = {
            "url": url,
            "json": json,
            "headers": headers,
        }
        return _OpenAIResponse()


class _ClaudeMessages:
    def __init__(self) -> None:
        self.request: dict[str, Any] = {}

    async def create(self, **kwargs: Any) -> SimpleNamespace:
        self.request = kwargs
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text="ok")],
            usage=SimpleNamespace(input_tokens=7, output_tokens=1),
        )


class _ClaudeClient:
    def __init__(self) -> None:
        self.messages = _ClaudeMessages()


@pytest.mark.asyncio
async def test_openai_provider_forwards_image_url_blocks_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _OpenAIClient()
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **_kwargs: client,
    )
    encoded = base64.b64encode(b"native-png-pixels").decode("ascii")
    content = [
        {"type": "text", "text": "Inspect the attached page."},
        {
            "type": "image_url",
            "image_url": {
                "url": f"data:image/png;base64,{encoded}",
                "detail": "high",
            },
        },
    ]

    response = await OpenAIProvider(
        "test-key",
        model="vision-reviewer",
        base_url="https://models.example/v1",
    ).chat([
        Message(role="system", content="Review pixels directly."),
        Message(role="user", content=content),
    ])

    sent = client.request["json"]["messages"]
    assert sent[0] == {
        "role": "system",
        "content": "Review pixels directly.",
    }
    assert sent[1]["content"] is content
    assert sent[1]["content"] == content
    assert response.content == "ok"


@pytest.mark.asyncio
async def test_claude_provider_converts_data_url_to_anthropic_image_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _ClaudeClient()
    provider = ClaudeProvider("test-key", model="claude-vision-reviewer")

    async def fake_get_client() -> _ClaudeClient:
        return client

    monkeypatch.setattr(provider, "_get_client", fake_get_client)
    encoded = base64.b64encode(b"native-png-pixels").decode("ascii")
    content = [
        {"type": "text", "text": "Inspect the attached page."},
        {
            "type": "image_url",
            "image_url": {
                "url": f"data:image/png;base64,{encoded}",
                "detail": "high",
            },
        },
    ]

    response = await provider.chat([
        Message(role="system", content="Review pixels directly."),
        Message(role="user", content=content),
    ])

    assert client.messages.request["system"] == "Review pixels directly."
    assert client.messages.request["messages"] == [{
        "role": "user",
        "content": [
            {"type": "text", "text": "Inspect the attached page."},
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": encoded,
                },
            },
        ],
    }]
    assert content[1]["type"] == "image_url"
    assert response.content == "ok"


@pytest.mark.asyncio
async def test_plain_text_messages_remain_plain_for_both_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    openai_client = _OpenAIClient()
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **_kwargs: openai_client,
    )
    await OpenAIProvider(
        "test-key",
        base_url="https://models.example/v1",
    ).chat([Message(role="user", content="plain text")])
    assert openai_client.request["json"]["messages"] == [{
        "role": "user",
        "content": "plain text",
    }]

    claude_client = _ClaudeClient()
    claude = ClaudeProvider("test-key")

    async def fake_get_client() -> _ClaudeClient:
        return claude_client

    monkeypatch.setattr(claude, "_get_client", fake_get_client)
    await claude.chat([Message(role="user", content="plain text")])
    assert claude_client.messages.request["messages"] == [{
        "role": "user",
        "content": "plain text",
    }]
