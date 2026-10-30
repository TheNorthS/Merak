"""Audit skill policy identity ignores installation relocation, not content changes."""

import hashlib
from pathlib import Path


def canonical_policy_digest(policy: str, skill_path: str = "") -> str:
    if not policy:
        return ""
    if skill_path:
        root = Path(skill_path).resolve().parent.parent
        for prefix in {str(root), root.as_posix()}:
            policy = policy.replace(prefix, "<merak-skill-root>")
    return hashlib.sha256(policy.encode("utf-8")).hexdigest()
