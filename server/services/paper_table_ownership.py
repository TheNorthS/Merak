"""Reject section-authored copies of tables owned by the registered table producer."""

import json
import re
from pathlib import Path

from .simulation_policy import strip_latex_comments


def registered_table_copy_issues(root: Path, text: str) -> list[str]:
    path = root / "paper/tables/TABLE_MANIFEST.json"
    if not path.exists():
        return []
    try:
        manifest = json.loads(path.read_bytes())
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        return [f"Registered table ownership inventory is unreadable: {error}"]
    if not isinstance(manifest, dict) or not isinstance(manifest.get("tables"), list):
        return ["Registered table ownership inventory is malformed"]
    labels = {str(item.get("label")): str(item.get("latex_path")) for item in manifest["tables"]
        if isinstance(item, dict) and item.get("label") and item.get("latex_path")}
    issues = []
    for block in re.findall(r"\\begin\{table\*?\}.*?\\end\{table\*?\}", strip_latex_comments(text), re.DOTALL):
        for label in re.findall(r"\\label\{([^}]+)\}", block):
            if label in labels:
                issues.append(f"Section reconstructs registered table {label}, owned by {labels[label]}; "
                    "remove the section-authored copy, retain its scientific prose reference, and use the canonical "
                    "table input exactly once in the manuscript. Do not edit or delete the registered table source.")
    return list(dict.fromkeys(issues))
