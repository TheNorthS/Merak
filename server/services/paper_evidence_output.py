"""Persist the evidence snapshot consumed by paper audits."""

from __future__ import annotations

import time
from typing import Any

from ..utils.atomic_write import atomic_write_json
from .paper_evidence import PaperEvidence


def write_evidence_snapshot(evidence: PaperEvidence) -> None:
    payload = {
        "schema": 1,
        "generated_at": time.time(),
        "title": evidence.title,
        "direction": evidence.direction,
        "experiments_pending": evidence.experiments_pending,
        "evidence_mode": evidence.evidence_mode,
        "submission_eligible": evidence.submission_eligible,
        "scientific_asset_plan": "figures/SCIENTIFIC_ASSET_PLAN.json",
        "claims": evidence.asset_plan.get("claims", []),
        "metrics": [
            {"name": item.name, "value": item.value,
             "source": item.source, "split": item.split}
            for item in evidence.metrics
        ],
        "figures": [_figure_snapshot(item) for item in evidence.figures],
    }
    atomic_write_json(evidence.root / "paper" / "EVIDENCE_SNAPSHOT.json", payload)


def _figure_snapshot(item: dict[str, Any]) -> dict[str, Any]:
    metadata = item.get("metadata") or {}
    return {
        "output_path": item.get("output_path"),
        "paper_path": item.get("paper_path"),
        "description": item.get("description"),
        "evidence_status": metadata.get("evidence_status", "artifact"),
        "scientific_role": metadata.get("scientific_role", ""),
        "claim_ids": metadata.get("claim_ids", []),
        "source_data": metadata.get("source_data", []),
        "label": metadata.get("label", ""),
    }
