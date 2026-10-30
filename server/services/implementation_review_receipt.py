"""Bind read-only implementation review to exact sources, and route its obligations."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..utils.atomic_write import atomic_write_json

REVIEW_POLICY = 3


def review_source_hash(root: Path) -> str:
    paths = [root / f"experiments/{name}" for name in
             ("RUN_SPEC.json", "METHOD_CONTRACT.json", "IMPLEMENTATION_BLUEPRINT.json", "EXPERIMENT_PLAN.md")]
    paths += sorted((root / "experiments/src").rglob("*.py"))
    paths += sorted(p for p in (root / "experiments/configs").rglob("*") if p.is_file())
    digest = hashlib.sha256(b"implementation-review-v1")
    for path in paths:
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes() if path.is_file() else b"<missing>")
    return digest.hexdigest()


def load_review(root: Path) -> dict:
    path = root / ".merak/quality/implementation_review.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def persist_review(root: Path, source_hash: str, assessment: dict) -> None:
    atomic_write_json(root / ".merak/quality/implementation_review.json", {
        "schema": 1, "review_policy": REVIEW_POLICY, "source_sha256": source_hash, "assessment": assessment,
    })


def stage_obligations(root: Path, targets: list[str]) -> list[str]:
    receipt = load_review(root)
    # Retain the old report, but require a fresh policy-aware review before it
    # can authorize author edits or acceptance under the current workflow.
    assessment = receipt.get("assessment", {}) if receipt.get("review_policy") == REVIEW_POLICY else {}
    obligations = []
    for finding in assessment.get("findings", []):
        from .training_review_policy import execution_artifact_finding
        if execution_artifact_finding(finding):
            continue
        if finding.get("severity", "blocker") not in {"blocker", "critical", "error", "fail"}:
            continue
        if finding.get("scope") == "execution_prerequisite":
            continue
        paths = [str(p).replace("\\", "/").rstrip("/") for p in finding.get("target_files", [])]
        if any(t == p or t.startswith(p + "/") for p in paths for t in targets):
            obligations.append(f"Review {finding.get('id')}: {finding.get('message')}; {finding.get('remediation', '')}")
    spec_path = root / "experiments/RUN_SPEC.json"
    if spec_path.is_file():
        from .implementation_readiness_checks import readiness_findings
        for finding in readiness_findings(root, json.loads(spec_path.read_text(encoding="utf-8-sig"))):
            if any(path in targets for path in finding["target_files"] if path.startswith("experiments/src/")):
                obligations.append(f"{finding['id']}: {finding['message']}")
    return obligations


def stage_obligation_signature(root: Path, targets: list[str]) -> str:
    """Bind owner work to the specific review and current declared blockers."""
    obligations = stage_obligations(root, targets)
    if not obligations:
        return ""
    payload = [load_review(root).get("source_sha256"), sorted(set(targets)), obligations]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def pending_stage_obligations(service, root: Path, stage_id: str, direction: str, targets: list[str]) -> list[str]:
    """Reuse completed owner work only; independent review must still pass later."""
    obligations = stage_obligations(root, targets)
    record = (service.load_build(root).get("stages") or {}).get(stage_id) or {}
    handled = str(record.get("handled_obligations_sha256") or "")
    if (handled and record.get("status") == "accepted"
            and handled == stage_obligation_signature(root, targets)
            and record.get("input_sha256") == service.input_hash(root, stage_id, direction)
            and record.get("output_sha256") == service.output_hash(root, stage_id)):
        return []
    return obligations
