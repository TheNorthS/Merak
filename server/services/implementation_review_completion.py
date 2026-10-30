"""Keep incomplete reviewer work out of scientific author-repair routing."""

from typing import Any
import json
from pathlib import Path


class ImplementationReviewIncomplete(RuntimeError):
    """Resume the read-only reviewer; no source edit is justified by missing coverage."""


def require_complete_review(payload: dict[str, Any]) -> None:
    findings = payload.get("findings") or []
    coverage = any(isinstance(item, dict) and (
        item.get("scope") == "review_coverage" or item.get("category") == "review_coverage"
    ) for item in findings) if isinstance(findings, list) else False
    if payload.get("review_complete") is False or payload.get("unreviewed_files") or coverage:
        raise ImplementationReviewIncomplete(
            "IMPLEMENTATION_REVIEW_INCOMPLETE: resume the read-only reviewer to finish coverage; "
            "no author repair is authorized by this incomplete review."
        )
    if "review_complete" in payload and type(payload["review_complete"]) is not bool:
        raise ValueError("training-check review_complete must be a boolean")
    if "unreviewed_files" in payload and not isinstance(payload["unreviewed_files"], list):
        raise ValueError("training-check unreviewed_files must be a list")


def review_completion_instruction() -> str:
    return (
        'Include top-level "review_complete": true|false and "unreviewed_files": []. '
        "Unread or unverified code is review_coverage, never an implementation defect. "
        "Set review_complete=false and list the remaining files when coverage is incomplete; "
        "the runtime will retain the review checkpoint instead of asking authors to edit code. "
        "Keep actual substantiated defects separate. Return only the final JSON object, "
        "without introductory progress prose."
    )


def format_repair_context(raw: str) -> str:
    """Repair a bounded existing response, preserving its verdict and findings."""
    if len(raw) > 64000:
        raise ImplementationReviewIncomplete("Review response exceeds bounded format-repair context; resume review.")
    return (
        "\n\nFormatting only: use the previous reviewer response below. Do not restart the review, "
        "read new files, change the scientific verdict, drop findings, or invent evidence. "
        "Return its complete JSON object without surrounding prose. If the response is incomplete, "
        "report review_complete=false.\n<previous-review-response>\n" + raw
        + "\n</previous-review-response>"
    )


def parse_review_checkpoint(parse: Any, result: str, *, assurance: str, project_path: str, trace: dict) -> dict:
    """Mark only the exact incomplete delegate trace resumable, retaining its transcript."""
    try:
        return parse(result, assurance=assurance)
    except ImplementationReviewIncomplete:
        relative = trace.get("trace_path")
        if relative:
            root = (Path(project_path).resolve() / ".merak/skill-invocations").resolve()
            path = Path(relative).resolve()
            if not path.is_relative_to(root):
                raise ValueError("Review checkpoint trace is outside its project")
            saved = json.loads(path.read_text(encoding="utf-8"))
            if saved.get("session_id") != trace.get("session_id") or saved.get("skill") != "training-check":
                raise ValueError("Review checkpoint trace identity changed")
            from ..utils.atomic_write import atomic_write_json
            atomic_write_json(path, {**saved, "status": "failed", "error_code": "IMPLEMENTATION_REVIEW_INCOMPLETE"})
        raise
