"""Design-only method contracts that never claim executable evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .research_contract_versions import METHOD_CONTRACT_SCHEMA


def scaffold_method_contract(selected_idea: str, idea_path: Path) -> dict[str, Any]:
    return {
        "schema": METHOD_CONTRACT_SCHEMA,
        "status": "scaffold_only", "selected_idea": selected_idea,
        "idea_contract_path": idea_path.as_posix(), "idea_contract_sha256": "",
        "mechanism_coverage": [], "claim_evidence_plan": [],
        "implementation_checks": [],
        "evaluation_contract": {
            "primary_outcomes": [], "comparators_or_controls": [],
            "component_tests": [], "failure_conditions": [],
        },
        "scientific_scene": {"schema": 1, "objects": [], "relations": []},
        "note": "Replace this unresolved scaffold with mappings to actual implementation artifacts.",
    }


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _strings(value: Any) -> list[str]:
    return [str(item).strip() for item in value if str(item).strip()] if isinstance(value, list) else []


def planned_method_contract(root: Path, idea_relative_path: Path) -> dict[str, Any]:
    idea_path = root / idea_relative_path
    idea = _json(idea_path)
    title = str(idea.get("title") or "").strip()
    mechanisms = [item for item in idea.get("mechanisms", []) if isinstance(item, dict) and str(item.get("id") or "").strip()]
    claims = [item for item in idea.get("claims", []) if isinstance(item, dict) and str(item.get("id") or "").strip()]
    failures = _strings(idea.get("falsification_conditions"))
    if not title or not mechanisms or not claims or not failures:
        return {}
    nearest = [str(item.get("title") or "").strip() for item in idea.get("nearest_prior_work", []) if isinstance(item, dict) and str(item.get("title") or "").strip()]
    comparators = list(dict.fromkeys(
        _strings((idea.get("publication") or {}).get("comparator_names")) or nearest
    ))
    from .scientific_scene import planned_scientific_scene
    return {
        "schema": METHOD_CONTRACT_SCHEMA,
        "status": "planned", "selected_idea": title,
        "idea_contract_path": idea_relative_path.as_posix(),
        "idea_contract_sha256": hashlib.sha256(idea_path.read_bytes()).hexdigest(),
        "mechanism_coverage": [{
            "idea_mechanism_id": str(item["id"]), "implementation_check_ids": [],
            "status": "planned", "design_requirement": str(item.get("description") or item.get("name") or "").strip(),
        } for item in mechanisms],
        "claim_evidence_plan": [{
            "idea_claim_id": str(item["id"]),
            "outcomes": [str(item.get("statement") or "").strip()],
            "failure_conditions": failures, "evidence_status": "pending_experiment",
        } for item in claims],
        "implementation_checks": [],
        "evaluation_contract": {
            "primary_outcomes": [str(item.get("statement") or "").strip() for item in claims[:2]],
            "comparators_or_controls": comparators,
            "component_tests": [
                f"Test necessity and sensitivity of {item['id']}: {item.get('name') or item.get('description') or item['id']}"
                for item in mechanisms
            ],
            "failure_conditions": failures,
        },
        'scientific_scene': planned_scientific_scene(idea),
        "implementation_status": "pending_project_specific_code",
        "evidence_status": "design_only_not_evidence",
        "note": (
            "This contract is complete at the design level because experiment execution is disabled. "
            "Replace planned mappings with executable symbols and tests before enabling exp-run."
        ),
    }
