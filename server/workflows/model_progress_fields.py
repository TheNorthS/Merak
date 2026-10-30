"""Forward bounded request diagnostics through every workflow delegate status."""

from typing import Any


def model_progress_fields(data: dict[str, Any]) -> dict[str, Any]:
    return {key: data[key] for key in (
        "elapsed", "attempt", "max_attempts", "next_attempt", "retry_in_seconds",
        "total_elapsed_seconds", "remaining_seconds", "total_budget_seconds", "error_code",
    ) if key in data}
