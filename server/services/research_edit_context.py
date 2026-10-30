"""Carry approved research edits into later workflow generation and repair."""

from pathlib import Path
import json


def research_edit_context(project_path: str, node_id: str) -> str:
    root = Path(project_path).resolve()
    changes = []
    for path in sorted((root / ".merak/research-edits").glob("*.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("status") != "applied" or node_id not in value.get("affected_phases", []):
            continue
        relative = str(value.get("path") or "")
        target = (root / relative).resolve()
        if not relative or not target.is_relative_to(root):
            raise ValueError("Approved research edit has an invalid artifact path")
        changes.append((float(value.get("created_at") or 0), relative, value.get("after_sha256", "")))
    if not changes:
        return ""
    latest = {}
    for created, relative, digest in sorted(changes):
        latest[relative] = (created, digest)
    lines = [f"- {path} (approved sha256: {digest})" for path, (_, digest) in latest.items()]
    return (
        "\n\n## User-approved research revisions\n"
        "Read these current files before making further changes. Preserve the user's approved "
        "intent and propagate its consequences to affected contracts, analysis, figures and prose. "
        "Do not restore older defaults to satisfy a stale gate. An edit is not experimental evidence; "
        "changed scientific inputs require fresh validation and, when authorized, new experiment results.\n"
        + "\n".join(lines)
    )
