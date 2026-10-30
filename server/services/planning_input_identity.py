"""Versioned semantic planning dependency identity, including the consumed run specification."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import yaml


PLANNING_SOURCES = (
    "ideas/ideas.md", "ideas/novelty_report.md", "ideas/SELECTED_IDEA.json",
    "experiments/EXPERIMENT_PLAN.md", "experiments/METHOD_CONTRACT.json",
    "experiments/RUN_SPEC.json", "experiments/configs/main.yaml",
)
RUNTIME_FIELDS = {
    "ideas/SELECTED_IDEA.json": {"created_at", "updated_at", "accepted_at"},
    "experiments/METHOD_CONTRACT.json": {"created_at", "updated_at", "idea_contract_sha256"},
}


def semantic_bytes(path: Path, relative: str) -> bytes:
    if not path.is_file():
        return b"<missing>"
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix in {".json", ".yaml", ".yml"}:
        value = json.loads(text) if path.suffix == ".json" else yaml.safe_load(text)
        if isinstance(value, dict):
            value = {key: item for key, item in value.items() if key not in RUNTIME_FIELDS.get(relative, set())}
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return text.replace("\r\n", "\n").encode()


def planning_identity(root: Path, direction: str = "", **settings: str) -> dict:
    defaults = {"evidence_mode": "design_only", "target_venue": "", "research_family": "", "study_archetype": ""}
    normalized = {key: str(settings.get(key, value) or value).strip() for key, value in defaults.items()}
    normalized["direction"] = direction.strip()
    normalized["evidence_mode"] = normalized["evidence_mode"].casefold()
    sources = {relative: hashlib.sha256(semantic_bytes(root / relative, relative)).hexdigest() for relative in PLANNING_SOURCES}
    payload = {"schema": 2, "sources": sources, "settings": normalized}
    return {**payload, "sha256": hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}
