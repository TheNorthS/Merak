"""Select paper projections without discarding the complete benchmark bundle."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .evidence_asset_portfolio import selected_evidence_asset_ids


def simulation_contribution_type(root: Path) -> str:
    """Read the current owner contract, never invent a generic contribution."""
    selected = json.loads((root / "ideas/SELECTED_IDEA.json").read_text(encoding="utf-8-sig"))
    if not isinstance(selected, dict) or selected.get("schema") != 2:
        raise ValueError("Simulation paper projection requires the current selected-idea schema")
    publication = selected.get("publication") or {}
    if not isinstance(publication, dict):
        raise ValueError("Simulation paper projection requires declared publication semantics")
    return str(publication.get("contribution_type") or "")


def selected_simulation_figures(
    records: list[dict[str, Any]], contribution_type: str,
) -> list[dict[str, Any]]:
    """Return the contribution portfolio in source order; reject missing assets."""
    selected = selected_evidence_asset_ids(contribution_type)
    identifiers = [str(record.get("id") or "") for record in records]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("Simulation paper projection refuses duplicate figure IDs")
    missing = selected - set(identifiers)
    if missing:
        raise ValueError("Simulation paper projection is missing selected figures: "
                         + ", ".join(sorted(missing)))
    return [record for record in records if record["id"] in selected]


def selected_simulation_figure_ids(root: Path, records: list[dict[str, Any]]) -> set[str]:
    """Keep registration and rendering bound to the same scientific selection."""
    return {record["id"] for record in selected_simulation_figures(records, simulation_contribution_type(root))}
