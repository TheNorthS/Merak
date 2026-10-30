"""Provider-specific message/payload projections and response parsing."""

from __future__ import annotations

import json
from typing import Any

from .anthropic_content import anthropic_message_content
from .model_types import LLMResponse, Message, ToolCall, ToolDefinition
from .tool_response_protocol import parse_tool_arguments, require_complete_tool_response


def anthropic_messages(messages: list[Message]) -> tuple[Any, list[dict[str, Any]]]:
    system: Any = ""
    output: list[dict[str, Any]] = []
    index = 0
    while index < len(messages):
        message = messages[index]
        if message.role == "system":
            system = message.content
        elif message.role == "user":
            output.append({"role": "user", "content": anthropic_message_content(message.content)})
        elif message.role == "assistant":
            content = anthropic_message_content(message.content)
            blocks = ([{"type": "text", "text": content}] if isinstance(content, str) and content else list(content) if isinstance(content, list) else [])
            blocks.extend({
                "type": "tool_use", "id": call["id"], "name": call["name"],
                "input": call["arguments"],
            } for call in message.tool_calls)
            output.append({"role": "assistant", "content": blocks or [{"type": "text", "text": ""}]})
        elif message.role == "tool":
            results = []
            while index < len(messages) and messages[index].role == "tool":
                current = messages[index]
                results.append({"type": "tool_result", "tool_use_id": current.tool_call_id, "content": current.content})
                index += 1
            output.append({"role": "user", "content": results})
            continue
        else:
            output.append({"role": message.role, "content": message.content})
        index += 1
    return system, output


def anthropic_payload(
    messages: list[Message],
    tools: list[ToolDefinition] | None,
    *,
    model: str,
    temperature: float,
    max_tokens: int,
) -> dict[str, Any]:
    system, api_messages = anthropic_messages(messages)
    payload: dict[str, Any] = {
        "model": model, "max_tokens": max_tokens,
        "temperature": temperature, "messages": api_messages,
    }
    if system:
        payload["system"] = system
    if tools:
        payload["tools"] = [
            {"name": tool.name, "description": tool.description, "input_schema": tool.parameters}
            for tool in tools
        ]
    return payload


def openai_messages(messages: list[Message]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "assistant":
            item: dict[str, Any] = {"role": "assistant", "content": message.content or None}
            if message.tool_calls:
                item["tool_calls"] = [{
                    "id": call["id"], "type": "function",
                    "function": {
                        "name": call["name"],
                        "arguments": json.dumps(call["arguments"])
                        if isinstance(call["arguments"], dict) else call["arguments"] or "{}",
                    },
                } for call in message.tool_calls]
            output.append(item)
        elif message.role == "tool":
            output.append({"role": "tool", "tool_call_id": message.tool_call_id or "", "content": message.content})
        else:
            output.append({"role": message.role, "content": message.content})
    return output


def openai_payload(
    messages: list[Message],
    tools: list[ToolDefinition] | None,
    *,
    model: str,
    temperature: float,
    max_tokens: int,
    stream: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model, "messages": openai_messages(messages),
        "temperature": temperature, "max_tokens": max_tokens,
    }
    if stream:
        payload["stream"] = True
    if tools:
        payload["tools"] = [{
            "type": "function",
            "function": {"name": tool.name, "description": tool.description, "parameters": tool.parameters},
        } for tool in tools]
    return payload


def parse_openai_response(data: Any, model: str) -> LLMResponse:
    content = ""
    calls: list[ToolCall] = []
    usage: dict[str, Any] = {}
    finish_reason = ""
    if isinstance(data, dict) and data.get("choices"):
        choice = data["choices"][0]
        finish_reason = str(choice.get("finish_reason") or "")
        message = choice.get("message", {})
        content = message.get("content", "") or ""
        require_complete_tool_response(
            finish_reason, has_tools=bool(message.get("tool_calls")),
        )
        for call in message.get("tool_calls") or []:
            function = call.get("function", {})
            arguments = parse_tool_arguments(function.get("arguments"), function.get("name", ""))
            calls.append(ToolCall(id=call.get("id", ""), name=function.get("name", ""), arguments=arguments))
        usage = data.get("usage", {})
    elif isinstance(data, dict) and "content" in data:
        content = data["content"]
    elif isinstance(data, str):
        content = data
    else:
        content = json.dumps(data)
    return LLMResponse(
        content=content, tool_calls=calls,
        stop_reason=finish_reason or ("tool_use" if calls else "end_turn"), model=model,
        usage={"input_tokens": usage.get("prompt_tokens", 0), "output_tokens": usage.get("completion_tokens", 0)},
    )
