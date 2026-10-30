"""Resolve the single current producer for each semantic figure asset."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping


FIGURE_PRODUCER_KINDS = frozenset({"model", "deterministic"})

_PRODUCTION_CONTRACTS = {
    "deterministic_architecture": {
        "figure_nature": "conceptual", "producer_kind": "deterministic",
        "recommended_backend": "figurespec", "recommended_skill": "figure-spec",
        "composition_owner": "runtime", "full_svg_authority": False,
    },
    "model_composed_full_svg": {
        "figure_nature": "conceptual", "producer_kind": "model",
        "recommended_backend": "rich_svg", "recommended_skill": "model-svg-figure",
        "composition_owner": "model", "full_svg_authority": True,
    },
    "deterministic_plot": {
        "figure_nature": "quantitative", "producer_kind": "deterministic",
        "recommended_backend": "matplotlib", "recommended_skill": "paper-figure",
        "composition_owner": "runtime", "full_svg_authority": False,
    },
    "deterministic_template": {
        "figure_nature": "standard_protocol", "producer_kind": "deterministic",
        "recommended_backend": "rich_svg",
        "recommended_skill": "deterministic-figure-template",
        "composition_owner": "runtime", "full_svg_authority": False,
    },
    "model_generated_image": {
        "figure_nature": "naturalistic", "producer_kind": "model",
        "recommended_backend": "nano_banana",
        "recommended_skill": "paper-illustration",
        "composition_owner": "model", "full_svg_authority": False,
    },
}


def figure_production_issues(record: Mapping[str, Any]) -> list[str]:
    """Validate a declared nature/producer route without rejecting legacy specs."""
    strategy = str(record.get("production_strategy") or "").strip().casefold()
    if not strategy:
        return []
    expected = _PRODUCTION_CONTRACTS.get(strategy)
    if expected is None:
        return [f"unsupported production_strategy: {strategy}"]
    issues = []
    for key, value in expected.items():
        actual = record.get(key)
        if key == "full_svg_authority":
            if actual is not value:
                issues.append(f"{strategy} requires {key}={str(value).lower()}")
        elif str(actual or "").strip().casefold() != str(value).casefold():
            issues.append(f"{strategy} requires {key}={value}")
    return issues


def figure_producers(
    project_path: str | Path, asset_ids: Iterable[str],
) -> tuple[dict[str, str], list[str]]:
    root = Path(project_path).expanduser().resolve()
    path = root / "figures/FIGURE_SPECS.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}, ["FIGURE_SPECS.json is missing or invalid"]
    if payload.get("schema") != 4 or payload.get("publication_label_schema") != 1:
        return {}, ["FIGURE_SPECS.json has an unsupported producer/label schema"]
    records = {
        str(item.get("id") or ""): item
        for item in payload.get("figures") or [] if isinstance(item, dict)
    }
    producers, issues = {}, []
    for asset_id in sorted({str(value).strip() for value in asset_ids if str(value).strip()}):
        record = records.get(asset_id)
        producer = str((record or {}).get("producer_kind") or "").casefold()
        if producer not in FIGURE_PRODUCER_KINDS:
            issues.append(f"{asset_id}: producer_kind must be model or deterministic")
            continue
        issues.extend(
            f"{asset_id}: {issue}"
            for issue in figure_production_issues(record or {})
        )
        producers[asset_id] = producer
    return producers, issues
