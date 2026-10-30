"""Resume unfinished section drafts before asking the complete-paper gate to pass."""

import json
from pathlib import Path
from typing import Any


async def resume_incomplete_paper_stages(context: Any) -> bool:
    """The durable section ledger owns progress, even after a failed outer resume."""
    if context.node.id != "paper" or not context.revalidate_done or context.upstream_preflight:
        return False
    path = Path(context.run.project_path) / "paper/DRAFT_STATE.json"
    if not path.is_file():
        return False
    state = json.loads(path.read_text(encoding="utf-8-sig"))
    if (state.get("schema_version") != 3 or not state.get("stages")
            or not any(record.get("status") in {"running", "pending"}
                       for record in state["stages"].values())):
        return False
    context.result = await context.host._execute_staged_paper(node=context.node, run=context.run,
        research_direction=context.research_direction, opts=context.opts)
    return True
