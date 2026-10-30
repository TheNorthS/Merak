"""Rollback interrupted evidence publication only when every canonical byte is recognized."""
import json
from pathlib import Path
from ..utils.atomic_write import atomic_write_json, atomic_write_bytes


def pending_publication(root: Path) -> dict:
    pending = [json.loads(path.read_text(encoding="utf-8")) for path in (root / ".merak/evidence-versions").glob("*/VERSION.json")]
    matches = [item for item in pending if item.get("status") == "publishing"]
    if len(matches) > 1:
        raise ValueError("Multiple unfinished evidence publications require manual reconciliation")
    return matches[0] if matches else {}


def recover_publications(root: Path) -> None:
    from .evidence_versions import _sha
    versions = root / ".merak/evidence-versions"
    for path in versions.glob("*/VERSION.json"):
        receipt = json.loads(path.read_text(encoding="utf-8"))
        if receipt.get("status") != "publishing":
            continue
        previous, following = receipt["previous"], receipt["next"]
        for relative, digest in previous.items():
            target, backup = root / relative, path.parent / "previous" / relative
            if not target.resolve().is_relative_to(root) or not backup.resolve().is_relative_to(path.parent):
                raise ValueError("Evidence rollback path escaped its owner")
            if _sha(target) not in {digest, following[relative]} or (digest and _sha(backup) != digest):
                raise ValueError("Evidence publication interrupted and files changed externally; preserve archives for manual reconciliation")
        for relative, digest in previous.items():
            if digest:
                atomic_write_bytes(root / relative, (path.parent / "previous" / relative).read_bytes())
            else:
                (root / relative).unlink(missing_ok=True)
        atomic_write_json(path, {**receipt, "status": "rolled_back_after_interruption"})
