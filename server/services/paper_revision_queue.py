"""Keep unvisited author repairs durable across a sibling stage's interruption."""

from pathlib import Path

from .manuscript_text import read_owned_state, write_json


def queue_consistency_authors(state_path: Path, findings: list[dict], signature) -> None:
    queued = {}
    for item in findings:
        for target in item.get('legal_write_targets') or item.get('target_files') or []:
            queued.setdefault(item['stage_id'], []).append('Target artifact: ' + target + '\n' + str(item['message']))
    queue_author_repairs(state_path, queued, {stage: signature(issues) for stage, issues in queued.items()})


def queue_author_repairs(state_path: Path, issues: dict[str, list[str]], signatures: dict[str, str]) -> None:
    """Persist all routed authors before invoking the first one."""
    state = read_owned_state(state_path)
    for stage in {*issues, "assembly"}:
        record = dict(state.setdefault("stages", {}).get(stage) or {})
        signature = signatures.get(stage, "")
        if stage in issues and record.get("directed_issue_signature") != signature:
            record["directed_issue_signature"] = signature
            record["directed_attempts"] = 0
        if stage in issues and stage != "consistency":
            record["pending_revision_issues"] = issues[stage]
        # Retain the interrupted in-flight marker until recovery refunds the
        # unreviewed attempt; overwriting it here strands a one-attempt repair.
        if record.get("status") != "running":
            record["status"] = "pending"
        record["review_passed"] = False
        state["stages"][stage] = record
    state["status"] = "drafting"
    write_json(state_path, state)


def pending_author_repairs(state_path: Path, author_stages: tuple[str, ...]) -> list[str]:
    """Return scoped obligations, never an old consistency verdict or acceptance."""
    records = read_owned_state(state_path).get("stages", {})
    return list(dict.fromkeys(issue for stage in author_stages if stage != "consistency"
        for issue in records.get(stage, {}).get("pending_revision_issues", [])))


def complete_author_repair(state_path: Path, stage: str) -> None:
    """Clear only this author's queue after successful invocation/local validation.

    The subsequent independent consistency review still decides scientific
    acceptance. A failed or cancelled invocation must leave every queue intact.
    """
    state = read_owned_state(state_path)
    record = state.get("stages", {}).get(stage, {})
    if record.get("pending_revision_issues"):
        record.pop("pending_revision_issues")
        write_json(state_path, state)
