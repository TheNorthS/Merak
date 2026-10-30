"""Share model-authored interface findings across isolated implementation owners."""

import json
from pathlib import Path


MAX_STAGE_HANDOFF_CHARS = 8000


def implementation_handoff_context(service, root: Path, stage_id: str, direction: str) -> str:
    """Expose bounded prior reports as claims to verify, never as acceptance evidence."""
    records = service.load_build(root).get("stages") or {}
    sections = []
    for stage in service.stages(root, direction):
        if stage.id == stage_id:
            continue
        record = records.get(stage.id) or {}
        summaries = record.get("session_summaries") or []
        if not summaries:
            continue
        current = (record.get("input_sha256") == service.input_hash(root, stage.id, direction)
                   and record.get("output_sha256") == service.output_hash(root, stage.id))
        sections.append({
            "owner": stage.id, "recorded_status": record.get("status"),
            "fingerprints_current": current, "owned_files": list(stage.targets),
            "reported_findings": str(summaries[-1])[:MAX_STAGE_HANDOFF_CHARS],
        })
    if not sections:
        return ""
    return (
        "\n\n## Implementation owner handoffs\n"
        "These are prior model reports, not proof of correctness or permission to change another "
        "owner's files. Read current source and verify each claim. Resolve interface requirements "
        "affecting your own outputs; do not leave both producers waiting for each other. Preserve "
        "unresolved cross-owner dependencies explicitly in your final report for the next owner. "
        "Prior accepted means the local static gate passed, not that independent review passed.\n"
        + json.dumps(sections, ensure_ascii=False)
    )
