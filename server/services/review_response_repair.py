"""Bound invalid structured reviewer responses without manufacturing a verdict."""

import json
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from ..utils.atomic_write import atomic_write_json, atomic_write_text


async def structured_review_response(*, call: Callable[[str, float], Awaitable[Any]],
    parse: Callable[[Any], str], prompt: str, timeout: float, directory: Path,
    bind_prompt: Callable[[str], None], activity: Callable[[], Awaitable[None]]) -> tuple[Any, str]:
    """Allow one model-authored format retry inside the original shared deadline."""
    deadline = time.monotonic() + max(30.0, float(timeout))
    current = prompt
    for attempt in (1, 2):
        remaining = deadline - time.monotonic()
        if remaining < (0.01 if attempt == 1 else 30.0):
            raise TimeoutError("Independent review format repair has no remaining request budget")
        bind_prompt(current)
        atomic_write_text(directory / f"attempt-{attempt}-prompt.txt", current)
        response = await call(current, remaining)
        raw = str(response.content or "")
        atomic_write_text(directory / f"attempt-{attempt}-response.txt", raw)
        await activity()
        try:
            result = parse(response)
        except (json.JSONDecodeError, TypeError) as error:
            atomic_write_json(directory / f"attempt-{attempt}-error.json",
                {"attempt": attempt, "type": type(error).__name__, "message": str(error)[:1600]})
            if attempt == 2 or deadline - time.monotonic() < 30.0:
                raise
            current = (prompt + "\n\n## Structured-output repair\nThe previous response was rejected locally: "
                + str(error)[:1600] + ". Return a new, valid JSON object matching the complete schema above. "
                "Retain your honest verdict, findings and evidence limits. Do not weaken findings to satisfy a schema. "
                "Use double-quoted keys/strings, no comments, no trailing commas and no prose outside JSON.")
            continue
        return response, result
    raise AssertionError("Structured reviewer retry budget exhausted")
