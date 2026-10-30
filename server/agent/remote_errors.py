"""Safe structured provider failures shared by model and read-only tool adapters."""
from __future__ import annotations

import asyncio
import re
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from typing import Any


class RemoteCallError(RuntimeError):
    def __init__(self, service: str, status: int, *, request_id: str = "", retry_after: float | None = None):
        self.service, self.status, self.retry_after = service, status, retry_after
        self.request_id = request_id if re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", request_id) else ""
        self.code = "REMOTE_RATE_LIMIT" if status == 429 else "REMOTE_HTTP_ERROR"
        self.retryable = status in {429, 502, 503, 504}
        super().__init__(f"{self.code}: {service} HTTP {status}" + (f" request_id={self.request_id}" if self.request_id else ""))


class RemoteTransportError(RemoteCallError):
    def __init__(self, service: str, kind: str):
        super().__init__(service, 0)
        self.status = None
        self.code = "REMOTE_TIMEOUT" if "timeout" in kind.casefold() else "REMOTE_TRANSPORT_ERROR"
        self.retryable = True
        self.args = (f"{self.code}: {service} {kind}",)


class RemoteStreamError(RemoteCallError):
    """A provider error frame cannot be treated as an empty or successful turn."""
    def __init__(self, code: Any):
        known = {"server_error", "rate_limit_exceeded", "insufficient_quota", "invalid_request_error",
                 "authentication_error", "overloaded_error", "internal_error"}
        reason = str(code) if str(code) in known else "unclassified_provider_error"
        super().__init__("openai-compatible", 0)
        self.status = None
        self.code = "MODEL_STREAM_PROVIDER_ERROR"
        self.retryable = reason in {"server_error", "rate_limit_exceeded", "overloaded_error", "internal_error"}
        self.args = (f"{self.code}: {reason}",)


def safe_exception_chain(error: BaseException) -> str:
    """Retain diagnostic types without including request URLs, bodies or credentials."""
    types, seen = [], set()
    while error is not None and id(error) not in seen and len(types) < 5:
        seen.add(id(error))
        types.append(type(error).__name__)
        error = error.__cause__ or error.__context__
    return " <- ".join(types)


def response_error(response: Any, service: str) -> RemoteCallError:
    headers = getattr(response, "headers", {})
    value = headers.get("retry-after", "")
    delay = None
    try:
        delay = max(0.0, float(value))
    except (ValueError, TypeError):
        try:
            delay = max(0.0, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())
        except (ValueError, TypeError, OverflowError):
            delay = None
    return RemoteCallError(service, response.status_code,
                           request_id=headers.get("x-request-id", ""), retry_after=delay)


async def read_only_get(client: Any, url: str, *, service: str, **kwargs: Any) -> Any:
    """One safe retry; a long Retry-After is reported, never shortened aggressively."""
    import httpx

    for attempt in range(2):
        try:
            response = await client.get(url, **kwargs)
        except httpx.TransportError as exc:
            if attempt:
                raise RemoteTransportError(service, type(exc).__name__) from exc
            await asyncio.sleep(1.0)
            continue
        if 200 <= response.status_code < 300:
            return response
        error = response_error(response, service)
        delay = error.retry_after if error.retry_after is not None else 2.0
        if attempt or not error.retryable or delay > 10.0:
            raise error
        await asyncio.sleep(delay)
    raise RuntimeError("read-only request exhausted its retry budget")
