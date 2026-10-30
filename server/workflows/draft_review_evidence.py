"""Bind draft integrity fields to the successful independent model response."""

import hashlib
import json
from pathlib import Path
from typing import Any


def draft_response_matches(root: Path, item: dict[str, Any], *, review: bool = False) -> bool:
    visual = item.get("visual_review") or {}
    relative = visual.get("_review_trace_path") if review else item.get("trace_path")
    if not relative:
        return False
    directory = (root / relative).resolve()
    if not directory.is_relative_to((root / ".merak/model-api-reviewer").resolve()):
        return False
    try:
        meta = json.loads((directory / "meta.json").read_bytes())
        raw = (directory / "response.txt").read_bytes()
        response = json.loads(raw)
        schema = json.loads((directory / "output.schema.json").read_bytes())
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    if not all(isinstance(value, dict) for value in (meta, response, schema)):
        return False
    partitioned = any(str(path).startswith(".merak/audit-batches/")
                      for path in meta.get("evidence_packet", {}).get("paths", []))
    if partitioned and not (directory / "audit-batches.json").is_file():
        return False
    if not review and (directory / "audit-batches.json").exists():
        from .audit_batch_receipts import verify_batch_receipt
        from .draft_audit_evidence import draft_audit_evidence
        from .review_audit import audit_source_bundle
        try:
            _, paths = audit_source_bundle(root)
            expected, _, _ = draft_audit_evidence(root, paths, item.get("skill_name"), allow_partition=True)
            verify_batch_receipt(root, directory, expected)
        except (OSError, ValueError, KeyError, TypeError):
            return False
    if not review and (meta.get("purpose") != f"audit-{item.get('skill_name')}"
            or meta.get("invocation_id") != item.get("session_id") or not item.get("session_id")
            or meta.get("model_identity") != item.get("model_name") or not item.get("model_name")):
        return False
    return bool(isinstance(meta, dict) and isinstance(response, dict) and isinstance(schema, dict)
        and meta.get("success") is True and meta.get("response_sha256") == hashlib.sha256(raw).hexdigest()
        and "draft_blockers" in schema.get("required", []) and isinstance(response.get("draft_blockers"), list)
        and response["draft_blockers"] == item.get("draft_blockers")
        and response.get("verdict") == item.get("verdict")
        and (response.get("score") == item.get("score") if review else response.get("summary") == item.get("summary")))
