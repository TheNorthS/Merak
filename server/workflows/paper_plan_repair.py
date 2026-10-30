"""Repair an explicitly scoped outline through its model delegate, preserving narration."""

from typing import Any


async def repair_plan_only(host: Any, node: Any, run: Any, diagnostics: dict,
                           instruction: str, direction: str, effort: str,
                           assurance: str, opts: dict) -> str | None:
    if node.id != "narrative":
        return None
    targets = (diagnostics.get("repair_scope") or {}).get("target_files") or []
    if {str(path).replace("\\", "/") for path in targets} != {"paper/PAPER_PLAN.md"}:
        return None
    await host._execute_stage_delegates(node=node, run=run, direction=direction, effort=effort,
        assurance=assurance, opts={**opts, "_paper_plan_revision_instruction": instruction})
    return "Revised the canonical model-authored paper plan; scientific narrative was preserved."
