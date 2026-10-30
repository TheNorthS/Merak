"""Provider-neutral model, message, tool, and streaming contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Optional


# Default response budget for model calls. This is an output-token limit, not
# the context-window size. Structured reviews and JSON audit reports need more
# room than the former 4096-token default.
DEFAULT_MAX_OUTPUT_TOKENS = 8192


class ModelRole(str, Enum):
    EXECUTOR = "executor"
    REVIEWER = "reviewer"
    SEARCH = "search"
    FIGURE = "figure"
    GENERAL = "general"


@dataclass
class Message:
    role: str
    content: str | list[dict[str, Any]]
    tool_calls: list[dict] = field(default_factory=list)
    tool_call_id: Optional[str] = None
    name: Optional[str] = None


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: dict


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class LLMResponse:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = "end_turn"
    model: str = ""
    usage: dict = field(default_factory=dict)


@dataclass
class StreamChunk:
    type: str
    content: str = ""
    tool_call: Optional[ToolCall] = None
    finish_reason: Optional[str] = None
    usage: dict = field(default_factory=dict)


class ModelProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @property
    @abstractmethod
    def supports_tool_use(self) -> bool:
        ...

    @property
    @abstractmethod
    def max_context(self) -> int:
        ...

    @abstractmethod
    async def chat(
        self,
        messages: list[Message],
        tools: Optional[list[ToolDefinition]] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        ...

    @abstractmethod
    async def chat_stream(
        self,
        messages: list[Message],
        tools: Optional[list[ToolDefinition]] = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        ...
