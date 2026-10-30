"""Claim-to-manuscript evidence sidecar generation."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from ..utils.atomic_write import atomic_write_json
from .latex_bundle import latex_source_bundle
from .paper_evidence import PaperEvidence


def refresh_paper_evidence_map(evidence: PaperEvidence) -> Path:
    root = evidence.root
    source_hash, source_paths = latex_source_bundle(root / "paper")
    claims = [
        item for item in evidence.selected_idea.get("claims", [])
        if isinstance(item, dict)
    ]
    body = {
        "schema": 2,
        "evidence_mode": evidence.evidence_mode,
        "submission_eligible": evidence.submission_eligible,
        "claims": claims,
        "mechanisms": _dict_items(evidence.selected_idea, "mechanisms"),
        "claim_evidence_plan": _dict_items(evidence.method_contract, "claim_evidence_plan"),
        "claim_mappings": _claim_mappings(evidence, claims),
        "manuscript": {
            "entrypoint": "paper/main.tex",
            "source_bundle_sha256": source_hash,
            "source_files": [
                str(path.relative_to(root).as_posix())
                for path in source_paths
                if path.is_file()
            ],
        },
    }
    target = root / ".merak" / "research_audit" / "PAPER_EVIDENCE_MAP.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    existing = _read_existing(target)
    payload = {"schema": body["schema"], "updated_at": _updated_at(existing, body)}
    payload.update({key: value for key, value in body.items() if key != "schema"})
    atomic_write_json(target, payload)
    return target


def _dict_items(container: dict[str, Any], key: str) -> list[dict[str, Any]]:
    return [item for item in container.get(key, []) if isinstance(item, dict)]


def _claim_mappings(
    evidence: PaperEvidence, claims: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    plans = {
        str(item.get("idea_claim_id") or ""): item
        for item in _dict_items(evidence.method_contract, "claim_evidence_plan")
    }
    return [_claim_mapping(claim, plans) for claim in claims]


def _claim_mapping(
    claim: dict[str, Any], plans: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    claim_id = str(claim.get("id") or "").strip()
    plan = plans.get(claim_id, {})
    return {
        "claim_id": claim_id,
        "statement": str(claim.get("statement") or claim.get("description") or "").strip(),
        "evidence_status": str(plan.get("evidence_status") or "pending").strip(),
        "decisive_evidence": _clean_list(plan.get("outcomes"), 8),
        "counterevidence": _clean_list(plan.get("failure_conditions"), 12),
        "manuscript_sections": [
            "Introduction", "Method", "Experiments",
            "Results and Discussion", "Limitations",
        ],
    }


def _clean_list(value: Any, limit: int) -> list[str]:
    return [
        str(item).strip() for item in (value if isinstance(value, list) else [])[:limit]
        if str(item).strip()
    ]


def _read_existing(target: Path) -> dict[str, Any]:
    if not target.is_file():
        return {}
    try:
        loaded = json.loads(target.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _updated_at(existing: dict[str, Any], body: dict[str, Any]) -> Any:
    existing_body = {key: value for key, value in existing.items() if key != "updated_at"}
    if existing_body == body and existing.get("updated_at") is not None:
        return existing["updated_at"]
    return time.time()
