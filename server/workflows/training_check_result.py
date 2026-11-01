"""Parse the current JSON-only implementation review contract."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Callable

TargetResolver = Callable[[Any, Any, str], list[str]]
MAX_TRAINING_CHECK_FINDINGS = 8
MAX_FINDING_MESSAGE_CHARS = 900
MAX_FINDING_EVIDENCE_ITEMS = 4
MAX_FINDING_EVIDENCE_CHARS = 240
MAX_FINDING_REMEDIATION_CHARS = 600


def compact_training_check_instruction() -> str:
    """Return the bounded retry contract for a truncated reviewer response."""
    from ..services.training_review_policy import review_scope_instruction
    return review_scope_instruction() + "\n" + (
        "Your previous response was not parseable JSON or was truncated. "
        "Return exactly one compact JSON object and no Markdown. Use at most "
        f"{MAX_TRAINING_CHECK_FINDINGS} findings. Each finding must contain only "
        "id, severity, scope, category, message, evidence, and remediation. Keep "
        f"message <= {MAX_FINDING_MESSAGE_CHARS} chars, evidence <= "
        f"{MAX_FINDING_EVIDENCE_ITEMS} items of <= {MAX_FINDING_EVIDENCE_CHARS} chars, "
        f"and remediation <= {MAX_FINDING_REMEDIATION_CHARS} chars."
    )


def protocol_failure_result(reason: str, stop_reason: str = "") -> str:
    """Keep an incomplete review resumable; a protocol failure has no scientific verdict."""
    detail = str(reason or "training-check response was not parseable")[:500]
    if stop_reason:
        detail += f" stop_reason={stop_reason}."
    raise RuntimeError("TRAINING_CHECK_PROTOCOL_ERROR: independent review incomplete; resume required. " + detail)


def _json_object(text: str) -> dict[str, Any]:
    if len(re.findall(r"```(?:json)?\s*([\s\S]*?)```", text, flags=re.IGNORECASE)) > 1:
        raise ValueError("training-check must return one JSON object, not competing responses")
    candidates = [text]
    candidates.extend(
        match.group(1).strip()
        for match in re.finditer(
            r"```(?:json)?\s*([\s\S]*?)```", text, flags=re.IGNORECASE
        )
    )
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    # A streamed progress sentence can precede a complete final object. Decode
    # exactly one object; never choose among competing verdicts or repair JSON.
    start = text.find("{")
    if start >= 0:
        try:
            value, end = json.JSONDecoder().raw_decode(text, start)
        except json.JSONDecodeError:
            pass
        else:
            if isinstance(value, dict) and not text[end:].strip():
                return value
    raise ValueError("training-check must return one JSON object")


def _finding(
    raw: Any, verdict: str, target_resolver: TargetResolver,
) -> dict[str, Any] | None:
    item = raw if isinstance(raw, dict) else {"message": str(raw)}
    message = str(
        item.get("message") or item.get("plain_message") or item.get("summary") or ""
    ).strip()[:MAX_FINDING_MESSAGE_CHARS]
    if not message:
        return None
    targets = target_resolver(item, item.get("evidence"), message)
    digest = hashlib.sha256(message.encode("utf-8", errors="replace")).hexdigest()[:10]
    evidence = item.get("evidence")
    if not isinstance(evidence, list):
        evidence = targets
    evidence = [str(value).strip()[:MAX_FINDING_EVIDENCE_CHARS]
                for value in evidence[:MAX_FINDING_EVIDENCE_ITEMS]
                if str(value).strip()]
    remediation = str(
        item.get("remediation") or item.get("action")
        or "Repair the named implementation or contract before scientific execution."
    ).strip()[:MAX_FINDING_REMEDIATION_CHARS]
    return {
        "id": str(item.get("id") or f"TRAINING-CHECK-{digest}"),
        "severity": str(
            item.get("severity") or ("warning" if verdict == "WARN" else "blocker")
        ),
        "category": str(item.get("category") or "implementation_review"),
        "scope": str(item.get("scope") or "implementation_correctness"),
        "message": message,
        "plain_message": str(item.get("plain_message") or message)[:MAX_FINDING_MESSAGE_CHARS],
        "target_files": targets,
        "evidence": evidence,
        "remediation": remediation,
        "owner_node": "exp-design",
        "upstream_node": "exp-design",
    }


def _findings(
    payload: dict[str, Any], verdict: str, summary: str,
    target_resolver: TargetResolver,
) -> list[dict[str, Any]]:
    raw = payload.get("findings")
    raw = [] if raw is None and verdict == "PASS" else [summary] if raw is None else raw
    if not isinstance(raw, list):
        raise ValueError("training-check JSON findings must be a list")
    findings, seen = [], set()
    for value in raw[:MAX_TRAINING_CHECK_FINDINGS]:
        finding = _finding(value, verdict, target_resolver)
        if finding is None or finding["message"] in seen:
            continue
        seen.add(finding["message"])
        findings.append(finding)
    return findings


def parse_training_check_result(
    result: str, *, assurance: str, target_resolver: TargetResolver,
) -> dict[str, Any]:
    """Require structured verdict/summary/findings; never infer them from prose."""
    text = str(result or "").strip()
    if not text:
        raise ValueError("training-check returned an empty response")
    payload = _json_object(text)
    from ..services.implementation_review_completion import require_complete_review
    require_complete_review(payload)
    verdict = str(payload.get("verdict") or "").strip().upper()
    if verdict not in {"PASS", "WARN", "FAIL"}:
        raise ValueError("training-check JSON must declare verdict PASS, WARN, or FAIL")
    summary = str(payload.get("summary") or "").strip()
    if not summary:
        raise ValueError("training-check JSON must declare a non-empty summary")
    findings = _findings(payload, verdict, summary, target_resolver)
    strict = str(assurance or "").strip().casefold() in {
        "submission", "strict", "publication", "high",
    }
    blockers = {"blocker", "critical", "error", "fail"}
    has_blocker = any(
        str(item.get("severity") or "").strip().casefold() in blockers
        for item in findings
    )
    return {
        "schema_version": 1, "verdict": verdict, "summary": summary[:2000],
        "blocking": verdict == "FAIL" or (verdict == "WARN" and strict and has_blocker),
        "assurance": assurance, "findings": findings,
        "resolved_findings": payload.get("resolved_findings", []),
        "raw_sha256": hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest(),
        "protocol_error": str(payload.get("protocol_error") or ""),
    }
