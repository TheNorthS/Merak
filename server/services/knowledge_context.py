"""Select only explicitly enabled, successfully collected personal context."""

import json
from pathlib import Path


def selected_personal_context(literature: Path, options: dict, sources: list[str]) -> str:
    sections = []
    for source in ("zotero", "obsidian"):
        if not options.get(f"enable_{source}") or source not in sources:
            continue
        path = literature / f"{source}_context.json"
        if not path.is_file():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if (payload.get("schema_version") != 1 or payload.get("source") != source
                or payload.get("status") not in {"completed", "completed_no_records"}):
            raise ValueError(f"Invalid collected personal context: {path.name}")
        sections.append(f"### {path.name}\n{json.dumps(payload, ensure_ascii=False)[:5000]}")
    return "\n\n".join(sections)
