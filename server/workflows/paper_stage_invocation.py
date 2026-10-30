"""Bound paper authoring by real activity and a hard ceiling, with joined cancellation."""

import asyncio
import time
from typing import Any, Awaitable, Callable


async def invoke_paper_stage(host: Any, node: Any, run: Any, skill: str,
                             prompt: str, contract: str,
                             on_event: Callable[[Any], Awaitable[None]], *, stage_id: str = "") -> str:
    from ..agent.tools import invoke_skill
    if stage_id == 'consistency':
        from .paper_consistency_invocation import invoke_consistency
        return await invoke_consistency(run, skill, on_event)
    from ..services.paper_drafting import paper_drafting_service
    paths = paper_drafting_service.paths(run.project_path)
    write_scope = [path.relative_to(paths['root']).as_posix()
                   for path in paper_drafting_service.stage_write_targets(paths, stage_id)] if stage_id else None

    last_activity = time.monotonic()

    async def observe(event: Any) -> None:
        nonlocal last_activity
        if host._agent_event_counts_as_progress(event):
            last_activity = time.monotonic()
        await on_event(event)

    task = asyncio.create_task(invoke_skill(skill, prompt, project_path=run.project_path,
        parent_context="skill-chain:workflow-staged-paper", workflow_node_id=node.id,
        on_event=observe, allowed_tools_override=["Read", "Write", "Edit", "Glob", "Grep"],
        invocation_contract=contract, max_iterations=18,
        allowed_write_paths=write_scope,
        resume_input_fingerprint=_resume_inputs(run.project_path, stage_id)))
    return await host._await_agent_with_activity_watchdog(task=task, run=run, node=node,
        is_revision=False, last_activity=lambda: last_activity)


def _resume_inputs(project_path: str, stage_id: str) -> str:
    """Preserve interrupted work only while its read-only scientific inputs remain current."""
    if not stage_id:
        return ""
    import hashlib
    from ..services.manuscript_text import sha256
    from ..services.paper_drafting import paper_drafting_service
    from .review_audit import review_source_bundle

    paths = paper_drafting_service.paths(project_path)
    upstream = paper_drafting_service.stage_input_signature(paths, stage_id)
    freeze = sha256(paths["paper"] / "SCIENTIFIC_FREEZE.json")
    reviewed = review_source_bundle(project_path)[0] if stage_id == "consistency" else ""
    return hashlib.sha256(f"{stage_id}:{upstream}:{freeze}:{reviewed}".encode()).hexdigest()
