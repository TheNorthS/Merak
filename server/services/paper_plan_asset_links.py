"""One required-asset linkage contract for plan prompts, reuse and figure gates."""

import json
from pathlib import Path


def required_figures(root: Path) -> dict[str, dict]:
    path = root / "figures/SCIENTIFIC_ASSET_PLAN.json"
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    return {str(item["id"]): item for item in payload.get("assets", [])
            if isinstance(item, dict) and item.get("kind") == "figure" and item.get("required")}


def missing_figure_links(text: str, assets: dict[str, dict]) -> list[str]:
    return [identity for identity, asset in assets.items()
            if asset.get("kind") == "figure" and asset.get("required")
            and identity not in text and not (asset.get("label") and str(asset["label"]) in text)]


def plan_link_issues(root: Path) -> list[str]:
    path = root / "paper/PAPER_PLAN.md"
    text = path.read_text(encoding="utf-8-sig") if path.is_file() else ""
    return [f"required figure is not referenced in paper/PAPER_PLAN.md: {identity}"
            for identity in missing_figure_links(text, required_figures(root))]


def plan_asset_instruction(root: Path) -> str:
    assets = required_figures(root)
    if not assets:
        return ""
    inventory = "\n".join(f"- {identity}: {asset.get('label') or ''}" for identity, asset in assets.items())
    return ("\n\nRequired existing figure links for this internal manuscript plan:\n" + inventory
            + "\nRetain each exact asset ID or LaTeX label in the figure-placement table, including appendix placements. "
            "These identifiers belong in the planning artifact, not reader-facing scientific prose. "
            "Use each asset only for its declared scientific question. Proposed additions cannot replace required links; "
            "do not invent unavailable outputs or combine distinct method/evaluation/result questions into a mandatory hero figure.")
