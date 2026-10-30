"""Provider tool-response boundaries; incomplete arguments never become tools."""

from __future__ import annotations

import json
from typing import Any


class ToolResponseProtocolError(RuntimeError):
    """A rejected provider response, safe to report without its argument content."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(f"{code}: {detail}. No tools from this response were executed.")


def parse_tool_arguments(raw: Any, name: str) -> dict[str, Any]:
    """Require a complete JSON object; never close, guess, or log partial JSON."""
    if raw is None or raw == "":
        raw = "{}"
    try:
        arguments = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError as exc:
        raise ToolResponseProtocolError(
            "MODEL_TOOL_ARGUMENTS_INVALID",
            f"tool {name!r} returned malformed JSON ({len(raw)} chars, offset {exc.pos})",
        ) from None
    if not isinstance(arguments, dict):
        raise ToolResponseProtocolError(
            "MODEL_TOOL_ARGUMENTS_INVALID", f"tool {name!r} arguments must be a JSON object",
        )
    return arguments


def require_complete_tool_response(finish_reason: str, *, has_tools: bool) -> None:
    """A token/content cutoff cannot authorize even syntactically valid tools."""
    if has_tools and finish_reason in {"length", "max_tokens", "content_filter"}:
        raise ToolResponseProtocolError(
            "MODEL_TOOL_RESPONSE_TRUNCATED",
            f"provider ended tool response with {finish_reason!r}; use smaller complete calls",
        )


def tool_response_retry_instruction(error: ToolResponseProtocolError) -> str:
    """Request a new complete response without replaying a corrupted tool turn."""
    return (
        f"The previous provider response was rejected ({error.code}) before any tool execution. "
        "Return a new native tool call with one complete JSON argument object. "
        "Do not repeat analysis, include raw tool JSON in prose, or claim a write succeeded. "
        "Keep each call small: use focused Edit operations after Read, or declared document-part "
        "tools when available for long documents. Never submit truncated content or change "
        "the artifact schema to fit. All declared inputs and output requirements still apply."
    )
