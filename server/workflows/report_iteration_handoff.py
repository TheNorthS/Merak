"""Join completed author tool writes to impact review without claiming research success."""
import hashlib
import json
from pathlib import Path

from .report_revision_store import fingerprints
from .report_revision_impact import verify_unchanged_science


def record_exhaustion(record: dict, owner: str, session_id: str, iterations: int, limit: int) -> None:
    record.setdefault("iteration_handoffs", []).append({
        "owner": owner, "session_id": session_id, "iterations": iterations, "limit": limit,
        "status": "requires_independent_impact_review",
    })


def recover_joined_report_edits(root: Path, run_id: str, record: dict) -> bool:
    """Recover only exact successful Edit receipts against the immutable before image.

    No tool is replayed. Unknown side effects, unjoined writes and user changes
    fail closed. The result only opens impact review, never accepts a finding.
    """
    if (record.get("status") != "needs_attention" or record.get("iteration_handoffs")
            or not str(record.get("error", "")).startswith("AgentIterationLimit:")
            or record.get("completed_owners") or not record.get("active_owner")):
        return False
    if not run_id:
        raise ValueError("Report iteration recovery requires its exact run identity")
    before_path = (root / record["before_path"]).resolve()
    if not before_path.is_relative_to(root / ".merak/report-revisions"):
        raise ValueError("Report before image is outside its runtime directory")
    if hashlib.sha256(before_path.read_bytes()).hexdigest() != record["before_sha256"]:
        raise ValueError("Original repair evidence changed")
    for path in sorted((root / ".merak/skill-invocations").glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        trace = json.loads(path.read_bytes())
        if (trace.get("workflow_run_id") != run_id or trace.get("parent_context") != "report-revision"
                or trace.get("started_at", 0) < record["started_at"]):
            continue
        if (trace.get("status") != "failed" or "AGENT_ITERATION_LIMIT" not in str(trace.get("error"))
                or set(trace.get("allowed_write_paths") or []) != set(record["targets"])):
            raise ValueError("Latest report attempt does not have a joined iteration checkpoint")
        session_id = str(trace.get("session_id") or "")
        if not session_id.isalnum():
            raise ValueError("Invalid report session identity")
        session = json.loads((root / ".merak/agent-sessions" / (session_id + ".json")).read_bytes())
        _verify_edits(root, json.loads(before_path.read_bytes()), session["messages"], record["targets"])
        verify_unchanged_science(root, record)
        record_exhaustion(record, record["active_owner"], session_id, 24, 24)
        record["expected"] = fingerprints(root, record["targets"])
        record["completed_owners"].append(record.pop("active_owner"))
        record["status"] = "verifying"
        return True
    raise ValueError("No bound report iteration trace; preserve unresolved edits")


def _verify_edits(root: Path, before: dict, messages: list[dict], targets: list[str]) -> None:
    pending, edits = {}, 0
    readonly = {"Read", "Glob", "Grep", "WebFetch", "arxiv_search", "semantic_scholar_search", "openalex_search"}
    for message in messages:
        for call in message.get("tool_calls") or []:
            if call["name"] in readonly:
                continue
            if call["name"] != "Edit":
                raise ValueError("Report checkpoint contains an unsupported side effect")
            pending[call["id"]] = call["arguments"]
        if message.get("role") == "tool" and message.get("tool_call_id") in pending:
            args = pending.pop(message["tool_call_id"])
            path = Path(args["path"])
            path = (path if path.is_absolute() else root / path).resolve()
            relative = path.relative_to(root).as_posix()
            if relative not in targets or not str(message.get("content", "")).startswith("Edited "):
                raise ValueError("Report Edit lacks a successful scoped receipt")
            old, new = args["old_text"], args["new_text"]
            if not old or before[relative].count(old) != 1:
                raise ValueError("Report Edit cannot be reconciled with its before image")
            before[relative] = before[relative].replace(old, new, 1)
            edits += 1
    if pending or not edits or any((root / name).read_text(encoding="utf-8-sig") != before[name] for name in targets):
        raise ValueError("Report target differs from joined Edit evidence; preserve user changes")
