"""Read-only current-producer checks for persisted deterministic design figures.

An accepted figure is not reusable merely because its old SVG and review bytes
are unchanged. Template and architecture owners must still match their exact
loaded implementation, current canonical specification and source portfolio.
This validator never generates assets, edits metadata or grants acceptance.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_DESIGN_STRATEGIES = {"deterministic_template": "rich_svg", "deterministic_architecture": "figurespec"}


def _read_object(path: Path) -> dict[str, Any]:
    if path.is_symlink() or path.stat().st_nlink > 1 or not path.is_file():
        raise ValueError("deterministic figure ownership contract is linked or not a file: " + path.name)
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("deterministic figure ownership contract is not an object: " + path.name)
    return payload


def _identity(entry: dict[str, Any]) -> str:
    return str((entry.get("metadata") or {}).get("semantic_key") or entry.get("id") or "").strip()


def _active_design(entry: dict[str, Any]) -> bool:
    metadata = entry.get("metadata") or {}
    if not isinstance(metadata, dict):
        raise ValueError("deterministic figure producer metadata is malformed")
    return (metadata.get("paper_selected") is not False and metadata.get("manuscript_eligible") is not False
            and metadata.get("producer_kind") == "deterministic"
            and metadata.get("production_strategy") in _DESIGN_STRATEGIES)


def _contracts(root: Path, entries: list[dict]) -> tuple[dict, dict[str, dict]]:
    plan = _read_object(root / "figures/SCIENTIFIC_ASSET_PLAN.json")
    specification = _read_object(root / "figures/FIGURE_SPECS.json")
    if plan.get("schema") != 2 or specification.get("schema") != 4:
        raise ValueError("deterministic figure freshness requires current plan/specification schemas")
    rows = specification.get("figures")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("deterministic figure specification inventory is malformed")
    specs = {str(row.get("id") or "").strip(): row for row in rows}
    if not all(specs) or len(specs) != len(rows):
        raise ValueError("deterministic figure specifications contain missing or duplicate identities")
    assets = {str(row.get("id") or "").strip(): row for row in plan.get("assets") or []
              if isinstance(row, dict) and row.get("kind") == "figure" and row.get("generation_policy") != "skip"}
    for entry in entries:
        identity = _identity(entry)
        source = assets.get(identity)
        spec = specs.get(identity)
        if not source or not spec:
            raise ValueError(identity + ": deterministic design figure is absent from its declared source portfolio")
        expected = {**source, "caption": str(source.get("caption") or source.get("scientific_question")
                    or f"Scientific figure: {identity}.")}
        if spec != expected:
            raise ValueError(identity + ": canonical specification differs from its declared source portfolio")
    return plan, specs


def current_design_input_sha256(spec: dict[str, Any], plan: dict[str, Any]) -> str:
    """Recompute the producer's shared hash without rendering or project writes."""
    from . import deterministic_figure_builder as producer

    style = str((plan.get("publication_style") or {}).get("visual_standard") or "field-adaptive-accessible-vector-v3")
    strategy = spec.get("production_strategy")
    if (spec.get("producer_kind") != "deterministic" or strategy not in _DESIGN_STRATEGIES
            or spec.get("recommended_backend") != _DESIGN_STRATEGIES[strategy]
            or str(spec.get("generation_policy") or "generate") != "generate"):
        raise ValueError("deterministic design specification has an invalid producer/backend identity")
    if strategy == "deterministic_template":
        return producer._template_input_sha256(spec, style, producer._template_code_sha256())
    from .figure_engine import _load_figurespec_renderer
    from .scientific_scene_figure import compile_scientific_scene_figure

    compiled = compile_scientific_scene_figure(spec).spec
    return producer.architecture_input_sha256(spec, style, compiled,
        producer._architecture_code_sha256(_load_figurespec_renderer()))


def deterministic_figure_freshness_issues(project_path: str | Path) -> list[str]:
    """Return stale findings; existing lifecycle invalidates declared dependents.

    Model-owned/quantitative-only portfolios keep their existing acceptance
    contracts. Missing/malformed design ownership proof fails closed without
    rewriting figure metadata, specification, hashes or persisted acceptance.
    """
    root = Path(project_path).resolve()
    manifest = root / "figures/FIGURE_MANIFEST.json"
    if not manifest.exists():
        return []
    try:
        payload = _read_object(manifest)
        rows = payload.get("figures") or []
        if not isinstance(rows, list):
            raise ValueError("deterministic figure manifest inventory is malformed")
        entries = [entry for entry in rows if isinstance(entry, dict) and _active_design(entry)]
        if not entries:
            return []
        if len({_identity(entry) for entry in entries}) != len(entries):
            raise ValueError("deterministic design figures contain duplicate semantic identities")
        plan, specs = _contracts(root, entries)
        issues = []
        for entry in entries:
            identity, metadata = _identity(entry), entry.get("metadata") or {}
            spec = specs[identity]
            if any(metadata.get(key) != spec.get(key) for key in (
                    "producer_kind", "production_strategy", "recommended_backend")):
                issues.append(identity + ": deterministic design producer identity changed")
                continue
            if metadata.get("producer_input_sha256") != current_design_input_sha256(spec, plan):
                issues.append(identity + ": accepted deterministic figure producer inputs or loaded implementation changed")
        return issues
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
        return ["accepted deterministic figure producer could not be revalidated: " + str(error)]
