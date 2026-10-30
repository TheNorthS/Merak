"""Retain exact delivered line ranges when a long static review view is compacted."""

import json
from pathlib import Path
from typing import Any

from . import Message


def _ranges(intervals: list[tuple[int, int]], count: int) -> tuple[list[list[int]], list[list[int]]]:
    merged: list[list[int]] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    gaps, cursor = [], 1
    for start, end in merged:
        if start > cursor:
            gaps.append([cursor, start - 1])
        cursor = end + 1
    if cursor <= count:
        gaps.append([cursor, count])
    return merged, gaps


def review_read_progress(session: Any) -> str:
    """Attest delivered slices against current bytes, never infer scientific acceptance."""
    if session.tool_policy != "workflow_artifacts" or not session.context_key.endswith("training-check"):
        return ""
    root = Path(session.project_path).resolve()
    results = {m.tool_call_id: m.content for m in session.messages if m.role == "tool"}
    files, coverage = {}, {}
    for message in session.messages:
        for call in message.tool_calls or []:
            args = call.get("arguments")
            if call.get("name") != "Read" or not isinstance(args, dict):
                continue
            path = (root / str(args.get("path") or "")).resolve()
            if not path.is_relative_to(root):
                continue
            if path not in files:
                if len(files) >= 32:
                    continue
                try:
                    files[path] = path.read_text(encoding="utf-8-sig").splitlines() if path.stat().st_size <= 256000 else None
                except (OSError, UnicodeError):
                    files[path] = None
            lines = files[path]
            if lines is None:
                continue
            start, end = args.get("start_line", 0), args.get("end_line", 0)
            if type(start) is not int or type(end) is not int:
                continue
            start, end = max(1, start), min(end or len(lines), len(lines))
            content = results.get(call.get("id"))
            if not isinstance(content, str) or end < start:
                continue
            # Truncated, failed, edited or mismatched reads cannot establish coverage.
            if content.splitlines() != lines[start - 1:end]:
                continue
            coverage.setdefault(path, []).append((start, end))
    records = []
    for path, intervals in coverage.items():
        delivered, missing = _ranges(intervals, len(files[path]))
        records.append({"path": path.relative_to(root).as_posix(), "total_lines": len(files[path]),
                        "delivered_ranges": delivered, "undelivered_ranges": missing})
    if not records:
        return ""
    records.sort(key=lambda r: (not bool(r["undelivered_ranges"]), r["path"]))
    return (
        "[Runtime static-review reading checkpoint]\n"
        "These ranges were returned by successful Read calls and still match current source. "
        "Delivery is not proof of review or correctness. Earlier full content remains in the transcript. "
        "Prioritize undelivered ranges before repeating whole-file reads. Preserve prior findings; "
        "read targeted symbols again only where needed for a concrete unresolved question. "
        "Past closeout notices applied to earlier attempts; this attempt has its current tool budget.\n"
        + json.dumps(records, ensure_ascii=False)
    )


def with_review_read_progress(messages: list[Message], session: Any) -> list[Message]:
    progress = review_read_progress(session)
    return [*messages, Message(role="user", content=progress)] if progress else messages
