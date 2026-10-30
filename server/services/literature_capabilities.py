"""Reject selected but unconfigured retrieval tools before model execution."""

import os


def validate_literature_configuration(options: dict) -> None:
    selected = set((options.get("research_strategy") or {}).get("literature_sources") or [])
    if "web" in selected and not os.environ.get("EXA_API_KEY", "").strip():
        raise ValueError(
            "LITERATURE_CONFIGURATION_ERROR: WebSearch is selected but Exa is not configured. "
            "Configure and test Exa, or explicitly deselect Web in literature sources; "
            "no model retry can repair missing credentials."
        )
