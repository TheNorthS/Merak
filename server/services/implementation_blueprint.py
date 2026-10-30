"""Creation and normalization of the current frozen implementation blueprint."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Protocol

from ..utils.atomic_write import atomic_write_json
from .implementation_stages import ImplementationStage
from .implementation_state_io import load_implementation_state
from .impl_stage_targets import declared_entrypoint


FAMILIES = {
    "machine_learning", "computational_general", "external_protocol",
    "formal_verification",
}


class BlueprintPort(Protocol):
    def blueprint_path(self, project_path: str | Path) -> Path: ...
    def _selected_contract(self, root: Path) -> dict[str, Any]: ...
    def _method_contract(self, root: Path) -> dict[str, Any]: ...
    def _stages_for_family(self, family: str) -> tuple[ImplementationStage, ...]: ...
    def project_stages(self, project_path: str | Path, family: str) -> tuple[ImplementationStage, ...]: ...


def publication_profile(
    root: Path, direction: str, selected: dict[str, Any],
) -> dict[str, Any]:
    persisted = load_implementation_state(root / "paper" / "PUBLICATION_STYLE.json")
    if persisted.get("family"):
        return persisted
    try:
        from .publication_style import publication_style_service

        return publication_style_service.build(
            context=" ".join((direction, json.dumps(selected, ensure_ascii=False))),
        )
    except Exception:
        return {}


def infer_family(*payloads: dict[str, Any]) -> str:
    for payload in payloads:
        candidate = str(payload.get("implementation_family") or "").strip().casefold()
        if candidate in FAMILIES:
            return candidate
    text = " ".join(json.dumps(item, ensure_ascii=False) for item in payloads if item).casefold()
    if re.search(
        r"(?:neural|deep learning|pytorch|torch|tensorflow|classifier|neural network|"
        r"representation learning|foundation model|transformer|embedding|encoder|decoder|"
        r"pretrain|fine[- ]?tun|contrastive|accuracy|auroc|f1)", text,
    ):
        return "machine_learning"
    if re.search(r"(?:theorem|proof|lemma|formal verification)", text):
        return "formal_verification"
    if re.search(r"(?:clinical protocol|recruitment|interview|observational|wet lab)", text):
        return "external_protocol"
    return "computational_general"


def entrypoint_for_family(family: str) -> str:
    return {
        "machine_learning": "experiments/src/train.py",
        "computational_general": "experiments/src/run_analysis.py",
        "external_protocol": "experiments/src/run_analysis.py",
        "formal_verification": "experiments/src/verify.py",
    }.get(str(family or "").strip().casefold(), "experiments/src/run_analysis.py")


def integration_flow_for_family(family: str) -> list[str]:
    flows = {
        "machine_learning": [
            "configured data", "split-safe batches", "model forward",
            "accepted mechanisms", "objective/loss", "optimization",
            "evaluation", "result and provenance persistence",
        ],
        "formal_verification": [
            "definitions and assumptions", "admissible instances",
            "lemmas or constructions", "proof obligations",
            "verification and counterexamples", "bounds",
            "result and provenance persistence",
        ],
        "external_protocol": [
            "population or sampling contract", "eligibility and quality control",
            "estimand or coding contract", "analysis path", "uncertainty and sensitivity",
            "validation", "result and provenance persistence",
        ],
    }
    return flows.get(family, [
        "configured inputs", "analysis units or scenarios", "accepted mechanisms",
        "algorithm or numerical method", "comparators and sensitivity", "evaluation",
        "result and provenance persistence",
    ])


def _stage_payload(stages: tuple[ImplementationStage, ...]) -> list[dict[str, Any]]:
    return [
        {"id": stage.id, "title": stage.title, "purpose": stage.purpose, "targets": list(stage.targets)}
        for stage in stages
    ]


def _upgrade_existing(
    service: BlueprintPort, existing: dict[str, Any], selected: dict[str, Any],
    method: dict[str, Any], publication: dict[str, Any], path: Path,
) -> dict[str, Any]:
    changed = False
    family = str(existing.get("implementation_family") or "").strip().casefold()
    if family not in FAMILIES:
        family = infer_family(selected, method, publication, existing)
        existing["implementation_family"] = family
        changed = True
    expected_stages = _stage_payload(service.project_stages(path.parent.parent, family))
    defaults = {
        "stages": expected_stages,
        "entrypoint": entrypoint_for_family(family),
        "research_family": str(publication.get("family") or "generic_quantitative"),
        "study_archetype": str(publication.get("study_archetype") or "generic_empirical"),
    }
    if existing.get("stages") != expected_stages:
        existing["stages"] = expected_stages
        changed = True
    current_entrypoint = declared_entrypoint(path.parent.parent, existing.get("entrypoint") or entrypoint_for_family(family))
    if existing.get("entrypoint") != current_entrypoint:
        existing["entrypoint"] = current_entrypoint
        changed = True
    for key in ("entrypoint", "research_family", "study_archetype"):
        if not str(existing.get(key) or "").strip():
            existing[key] = defaults[key]
            changed = True
    if not isinstance(existing.get("domain_evidence_contract"), dict):
        existing["domain_evidence_contract"] = dict(publication.get("domain_evidence_contract") or {})
        changed = True
    if changed:
        atomic_write_json(path, existing)
    return existing


def _new_blueprint(
    service: BlueprintPort, selected: dict[str, Any], publication: dict[str, Any],
    method: dict[str, Any], direction: str, root: Path,
) -> dict[str, Any]:
    family = infer_family(selected, method, publication)
    mechanisms = [
        {"id": str(item.get("id") or "").strip(),
         "name": str(item.get("name") or item.get("description") or "").strip(),
         "required": item.get("required", True) is not False}
        for item in selected.get("mechanisms") or []
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    ]
    claims = [
        {"id": str(item.get("id") or "").strip(),
         "statement": str(item.get("statement") or "").strip()}
        for item in selected.get("claims") or []
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    ]
    return {
        "schema": 1, "status": "frozen_for_implementation",
        "title": str(selected.get("title") or direction or "Research implementation"),
        "research_direction": direction, "implementation_family": family,
        "research_family": str(publication.get("family") or "generic_quantitative"),
        "study_archetype": str(publication.get("study_archetype") or "generic_empirical"),
        "domain_evidence_contract": dict(publication.get("domain_evidence_contract") or {}),
        "entrypoint": declared_entrypoint(root, entrypoint_for_family(family)), "mechanisms": mechanisms,
        "claims": claims, "stages": _stage_payload(service.project_stages(root, family)),
        "integration_contract": {
            "required_flow": integration_flow_for_family(family),
            "predictive_metrics_require_task_head": family == "machine_learning",
            "defined_symbols_must_be_reachable": True,
        },
    }


def ensure_blueprint(
    service: BlueprintPort, project_path: str | Path, direction: str = "",
) -> dict[str, Any]:
    root = Path(project_path).expanduser().resolve()
    path = service.blueprint_path(root)
    existing = load_implementation_state(path)
    selected = service._selected_contract(root)
    method = service._method_contract(root)
    publication = publication_profile(root, direction, selected)
    if int(existing.get("schema") or 0) == 1 and existing.get("stages"):
        return _upgrade_existing(service, existing, selected, method, publication, path)
    blueprint = _new_blueprint(service, selected, publication, method, direction, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, blueprint)
    return blueprint
