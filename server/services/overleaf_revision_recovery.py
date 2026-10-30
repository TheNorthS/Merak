"""Recover an interrupted local publication import without overwriting later edits."""

import json
from pathlib import Path

from ..utils.atomic_write import atomic_write_json


def recover_publication_imports(service, root: Path) -> None:
    from .overleaf_research_revision import publication_fingerprints

    for path in sorted((root / ".merak/overleaf-revisions").glob("*/revision.json")):
        receipt = json.loads(path.read_text(encoding="utf-8"))
        if receipt.get("status") != "prepared":
            continue
        before, after = receipt.get("before"), receipt.get("after")
        if not isinstance(before, dict) or not isinstance(after, dict):
            raise ValueError("Interrupted Overleaf import has invalid recovery metadata")
        backup = path.parent / "backup"
        if publication_fingerprints(backup) != before:
            raise ValueError("Interrupted Overleaf import backup is incomplete or changed")
        current = publication_fingerprints(root)
        for name in before.keys() | after.keys() | current.keys():
            if current.get(name) not in {before.get(name), after.get(name)}:
                raise ValueError("Local publication changed after interrupted Overleaf import; explicit reconciliation required")
        for name in ("paper", "figures"):
            (backup / name).mkdir(parents=True, exist_ok=True)
            service._copy_research_tree(backup / name, root / name)
        receipt["status"] = "rolled_back"
        receipt["recovered_after_restart"] = True
        atomic_write_json(path, receipt)
