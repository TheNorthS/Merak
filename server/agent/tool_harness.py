"""Bounded failure tracking and value-free tool receipts shared by the agent loop."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from .session_models import ToolResult


def argument_fingerprint(name: str, arguments: Any) -> str:
    raw = json.dumps([name, arguments], sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def argument_shape(arguments: Any) -> dict[str, Any]:
    """Diagnose missing versus empty fields without logging their contents."""
    if not isinstance(arguments, dict):
        return {"type": type(arguments).__name__}
    return {key: {"type": type(value).__name__, **(
        {"length": len(value)} if isinstance(value, (str, list, dict)) else {}
    )} for key, value in list(arguments.items())[:32]}


def classify_result(result: ToolResult) -> None:
    if result.success:
        result.phase = result.phase or "execution"
        return
    message = result.error or result.output
    prefix = message.partition(":")[0]
    known = {"TOOL_SCHEMA_ERROR", "TOOL_NOT_ALLOWED", "TOOL_CALL_LIMIT_REACHED",
             "TOOL_TIMEOUT", "TOOL_CANCELLED", "TOOL_REPEAT_LIMIT"}
    result.error_code = result.error_code or (prefix if prefix in known else "TOOL_EXECUTION_ERROR")
    result.phase = result.phase or ("validation" if prefix == "TOOL_SCHEMA_ERROR" else "execution")
    result.retryable = result.retryable or result.error_code == "ARTIFACT_CONTRACT_ERROR" or prefix == "TOOL_SCHEMA_ERROR"


@dataclass
class FailureBudget:
    """Unrelated successful reads cannot reset a repeatedly failing mutation."""

    counts: dict[str, int] = field(default_factory=dict)

    def exhausted(self, fingerprint: str) -> bool:
        return any(key.startswith(fingerprint + ":") and count >= 3
                   for key, count in self.counts.items())

    def observe(self, fingerprint: str, result: ToolResult) -> bool:
        key = f"{fingerprint}:{result.error_code}"
        if result.success:
            for existing in list(self.counts):
                if existing.startswith(fingerprint + ":"):
                    del self.counts[existing]
            return False
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key] >= 3


def tool_receipt(result: ToolResult) -> dict[str, Any]:
    return {"tool_call_id": result.tool_call_id, "error_code": result.error_code,
            "phase": result.phase, "retryable": result.retryable,
            "duration_ms": result.duration_ms, "argument_fingerprint": result.argument_fingerprint,
            "http_status": result.http_status, "request_id": result.request_id, "retry_after": result.retry_after}
