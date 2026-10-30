"""Bound transient retries to no-tool requests that have produced no text."""

import asyncio
from typing import Any, Awaitable, Callable

from ..agent.remote_errors import RemoteCallError


async def retry_read_only_review(
    call: Callable[[Callable[[], Awaitable[None]]], Awaitable[Any]],
    activity: Callable[[], Awaitable[None]],
    record_retry: Callable[[dict[str, Any]], None] | None = None,
) -> Any:
    """The caller's original timeout covers all attempts and backoff together.

    Never replay partial output, cancellation, auth/schema errors or tool calls.
    This helper is only for stateless, output-only reviewers, not agent stages.
    """
    for attempt in range(1, 4):
        received_text = False

        async def observe() -> None:
            nonlocal received_text
            received_text = True
            await activity()

        try:
            return await call(observe)
        except RemoteCallError as error:
            error.model_request_attempts = attempt
            error.model_request_max_attempts = 3
            delay = error.retry_after if error.retry_after is not None else float(2 ** attempt)
            eligible = (not received_text and error.status in {429, 502, 503, 504}
                        and error.retryable and attempt < 3 and delay <= 30)
            if record_retry:
                record_retry({'attempt': attempt, 'max_attempts': 3, 'http_status': error.status,
                    'received_text': received_text, 'retry_scheduled': eligible,
                    'delay_seconds': delay if eligible else 0})
            if not eligible:
                raise
            await asyncio.sleep(delay)
    raise AssertionError('Unreachable native review retry state')
