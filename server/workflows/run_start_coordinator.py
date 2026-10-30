"""Start a selected workflow through validated preparation and durable lifecycle."""

from __future__ import annotations

from typing import Any

from .run_start_lifecycle import create_run, launch_run
from .run_start_preparation import prepare_run_start


async def start_run(
    host: Any,
    node_ids: list[str],
    project_path: str,
    research_direction: str = "",
    effort: str = "balanced",
    assurance: str = "draft",
    pipeline_options: dict[str, Any] | None = None,
    on_event: Any = None,
) -> str:
    plan = await prepare_run_start(
        host,
        node_ids,
        project_path,
        assurance,
        pipeline_options,
    )
    run, state = create_run(
        host,
        plan,
        project_path,
        research_direction,
        effort,
        on_event,
    )
    return launch_run(
        host,
        run,
        state,
        research_direction,
        effort,
        plan.assurance,
    )
