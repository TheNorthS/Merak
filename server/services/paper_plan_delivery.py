"""Bound updates to an existing authored outline instead of regenerating a long response."""

from pathlib import Path

from .paper_plan_changes import plan_change_instruction


def plan_delivery(root: Path, current_valid: bool) -> tuple[str, list[str] | None]:
    if not current_valid:
        return "\nFor initial authoring, keep the outline concise; prefer compact section contracts over repeated prose.", None
    path = root / "paper/PAPER_PLAN.md"
    return (
        f"\nThe canonical plan already exists ({path.stat().st_size} bytes). Read its relevant sections, "
        "compare them with the current evidence, then use targeted Edit calls only for changed claims, "
        "evidence boundaries, asset links or reviewer findings. Preserve unaffected wording and structure. "
        "Each Edit should replace one short passage, preferably under 1500 new characters. Do not regenerate "
        "the complete document or append a duplicate outline. Review the resulting plan and return a short summary. "
        "A current plan may need no text change, but still requires fresh source review."
        + plan_change_instruction(root),
        ["Read", "Edit", "Glob", "Grep", "reviewer_api", "reviewer_api_reply"],
    )
