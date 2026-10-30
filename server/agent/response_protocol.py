"""Model response protocol recovery and streaming text normalization."""

from __future__ import annotations

import html
import re
import uuid
from typing import Any

from . import ToolCall, ToolDefinition


class ResponseProtocolMixin:
    def _parse_text_tool_calls(self, content: str, tools: list[ToolDefinition]) -> list[ToolCall]:
        """Recover XML-style pseudo tool calls emitted by weak OpenAI-compatible routes."""
        if not content or "<tool_use" not in content:
            return []
        allowed_names = {tool.name for tool in tools}
        if not allowed_names:
            return []

        calls: list[ToolCall] = []
        tool_pattern = re.compile(
            r"<tool_use\s+name=[\"']([^\"']+)[\"']\s*>(.*?)</tool_use>",
            re.IGNORECASE | re.DOTALL,
        )
        arg_pattern = re.compile(
            r"<arg\s+name=[\"']([^\"']+)[\"']\s*>(.*?)</arg>",
            re.IGNORECASE | re.DOTALL,
        )
        for tool_match in tool_pattern.finditer(content):
            name = html.unescape(tool_match.group(1).strip())
            if name not in allowed_names:
                continue
            body = tool_match.group(2)
            args: dict[str, Any] = {}
            for arg_match in arg_pattern.finditer(body):
                key = html.unescape(arg_match.group(1).strip())
                value = html.unescape(arg_match.group(2).strip())
                if key and key not in args:
                    args[key] = value
            if args:
                calls.append(ToolCall(id=f"text_tool_{uuid.uuid4().hex[:8]}", name=name, arguments=args))
        return calls

    def _strip_text_tool_calls(self, content: str) -> str:
        if not content:
            return ""
        stripped = re.sub(
            r"<tool_use\s+name=[\"'][^\"']+[\"']\s*>.*?</tool_use>",
            "",
            content,
            flags=re.IGNORECASE | re.DOTALL,
        )
        return stripped.strip()

    def _looks_like_tool_protocol_failure(self, content: str, tools: list[ToolDefinition]) -> bool:
        if not content or not tools:
            return False
        lower = content.lower()
        markers = (
            "no tools available",
            "no available tools",
            "tool calls are unavailable",
            "cannot call tools",
            "没有提供任何可调用工具",
            "没有任何可调用工具",
            "无法调用工具",
            "不能调用工具",
        )
        return "<tool_use" in lower or any(marker in lower for marker in markers)

    def _tool_protocol_retry_message(self, tools: list[ToolDefinition]) -> str:
        names = ", ".join(tool.name for tool in tools[:40])
        return (
            "工具实际已经提供给你。上一轮没有按协议调用工具，或把工具调用写成了正文。"
            "请立即使用原生 function/tool call 调用需要的工具；不要在正文中输出 <tool_use>、<arg>、代码块或文件全文。"
            f"可用工具包括：{names}。"
        )

    @staticmethod
    def _dedupe_stream_text(existing: str, incoming: str) -> str:
        """Normalize cumulative and substantially overlapping chunks from compatible APIs."""
        if not incoming or not existing:
            return incoming
        # Some proxies emit the entire generated prefix on every SSE event.
        if len(existing) >= 16 and incoming.startswith(existing):
            return incoming[len(existing):]
        # Suppress only substantial duplicates; short repeated tokens can be legitimate prose.
        if len(incoming) >= 24 and existing.endswith(incoming):
            return ""
        max_overlap = min(len(existing), len(incoming))
        for overlap in range(max_overlap, 15, -1):
            if existing.endswith(incoming[:overlap]):
                return incoming[overlap:]
        return incoming
