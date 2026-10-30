"""Current presentation metadata for generated scenarios, separate from publication evidence."""

from typing import Any

from .simulation_interval_caption import scenario_interval_caption


def simulation_presentation_fields(value: dict[str, Any]) -> dict[str, Any]:
    """Correct eligibility and explanatory text without changing labels, values or source identities."""
    fields: dict[str, Any] = {"manuscript_eligible": True, "submission_eligible": False}
    for key in ("description", "caption", "table_description", "visual_encoding", "uncertainty_encoding"):
        if isinstance(value.get(key), str):
            fields[key] = scenario_interval_caption(value[key])
    return fields
